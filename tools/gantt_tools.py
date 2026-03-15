##########################################################################################
#
# Module: tools/gantt_tools.py
#
# Description: Gantt planning tools for agent use.
#              Wraps the Gantt planning snapshot workflow as agent-callable tools.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from typing import Optional

from tools.base import BaseTool, ToolResult, tool

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


@tool(
    description='Create a Gantt planning snapshot from Jira backlog state'
)
def create_gantt_snapshot(
    project_key: str,
    planning_horizon_days: int = 90,
    limit: int = 200,
    include_done: bool = False,
    backlog_jql: Optional[str] = None,
    policy_profile: str = 'default',
    persist: bool = True,
) -> ToolResult:
    '''
    Create a Gantt planning snapshot from Jira backlog state.

    Input:
        project_key: Jira project key to snapshot.
        planning_horizon_days: Planning horizon in days.
        limit: Maximum number of issues to inspect.
        include_done: Whether to include done/closed issues.
        backlog_jql: Optional JQL override for backlog selection.
        policy_profile: Optional future-facing planning policy profile.
        persist: Whether to save the snapshot in the durable snapshot store.

    Output:
        ToolResult with the generated snapshot and optional storage metadata.
    '''
    log.debug(
        f'create_gantt_snapshot(project_key={project_key}, '
        f'planning_horizon_days={planning_horizon_days}, limit={limit}, '
        f'include_done={include_done}, backlog_jql={backlog_jql}, '
        f'policy_profile={policy_profile}, persist={persist})'
    )

    try:
        from agents.gantt_agent import GanttProjectPlannerAgent
        from agents.gantt_models import PlanningRequest
        from state.gantt_snapshot_store import GanttSnapshotStore

        agent = GanttProjectPlannerAgent(project_key=project_key)
        request = PlanningRequest(
            project_key=project_key,
            planning_horizon_days=planning_horizon_days,
            limit=limit,
            include_done=include_done,
            backlog_jql=backlog_jql,
            policy_profile=policy_profile,
        )
        snapshot = agent.create_snapshot(request)

        result = {
            'snapshot': snapshot.to_dict(),
        }

        if persist:
            stored = GanttSnapshotStore().save_snapshot(
                snapshot,
                summary_markdown=snapshot.summary_markdown,
            )
            result['stored'] = stored

        return ToolResult.success(
            result,
            snapshot_id=snapshot.snapshot_id,
            project_key=project_key,
            persisted=persist,
        )
    except Exception as e:
        log.error(f'Failed to create Gantt snapshot: {e}')
        return ToolResult.failure(f'Failed to create Gantt snapshot: {e}')


@tool(
    description='Get a persisted Gantt planning snapshot by snapshot ID'
)
def get_gantt_snapshot(
    snapshot_id: str,
    project_key: Optional[str] = None,
) -> ToolResult:
    '''
    Get a persisted Gantt planning snapshot by snapshot ID.

    Input:
        snapshot_id: Stored snapshot ID.
        project_key: Optional project key to disambiguate the lookup.

    Output:
        ToolResult with the stored snapshot payload and storage summary.
    '''
    log.debug(f'get_gantt_snapshot(snapshot_id={snapshot_id}, project_key={project_key})')

    try:
        from state.gantt_snapshot_store import GanttSnapshotStore

        record = GanttSnapshotStore().get_snapshot(snapshot_id, project_key=project_key)
        if not record:
            return ToolResult.failure(f'Gantt snapshot {snapshot_id} not found')

        return ToolResult.success(record, snapshot_id=snapshot_id, project_key=project_key)
    except Exception as e:
        log.error(f'Failed to get Gantt snapshot: {e}')
        return ToolResult.failure(f'Failed to get Gantt snapshot: {e}')


@tool(
    description='List persisted Gantt planning snapshots'
)
def list_gantt_snapshots(
    project_key: Optional[str] = None,
    limit: int = 20,
) -> ToolResult:
    '''
    List persisted Gantt planning snapshots.

    Input:
        project_key: Optional project key filter.
        limit: Maximum number of snapshots to return.

    Output:
        ToolResult with snapshot summary rows.
    '''
    log.debug(f'list_gantt_snapshots(project_key={project_key}, limit={limit})')

    try:
        from state.gantt_snapshot_store import GanttSnapshotStore

        rows = GanttSnapshotStore().list_snapshots(project_key=project_key, limit=limit)
        return ToolResult.success(rows, count=len(rows), project_key=project_key)
    except Exception as e:
        log.error(f'Failed to list Gantt snapshots: {e}')
        return ToolResult.failure(f'Failed to list Gantt snapshots: {e}')


