##########################################################################################
#
# Module: agents/gantt_models.py
#
# Description: Data models for the Gantt Project Planner agent.
#              Defines structured planning snapshot, milestone, dependency,
#              and risk records used by the Gantt planning workflow.
#
# Author: Cornelis Networks
#
##########################################################################################

from __future__ import annotations

import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


@dataclass
class PlanningRequest:
    '''
    Input request for generating a planning snapshot.
    '''
    project_key: str = ''
    planning_horizon_days: int = 90
    limit: int = 200
    include_done: bool = False
    backlog_jql: Optional[str] = None
    policy_profile: str = 'default'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'project_key': self.project_key,
            'planning_horizon_days': self.planning_horizon_days,
            'limit': self.limit,
            'include_done': self.include_done,
            'backlog_jql': self.backlog_jql,
            'policy_profile': self.policy_profile,
        }


@dataclass
class DependencyEdge:
    '''
    A single dependency relationship between two work items.
    '''
    source_key: str
    target_key: str
    relationship: str
    inferred: bool = False
    evidence: str = ''
    confidence: str = 'high'
    rule_id: str = ''
    review_state: str = 'accepted'
    rationale: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'source_key': self.source_key,
            'target_key': self.target_key,
            'relationship': self.relationship,
            'inferred': self.inferred,
            'evidence': self.evidence,
            'confidence': self.confidence,
            'rule_id': self.rule_id,
            'review_state': self.review_state,
            'rationale': self.rationale,
        }


@dataclass
class DependencyGraph:
    '''
    Directed dependency graph for a project backlog.
    '''
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[DependencyEdge] = field(default_factory=list)
    blocked_keys: List[str] = field(default_factory=list)
    unscheduled_keys: List[str] = field(default_factory=list)
    cycle_paths: List[List[str]] = field(default_factory=list)
    depth_by_key: Dict[str, int] = field(default_factory=dict)
    blocker_chains: List[List[str]] = field(default_factory=list)
    root_blockers: List[str] = field(default_factory=list)
    review_summary: Dict[str, int] = field(default_factory=dict)
    suppressed_edges: List[DependencyEdge] = field(default_factory=list)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def explicit_edge_count(self) -> int:
        return sum(1 for edge in self.edges if not edge.inferred)

    @property
    def inferred_edge_count(self) -> int:
        return sum(1 for edge in self.edges if edge.inferred)

    @property
    def suppressed_edge_count(self) -> int:
        return len(self.suppressed_edges)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'node_count': self.node_count,
            'edge_count': self.edge_count,
            'explicit_edge_count': self.explicit_edge_count,
            'inferred_edge_count': self.inferred_edge_count,
            'suppressed_edge_count': self.suppressed_edge_count,
            'blocked_keys': self.blocked_keys,
            'unscheduled_keys': self.unscheduled_keys,
            'cycle_paths': self.cycle_paths,
            'depth_by_key': self.depth_by_key,
            'blocker_chains': self.blocker_chains,
            'root_blockers': self.root_blockers,
            'review_summary': self.review_summary,
            'nodes': self.nodes,
            'edges': [edge.to_dict() for edge in self.edges],
            'suppressed_edges': [edge.to_dict() for edge in self.suppressed_edges],
        }


@dataclass
class MilestoneProposal:
    '''
    Proposed milestone grouping derived from Jira release targets or backlog state.
    '''
    name: str
    source: str = 'fix_version'
    target_date: str = ''
    issue_keys: List[str] = field(default_factory=list)
    total_issues: int = 0
    open_issues: int = 0
    done_issues: int = 0
    blocked_issues: int = 0
    unassigned_issues: int = 0
    confidence: str = 'medium'
    risk_level: str = 'low'
    summary: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'source': self.source,
            'target_date': self.target_date,
            'issue_keys': self.issue_keys,
            'total_issues': self.total_issues,
            'open_issues': self.open_issues,
            'done_issues': self.done_issues,
            'blocked_issues': self.blocked_issues,
            'unassigned_issues': self.unassigned_issues,
            'confidence': self.confidence,
            'risk_level': self.risk_level,
            'summary': self.summary,
        }


@dataclass
class PlanningRiskRecord:
    '''
    Risk identified during planning snapshot generation.
    '''
    risk_type: str
    severity: str
    title: str
    description: str
    issue_keys: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    recommendation: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'risk_type': self.risk_type,
            'severity': self.severity,
            'title': self.title,
            'description': self.description,
            'issue_keys': self.issue_keys,
            'evidence': self.evidence,
            'recommendation': self.recommendation,
        }


@dataclass
class PlanningSnapshot:
    '''
    Durable planning snapshot produced by the Gantt Project Planner.
    '''
    project_key: str = ''
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    planning_horizon_days: int = 90
    project_info: Dict[str, Any] = field(default_factory=dict)
    backlog_overview: Dict[str, Any] = field(default_factory=dict)
    milestones: List[MilestoneProposal] = field(default_factory=list)
    dependency_graph: DependencyGraph = field(default_factory=DependencyGraph)
    risks: List[PlanningRiskRecord] = field(default_factory=list)
    issues: List[Dict[str, Any]] = field(default_factory=list)
    evidence_gaps: List[str] = field(default_factory=list)
    summary_markdown: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'snapshot_id': self.snapshot_id,
            'project_key': self.project_key,
            'created_at': self.created_at,
            'planning_horizon_days': self.planning_horizon_days,
            'project_info': self.project_info,
            'backlog_overview': self.backlog_overview,
            'milestones': [milestone.to_dict() for milestone in self.milestones],
            'dependency_graph': self.dependency_graph.to_dict(),
            'risks': [risk.to_dict() for risk in self.risks],
            'issues': self.issues,
            'evidence_gaps': self.evidence_gaps,
            'summary_markdown': self.summary_markdown,
        }
