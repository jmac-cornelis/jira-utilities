##########################################################################################
#
# Module: agents/gantt_agent.py
#
# Description: Gantt Project Planner Agent.
#              Produces evidence-backed planning snapshots, milestone proposals,
#              dependency views, and planning-risk summaries from Jira data.
#
# Author: Cornelis Networks
#
##########################################################################################

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from agents.base import BaseAgent, AgentConfig, AgentResponse
from agents.gantt_models import (
    DependencyEdge,
    DependencyGraph,
    MilestoneProposal,
    PlanningRequest,
    PlanningRiskRecord,
    PlanningSnapshot,
)
from core.tickets import issue_to_dict
from tools.jira_tools import JiraTools, get_jira, get_project_info, get_releases

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


class GanttProjectPlannerAgent(BaseAgent):
    '''
    Agent for producing project-planning snapshots from Jira data.

    The first implementation slice is deterministic by design. It creates a
    planning snapshot with milestone proposals, dependency edges, and risk
    records without needing an LLM call.
    '''

    STALE_DAYS = 30

    def __init__(self, project_key: Optional[str] = None, **kwargs):
        '''
        Initialize the Gantt Project Planner agent.
        '''
        instruction = self._load_prompt_file()
        if not instruction:
            raise FileNotFoundError(
                'config/prompts/gantt_agent.md is required but not found. '
                'The Gantt Project Planner Agent has no hardcoded fallback prompt.'
            )

        config = AgentConfig(
            name='gantt_project_planner',
            description='Builds planning snapshots, milestones, dependencies, and risks',
            instruction=instruction,
            max_iterations=10,
        )

        super().__init__(config=config, tools=[JiraTools()], **kwargs)
        self.project_key = project_key

    @staticmethod
    def _load_prompt_file() -> Optional[str]:
        '''Load the Gantt agent prompt from config/prompts/.'''
        prompt_path = os.path.join('config', 'prompts', 'gantt_agent.md')
        if os.path.exists(prompt_path):
            try:
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                log.warning(f'Failed to load Gantt agent prompt: {e}')
        return None

    @staticmethod
    def _utc_now() -> datetime:
        '''Return the current UTC time as a timezone-aware datetime.'''
        return datetime.now(timezone.utc)

    def run(self, input_data: Any) -> AgentResponse:
        '''
        Build a planning snapshot from Jira data.
        '''
        log.debug(f'GanttProjectPlannerAgent.run(input_data={input_data})')

        if isinstance(input_data, str):
            request = PlanningRequest(project_key=input_data)
        elif isinstance(input_data, dict):
            request = PlanningRequest(
                project_key=input_data.get('project_key', self.project_key or ''),
                planning_horizon_days=int(input_data.get('planning_horizon_days', 90)),
                limit=int(input_data.get('limit', 200)),
                include_done=bool(input_data.get('include_done', False)),
                backlog_jql=input_data.get('backlog_jql'),
                policy_profile=input_data.get('policy_profile', 'default'),
            )
        else:
            return AgentResponse.error_response(
                'Invalid input: expected project key string or request dict'
            )

        if not request.project_key:
            return AgentResponse.error_response('No project_key provided')

        try:
            snapshot = self.create_snapshot(request)
        except Exception as e:
            log.error(f'Gantt planning snapshot failed: {e}')
            return AgentResponse.error_response(str(e))

        return AgentResponse.success_response(
            content=snapshot.summary_markdown,
            metadata={'planning_snapshot': snapshot.to_dict()},
        )

    def create_snapshot(self, request: PlanningRequest) -> PlanningSnapshot:
        '''
        Create a deterministic planning snapshot from Jira backlog data.
        '''
        log.info(f'Creating Gantt planning snapshot for {request.project_key}')

        project_info = self._load_project_info(request.project_key)
        releases = self._load_releases(request.project_key)
        issues = self._load_backlog_issues(request)
        dependency_graph = self._build_dependency_graph(issues)
        milestones = self._build_milestones(issues, releases, dependency_graph)
        evidence_gaps = self._build_evidence_gaps(issues)
        risks = self._build_risks(issues, milestones, dependency_graph)
        backlog_overview = self._build_backlog_overview(
            issues,
            milestones,
            dependency_graph,
            risks,
        )

        snapshot = PlanningSnapshot(
            project_key=request.project_key,
            planning_horizon_days=request.planning_horizon_days,
            project_info=project_info,
            backlog_overview=backlog_overview,
            milestones=milestones,
            dependency_graph=dependency_graph,
            risks=risks,
            issues=issues,
            evidence_gaps=evidence_gaps,
        )
        snapshot.summary_markdown = self._format_snapshot(snapshot)
        return snapshot

    def _load_project_info(self, project_key: str) -> Dict[str, Any]:
        result = get_project_info(project_key)
        if result.is_success:
            return result.data
        raise RuntimeError(result.error or f'Failed to load project info for {project_key}')

    def _load_releases(self, project_key: str) -> List[Dict[str, Any]]:
        result = get_releases(
            project_key,
            include_released=True,
            include_unreleased=True,
        )
        if result.is_success:
            return result.data
        raise RuntimeError(result.error or f'Failed to load releases for {project_key}')

    def _load_backlog_issues(self, request: PlanningRequest) -> List[Dict[str, Any]]:
        '''
        Query Jira directly so dependency-related fields remain available.
        '''
        jira = get_jira()
        jql = request.backlog_jql or self._build_backlog_jql(request)
        fields = ','.join([
            'summary',
            'description',
            'issuetype',
            'status',
            'priority',
            'assignee',
            'reporter',
            'created',
            'updated',
            'resolutiondate',
            'project',
            'fixVersions',
            'versions',
            'components',
            'labels',
            'issuelinks',
            'parent',
            'duedate',
        ])
        issues = jira.search_issues(jql, maxResults=request.limit, fields=fields)
        normalized = [self._normalize_issue(issue) for issue in issues]
        return normalized

    @staticmethod
    def _build_backlog_jql(request: PlanningRequest) -> str:
        clauses = [
            f'project = "{request.project_key}"',
            'issuetype != "Sub-task"',
        ]
        if not request.include_done:
            clauses.append('statusCategory != Done')
        return ' AND '.join(clauses) + ' ORDER BY updated DESC'

    def _normalize_issue(self, issue: Any) -> Dict[str, Any]:
        base = issue_to_dict(issue)
        raw = getattr(issue, 'raw', None) if hasattr(issue, 'raw') else issue
        fields = raw.get('fields', {}) if isinstance(raw, dict) else {}

        parent = fields.get('parent') or {}
        parent_key = parent.get('key', '') if isinstance(parent, dict) else ''
        due_date = str(fields.get('duedate') or '')
        status_obj = fields.get('status') or {}
        status_category = ''
        if isinstance(status_obj, dict):
            status_category = str(
                (status_obj.get('statusCategory') or {}).get('name', '') or ''
            )

        updated_ts = base.get('updated') or ''
        updated_dt = self._parse_jira_datetime(updated_ts)
        now = self._utc_now()
        age_days = (now - updated_dt).days if updated_dt else 0
        is_done = status_category.casefold() == 'done' or self._is_done_status(
            base.get('status', '')
        )

        edges = self._extract_edges(base['key'], parent_key, fields.get('issuelinks') or [])

        normalized = dict(base)
        normalized.update({
            'parent_key': parent_key,
            'due_date': due_date,
            'status_category': status_category,
            'is_done': is_done,
            'age_days': age_days,
            'is_stale': age_days >= self.STALE_DAYS and not is_done,
            'dependency_edges': [edge.to_dict() for edge in edges],
        })
        return normalized

    def _extract_edges(
        self,
        issue_key: str,
        parent_key: str,
        issue_links: Iterable[Any],
    ) -> List[DependencyEdge]:
        edges: List[DependencyEdge] = []

        if parent_key:
            edges.append(
                DependencyEdge(
                    source_key=parent_key,
                    target_key=issue_key,
                    relationship='parent_of',
                    evidence='jira_parent',
                )
            )

        for link in issue_links:
            if not isinstance(link, dict):
                continue
            link_type = link.get('type') or {}
            outward = self._slugify_relationship(link_type.get('outward') or link_type.get('name') or 'linked_to')
            if link.get('outwardIssue'):
                target = link['outwardIssue'].get('key', '')
                if target:
                    edges.append(
                        DependencyEdge(
                            source_key=issue_key,
                            target_key=target,
                            relationship=outward,
                            evidence='jira_issue_link',
                        )
                    )
            elif link.get('inwardIssue'):
                source = link['inwardIssue'].get('key', '')
                if source:
                    edges.append(
                        DependencyEdge(
                            source_key=source,
                            target_key=issue_key,
                            relationship=outward,
                            evidence='jira_issue_link',
                        )
                    )

        return edges

    @staticmethod
    def _slugify_relationship(value: str) -> str:
        slug = re.sub(r'[^a-z0-9]+', '_', str(value).casefold()).strip('_')
        return slug or 'linked_to'

    @staticmethod
    def _parse_jira_datetime(value: str) -> Optional[datetime]:
        if not value:
            return None

        formats = [
            '%Y-%m-%dT%H:%M:%S.%f%z',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%d',
        ]
        for fmt in formats:
            try:
                parsed = datetime.strptime(value, fmt)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def _is_done_status(status: str) -> bool:
        return str(status).casefold() in {'done', 'closed', 'resolved'}

    @staticmethod
    def _is_high_priority(priority: str) -> bool:
        normalized = str(priority).casefold()
        return any(token in normalized for token in ('blocker', 'critical', 'highest', 'high', 'p0', 'p1'))

    @staticmethod
    def _is_blocked_status(status: str) -> bool:
        normalized = str(status).casefold()
        return any(token in normalized for token in ('blocked', 'on hold', 'impeded'))

    def _build_dependency_graph(self, issues: List[Dict[str, Any]]) -> DependencyGraph:
        nodes = []
        edges: List[DependencyEdge] = []
        seen_edges = set()
        blocked_keys = set()
        unscheduled_keys = set()

        for issue in issues:
            nodes.append({
                'key': issue.get('key', ''),
                'summary': issue.get('summary', ''),
                'issue_type': issue.get('issue_type', ''),
                'status': issue.get('status', ''),
                'assignee': issue.get('assignee_display') or issue.get('assignee', ''),
                'fix_versions': issue.get('fix_versions', []),
            })

            if self._is_blocked_status(issue.get('status', '')):
                blocked_keys.add(issue.get('key', ''))
            if not issue.get('fix_versions') and not issue.get('is_done', False):
                unscheduled_keys.add(issue.get('key', ''))

            for edge_dict in issue.get('dependency_edges', []):
                edge = DependencyEdge(**edge_dict)
                dedupe_key = (edge.source_key, edge.target_key, edge.relationship)
                if dedupe_key in seen_edges:
                    continue
                seen_edges.add(dedupe_key)
                edges.append(edge)
                if edge.relationship == 'blocks':
                    blocked_keys.add(edge.target_key)

        return DependencyGraph(
            nodes=nodes,
            edges=edges,
            blocked_keys=sorted(key for key in blocked_keys if key),
            unscheduled_keys=sorted(key for key in unscheduled_keys if key),
        )

    def _build_milestones(
        self,
        issues: List[Dict[str, Any]],
        releases: List[Dict[str, Any]],
        dependency_graph: DependencyGraph,
    ) -> List[MilestoneProposal]:
        release_map = {release.get('name', ''): release for release in releases}
        grouped: Dict[str, List[Dict[str, Any]]] = {}

        for issue in issues:
            targets = issue.get('fix_versions') or []
            milestone_name = targets[0] if targets else 'Unscheduled Backlog'
            grouped.setdefault(milestone_name, []).append(issue)

        proposals: List[MilestoneProposal] = []
        for name, bucket in grouped.items():
            release = release_map.get(name, {})
            total_issues = len(bucket)
            done_issues = sum(1 for issue in bucket if issue.get('is_done'))
            open_issues = total_issues - done_issues
            blocked_issues = sum(
                1 for issue in bucket if issue.get('key') in dependency_graph.blocked_keys
            )
            unassigned_issues = sum(
                1
                for issue in bucket
                if not issue.get('is_done')
                and (issue.get('assignee_display') or issue.get('assignee')) in ('', None, 'Unassigned')
            )

            risk_level = self._milestone_risk_level(
                open_issues,
                blocked_issues,
                unassigned_issues,
                release.get('releaseDate'),
            )
            confidence = 'high'
            if name == 'Unscheduled Backlog' or blocked_issues:
                confidence = 'medium'
            if not release.get('releaseDate') and name != 'Unscheduled Backlog':
                confidence = 'low'

            summary = (
                f'{open_issues} open, {blocked_issues} blocked, '
                f'{unassigned_issues} unassigned'
            )

            proposals.append(
                MilestoneProposal(
                    name=name,
                    source='fix_version' if name != 'Unscheduled Backlog' else 'backlog',
                    target_date=str(release.get('releaseDate') or ''),
                    issue_keys=[issue.get('key', '') for issue in bucket],
                    total_issues=total_issues,
                    open_issues=open_issues,
                    done_issues=done_issues,
                    blocked_issues=blocked_issues,
                    unassigned_issues=unassigned_issues,
                    confidence=confidence,
                    risk_level=risk_level,
                    summary=summary,
                )
            )

        proposals.sort(key=self._milestone_sort_key)
        return proposals

    def _milestone_risk_level(
        self,
        open_issues: int,
        blocked_issues: int,
        unassigned_issues: int,
        release_date: Optional[str],
    ) -> str:
        if blocked_issues >= 2 or unassigned_issues >= 3:
            return 'high'
        if blocked_issues >= 1 or unassigned_issues >= 1:
            return 'medium'
        if release_date and open_issues >= 8:
            return 'medium'
        return 'low'

    @staticmethod
    def _milestone_sort_key(milestone: MilestoneProposal) -> tuple[int, str, str]:
        if milestone.name == 'Unscheduled Backlog':
            return (1, '9999-99-99', milestone.name)
        target = milestone.target_date or '9999-99-99'
        return (0, target, milestone.name)

    def _build_evidence_gaps(self, issues: List[Dict[str, Any]]) -> List[str]:
        gaps = [
            'Build, test, release, and traceability evidence are not yet integrated into Gantt snapshots.',
            'Meeting-derived decisions and action items are not yet connected to planning snapshots.',
        ]

        unscheduled = sum(
            1 for issue in issues if not issue.get('fix_versions') and not issue.get('is_done')
        )
        if unscheduled:
            gaps.append(
                f'{unscheduled} active work items have no release target/fix version.'
            )

        return gaps

    def _build_risks(
        self,
        issues: List[Dict[str, Any]],
        milestones: List[MilestoneProposal],
        dependency_graph: DependencyGraph,
    ) -> List[PlanningRiskRecord]:
        risks: List[PlanningRiskRecord] = []

        stale = [issue for issue in issues if issue.get('is_stale')]
        if stale:
            risks.append(
                PlanningRiskRecord(
                    risk_type='stale_work',
                    severity='high' if len(stale) >= 3 else 'medium',
                    title='Stale active work detected',
                    description='Open work items have not been updated recently and may indicate roadmap drift.',
                    issue_keys=[issue['key'] for issue in stale],
                    evidence=[
                        f"{issue['key']} last updated {issue.get('updated_date', '')} ({issue.get('age_days', 0)} days ago)"
                        for issue in stale[:10]
                    ],
                    recommendation='Review stale items and confirm whether they should move, close, or regain ownership.',
                )
            )

        blocked = [
            issue
            for issue in issues
            if issue.get('key') in dependency_graph.blocked_keys and not issue.get('is_done')
        ]
        if blocked:
            risks.append(
                PlanningRiskRecord(
                    risk_type='blocked_work',
                    severity='high' if len(blocked) >= 2 else 'medium',
                    title='Blocked work items detected',
                    description='Dependencies or blocked statuses may threaten milestone confidence.',
                    issue_keys=[issue['key'] for issue in blocked],
                    evidence=[
                        f"{issue['key']} status={issue.get('status', '')}"
                        for issue in blocked[:10]
                    ],
                    recommendation='Resolve blockers before committing to milestone dates or delivery promises.',
                )
            )

        unassigned_high = [
            issue
            for issue in issues
            if not issue.get('is_done')
            and self._is_high_priority(issue.get('priority', ''))
            and (issue.get('assignee_display') or issue.get('assignee')) in ('', None, 'Unassigned')
        ]
        if unassigned_high:
            risks.append(
                PlanningRiskRecord(
                    risk_type='unassigned_priority_work',
                    severity='high',
                    title='High-priority work lacks ownership',
                    description='Priority backlog items without assignees are likely to slip silently.',
                    issue_keys=[issue['key'] for issue in unassigned_high],
                    evidence=[
                        f"{issue['key']} priority={issue.get('priority', '')}"
                        for issue in unassigned_high[:10]
                    ],
                    recommendation='Assign owners or explicitly de-scope these items from current milestones.',
                )
            )

        unscheduled = [
            issue
            for issue in issues
            if not issue.get('is_done') and not issue.get('fix_versions')
        ]
        if unscheduled:
            risks.append(
                PlanningRiskRecord(
                    risk_type='unscheduled_work',
                    severity='medium',
                    title='Backlog items without milestone targets',
                    description='Active work without a release target weakens milestone and roadmap clarity.',
                    issue_keys=[issue['key'] for issue in unscheduled],
                    evidence=[
                        f"{issue['key']} has no fix version"
                        for issue in unscheduled[:10]
                    ],
                    recommendation='Either assign these items to a milestone or classify them explicitly as unscheduled backlog.',
                )
            )

        overloaded = [
            milestone for milestone in milestones if milestone.open_issues >= 10
        ]
        if overloaded:
            risks.append(
                PlanningRiskRecord(
                    risk_type='milestone_overload',
                    severity='medium',
                    title='Milestones with heavy open scope detected',
                    description='Large open milestone scope increases coordination risk and reduces confidence.',
                    issue_keys=[
                        key
                        for milestone in overloaded
                        for key in milestone.issue_keys[:5]
                    ],
                    evidence=[
                        f'{milestone.name}: {milestone.open_issues} open items'
                        for milestone in overloaded
                    ],
                    recommendation='Consider splitting large milestones or rebalancing scope across release targets.',
                )
            )

        return risks

    def _build_backlog_overview(
        self,
        issues: List[Dict[str, Any]],
        milestones: List[MilestoneProposal],
        dependency_graph: DependencyGraph,
        risks: List[PlanningRiskRecord],
    ) -> Dict[str, Any]:
        total_issues = len(issues)
        done_issues = sum(1 for issue in issues if issue.get('is_done'))
        open_issues = total_issues - done_issues
        stale_issues = sum(1 for issue in issues if issue.get('is_stale'))
        unassigned_issues = sum(
            1
            for issue in issues
            if not issue.get('is_done')
            and (issue.get('assignee_display') or issue.get('assignee')) in ('', None, 'Unassigned')
        )

        return {
            'total_issues': total_issues,
            'open_issues': open_issues,
            'done_issues': done_issues,
            'blocked_issues': len(dependency_graph.blocked_keys),
            'stale_issues': stale_issues,
            'unassigned_issues': unassigned_issues,
            'milestone_count': len(milestones),
            'risk_count': len(risks),
            'dependency_edges': dependency_graph.edge_count,
        }

    def _format_snapshot(self, snapshot: PlanningSnapshot) -> str:
        overview = snapshot.backlog_overview
        lines = [
            f'# GANTT PLANNING SNAPSHOT: {snapshot.project_key}',
            '',
            f'**Snapshot ID**: {snapshot.snapshot_id}',
            f'**Created At**: {snapshot.created_at}',
            f'**Planning Horizon**: {snapshot.planning_horizon_days} days',
            '',
            '## Backlog Overview',
            '',
            f"- Total issues: {overview.get('total_issues', 0)}",
            f"- Open issues: {overview.get('open_issues', 0)}",
            f"- Done issues: {overview.get('done_issues', 0)}",
            f"- Blocked issues: {overview.get('blocked_issues', 0)}",
            f"- Stale issues: {overview.get('stale_issues', 0)}",
            f"- Unassigned issues: {overview.get('unassigned_issues', 0)}",
            f"- Dependency edges: {overview.get('dependency_edges', 0)}",
            '',
            '## Milestone Proposals',
            '',
        ]

        if snapshot.milestones:
            for milestone in snapshot.milestones:
                target = milestone.target_date or 'unscheduled'
                lines.extend([
                    f"- **{milestone.name}** ({target})",
                    f"  Open: {milestone.open_issues}, Blocked: {milestone.blocked_issues}, "
                    f"Unassigned: {milestone.unassigned_issues}, Risk: {milestone.risk_level.upper()}, "
                    f"Confidence: {milestone.confidence.upper()}",
                    f"  Summary: {milestone.summary}",
                ])
        else:
            lines.append('- No milestone proposals generated.')

        lines.extend([
            '',
            '## Planning Risks',
            '',
        ])

        if snapshot.risks:
            for risk in snapshot.risks:
                lines.extend([
                    f"- **{risk.title}** [{risk.severity.upper()}]",
                    f"  {risk.description}",
                    f"  Recommendation: {risk.recommendation}",
                ])
        else:
            lines.append('- No major planning risks detected from the current Jira view.')

        lines.extend([
            '',
            '## Dependency Summary',
            '',
            f"- Nodes: {snapshot.dependency_graph.node_count}",
            f"- Edges: {snapshot.dependency_graph.edge_count}",
            f"- Blocked keys: {len(snapshot.dependency_graph.blocked_keys)}",
            f"- Unscheduled keys: {len(snapshot.dependency_graph.unscheduled_keys)}",
            '',
            '## Evidence Gaps',
            '',
        ])

        for gap in snapshot.evidence_gaps:
            lines.append(f'- {gap}')

        return '\n'.join(lines)