@tool(
    description='Accept or reject an inferred Gantt dependency edge'
)
def review_gantt_dependency(
    project_key: str,
    source_key: str,
    target_key: str,
    relationship: str = 'blocks',
    accepted: bool = True,
    note: Optional[str] = None,
    reviewer: Optional[str] = None,
) -> ToolResult:
    '''
    Accept or reject an inferred Gantt dependency edge.

    Input:
        project_key: Jira project key for the planning graph.
        source_key: Upstream issue key.
        target_key: Downstream issue key.
        relationship: Dependency relationship, usually ``blocks``.
        accepted: Whether the inferred dependency is accepted.
        note: Optional review note.
        reviewer: Optional reviewer identifier.

    Output:
        ToolResult with the stored review record.
    '''
    log.debug(
        f'review_gantt_dependency(project_key={project_key}, '
        f'source_key={source_key}, target_key={target_key}, '
        f'relationship={relationship}, accepted={accepted}, reviewer={reviewer})'
    )

    try:
        from state.gantt_dependency_review_store import GanttDependencyReviewStore

        record = GanttDependencyReviewStore().record_review(
            project_key=project_key,
            source_key=source_key,
            target_key=target_key,
            relationship=relationship,
            accepted=accepted,
            note=note,
            reviewer=reviewer,
        )
        return ToolResult.success(
            record,
            project_key=project_key,
            source_key=source_key,
            target_key=target_key,
            relationship=relationship,
            status=record['status'],
        )
    except Exception as e:
        log.error(f'Failed to review Gantt dependency: {e}')
        return ToolResult.failure(f'Failed to review Gantt dependency: {e}')


@tool(
    description='List stored Gantt dependency review decisions'
)
def list_gantt_dependency_reviews(
    project_key: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> ToolResult:
    '''
    List stored Gantt dependency review decisions.

    Input:
        project_key: Optional Jira project key filter.
        status: Optional status filter (``accepted`` or ``rejected``).
        limit: Maximum number of records to return.

    Output:
        ToolResult with dependency review rows.
    '''
    log.debug(
        f'list_gantt_dependency_reviews(project_key={project_key}, '
        f'status={status}, limit={limit})'
    )

    try:
        from state.gantt_dependency_review_store import GanttDependencyReviewStore

        rows = GanttDependencyReviewStore().list_reviews(
            project_key=project_key,
            status=status,
            limit=limit,
        )
        return ToolResult.success(
            rows,
            count=len(rows),
            project_key=project_key,
            status=status,
        )
    except Exception as e:
        log.error(f'Failed to list Gantt dependency reviews: {e}')
        return ToolResult.failure(f'Failed to list Gantt dependency reviews: {e}')


class GanttTools(BaseTool):
    '''
    Collection of Gantt planning tools for agent use.
    '''

    @tool(description='Create a Gantt planning snapshot from Jira backlog state')
    def create_gantt_snapshot(
        self,
        project_key: str,
        planning_horizon_days: int = 90,
        limit: int = 200,
        include_done: bool = False,
        backlog_jql: Optional[str] = None,
        policy_profile: str = 'default',
        persist: bool = True,
    ) -> ToolResult:
        return create_gantt_snapshot(
            project_key,
            planning_horizon_days,
            limit,
            include_done,
            backlog_jql,
            policy_profile,
            persist,
        )

    @tool(description='Get a persisted Gantt planning snapshot by snapshot ID')
    def get_gantt_snapshot(
        self,
        snapshot_id: str,
        project_key: Optional[str] = None,
    ) -> ToolResult:
        return get_gantt_snapshot(snapshot_id, project_key)

    @tool(description='List persisted Gantt planning snapshots')
    def list_gantt_snapshots(
        self,
        project_key: Optional[str] = None,
        limit: int = 20,
    ) -> ToolResult:
        return list_gantt_snapshots(project_key, limit)

    @tool(description='Accept or reject an inferred Gantt dependency edge')
    def review_gantt_dependency(
        self,
        project_key: str,
        source_key: str,
        target_key: str,
        relationship: str = 'blocks',
        accepted: bool = True,
        note: Optional[str] = None,
        reviewer: Optional[str] = None,
    ) -> ToolResult:
        return review_gantt_dependency(
            project_key,
            source_key,
            target_key,
            relationship,
            accepted,
            note,
            reviewer,
        )

    @tool(description='List stored Gantt dependency review decisions')
    def list_gantt_dependency_reviews(
        self,
        project_key: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> ToolResult:
        return list_gantt_dependency_reviews(project_key, status, limit)
