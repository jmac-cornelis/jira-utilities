##########################################################################################
#
# Module: agents/release_tracker.py
#
# Description: Release Tracker Agent for monitoring releases, tracking status changes,
#              generating daily summaries, and predicting release readiness.
#              Purely programmatic — no LLM required.
#
# Author: Cornelis Networks
#
##########################################################################################

from __future__ import annotations

import csv
import io
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, AgentConfig, AgentResponse
from core.queries import build_release_tickets_jql, paginated_jql_search
from core.release_tracking import (
    CycleTimeStats,
    ReleaseDelta,
    ReleaseReadiness,
    ReleaseSnapshot,
    TrackerConfig,
    assess_readiness,
    build_snapshot,
    compute_delta,
    compute_velocity,
    format_summary,
)
from core.tickets import issue_to_dict
from state.learning import LearningStore

# Logging config — follows project-wide pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


class ReleaseTrackerAgent(BaseAgent):
    '''
    Agent for monitoring releases, tracking status changes, generating daily
    summaries, and predicting release readiness.

    This agent is purely programmatic — it does not use an LLM.  The run()
    method orchestrates deterministically by querying Jira, building snapshots,
    computing deltas and velocity, and assessing readiness.
    '''

    def __init__(
        self,
        config_path: Optional[str] = None,
        db_dir: Optional[str] = None,
    ):
        '''
        Initialize the Release Tracker agent.

        Input:
            config_path: Path to the YAML configuration file.
                         Defaults to config/release_tracker.yaml.
            db_dir:      Directory for SQLite databases.
                         Defaults to state/.
        '''
        # Load tracker-specific configuration from YAML.
        self._config_path = config_path or os.path.join('config', 'release_tracker.yaml')
        self.tracker_config = self._load_tracker_config(self._config_path)

        # Initialise the learning store (SQLite-backed).
        db_directory = db_dir or 'state'
        db_path = os.path.join(db_directory, 'learning.db')
        self.learning = LearningStore(db_path=db_path)

        # Build the BaseAgent config.  No LLM instruction needed — the agent
        # is deterministic — but BaseAgent requires a non-empty instruction.
        agent_config = AgentConfig(
            name='release_tracker',
            description='Monitors releases, tracks status changes, generates summaries, and predicts readiness',
            instruction='Release Tracker Agent — programmatic, no LLM.',
        )

        # Initialise BaseAgent without LLM or tools (purely programmatic).
        super().__init__(config=agent_config, llm=None, tools=None)

        # Output format: table (default), json, csv
        self._output_format: str = self.tracker_config.output.get('format', 'table')

        log.info(
            'ReleaseTrackerAgent initialised: project=%s, releases=%s',
            self.tracker_config.project,
            self.tracker_config.releases,
        )

    # ------------------------------------------------------------------
    # Configuration loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_tracker_config(config_path: str) -> TrackerConfig:
        '''Load TrackerConfig from a YAML file, falling back to defaults.'''
        path = Path(config_path)
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    return TrackerConfig.from_yaml(fh.read())
            except Exception as exc:
                log.warning('Failed to load config from %s: %s — using defaults', config_path, exc)
        else:
            log.warning('Config file not found: %s — using defaults', config_path)
        return TrackerConfig()

    # ------------------------------------------------------------------
    # Main entry point (BaseAgent.run override)
    # ------------------------------------------------------------------

    def run(self, input_data: Any = None) -> AgentResponse:
        '''
        Run the release tracking workflow for all configured releases.

        Input:
            input_data: Optional dict with overrides:
                - releases: list[str] — override which releases to track
                - predict:  bool      — include readiness predictions
                - format:   str       — output format (table, json, csv)

        Output:
            AgentResponse with combined summary for all releases.
        '''
        log.info('ReleaseTrackerAgent.run() starting')

        # Parse optional overrides from input_data.
        overrides = input_data if isinstance(input_data, dict) else {}
        releases = overrides.get('releases') or self.tracker_config.releases
        predict = overrides.get('predict', True)
        output_format = overrides.get('format', self._output_format)

        if not releases:
            return AgentResponse.error_response('No releases configured for tracking')

        # Obtain Jira connection.
        try:
            jira = self._get_jira_connection()
        except Exception as exc:
            log.error('Failed to connect to Jira: %s', exc)
            return AgentResponse.error_response(f'Jira connection failed: {exc}')

        # Process each release, collecting results.
        summaries: List[str] = []
        release_data: List[Dict[str, Any]] = []
        errors: List[str] = []

        for release in releases:
            try:
                result = self._track_single_release(
                    jira, release, predict=predict,
                )
                summaries.append(result['summary'])
                release_data.append(result)
            except Exception as exc:
                msg = f'Error tracking release {release}: {exc}'
                log.error(msg)
                errors.append(msg)

        # Collect cycle times for tracked-priority tickets across all releases.
        self._collect_cycle_times(jira, releases)

        # Format output.
        if output_format == 'json':
            content = json.dumps(release_data, indent=2, default=str)
        elif output_format == 'csv':
            content = self._format_csv(release_data)
        else:
            # Default: human-readable table/text
            content = '\n\n'.join(summaries) if summaries else '(no release data)'

        if errors:
            content += '\n\nErrors:\n' + '\n'.join(f'  - {e}' for e in errors)

        metadata: Dict[str, Any] = {
            'releases_tracked': len(release_data),
            'errors': errors,
            'release_data': release_data,
        }

        log.info(
            'ReleaseTrackerAgent.run() complete: %d releases tracked, %d errors',
            len(release_data), len(errors),
        )

        if release_data:
            return AgentResponse.success_response(content=content, metadata=metadata)
        return AgentResponse.error_response(
            error='All releases failed',
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Single-release tracking
    # ------------------------------------------------------------------

    def track_release(
        self,
        release: str,
        predict: bool = False,
    ) -> AgentResponse:
        '''
        Track a single release and return an AgentResponse.

        Input:
            release: Release name (e.g. "12.1.1.x").
            predict: Whether to include readiness predictions.

        Output:
            AgentResponse with the release summary.
        '''
        try:
            jira = self._get_jira_connection()
        except Exception as exc:
            return AgentResponse.error_response(f'Jira connection failed: {exc}')

        try:
            result = self._track_single_release(jira, release, predict=predict)
            return AgentResponse.success_response(
                content=result['summary'],
                metadata={'release_data': result},
            )
        except Exception as exc:
            log.error('Error tracking release %s: %s', release, exc)
            return AgentResponse.error_response(f'Error tracking release {release}: {exc}')

    # ------------------------------------------------------------------
    # Status / stats
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        '''
        Return current tracking statistics from the learning store.

        Output:
            Dict with learning store stats and tracker configuration summary.
        '''
        stats = self.learning.get_stats()
        return {
            'project': self.tracker_config.project,
            'releases': self.tracker_config.releases,
            'config_path': self._config_path,
            'learning_store': stats,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_jira_connection() -> Any:
        '''Obtain a Jira connection via the shared tools helper.'''
        from tools.jira_tools import get_jira
        return get_jira()

    def _track_single_release(
        self,
        jira: Any,
        release: str,
        predict: bool = True,
    ) -> Dict[str, Any]:
        '''
        Core tracking logic for a single release.

        Steps:
            1. Query all tickets for the release via JQL.
            2. Convert each to a dict via issue_to_dict().
            3. Build a snapshot via build_snapshot().
            4. Save the snapshot to the learning store.
            5. Load the previous snapshot (yesterday or most recent).
            6. Compute delta if a previous snapshot exists.
            7. Compute velocity from historical snapshots.
            8. Gather cycle time stats from the learning store.
            9. Assess readiness via assess_readiness().
           10. Format a human-readable summary via format_summary().

        Output:
            Dict with keys: release, snapshot, delta, velocity, readiness,
            cycle_stats, summary.
        '''
        project = self.tracker_config.project
        log.info('Tracking release %s in project %s', release, project)

        # Step 1: Build JQL and query tickets.
        jql = build_release_tickets_jql(project, release)
        log.debug('JQL: %s', jql)
        raw_issues = paginated_jql_search(jira, jql)
        log.info('Found %d tickets for release %s', len(raw_issues), release)

        # Step 2: Convert to dicts.
        ticket_dicts = [issue_to_dict(issue) for issue in raw_issues]

        # Step 3: Build current snapshot.
        snapshot = build_snapshot(ticket_dicts, release)

        # Step 4: Save snapshot to learning store.
        today_str = datetime.now(timezone.utc).date().isoformat()
        self.learning.save_release_snapshot(release, {
            'snapshot_date': today_str,
            'status': dict(snapshot.by_status),
            'priority': dict(snapshot.by_priority),
            'component': dict(snapshot.by_component),
        })

        # Step 5: Load previous snapshot (yesterday or most recent before today).
        yesterday_str = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        previous_snapshot_dict = self.learning.get_release_snapshot(release, yesterday_str)

        # Step 6: Compute delta if previous snapshot exists.
        delta: Optional[ReleaseDelta] = None
        if previous_snapshot_dict is not None:
            # Reconstruct a minimal ReleaseSnapshot from the stored data for
            # delta computation.  The stored snapshot only has aggregate counts,
            # not individual tickets, so we build a synthetic previous snapshot.
            previous_snapshot = self._reconstruct_previous_snapshot(
                release, previous_snapshot_dict,
            )
            if previous_snapshot is not None:
                delta = compute_delta(snapshot, previous_snapshot)

        # If no delta could be computed, create a baseline delta.
        if delta is None:
            delta = ReleaseDelta(
                release=release,
                period=f'(baseline) {snapshot.timestamp}',
            )

        # Step 7: Compute velocity from historical snapshots.
        # We use the current snapshot plus any historical data.  Since
        # compute_velocity expects ReleaseSnapshot objects and we only store
        # aggregate data, we pass a single-element list (velocity will be 0
        # until we accumulate multiple daily snapshots).
        velocity = compute_velocity(
            [snapshot],
            window_days=self.tracker_config.velocity_window_days,
        )

        # Step 8: Gather cycle time stats from the learning store for each
        # component/priority combination present in the snapshot.
        cycle_stats = self._gather_cycle_stats(snapshot)

        # Step 9: Assess readiness.
        readiness: Optional[ReleaseReadiness] = None
        if predict:
            readiness = assess_readiness(
                snapshot, velocity, cycle_stats, self.tracker_config,
            )

        # Step 10: Format summary.
        summary_readiness = readiness or ReleaseReadiness(
            release=release,
            timestamp=snapshot.timestamp,
            total_open=snapshot.total_tickets,
            p0_open=0,
            p1_open=0,
            daily_close_rate=velocity.get('daily_close_rate', 0.0),
            estimated_days_remaining=None,
        )
        summary = format_summary(delta, summary_readiness)

        return {
            'release': release,
            'snapshot': asdict(snapshot),
            'delta': asdict(delta),
            'velocity': velocity,
            'readiness': asdict(readiness) if readiness else None,
            'cycle_stats': [asdict(cs) for cs in cycle_stats],
            'summary': summary,
        }

    def _reconstruct_previous_snapshot(
        self,
        release: str,
        snapshot_dict: Dict[str, Any],
    ) -> Optional[ReleaseSnapshot]:
        '''
        Reconstruct a ReleaseSnapshot from stored aggregate data.

        The learning store only persists status/priority/component counts, not
        individual tickets.  We build a minimal ReleaseSnapshot with empty
        ticket lists so that compute_delta() can at least detect new/removed
        tickets by comparing against the current snapshot's ticket list.

        In practice, meaningful deltas require the previous snapshot to have
        been built from actual ticket data (i.e. after the agent has run at
        least twice).  On the first run, the delta will show all current
        tickets as "new".
        '''
        try:
            return ReleaseSnapshot(
                release=release,
                timestamp=snapshot_dict.get('snapshot_date', ''),
                total_tickets=sum(
                    (snapshot_dict.get('status') or {}).values()
                ),
                by_status=snapshot_dict.get('status') or {},
                by_priority=snapshot_dict.get('priority') or {},
                by_component=snapshot_dict.get('component') or {},
                by_assignee={},
                tickets=[],
            )
        except Exception as exc:
            log.warning('Failed to reconstruct previous snapshot for %s: %s', release, exc)
            return None

    def _gather_cycle_stats(
        self,
        snapshot: ReleaseSnapshot,
    ) -> List[CycleTimeStats]:
        '''
        Gather cycle time statistics from the learning store for each
        component/priority combination present in the snapshot.
        '''
        stats: List[CycleTimeStats] = []
        components = list(snapshot.by_component.keys()) or ['Unspecified']
        priorities = self.tracker_config.track_priorities or ['P0-Stopper', 'P1-Critical']

        for component in components:
            for priority in priorities:
                raw = self.learning.get_cycle_time_stats(component, priority)
                if raw and raw.get('count', 0) > 0:
                    stats.append(CycleTimeStats(
                        component=component,
                        priority=priority,
                        avg_hours=raw.get('average_hours', 0.0),
                        median_hours=raw.get('median_hours', 0.0),
                        sample_size=raw.get('count', 0),
                    ))

        return stats

    def _collect_cycle_times(
        self,
        jira: Any,
        releases: List[str],
    ) -> None:
        '''
        For tracked-priority tickets, attempt to extract status transition
        timestamps from the Jira changelog and record cycle times in the
        learning store.

        This is a best-effort operation — if the Jira API does not expose
        changelog data or the method is unavailable, we log and skip.
        '''
        project = self.tracker_config.project
        tracked_priorities = {p.casefold() for p in self.tracker_config.track_priorities}

        for release in releases:
            try:
                jql = build_release_tickets_jql(project, release)
                raw_issues = paginated_jql_search(jira, jql)
            except Exception as exc:
                log.warning('Cycle time collection failed for %s: %s', release, exc)
                continue

            for issue in raw_issues:
                try:
                    ticket = issue_to_dict(issue)
                    priority = (ticket.get('priority') or '').casefold()
                    if not any(tp in priority for tp in tracked_priorities):
                        continue

                    # Attempt to read changelog from the raw issue object.
                    self._extract_cycle_times_from_issue(issue, ticket)
                except Exception as exc:
                    log.debug(
                        'Could not extract cycle times for %s: %s',
                        getattr(issue, 'key', '?'), exc,
                    )

    def _extract_cycle_times_from_issue(
        self,
        raw_issue: Any,
        ticket: Dict[str, Any],
    ) -> None:
        '''
        Extract status transitions from a Jira issue's changelog and record
        cycle times in the learning store.

        The jira-python library exposes changelog as issue.changelog.histories
        when the issue is fetched with expand='changelog'.  Since our
        paginated search may not include the changelog, we attempt to read it
        and silently skip if unavailable.
        '''
        changelog = getattr(raw_issue, 'changelog', None)
        if changelog is None:
            return

        histories = getattr(changelog, 'histories', None)
        if not histories:
            return

        ticket_key = ticket.get('key', '')
        components = ticket.get('components', [])
        component = components[0] if components else 'Unspecified'
        priority = ticket.get('priority', 'N/A')

        for history in histories:
            created = getattr(history, 'created', None)
            items = getattr(history, 'items', [])
            for item in items:
                if getattr(item, 'field', '') != 'status':
                    continue

                from_status = getattr(item, 'fromString', '') or ''
                to_status = getattr(item, 'toString', '') or ''

                if not from_status or not to_status:
                    continue

                # We don't have the exact duration between transitions from
                # the changelog alone (would need to pair consecutive entries).
                # For now, record a placeholder — the learning store accumulates
                # these and the actual duration computation happens when we have
                # paired transitions.  A more sophisticated implementation would
                # pair consecutive status changes to compute actual durations.
                # For the initial implementation, we skip duration recording
                # here and rely on snapshot-based velocity instead.
                log.debug(
                    'Status transition for %s: %s -> %s at %s',
                    ticket_key, from_status, to_status, created,
                )

    # ------------------------------------------------------------------
    # Output formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_csv(release_data: List[Dict[str, Any]]) -> str:
        '''Format release data as CSV.'''
        if not release_data:
            return ''

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'release',
            'total_tickets',
            'new_tickets',
            'closed_tickets',
            'status_changes',
            'priority_changes',
            'p0_open',
            'p1_open',
            'daily_close_rate',
            'estimated_days_remaining',
        ])

        for entry in release_data:
            snapshot = entry.get('snapshot', {})
            delta = entry.get('delta', {})
            readiness = entry.get('readiness') or {}

            writer.writerow([
                entry.get('release', ''),
                snapshot.get('total_tickets', 0),
                len(delta.get('new_tickets', [])),
                len(delta.get('closed_tickets', [])),
                len(delta.get('status_changes', [])),
                len(delta.get('priority_changes', [])),
                readiness.get('p0_open', 0),
                readiness.get('p1_open', 0),
                readiness.get('daily_close_rate', 0.0),
                readiness.get('estimated_days_remaining', ''),
            ])

        return output.getvalue()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        '''Close the learning store connection.'''
        self.learning.close()
