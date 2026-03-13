##########################################################################################
#
# Module: agents/ticket_monitor.py
#
# Description: Ticket Monitor Agent — watches for newly created Jira tickets,
#              validates required fields, auto-fills when confident, flags
#              creators when not.  Purely programmatic (no LLM).
#
# Author: Cornelis Networks
#
##########################################################################################

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, AgentConfig, AgentResponse
from llm.base import BaseLLM
from core.monitoring import (
    MonitorConfig,
    ValidationResult,
    determine_actions,
    load_monitor_config,
    validate_ticket,
)
from core.queries import paginated_jql_search
from core.tickets import issue_to_dict
from notifications.jira_comments import JiraCommentNotifier
from state.learning import LearningStore
from state.monitor_state import MonitorState

# Logging config — follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# Default config file path
_DEFAULT_CONFIG_PATH = os.path.join('config', 'ticket_monitor.yaml')
_DEFAULT_DB_DIR = 'state'


class TicketMonitorAgent(BaseAgent):
    '''
    Agent that monitors newly created Jira tickets, validates required fields,
    and takes action (auto-fill, suggest, or flag) based on learned patterns.

    This agent is purely programmatic — no LLM is needed.  The run() method
    orchestrates a deterministic validation + notification loop.
    '''

    def __init__(
        self,
        config_path: Optional[str] = None,
        db_dir: Optional[str] = None,
        dry_run: bool = False,
    ):
        '''
        Initialize the Ticket Monitor agent.

        Input:
            config_path: Path to ticket_monitor.yaml (default: config/ticket_monitor.yaml).
            db_dir:      Directory for SQLite state databases (default: state/).
            dry_run:     If True, validate and report but do not update tickets or
                         post comments.
        '''
        resolved_config_path = config_path or _DEFAULT_CONFIG_PATH
        if os.path.exists(resolved_config_path):
            self.monitor_config: MonitorConfig = load_monitor_config(resolved_config_path)
        else:
            log.warning(
                'Config file not found at %s — using defaults', resolved_config_path
            )
            self.monitor_config = MonitorConfig()

        self.dry_run = dry_run

        resolved_db_dir = db_dir or _DEFAULT_DB_DIR
        Path(resolved_db_dir).mkdir(parents=True, exist_ok=True)

        self.state = MonitorState(
            db_path=os.path.join(resolved_db_dir, 'monitor_state.db')
        )
        self.learning = LearningStore(
            db_path=os.path.join(resolved_db_dir, 'learning.db')
        )

        self._jira: Any = None
        self._notifier: Optional[JiraCommentNotifier] = None

        agent_config = AgentConfig(
            name='ticket_monitor',
            description=(
                'Monitors newly created Jira tickets, validates required fields, '
                'and auto-fills or flags missing data based on learned patterns.'
            ),
            instruction='Programmatic agent — no LLM instruction required.',
        )

        class _NoOpLLM(BaseLLM):
            def __init__(self):
                super().__init__(model='none')

            def chat(self, messages, temperature=0.7, max_tokens=None, **kwargs):
                raise NotImplementedError('Programmatic agent — no LLM calls')

            def chat_with_vision(self, messages, images, temperature=0.7, max_tokens=None, **kwargs):
                raise NotImplementedError('Programmatic agent — no LLM calls')

            def supports_vision(self):
                return False

        super().__init__(config=agent_config, llm=_NoOpLLM(), tools=None)

    # ------------------------------------------------------------------
    # Lazy Jira connection helpers
    # ------------------------------------------------------------------

    def _get_jira(self) -> Any:
        '''Return (and cache) a live Jira connection.'''
        if self._jira is None:
            from tools.jira_tools import get_jira
            self._jira = get_jira()
        return self._jira

    def _get_notifier(self) -> JiraCommentNotifier:
        '''Return (and cache) the Jira comment notifier.'''
        if self._notifier is None:
            self._notifier = JiraCommentNotifier(self._get_jira())
        return self._notifier

    # ------------------------------------------------------------------
    # Field-update helper for Jira Cloud
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_date(date_str: str) -> Optional[str]:
        for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M',
                    '%m-%d-%Y', '%m/%d/%Y', '%d-%m-%Y', '%d/%m/%Y'):
            try:
                dt = datetime.strptime(date_str.split('.')[0].split('+')[0], fmt)
                return dt.strftime('%Y-%m-%d %H:%M')
            except ValueError:
                continue
        if 'T' in date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.strftime('%Y-%m-%d %H:%M')
            except ValueError:
                pass
        return date_str

    @staticmethod
    def _build_update_fields(field: str, value: str) -> Dict[str, Any]:
        '''
        Build the ``fields`` dict for a ``jira.issue(key).update(fields=...)``
        call.  Jira Cloud expects array-of-objects for components, fixVersions,
        and versions (affectedVersion).

        Input:
            field:  Canonical field name from the action dict (e.g. 'components').
            value:  The predicted string value.

        Output:
            Dict suitable for ``issue.update(fields=result)``.
        '''
        lower = field.lower().replace('_', '').replace('-', '')

        if lower in {'component', 'components'}:
            return {'components': [{'name': value}]}
        if lower in {'affectedversion', 'affectedversions', 'affectsversion',
                      'affectsversions', 'versions'}:
            return {'versions': [{'name': value}]}
        if lower in {'fixversion', 'fixversions'}:
            return {'fixVersions': [{'name': value}]}
        if lower == 'priority':
            return {'priority': {'name': value}}
        if lower == 'labels':
            return {'labels': [value]}

        return {field: value}

    # ------------------------------------------------------------------
    # Core orchestration — implements the monitoring loop
    # ------------------------------------------------------------------

    def run(self, input_data: Any = None) -> AgentResponse:
        '''
        Run the ticket monitoring loop.

        Input:
            input_data: Optional dict with overrides:
                - since (str):   ISO timestamp to use instead of last_checked.
                - project (str): Override project from config.

        Output:
            AgentResponse with a summary of actions taken.
        '''
        overrides = input_data if isinstance(input_data, dict) else {}
        project = overrides.get('project') or self.monitor_config.project
        since_override: Optional[str] = overrides.get('since')

        if not project:
            return AgentResponse.error_response('No project configured or provided.')

        log.info('TicketMonitorAgent.run() — project=%s dry_run=%s', project, self.dry_run)

        stats: Dict[str, int] = {
            'tickets_queried': 0,
            'tickets_skipped': 0,
            'tickets_processed': 0,
            'auto_fills': 0,
            'suggestions': 0,
            'flags': 0,
            'errors': 0,
            'corrections_detected': 0,
        }

        try:
            jira = self._get_jira()
        except Exception as exc:
            log.error('Failed to connect to Jira: %s', exc)
            return AgentResponse.error_response(f'Jira connection failed: {exc}')

        last_checked = since_override or self.state.get_last_checked(project)
        if last_checked:
            last_checked = self._normalize_date(last_checked)
        if not last_checked:
            last_checked = (
                datetime.now(timezone.utc) - timedelta(hours=24)
            ).strftime('%Y-%m-%d %H:%M')

        log.info('Querying tickets created since %s', last_checked)

        jql = f'project = {project} AND created >= "{last_checked}" ORDER BY created ASC'
        try:
            raw_issues = paginated_jql_search(jira, jql, max_results=None)
        except Exception as exc:
            log.error('JQL search failed: %s', exc)
            return AgentResponse.error_response(f'JQL search failed: {exc}')

        stats['tickets_queried'] = len(raw_issues)
        log.info('Found %d tickets since %s', len(raw_issues), last_checked)

        for raw_issue in raw_issues:
            try:
                ticket = issue_to_dict(raw_issue)
            except Exception as exc:
                log.error('Failed to convert issue to dict: %s', exc)
                stats['errors'] += 1
                continue

            ticket_key = ticket.get('key', '')
            if not ticket_key:
                stats['errors'] += 1
                continue

            if self.state.is_processed(ticket_key):
                stats['tickets_skipped'] += 1
                continue

            try:
                self._process_ticket(ticket, project, stats)
            except Exception as exc:
                log.error('Error processing %s: %s', ticket_key, exc, exc_info=True)
                stats['errors'] += 1

        try:
            self._check_corrections(jira, project, last_checked, stats)
        except Exception as exc:
            log.error('Feedback loop error: %s', exc, exc_info=True)

        self.state.set_last_checked(project)

        summary = self._build_summary(stats, project)

        return AgentResponse.success_response(
            content=summary,
            metadata={'stats': stats, 'project': project},
        )

    # ------------------------------------------------------------------
    # Per-ticket processing
    # ------------------------------------------------------------------

    def _process_ticket(
        self,
        ticket: Dict[str, Any],
        project: str,
        stats: Dict[str, int],
    ) -> None:
        '''Validate a single ticket and execute resulting actions.'''
        ticket_key = ticket['key']
        log.debug('Processing %s (%s)', ticket_key, ticket.get('issue_type', '?'))

        self.learning.record_ticket(ticket)

        validation = validate_ticket(ticket, self.monitor_config)

        if not validation.missing_required and not validation.missing_warned:
            self.state.mark_processed(ticket_key, project=project)
            stats['tickets_processed'] += 1
            log.debug('%s — all fields present, no action needed', ticket_key)
            return

        validation = determine_actions(validation, self.learning, self.monitor_config)

        for action in validation.actions:
            self._execute_action(ticket_key, action, ticket, stats)

        result_dict = {
            'issue_type': validation.issue_type,
            'missing_required': validation.missing_required,
            'missing_warned': validation.missing_warned,
            'actions': validation.actions,
        }
        self.state.mark_processed(ticket_key, project=project, result=result_dict)
        stats['tickets_processed'] += 1

    def _execute_action(
        self,
        ticket_key: str,
        action: Dict[str, Any],
        ticket: Dict[str, Any],
        stats: Dict[str, int],
    ) -> None:
        '''Execute a single action (auto_fill, suggest, flag, or warn).'''
        action_type = action.get('action', 'flag')
        field = action.get('field', '')
        value = action.get('value')
        confidence = action.get('confidence', 0.0)

        if action_type == 'auto_fill':
            self._do_auto_fill(ticket_key, field, value, confidence, stats)
        elif action_type == 'suggest':
            self._do_suggest(ticket_key, field, value, confidence, stats)
        elif action_type == 'flag':
            self._do_flag(ticket_key, field, stats)
        elif action_type == 'warn':
            # Warnings are informational — log but don't notify.
            log.info('%s — warn: missing optional field %s', ticket_key, field)
        else:
            log.warning('%s — unknown action type: %s', ticket_key, action_type)

    def _do_auto_fill(
        self,
        ticket_key: str,
        field: str,
        value: Any,
        confidence: float,
        stats: Dict[str, int],
    ) -> None:
        '''Auto-fill a field on the ticket and notify.'''
        if not value:
            log.warning('%s — auto_fill requested but no predicted value for %s', ticket_key, field)
            return

        log.info(
            '%s — auto_fill: %s = %s (confidence: %.0f%%)',
            ticket_key, field, value, confidence * 100,
        )

        if self.dry_run:
            stats['auto_fills'] += 1
            return

        try:
            jira = self._get_jira()
            update_fields = self._build_update_fields(field, str(value))
            issue = jira.issue(ticket_key)
            issue.update(fields=update_fields)
            log.info('%s — updated field %s to %s', ticket_key, field, value)
        except Exception as exc:
            log.error('%s — failed to update field %s: %s', ticket_key, field, exc)
            stats['errors'] += 1
            return

        try:
            notifier = self._get_notifier()
            reason = f'learned patterns (confidence {confidence:.0%})'
            notifier.send_auto_fill(ticket_key, field, str(value), confidence, reason)
        except Exception as exc:
            log.error('%s — failed to post auto_fill comment: %s', ticket_key, exc)

        self.learning.record_auto_fill(ticket_key, field, str(value), confidence)
        self.learning.record_observation(ticket_key, field, str(value), str(value), correct=True)
        stats['auto_fills'] += 1

    def _do_suggest(
        self,
        ticket_key: str,
        field: str,
        value: Any,
        confidence: float,
        stats: Dict[str, int],
    ) -> None:
        '''Post a suggestion comment on the ticket.'''
        if not value:
            log.warning('%s — suggest requested but no predicted value for %s', ticket_key, field)
            return

        log.info(
            '%s — suggest: %s = %s (confidence: %.0f%%)',
            ticket_key, field, value, confidence * 100,
        )

        if self.dry_run:
            stats['suggestions'] += 1
            return

        try:
            notifier = self._get_notifier()
            reason = f'similar tickets (confidence {confidence:.0%})'
            notifier.send_suggestion(ticket_key, field, str(value), confidence, reason)
        except Exception as exc:
            log.error('%s — failed to post suggestion comment: %s', ticket_key, exc)
            stats['errors'] += 1
            return

        stats['suggestions'] += 1

    def _do_flag(
        self,
        ticket_key: str,
        field: str,
        stats: Dict[str, int],
    ) -> None:
        '''Flag a missing required field on the ticket.'''
        log.info('%s — flag: missing required field %s', ticket_key, field)

        if self.dry_run:
            stats['flags'] += 1
            return

        try:
            notifier = self._get_notifier()
            notifier.send_flag(ticket_key, [field])
        except Exception as exc:
            log.error('%s — failed to post flag comment: %s', ticket_key, exc)
            stats['errors'] += 1
            return

        stats['flags'] += 1

    # ------------------------------------------------------------------
    # Feedback loop — detect human corrections to auto-filled fields
    # ------------------------------------------------------------------

    def _check_corrections(
        self,
        jira: Any,
        project: str,
        last_checked: str,
        stats: Dict[str, int],
    ) -> None:
        '''
        Query tickets that were updated since last_checked and that we
        previously auto-filled.  If a human changed the value we set,
        record the correction so the learning store can improve.
        '''
        if not self.monitor_config.feedback_detection:
            return

        conn = self.learning._require_conn()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT DISTINCT ticket_key, field, value_set
            FROM auto_fill_log
            WHERE corrected_by_human = 0
            ORDER BY ticket_key
            '''
        )
        auto_filled_rows = cursor.fetchall()

        if not auto_filled_rows:
            return

        ticket_fields: Dict[str, List[Dict[str, str]]] = {}
        for row in auto_filled_rows:
            tk = str(row['ticket_key'])
            ticket_fields.setdefault(tk, []).append({
                'field': str(row['field']),
                'value_set': str(row['value_set']),
            })

        ticket_keys = list(ticket_fields.keys())
        batch_size = 50
        for i in range(0, len(ticket_keys), batch_size):
            batch = ticket_keys[i:i + batch_size]
            keys_jql = ', '.join(batch)
            jql = (
                f'key IN ({keys_jql}) '
                f'AND updated >= "{last_checked}"'
            )
            try:
                updated_issues = paginated_jql_search(jira, jql, max_results=None)
            except Exception as exc:
                log.error('Feedback query failed: %s', exc)
                continue

            for raw_issue in updated_issues:
                try:
                    ticket = issue_to_dict(raw_issue)
                except Exception:
                    continue

                tk = ticket.get('key', '')
                if tk not in ticket_fields:
                    continue

                for entry in ticket_fields[tk]:
                    af_field = entry['field']
                    af_value = entry['value_set']
                    current_value = self._get_current_field_value(ticket, af_field)

                    if current_value and current_value != af_value:
                        log.info(
                            '%s — correction detected: %s changed from %s to %s',
                            tk, af_field, af_value, current_value,
                        )
                        self.learning.update_from_correction(
                            tk, af_field, af_value, current_value
                        )
                        stats['corrections_detected'] += 1

    @staticmethod
    def _get_current_field_value(ticket: Dict[str, Any], field: str) -> str:
        '''
        Extract the current value of a field from a ticket dict.
        Handles the various key aliases produced by issue_to_dict().
        '''
        lower = field.lower().replace('_', '')

        if field in ticket:
            val = ticket[field]
            if isinstance(val, list):
                return ', '.join(str(v) for v in val) if val else ''
            return str(val).strip() if val else ''

        alias_map: Dict[str, List[str]] = {
            'component': ['component', 'components'],
            'components': ['component', 'components'],
            'affectsversion': ['affects_version', 'affects_versions'],
            'affectsversions': ['affects_version', 'affects_versions'],
            'versions': ['affects_version', 'affects_versions'],
            'fixversion': ['fix_version', 'fix_versions'],
            'fixversions': ['fix_version', 'fix_versions'],
            'priority': ['priority', 'priority_name'],
            'labels': ['labels_csv', 'labels'],
        }

        for candidate in alias_map.get(lower, []):
            val = ticket.get(candidate)
            if val is not None:
                if isinstance(val, list):
                    return ', '.join(str(v) for v in val) if val else ''
                return str(val).strip() if val else ''

        return ''

    # ------------------------------------------------------------------
    # Learning-only mode
    # ------------------------------------------------------------------

    def run_learning_only(self, since: Optional[str] = None) -> AgentResponse:
        '''
        Process tickets to build the learning store without taking any actions.

        Input:
            since: Optional ISO timestamp.  Defaults to 24h ago.

        Output:
            AgentResponse with a summary of tickets processed.
        '''
        project = self.monitor_config.project
        if not project:
            return AgentResponse.error_response('No project configured.')

        log.info('run_learning_only — project=%s', project)

        last_checked = since
        if not last_checked:
            last_checked = (
                datetime.now(timezone.utc) - timedelta(hours=24)
            ).strftime('%Y-%m-%d %H:%M')

        jql = f'project = {project} AND created >= "{last_checked}" ORDER BY created ASC'

        try:
            jira = self._get_jira()
            raw_issues = paginated_jql_search(jira, jql, max_results=None)
        except Exception as exc:
            log.error('Learning-only query failed: %s', exc)
            return AgentResponse.error_response(f'Query failed: {exc}')

        processed = 0
        errors = 0
        for raw_issue in raw_issues:
            try:
                ticket = issue_to_dict(raw_issue)
                self.learning.record_ticket(ticket)
                processed += 1
            except Exception as exc:
                log.error('Failed to record ticket for learning: %s', exc)
                errors += 1

        summary = (
            f'Learning-only complete: {processed} tickets recorded, '
            f'{errors} errors.'
        )
        log.info(summary)
        return AgentResponse.success_response(
            content=summary,
            metadata={'tickets_recorded': processed, 'errors': errors},
        )

    # ------------------------------------------------------------------
    # Status / stats
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        '''
        Return current state stats and learning stats.

        Output:
            Dict with monitor_state and learning_store statistics.
        '''
        return {
            'monitor_state': self.state.get_stats(),
            'learning_store': self.learning.get_stats(),
            'project': self.monitor_config.project,
            'dry_run': self.dry_run,
        }

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(
        self,
        project: Optional[str] = None,
        since: Optional[str] = None,
    ) -> AgentResponse:
        '''
        Query tickets and produce a categorized report grouped by issue type,
        flagging tickets that are missing required or warned fields.

        Returns:
            AgentResponse with formatted report as content and structured
            data in metadata.
        '''
        project = project or self.monitor_config.project
        if not project:
            return AgentResponse.error_response('No project configured.')

        since_date = since
        if since_date:
            since_date = self._normalize_date(since_date)
        if not since_date:
            since_date = (
                datetime.now(timezone.utc) - timedelta(hours=24)
            ).strftime('%Y-%m-%d %H:%M')

        jql = f'project = {project} AND created >= "{since_date}" ORDER BY created ASC'
        log.info('Generating report — project=%s since=%s', project, since_date)

        try:
            jira = self._get_jira()
            raw_issues = paginated_jql_search(jira, jql, max_results=None)
        except Exception as exc:
            log.error('Report query failed: %s', exc)
            return AgentResponse.error_response(f'Query failed: {exc}')

        log.info('Found %d tickets for report', len(raw_issues))

        tickets_by_type: Dict[str, list] = {}
        total_flagged = 0

        for raw_issue in raw_issues:
            try:
                ticket = issue_to_dict(raw_issue)
                validation = validate_ticket(ticket, self.monitor_config)

                issue_type = ticket.get('issue_type', 'Unknown')
                missing_req = validation.missing_required
                missing_warn = validation.missing_warned

                entry = {
                    'key': ticket.get('key', '?'),
                    'issue_type': issue_type,
                    'summary': ticket.get('summary', ''),
                    'status': ticket.get('status', ''),
                    'priority': ticket.get('priority', ''),
                    'assignee': ticket.get('assignee', 'Unassigned'),
                    'components': ', '.join(ticket.get('components', [])) or '—',
                    'missing_required': missing_req,
                    'missing_warned': missing_warn,
                    'flagged': bool(missing_req),
                }

                if missing_req:
                    total_flagged += 1

                tickets_by_type.setdefault(issue_type, []).append(entry)
            except Exception as exc:
                log.error('Error processing ticket for report: %s', exc)

        report = self._format_report(tickets_by_type, project, since_date, total_flagged)

        return AgentResponse.success_response(
            content=report,
            metadata={
                'project': project,
                'since': since_date,
                'total_tickets': sum(len(v) for v in tickets_by_type.values()),
                'total_flagged': total_flagged,
                'by_type': {k: len(v) for k, v in tickets_by_type.items()},
            },
        )

    def generate_daily_report(self, project: Optional[str] = None) -> AgentResponse:
        project = project or self.monitor_config.project
        if not project:
            return AgentResponse.error_response('No project configured.')

        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        today_display = datetime.now(timezone.utc).strftime('%A %B %d, %Y')

        try:
            jira = self._get_jira()
        except Exception as exc:
            return AgentResponse.error_response(f'Jira connection failed: {exc}')

        log.info('Generating daily bug report — project=%s date=%s', project, today)

        opened_bugs: list = []
        closed_bugs: list = []
        open_p0_p1: list = []

        try:
            opened_jql = (
                f'project = {project} AND issuetype = Bug '
                f'AND created >= "{today}" ORDER BY priority ASC, created ASC'
            )
            for raw in paginated_jql_search(jira, opened_jql, max_results=None):
                ticket = issue_to_dict(raw)
                validation = validate_ticket(ticket, self.monitor_config)
                opened_bugs.append(self._daily_entry(ticket, validation))
        except Exception as exc:
            log.error('Failed querying opened bugs: %s', exc)

        try:
            closed_jql = (
                f'project = {project} AND issuetype = Bug '
                f'AND status changed to (Closed, Done, Resolved) AFTER startOfDay() '
                f'ORDER BY priority ASC, resolutiondate ASC'
            )
            for raw in paginated_jql_search(jira, closed_jql, max_results=None):
                ticket = issue_to_dict(raw)
                closed_bugs.append(self._daily_entry(ticket, None))
        except Exception as exc:
            log.error('Failed querying closed bugs: %s', exc)

        try:
            open_jql = (
                f'project = {project} AND issuetype = Bug '
                f'AND status not in (Closed, Done, Resolved) '
                f'AND priority in ("P0-Stopper", "P1-Critical") '
                f'ORDER BY priority ASC, created ASC'
            )
            for raw in paginated_jql_search(jira, open_jql, max_results=None):
                ticket = issue_to_dict(raw)
                validation = validate_ticket(ticket, self.monitor_config)
                open_p0_p1.append(self._daily_entry(ticket, validation))
        except Exception as exc:
            log.error('Failed querying open P0/P1 bugs: %s', exc)

        log.info(
            'Daily: %d opened, %d closed, %d open P0/P1',
            len(opened_bugs), len(closed_bugs), len(open_p0_p1),
        )

        report = self._format_daily_report(
            opened_bugs, closed_bugs, open_p0_p1, project, today_display,
        )

        return AgentResponse.success_response(
            content=report,
            metadata={
                'project': project,
                'date': today,
                'opened': len(opened_bugs),
                'closed': len(closed_bugs),
                'open_p0_p1': len(open_p0_p1),
            },
        )

    @staticmethod
    def _daily_entry(ticket: dict, validation: Optional['ValidationResult']) -> dict:
        created_str = ticket.get('created', '')
        age_days = None
        if created_str:
            try:
                created_dt = datetime.fromisoformat(
                    created_str.replace('Z', '+00:00').split('.')[0]
                )
                age_days = (datetime.now(timezone.utc) - created_dt.replace(
                    tzinfo=timezone.utc if created_dt.tzinfo is None else created_dt.tzinfo
                )).days
            except (ValueError, TypeError):
                pass

        resolved_str = ticket.get('resolution_date') or ticket.get('resolutiondate', '')
        resolve_days = None
        if resolved_str and created_str:
            try:
                created_dt = datetime.fromisoformat(
                    created_str.replace('Z', '+00:00').split('.')[0]
                )
                resolved_dt = datetime.fromisoformat(
                    resolved_str.replace('Z', '+00:00').split('.')[0]
                )
                delta = resolved_dt - created_dt
                resolve_days = round(delta.total_seconds() / 86400, 1)
            except (ValueError, TypeError):
                pass

        return {
            'key': ticket.get('key', '?'),
            'summary': ticket.get('summary', ''),
            'status': ticket.get('status', ''),
            'priority': ticket.get('priority', ''),
            'assignee': ticket.get('assignee', 'Unassigned'),
            'components': ', '.join(ticket.get('components', [])) or '—',
            'missing_required': validation.missing_required if validation else [],
            'missing_warned': validation.missing_warned if validation else [],
            'flagged': bool(validation and validation.missing_required),
            'age_days': age_days,
            'resolve_days': resolve_days,
        }

    @staticmethod
    def _format_daily_report(
        opened: list,
        closed: list,
        open_p0_p1: list,
        project: str,
        date_display: str,
    ) -> str:
        lines: list = []
        priority_order = ['P0-Stopper', 'P1-Critical', 'P2-High', 'P3-Medium', 'P4-Low']

        def _sort_key(p: str) -> int:
            return priority_order.index(p) if p in priority_order else 999

        def _group_by_priority(entries: list) -> Dict[str, list]:
            groups: Dict[str, list] = {}
            for e in entries:
                groups.setdefault(e['priority'], []).append(e)
            return dict(sorted(groups.items(), key=lambda kv: _sort_key(kv[0])))

        net = len(opened) - len(closed)
        net_str = f'+{net}' if net > 0 else str(net)
        p0_count = sum(1 for e in open_p0_p1 if e['priority'] == 'P0-Stopper')
        p1_count = sum(1 for e in open_p0_p1 if e['priority'] == 'P1-Critical')

        lines.append(f'Bug Daily Report — {project} ({date_display})')
        lines.append('=' * 80)

        key_w, status_w, assignee_w, comp_w = 14, 14, 18, 20

        lines.append('')
        opened_flagged = sum(1 for e in opened if e['flagged'])
        lines.append(f'  OPENED TODAY ({len(opened)} bugs, {opened_flagged} flagged)')
        lines.append(f'  {"-" * 76}')
        if opened:
            for pri, entries in _group_by_priority(opened).items():
                flagged_ct = sum(1 for e in entries if e['flagged'])
                lines.append(f'    {pri} ({len(entries)} bugs, {flagged_ct} flagged)')
                lines.append(f'    {"·" * 72}')
                lines.append(
                    f'    {"Key":<{key_w}} {"Status":<{status_w}} '
                    f'{"Assignee":<{assignee_w}} {"Components":<{comp_w}} Missing'
                )
                lines.append(
                    f'    {"—" * key_w} {"—" * status_w} '
                    f'{"—" * assignee_w} {"—" * comp_w} {"—" * 16}'
                )
                for e in entries:
                    flag = '⚠️ ' if e['flagged'] else '   '
                    lines.append(
                        f' {flag}{e["key"]:<{key_w}} {e["status"][:status_w]:<{status_w}} '
                        f'{(e["assignee"] or "Unassigned")[:assignee_w]:<{assignee_w}} '
                        f'{e["components"][:comp_w]:<{comp_w}} '
                        f'{TicketMonitorAgent._missing_str(e)}'
                    )
                lines.append('')
        else:
            lines.append('    (none)')
            lines.append('')

        lines.append(f'  CLOSED TODAY ({len(closed)} bugs)')
        lines.append(f'  {"-" * 76}')
        if closed:
            for pri, entries in _group_by_priority(closed).items():
                lines.append(f'    {pri} ({len(entries)} bugs)')
                lines.append(f'    {"·" * 72}')
                lines.append(
                    f'    {"Key":<{key_w}} {"Status":<{status_w}} '
                    f'{"Assignee":<{assignee_w}} {"Components":<{comp_w}} Resolved In'
                )
                lines.append(
                    f'    {"—" * key_w} {"—" * status_w} '
                    f'{"—" * assignee_w} {"—" * comp_w} {"—" * 16}'
                )
                for e in entries:
                    resolve_str = f'{e["resolve_days"]}d' if e['resolve_days'] is not None else '—'
                    lines.append(
                        f'   {e["key"]:<{key_w}} {e["status"][:status_w]:<{status_w}} '
                        f'{(e["assignee"] or "Unassigned")[:assignee_w]:<{assignee_w}} '
                        f'{e["components"][:comp_w]:<{comp_w}} {resolve_str}'
                    )
                lines.append('')
        else:
            lines.append('    (none)')
            lines.append('')

        lines.append(f'  STILL OPEN P0/P1 ({len(open_p0_p1)} bugs)')
        lines.append(f'  {"-" * 76}')
        if open_p0_p1:
            for pri, entries in _group_by_priority(open_p0_p1).items():
                flagged_ct = sum(1 for e in entries if e['flagged'])
                lines.append(f'    {pri} ({len(entries)} bugs, {flagged_ct} flagged)')
                lines.append(f'    {"·" * 72}')
                lines.append(
                    f'    {"Key":<{key_w}} {"Status":<{status_w}} '
                    f'{"Assignee":<{assignee_w}} {"Components":<{comp_w}} Age    Missing'
                )
                lines.append(
                    f'    {"—" * key_w} {"—" * status_w} '
                    f'{"—" * assignee_w} {"—" * comp_w} {"—" * 6} {"—" * 16}'
                )
                for e in entries:
                    flag = '⚠️ ' if e['flagged'] else '   '
                    age_str = f'{e["age_days"]}d' if e['age_days'] is not None else '—'
                    lines.append(
                        f' {flag}{e["key"]:<{key_w}} {e["status"][:status_w]:<{status_w}} '
                        f'{(e["assignee"] or "Unassigned")[:assignee_w]:<{assignee_w}} '
                        f'{e["components"][:comp_w]:<{comp_w}} '
                        f'{age_str:<6} {TicketMonitorAgent._missing_str(e)}'
                    )
                lines.append('')
        else:
            lines.append('    (none)')
            lines.append('')

        lines.append('=' * 80)
        lines.append(
            f'  Summary: +{len(opened)} opened, -{len(closed)} closed, '
            f'net {net_str} | {len(open_p0_p1)} open P0/P1 '
            f'({p0_count} P0, {p1_count} P1)'
        )
        lines.append('=' * 80)

        return '\n'.join(lines)

    @staticmethod
    def _format_report(
        tickets_by_type: Dict[str, list],
        project: str,
        since: str,
        total_flagged: int,
    ) -> str:
        total = sum(len(v) for v in tickets_by_type.values())
        lines: list = []

        lines.append(f'Ticket Report — {project} (since {since})')
        lines.append(f'Total: {total} tickets, {total_flagged} flagged')
        lines.append('=' * 80)

        type_order = ['Bug', 'Story', 'Epic', 'Sub-task', 'Initiative']
        sorted_types = sorted(
            tickets_by_type.keys(),
            key=lambda t: type_order.index(t) if t in type_order else 999,
        )

        for issue_type in sorted_types:
            entries = tickets_by_type[issue_type]
            flagged_count = sum(1 for e in entries if e['flagged'])
            lines.append('')
            lines.append(f'  {issue_type} ({len(entries)} tickets, {flagged_count} flagged)')
            lines.append(f'  {"-" * 76}')

            if issue_type == 'Bug':
                TicketMonitorAgent._format_bug_section(entries, lines)
            else:
                TicketMonitorAgent._format_ticket_table(entries, issue_type, lines)

            lines.append('')

        if not tickets_by_type:
            lines.append('')
            lines.append('  No tickets found.')
            lines.append('')

        lines.append('=' * 80)
        return '\n'.join(lines)

    @staticmethod
    def _format_ticket_table(entries: list, issue_type: str, lines: list) -> None:
        key_w, type_w, status_w, pri_w, assignee_w = 14, 12, 14, 14, 18
        lines.append(
            f'  {"Key":<{key_w}} {"Type":<{type_w}} {"Status":<{status_w}} '
            f'{"Priority":<{pri_w}} {"Assignee":<{assignee_w}} Missing'
        )
        lines.append(
            f'  {"—" * key_w} {"—" * type_w} {"—" * status_w} '
            f'{"—" * pri_w} {"—" * assignee_w} {"—" * 16}'
        )

        for entry in entries:
            flag = '⚠️ ' if entry['flagged'] else '   '
            missing_str = TicketMonitorAgent._missing_str(entry)
            key_str = entry['key'][:key_w]
            type_str = entry.get('issue_type', issue_type)[:type_w]
            status_str = entry['status'][:status_w]
            pri_str = entry['priority'][:pri_w]
            assignee_str = (entry['assignee'] or 'Unassigned')[:assignee_w]

            lines.append(
                f'{flag}{key_str:<{key_w}} {type_str:<{type_w}} {status_str:<{status_w}} '
                f'{pri_str:<{pri_w}} {assignee_str:<{assignee_w}} {missing_str}'
            )

    @staticmethod
    def _format_bug_section(entries: list, lines: list) -> None:
        priority_order = ['P0-Stopper', 'P1-Critical', 'P2-High', 'P3-Medium', 'P4-Low']
        bugs_by_priority: Dict[str, list] = {}
        for entry in entries:
            pri = entry.get('priority', 'Unknown')
            bugs_by_priority.setdefault(pri, []).append(entry)

        sorted_priorities = sorted(
            bugs_by_priority.keys(),
            key=lambda p: priority_order.index(p) if p in priority_order else 999,
        )

        key_w, status_w, assignee_w, comp_w = 14, 14, 18, 20
        for priority in sorted_priorities:
            pri_entries = bugs_by_priority[priority]
            flagged_count = sum(1 for e in pri_entries if e['flagged'])
            lines.append('')
            lines.append(f'    {priority} ({len(pri_entries)} bugs, {flagged_count} flagged)')
            lines.append(f'    {"·" * 72}')
            lines.append(
                f'    {"Key":<{key_w}} {"Status":<{status_w}} '
                f'{"Assignee":<{assignee_w}} {"Components":<{comp_w}} Missing'
            )
            lines.append(
                f'    {"—" * key_w} {"—" * status_w} '
                f'{"—" * assignee_w} {"—" * comp_w} {"—" * 16}'
            )

            for entry in pri_entries:
                flag = '⚠️ ' if entry['flagged'] else '   '
                missing_str = TicketMonitorAgent._missing_str(entry)
                key_str = entry['key'][:key_w]
                status_str = entry['status'][:status_w]
                assignee_str = (entry['assignee'] or 'Unassigned')[:assignee_w]
                comp_str = entry.get('components', '—')[:comp_w]

                lines.append(
                    f' {flag}{key_str:<{key_w}} {status_str:<{status_w}} '
                    f'{assignee_str:<{assignee_w}} {comp_str:<{comp_w}} {missing_str}'
                )

    @staticmethod
    def _missing_str(entry: dict) -> str:
        parts: list = []
        if entry['missing_required']:
            parts.append(', '.join(entry['missing_required']))
        if entry['missing_warned']:
            parts.append(f"(warn: {', '.join(entry['missing_warned'])})")
        return ' '.join(parts) if parts else '✓'

    @staticmethod
    def _build_summary(stats: Dict[str, int], project: str) -> str:
        lines = [
            f'Ticket Monitor run complete for project {project}:',
            f'  Tickets queried:  {stats["tickets_queried"]}',
            f'  Tickets skipped:  {stats["tickets_skipped"]}',
            f'  Tickets processed:{stats["tickets_processed"]}',
            f'  Auto-fills:       {stats["auto_fills"]}',
            f'  Suggestions:      {stats["suggestions"]}',
            f'  Flags:            {stats["flags"]}',
            f'  Corrections:      {stats["corrections_detected"]}',
            f'  Errors:           {stats["errors"]}',
        ]
        return '\n'.join(lines)

    def close(self) -> None:
        try:
            self.state.close()
        except Exception:
            pass
        try:
            self.learning.close()
        except Exception:
            pass
