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
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from agents.base import BaseAgent, AgentConfig, AgentResponse
from agents.gantt_components import (
    BacklogInterpreter,
    DependencyMapper,
    MilestonePlanner,
    PlanningSummarizer,
    RiskProjector,
)
from agents.gantt_models import (
    DependencyEdge,
    DependencyGraph,
    MilestoneProposal,
    PlanningRequest,
    PlanningRiskRecord,
    PlanningSnapshot,
)
from state.gantt_dependency_review_store import GanttDependencyReviewStore
from tools.jira_tools import JiraTools, get_jira, get_project_info, get_releases

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


class GanttProjectPlannerAgent(BaseAgent):
    '''
    Agent for producing project-planning snapshots from Jira data.

    The implementation is deterministic-first. Specialized planner components
    handle backlog interpretation, dependency mapping, milestone planning,
    risk projection, and summary formatting.
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
        self.backlog_interpreter = BacklogInterpreter(
            jira_provider=get_jira,
            now_provider=self._utc_now,
            stale_days=self.STALE_DAYS,
        )
        self.dependency_mapper = DependencyMapper(
            review_store=GanttDependencyReviewStore()
        )
        self.milestone_planner = MilestonePlanner()
        self.risk_projector = RiskProjector()
        self.planning_summarizer = PlanningSummarizer()

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
        issues = self.backlog_interpreter.load_backlog_issues(request)
        return self.dependency_mapper.attach_dependency_edges(
            issues,
            project_key=request.project_key,
        )

    @staticmethod
    def _build_backlog_jql(request: PlanningRequest) -> str:
        return BacklogInterpreter.build_backlog_jql(request)

    def _normalize_issue(self, issue: Any) -> Dict[str, Any]:
        normalized = self.backlog_interpreter.normalize_issue(issue)
        return self.dependency_mapper.attach_dependency_edges(
            [normalized],
            project_key=self.project_key,
        )[0]

    def _extract_edges(
        self,
        issue_key: str,
        parent_key: str,
        issue_links: Iterable[Any],
    ) -> List[DependencyEdge]:
        return self.dependency_mapper.extract_edges(issue_key, parent_key, issue_links)

    @staticmethod
    def _slugify_relationship(value: str) -> str:
        return DependencyMapper.slugify_relationship(value)

    @staticmethod
    def _parse_jira_datetime(value: str) -> Optional[datetime]:
        return BacklogInterpreter.parse_jira_datetime(value)

    @staticmethod
    def _is_done_status(status: str) -> bool:
        return BacklogInterpreter.is_done_status(status)

    @staticmethod
    def _is_high_priority(priority: str) -> bool:
        return BacklogInterpreter.is_high_priority(priority)

    @staticmethod
    def _is_blocked_status(status: str) -> bool:
        return DependencyMapper.is_blocked_status(status)

    def _build_dependency_graph(self, issues: List[Dict[str, Any]]) -> DependencyGraph:
        return self.dependency_mapper.build_graph(issues)

    def _build_milestones(
        self,
        issues: List[Dict[str, Any]],
        releases: List[Dict[str, Any]],
        dependency_graph: DependencyGraph,
    ) -> List[MilestoneProposal]:
        return self.milestone_planner.build_milestones(
            issues,
            releases,
            dependency_graph,
        )

    def _milestone_risk_level(
        self,
        open_issues: int,
        blocked_issues: int,
        unassigned_issues: int,
        release_date: Optional[str],
    ) -> str:
        return self.milestone_planner.milestone_risk_level(
            open_issues,
            blocked_issues,
            unassigned_issues,
            release_date,
        )

    @staticmethod
    def _milestone_sort_key(milestone: MilestoneProposal) -> tuple[int, str, str]:
        return MilestonePlanner.milestone_sort_key(milestone)

    def _build_evidence_gaps(self, issues: List[Dict[str, Any]]) -> List[str]:
        return self.risk_projector.build_evidence_gaps(issues)

    def _build_risks(
        self,
        issues: List[Dict[str, Any]],
        milestones: List[MilestoneProposal],
        dependency_graph: DependencyGraph,
    ) -> List[PlanningRiskRecord]:
        return self.risk_projector.build_risks(issues, milestones, dependency_graph)

    def _build_backlog_overview(
        self,
        issues: List[Dict[str, Any]],
        milestones: List[MilestoneProposal],
        dependency_graph: DependencyGraph,
        risks: List[PlanningRiskRecord],
    ) -> Dict[str, Any]:
        return self.planning_summarizer.build_backlog_overview(
            issues,
            milestones,
            dependency_graph,
            risks,
        )

    def _format_snapshot(self, snapshot: PlanningSnapshot) -> str:
        return self.planning_summarizer.format_snapshot(snapshot)
