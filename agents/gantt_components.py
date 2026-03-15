##########################################################################################
#
# Module: agents/gantt_components.py
#
# Description: Deterministic planning components used by the Gantt Project Planner.
#              Splits backlog interpretation, dependency mapping, milestone planning,
#              risk projection, and summary formatting into reusable units.
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
from typing import Any, Callable, Dict, Iterable, List, Optional

from agents.gantt_models import (
    DependencyEdge,
    DependencyGraph,
    MilestoneProposal,
    PlanningRequest,
    PlanningRiskRecord,
    PlanningSnapshot,
)
from core.tickets import issue_to_dict

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


class BacklogInterpreter:
    '''
    Normalizes Jira backlog issues into a consistent planning shape.
    '''

    DEFAULT_FIELDS = ','.join([
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

    def __init__(
        self,
        jira_provider: Callable[[], Any],
        now_provider: Callable[[], datetime],
        stale_days: int = 30,
    ):
        self._jira_provider = jira_provider
        self._now_provider = now_provider
        self._stale_days = stale_days

    def load_backlog_issues(self, request: PlanningRequest) -> List[Dict[str, Any]]:
        '''
        Query Jira and normalize issues for planning.
        '''
        jira = self._jira_provider()
        jql = request.backlog_jql or self.build_backlog_jql(request)
        issues = jira.search_issues(
            jql,
            maxResults=request.limit,
            fields=self.DEFAULT_FIELDS,
        )
        return [self.normalize_issue(issue) for issue in issues]

    @staticmethod
    def build_backlog_jql(request: PlanningRequest) -> str:
        clauses = [
            f'project = "{request.project_key}"',
            'issuetype != "Sub-task"',
        ]
        if not request.include_done:
            clauses.append('statusCategory != Done')
        return ' AND '.join(clauses) + ' ORDER BY updated DESC'

    def normalize_issue(self, issue: Any) -> Dict[str, Any]:
        '''
        Convert a Jira issue resource into a normalized planning record.
        '''
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
        updated_dt = self.parse_jira_datetime(updated_ts)
        now = self._now_provider()
        age_days = (now - updated_dt).days if updated_dt else 0
        is_done = status_category.casefold() == 'done' or self.is_done_status(
            base.get('status', '')
        )

        normalized = dict(base)
        normalized.update({
            'parent_key': parent_key,
            'due_date': due_date,
            'status_category': status_category,
            'is_done': is_done,
            'age_days': age_days,
            'is_stale': age_days >= self._stale_days and not is_done,
            # Internal planner-only field. DependencyMapper consumes and removes it.
            '_issue_links': fields.get('issuelinks') or [],
        })
        return normalized

    @staticmethod
    def parse_jira_datetime(value: str) -> Optional[datetime]:
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
    def is_done_status(status: str) -> bool:
        return str(status).casefold() in {'done', 'closed', 'resolved'}

    @staticmethod
    def is_high_priority(priority: str) -> bool:
        normalized = str(priority).casefold()
        return any(
            token in normalized
            for token in ('blocker', 'critical', 'highest', 'high', 'p0', 'p1')
        )


class DependencyMapper:
    '''
    Identifies explicit dependency relationships and produces a graph view.
    '''

    KEY_PATTERN = re.compile(r'\b[A-Z][A-Z0-9]+-\d+\b')
    PREDECESSOR_PATTERNS = [
        ('blocked by', 'text.blocked_by'),
        ('depends on', 'text.depends_on'),
        ('dependent on', 'text.depends_on'),
        ('requires', 'text.requires'),
        ('waiting for', 'text.waiting_for'),
        ('after', 'text.after'),
        ('needs', 'text.needs'),
    ]
    SUCCESSOR_PATTERNS = [
        ('blocks', 'text.blocks'),
        ('unblocks', 'text.unblocks'),
        ('before', 'text.before'),
        ('prerequisite for', 'text.prerequisite_for'),
    ]

    def __init__(self, review_store: Optional[Any] = None):
        self._review_store = review_store

    def attach_dependency_edges(
        self,
        issues: List[Dict[str, Any]],
        project_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        '''
        Enrich normalized issues with explicit and inferred dependency edges.
        '''
        known_keys = {
            str(issue.get('key') or '').upper()
            for issue in issues
            if str(issue.get('key') or '').strip()
        }

        enriched: List[Dict[str, Any]] = []
        for issue in issues:
            issue_copy = dict(issue)
            explicit_edges = self.extract_edges(
                issue_copy.get('key', ''),
                issue_copy.get('parent_key', ''),
                issue_copy.pop('_issue_links', []),
            )
            inferred_edges = self.infer_edges(issue_copy, known_keys)

            seen_active = {
                self._edge_signature(edge.source_key, edge.target_key, edge.relationship)
                for edge in explicit_edges
            }
            active_edges = list(explicit_edges)
            suppressed_edges: List[DependencyEdge] = []

            for edge in inferred_edges:
                signature = self._edge_signature(
                    edge.source_key,
                    edge.target_key,
                    edge.relationship,
                )
                if signature in seen_active:
                    continue

                edge = self._apply_review(edge, project_key=project_key)
                if edge.review_state == 'rejected':
                    suppressed_edges.append(edge)
                    continue

                seen_active.add(signature)
                active_edges.append(edge)

            issue_copy['dependency_edges'] = [edge.to_dict() for edge in active_edges]
            if suppressed_edges:
                issue_copy['suppressed_dependency_edges'] = [
                    edge.to_dict() for edge in suppressed_edges
                ]
            enriched.append(issue_copy)
        return enriched

    def build_graph(self, issues: List[Dict[str, Any]]) -> DependencyGraph:
        nodes = []
        edges: List[DependencyEdge] = []
        suppressed_edges: List[DependencyEdge] = []
        seen_edges = set()
        seen_suppressed = set()
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

            if self.is_blocked_status(issue.get('status', '')):
                blocked_keys.add(issue.get('key', ''))
            if not issue.get('fix_versions') and not issue.get('is_done', False):
                unscheduled_keys.add(issue.get('key', ''))

            for edge_dict in issue.get('dependency_edges', []):
                edge = DependencyEdge(**edge_dict)
                dedupe_key = self._edge_signature(
                    edge.source_key,
                    edge.target_key,
                    edge.relationship,
                )
                if dedupe_key in seen_edges:
                    continue
                seen_edges.add(dedupe_key)
                edges.append(edge)
                if edge.relationship == 'blocks':
                    blocked_keys.add(edge.target_key)

            for edge_dict in issue.get('suppressed_dependency_edges', []):
                edge = DependencyEdge(**edge_dict)
                dedupe_key = self._edge_signature(
                    edge.source_key,
                    edge.target_key,
                    edge.relationship,
                )
                if dedupe_key in seen_suppressed:
                    continue
                seen_suppressed.add(dedupe_key)
                suppressed_edges.append(edge)

        analysis_edges = [edge for edge in edges if edge.relationship != 'parent_of']
        cycle_paths = self._find_cycles(analysis_edges)
        depth_by_key = self._compute_depth_by_key(nodes, analysis_edges, cycle_paths)
        blocker_chains = self._build_blocker_chains(analysis_edges)
        root_blockers = sorted({chain[0] for chain in blocker_chains if chain})
        review_summary = self._build_review_summary(edges, suppressed_edges)

        return DependencyGraph(
            nodes=nodes,
            edges=edges,
            blocked_keys=sorted(key for key in blocked_keys if key),
            unscheduled_keys=sorted(key for key in unscheduled_keys if key),
            cycle_paths=cycle_paths,
            depth_by_key=depth_by_key,
            blocker_chains=blocker_chains,
            root_blockers=root_blockers,
            review_summary=review_summary,
            suppressed_edges=suppressed_edges,
        )

    def extract_edges(
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
                    confidence='high',
                    rule_id='explicit.parent',
                    review_state='accepted',
                    rationale='Derived from Jira parent relationship.',
                )
            )

        for link in issue_links:
            if not isinstance(link, dict):
                continue
            link_type = link.get('type') or {}
            outward = self.slugify_relationship(
                link_type.get('outward') or link_type.get('name') or 'linked_to'
            )
            if link.get('outwardIssue'):
                target = link['outwardIssue'].get('key', '')
                if target:
                    edges.append(
                        DependencyEdge(
                            source_key=issue_key,
                            target_key=target,
                            relationship=outward,
                            evidence='jira_issue_link',
                            confidence='high',
                            rule_id='explicit.issue_link',
                            review_state='accepted',
                            rationale='Derived from explicit Jira issue link.',
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
                            confidence='high',
                            rule_id='explicit.issue_link',
                            review_state='accepted',
                            rationale='Derived from explicit Jira issue link.',
                        )
                    )

        return edges

    def infer_edges(
        self,
        issue: Dict[str, Any],
        known_keys: Iterable[str],
    ) -> List[DependencyEdge]:
        '''
        Infer dependency edges from summary/description text references.
        '''
        issue_key = str(issue.get('key') or '').upper()
        if not issue_key:
            return []

        known = {str(key).upper() for key in known_keys if str(key).strip()}
        text = ' '.join([
            str(issue.get('summary') or ''),
            str(issue.get('description') or ''),
        ])
        normalized_text = re.sub(r'\s+', ' ', text).strip()
        if not normalized_text:
            return []

        inferred_edges: List[DependencyEdge] = []
        seen = set()

        for match in self.KEY_PATTERN.finditer(normalized_text):
            referenced_key = match.group(0).upper()
            if referenced_key == issue_key or referenced_key not in known:
                continue

            context = normalized_text[max(0, match.start() - 60): min(
                len(normalized_text),
                match.end() + 60,
            )].casefold()

            for phrase, rule_id in self.PREDECESSOR_PATTERNS:
                if self._context_matches_reference(context, phrase, referenced_key):
                    edge = DependencyEdge(
                        source_key=referenced_key,
                        target_key=issue_key,
                        relationship='blocks',
                        inferred=True,
                        evidence='issue_text',
                        confidence='medium',
                        rule_id=rule_id,
                        review_state='pending',
                        rationale=f'Issue text suggests {issue_key} depends on {referenced_key} via "{phrase}".',
                    )
                    signature = self._edge_signature(
                        edge.source_key,
                        edge.target_key,
                        edge.relationship,
                    )
                    if signature not in seen:
                        seen.add(signature)
                        inferred_edges.append(edge)
                    break
            else:
                for phrase, rule_id in self.SUCCESSOR_PATTERNS:
                    if self._context_matches_reference(context, phrase, referenced_key):
                        edge = DependencyEdge(
                            source_key=issue_key,
                            target_key=referenced_key,
                            relationship='blocks',
                            inferred=True,
                            evidence='issue_text',
                            confidence='medium',
                            rule_id=rule_id,
                            review_state='pending',
                            rationale=f'Issue text suggests {issue_key} blocks {referenced_key} via "{phrase}".',
                        )
                        signature = self._edge_signature(
                            edge.source_key,
                            edge.target_key,
                            edge.relationship,
                        )
                        if signature not in seen:
                            seen.add(signature)
                            inferred_edges.append(edge)
                        break

        return inferred_edges

    @staticmethod
    def slugify_relationship(value: str) -> str:
        slug = re.sub(r'[^a-z0-9]+', '_', str(value).casefold()).strip('_')
        return slug or 'linked_to'

    @staticmethod
    def is_blocked_status(status: str) -> bool:
        normalized = str(status).casefold()
        return any(token in normalized for token in ('blocked', 'on hold', 'impeded'))

    def _apply_review(
        self,
        edge: DependencyEdge,
        project_key: Optional[str],
    ) -> DependencyEdge:
        if not edge.inferred or not self._review_store or not project_key:
            return edge

        review = self._review_store.get_review(
            project_key,
            edge.source_key,
            edge.target_key,
            edge.relationship,
        )
        if not review:
            return edge

        reviewed_edge = DependencyEdge(
            source_key=edge.source_key,
            target_key=edge.target_key,
            relationship=edge.relationship,
            inferred=edge.inferred,
            evidence=edge.evidence,
            confidence=edge.confidence,
            rule_id=edge.rule_id,
            review_state=str(review.get('status') or edge.review_state),
            rationale=edge.rationale,
        )
        note = str(review.get('note') or '').strip()
        if note:
            reviewed_edge.rationale = (
                f'{reviewed_edge.rationale} Review note: {note}'.strip()
            )
        return reviewed_edge

    @staticmethod
    def _context_matches_reference(context: str, phrase: str, referenced_key: str) -> bool:
        reference = referenced_key.casefold()
        return (
            f'{phrase} {reference}' in context
            or f'{reference} {phrase}' in context
        )

    @staticmethod
    def _edge_signature(source_key: str, target_key: str, relationship: str) -> tuple[str, str, str]:
        return (
            str(source_key or '').upper(),
            str(target_key or '').upper(),
            str(relationship or '').casefold(),
        )

    def _find_cycles(self, edges: List[DependencyEdge]) -> List[List[str]]:
        adjacency: Dict[str, List[str]] = {}
        for edge in edges:
            adjacency.setdefault(edge.source_key, []).append(edge.target_key)

        cycles: List[List[str]] = []
        seen = set()

        def _canonical_cycle(path: List[str]) -> tuple[str, ...]:
            body = path[:-1] if len(path) > 1 and path[0] == path[-1] else path
            rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
            reverse_body = list(reversed(body))
            rotations.extend(
                tuple(reverse_body[index:] + reverse_body[:index])
                for index in range(len(reverse_body))
            )
            return min(rotations) if rotations else tuple()

        def _dfs(node: str, path: List[str], stack: set[str]) -> None:
            for target in adjacency.get(node, []):
                if target in stack:
                    start_index = path.index(target)
                    cycle = path[start_index:] + [target]
                    signature = _canonical_cycle(cycle)
                    if signature and signature not in seen:
                        seen.add(signature)
                        cycles.append(cycle)
                    continue
                _dfs(target, path + [target], stack | {target})

        for node in sorted(adjacency):
            _dfs(node, [node], {node})

        return cycles

    def _compute_depth_by_key(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[DependencyEdge],
        cycle_paths: List[List[str]],
    ) -> Dict[str, int]:
        blocker_edges = [edge for edge in edges if edge.relationship == 'blocks']
        reverse_adjacency: Dict[str, List[str]] = {}
        for edge in blocker_edges:
            reverse_adjacency.setdefault(edge.target_key, []).append(edge.source_key)

        cycle_nodes = {
            node
            for cycle in cycle_paths
            for node in cycle[:-1] if cycle
        }
        memo: Dict[str, int] = {}

        def _depth(node_key: str) -> int:
            if node_key in memo:
                return memo[node_key]
            if node_key in cycle_nodes:
                memo[node_key] = -1
                return memo[node_key]

            predecessors = reverse_adjacency.get(node_key, [])
            valid_predecessors = [
                _depth(predecessor)
                for predecessor in predecessors
                if predecessor != node_key
            ]
            valid_predecessors = [depth for depth in valid_predecessors if depth >= 0]
            memo[node_key] = max(valid_predecessors) + 1 if valid_predecessors else 0
            return memo[node_key]

        depth_by_key: Dict[str, int] = {}
        for node in nodes:
            key = str(node.get('key') or '')
            if key:
                depth_by_key[key] = _depth(key)
        return depth_by_key

    def _build_blocker_chains(self, edges: List[DependencyEdge]) -> List[List[str]]:
        blocker_edges = [edge for edge in edges if edge.relationship == 'blocks']
        reverse_adjacency: Dict[str, List[str]] = {}
        for edge in blocker_edges:
            reverse_adjacency.setdefault(edge.target_key, []).append(edge.source_key)

        chains: List[List[str]] = []
        seen = set()

        def _walk(node_key: str, path: List[str]) -> None:
            predecessors = sorted(reverse_adjacency.get(node_key, []))
            if not predecessors:
                signature = tuple(path)
                if len(signature) >= 2 and signature not in seen:
                    seen.add(signature)
                    chains.append(path)
                return

            for predecessor in predecessors:
                if predecessor in path:
                    continue
                _walk(predecessor, [predecessor] + path)

        for blocked_key in sorted(reverse_adjacency):
            _walk(blocked_key, [blocked_key])

        chains.sort(key=lambda chain: (len(chain), tuple(chain)), reverse=True)
        return chains

    @staticmethod
    def _build_review_summary(
        edges: List[DependencyEdge],
        suppressed_edges: List[DependencyEdge],
    ) -> Dict[str, int]:
        summary = {
            'accepted': 0,
            'pending': 0,
            'rejected': 0,
        }
        for edge in [*edges, *suppressed_edges]:
            if not edge.inferred:
                continue
            state = str(edge.review_state or 'pending').casefold()
            if state not in summary:
                summary[state] = 0
            summary[state] += 1
        return summary


class MilestonePlanner:
    '''
    Groups backlog work into milestone proposals.
    '''

    def build_milestones(
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
                and (issue.get('assignee_display') or issue.get('assignee'))
                in ('', None, 'Unassigned')
            )

            risk_level = self.milestone_risk_level(
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

        proposals.sort(key=self.milestone_sort_key)
        return proposals

    def milestone_risk_level(
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
    def milestone_sort_key(milestone: MilestoneProposal) -> tuple[int, str, str]:
        if milestone.name == 'Unscheduled Backlog':
            return (1, '9999-99-99', milestone.name)
        target = milestone.target_date or '9999-99-99'
        return (0, target, milestone.name)


class RiskProjector:
    '''
    Projects evidence gaps and planning risks from the current backlog view.
    '''

    def build_evidence_gaps(self, issues: List[Dict[str, Any]]) -> List[str]:
        gaps = [
            'Build, test, release, and traceability evidence are not yet integrated into Gantt snapshots.',
            'Meeting-derived decisions and action items are not yet connected to planning snapshots.',
        ]

        unscheduled = sum(
            1
            for issue in issues
            if not issue.get('fix_versions') and not issue.get('is_done')
        )
        if unscheduled:
            gaps.append(
                f'{unscheduled} active work items have no release target/fix version.'
            )

        return gaps

    def build_risks(
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
            and BacklogInterpreter.is_high_priority(issue.get('priority', ''))
            and (issue.get('assignee_display') or issue.get('assignee'))
            in ('', None, 'Unassigned')
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
            issue for issue in issues if not issue.get('is_done') and not issue.get('fix_versions')
        ]
        if unscheduled:
            risks.append(
                PlanningRiskRecord(
                    risk_type='unscheduled_work',
                    severity='medium',
                    title='Backlog items without milestone targets',
                    description='Active work without a release target weakens milestone and roadmap clarity.',
                    issue_keys=[issue['key'] for issue in unscheduled],
                    evidence=[f"{issue['key']} has no fix version" for issue in unscheduled[:10]],
                    recommendation='Either assign these items to a milestone or classify them explicitly as unscheduled backlog.',
                )
            )

        overloaded = [milestone for milestone in milestones if milestone.open_issues >= 10]
        if overloaded:
            risks.append(
                PlanningRiskRecord(
                    risk_type='milestone_overload',
                    severity='medium',
                    title='Milestones with heavy open scope detected',
                    description='Large open milestone scope increases coordination risk and reduces confidence.',
                    issue_keys=[key for milestone in overloaded for key in milestone.issue_keys[:5]],
                    evidence=[
                        f'{milestone.name}: {milestone.open_issues} open items'
                        for milestone in overloaded
                    ],
                    recommendation='Consider splitting large milestones or rebalancing scope across release targets.',
                )
            )

        if dependency_graph.cycle_paths:
            risks.append(
                PlanningRiskRecord(
                    risk_type='dependency_cycle',
                    severity='high',
                    title='Dependency cycles detected in backlog graph',
                    description='Circular blockers can stall planning, obscure sequencing, and invalidate milestone assumptions.',
                    issue_keys=sorted({
                        node_key
                        for cycle in dependency_graph.cycle_paths
                        for node_key in cycle[:-1]
                    }),
                    evidence=[
                        ' -> '.join(cycle)
                        for cycle in dependency_graph.cycle_paths[:10]
                    ],
                    recommendation='Review cyclical dependencies and break the loop with a planning or ownership decision.',
                )
            )

        long_blocker_chains = [
            chain for chain in dependency_graph.blocker_chains if len(chain) >= 3
        ]
        if long_blocker_chains:
            risks.append(
                PlanningRiskRecord(
                    risk_type='blocker_chain',
                    severity='high' if len(long_blocker_chains) >= 2 else 'medium',
                    title='Long blocker chains detected',
                    description='Multi-hop dependency chains raise sequencing risk and make schedule slips more likely.',
                    issue_keys=sorted({
                        node_key
                        for chain in long_blocker_chains
                        for node_key in chain
                    }),
                    evidence=[
                        ' -> '.join(chain)
                        for chain in long_blocker_chains[:10]
                    ],
                    recommendation='Shorten or explicitly manage blocker chains before treating milestone dates as reliable.',
                )
            )

        return risks


class PlanningSummarizer:
    '''
    Builds machine-readable overview data and human-readable planning summaries.
    '''

    def build_backlog_overview(
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
            and (issue.get('assignee_display') or issue.get('assignee'))
            in ('', None, 'Unassigned')
        )
        non_cycle_depths = [
            depth
            for depth in dependency_graph.depth_by_key.values()
            if isinstance(depth, int) and depth >= 0
        ]

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
            'explicit_dependency_edges': dependency_graph.explicit_edge_count,
            'inferred_dependency_edges': dependency_graph.inferred_edge_count,
            'suppressed_dependency_edges': dependency_graph.suppressed_edge_count,
            'dependency_cycles': len(dependency_graph.cycle_paths),
            'max_dependency_depth': max(non_cycle_depths) if non_cycle_depths else 0,
            'blocker_chain_count': len(dependency_graph.blocker_chains),
            'root_blocker_count': len(dependency_graph.root_blockers),
            'dependency_review_summary': dict(dependency_graph.review_summary),
        }

    def format_snapshot(self, snapshot: PlanningSnapshot) -> str:
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
            f"- Explicit dependency edges: {overview.get('explicit_dependency_edges', 0)}",
            f"- Inferred dependency edges: {overview.get('inferred_dependency_edges', 0)}",
            f"- Suppressed dependency edges: {overview.get('suppressed_dependency_edges', 0)}",
            f"- Dependency cycles: {overview.get('dependency_cycles', 0)}",
            f"- Max dependency depth: {overview.get('max_dependency_depth', 0)}",
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
            f"- Explicit edges: {snapshot.dependency_graph.explicit_edge_count}",
            f"- Inferred edges: {snapshot.dependency_graph.inferred_edge_count}",
            f"- Suppressed inferred edges: {snapshot.dependency_graph.suppressed_edge_count}",
            f"- Blocked keys: {len(snapshot.dependency_graph.blocked_keys)}",
            f"- Unscheduled keys: {len(snapshot.dependency_graph.unscheduled_keys)}",
            f"- Cycle paths: {len(snapshot.dependency_graph.cycle_paths)}",
            f"- Blocker chains: {len(snapshot.dependency_graph.blocker_chains)}",
            f"- Root blockers: {', '.join(snapshot.dependency_graph.root_blockers[:5]) or 'none'}",
            f"- Review summary: accepted={snapshot.dependency_graph.review_summary.get('accepted', 0)}, "
            f"pending={snapshot.dependency_graph.review_summary.get('pending', 0)}, "
            f"rejected={snapshot.dependency_graph.review_summary.get('rejected', 0)}",
        ])

        if snapshot.dependency_graph.cycle_paths:
            lines.extend([
                '',
                '## Dependency Cycles',
                '',
            ])
            for cycle in snapshot.dependency_graph.cycle_paths[:5]:
                lines.append(f"- {' -> '.join(cycle)}")

        notable_chains = [
            chain for chain in snapshot.dependency_graph.blocker_chains if len(chain) >= 3
        ]
        if notable_chains:
            lines.extend([
                '',
                '## Blocker Chains',
                '',
            ])
            for chain in notable_chains[:5]:
                lines.append(f"- {' -> '.join(chain)}")

        lines.extend([
            '',
            '## Evidence Gaps',
            '',
        ])

        for gap in snapshot.evidence_gaps:
            lines.append(f'- {gap}')

        return '\n'.join(lines)
