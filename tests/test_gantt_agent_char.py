import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents.base import AgentResponse
from agents.gantt_models import PlanningRequest, PlanningSnapshot
from tools.base import ToolResult


def test_gantt_agent_create_snapshot_builds_milestones_dependencies_and_risks(
    monkeypatch: pytest.MonkeyPatch,
    fake_issue_resource_factory,
):
    from agents.gantt_agent import GanttProjectPlannerAgent
    from agents import gantt_agent

    monkeypatch.setattr(
        GanttProjectPlannerAgent,
        '_load_prompt_file',
        staticmethod(lambda: 'gantt prompt'),
    )

    jira = MagicMock()

    blocking_story = fake_issue_resource_factory(
        key='STL-101',
        summary='Implement planning snapshot',
        issue_type='Story',
        status='In Progress',
        priority='High',
        assignee='Jane Dev',
        fix_versions=['12.1.0'],
        updated='2026-02-15T10:00:00.000+0000',
        issuelinks=[
            {
                'type': {
                    'name': 'Blocks',
                    'outward': 'blocks',
                    'inward': 'is blocked by',
                },
                'outwardIssue': {'key': 'STL-102'},
            }
        ],
    )

    dependent_story = fake_issue_resource_factory(
        key='STL-102',
        summary='Add milestone view',
        issue_type='Story',
        status='Open',
        priority='High',
        assignee=None,
        fix_versions=['12.1.0'],
        updated='2026-02-20T10:00:00.000+0000',
    )

    stale_bug = fake_issue_resource_factory(
        key='STL-103',
        summary='Old backlog bug',
        issue_type='Bug',
        status='Blocked',
        priority='P1-Critical',
        assignee=None,
        fix_versions=[],
        updated='2026-01-01T10:00:00.000+0000',
    )
    stale_bug.raw['fields']['fixVersions'] = []

    jira.search_issues.return_value = [blocking_story, dependent_story, stale_bug]

    monkeypatch.setattr(gantt_agent, 'get_jira', lambda: jira)
    monkeypatch.setattr(
        gantt_agent,
        'get_project_info',
        lambda project_key: ToolResult.success({
            'key': project_key,
            'name': 'Storage Team',
            'url': 'https://example.test/browse/STL',
        }),
    )
    monkeypatch.setattr(
        gantt_agent,
        'get_releases',
        lambda project_key, include_released=True, include_unreleased=True: ToolResult.success([
            {
                'id': '1001',
                'name': '12.1.0',
                'released': False,
                'releaseDate': '2026-04-01',
            }
        ]),
    )
    monkeypatch.setattr(
        GanttProjectPlannerAgent,
        '_utc_now',
        staticmethod(lambda: datetime(2026, 3, 15, tzinfo=timezone.utc)),
    )

    agent = GanttProjectPlannerAgent()
    snapshot = agent.create_snapshot(
        PlanningRequest(project_key='STL', planning_horizon_days=90, limit=50)
    )

    assert snapshot.project_key == 'STL'
    assert snapshot.backlog_overview['total_issues'] == 3
    assert snapshot.backlog_overview['blocked_issues'] == 2
    assert snapshot.backlog_overview['stale_issues'] == 1

    milestone_names = [milestone.name for milestone in snapshot.milestones]
    assert '12.1.0' in milestone_names
    assert 'Unscheduled Backlog' in milestone_names

    risk_types = {risk.risk_type for risk in snapshot.risks}
    assert 'stale_work' in risk_types
    assert 'blocked_work' in risk_types
    assert 'unassigned_priority_work' in risk_types
    assert 'unscheduled_work' in risk_types

    assert snapshot.dependency_graph.edge_count == 1
    assert 'STL-102' in snapshot.dependency_graph.blocked_keys
    assert 'STL-103' in snapshot.dependency_graph.unscheduled_keys
    assert 'Build, test, release' in snapshot.evidence_gaps[0]
    assert '## Milestone Proposals' in snapshot.summary_markdown


def test_gantt_agent_run_returns_snapshot_metadata(monkeypatch: pytest.MonkeyPatch):
    from agents.gantt_agent import GanttProjectPlannerAgent

    monkeypatch.setattr(
        GanttProjectPlannerAgent,
        '_load_prompt_file',
        staticmethod(lambda: 'gantt prompt'),
    )
    snapshot = PlanningSnapshot(
        project_key='STL',
        summary_markdown='# Snapshot\n\nBody',
    )
    monkeypatch.setattr(
        GanttProjectPlannerAgent,
        'create_snapshot',
        lambda self, request: snapshot,
    )

    agent = GanttProjectPlannerAgent(project_key='STL')
    response = agent.run({'project_key': 'STL', 'planning_horizon_days': 120})

    assert response.success is True
    assert response.content == '# Snapshot\n\nBody'
    assert response.metadata['planning_snapshot']['project_key'] == 'STL'


def test_gantt_agent_applies_dependency_review_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    fake_issue_resource_factory,
):
    from agents.gantt_agent import GanttProjectPlannerAgent
    from agents import gantt_agent
    from state.gantt_dependency_review_store import GanttDependencyReviewStore

    monkeypatch.setattr(
        GanttProjectPlannerAgent,
        '_load_prompt_file',
        staticmethod(lambda: 'gantt prompt'),
    )
    monkeypatch.setenv('GANTT_DEPENDENCY_REVIEW_DIR', str(tmp_path / 'reviews'))

    review_store = GanttDependencyReviewStore(storage_dir=str(tmp_path / 'reviews'))
    review_store.record_review(
        project_key='STL',
        source_key='STL-201',
        target_key='STL-202',
        relationship='blocks',
        accepted=True,
    )
    review_store.record_review(
        project_key='STL',
        source_key='STL-202',
        target_key='STL-203',
        relationship='blocks',
        accepted=False,
    )

    jira = MagicMock()
    jira.search_issues.return_value = [
        fake_issue_resource_factory(
            key='STL-201',
            summary='Foundation task',
            description='',
            issue_type='Story',
            status='In Progress',
            priority='High',
            assignee='Jane Dev',
            fix_versions=['12.1.0'],
            updated='2026-03-01T10:00:00.000+0000',
        ),
        fake_issue_resource_factory(
            key='STL-202',
            summary='Integration task',
            description='Blocked by STL-201. Blocks STL-203.',
            issue_type='Story',
            status='Open',
            priority='High',
            assignee='Jane Dev',
            fix_versions=['12.1.0'],
            updated='2026-03-05T10:00:00.000+0000',
        ),
        fake_issue_resource_factory(
            key='STL-203',
            summary='Validation task',
            description='',
            issue_type='Story',
            status='Open',
            priority='Medium',
            assignee='Jane Dev',
            fix_versions=['12.1.0'],
            updated='2026-03-10T10:00:00.000+0000',
        ),
    ]

    monkeypatch.setattr(gantt_agent, 'get_jira', lambda: jira)
    monkeypatch.setattr(
        gantt_agent,
        'get_project_info',
        lambda project_key: ToolResult.success({'key': project_key, 'name': 'Storage Team'}),
    )
    monkeypatch.setattr(
        gantt_agent,
        'get_releases',
        lambda project_key, include_released=True, include_unreleased=True: ToolResult.success([
            {'id': '1001', 'name': '12.1.0', 'released': False, 'releaseDate': '2026-04-01'}
        ]),
    )
    monkeypatch.setattr(
        GanttProjectPlannerAgent,
        '_utc_now',
        staticmethod(lambda: datetime(2026, 3, 15, tzinfo=timezone.utc)),
    )

    snapshot = GanttProjectPlannerAgent(project_key='STL').create_snapshot(
        PlanningRequest(project_key='STL')
    )

    assert snapshot.dependency_graph.inferred_edge_count == 1
    assert snapshot.dependency_graph.suppressed_edge_count == 1
    assert snapshot.dependency_graph.review_summary == {
        'accepted': 1,
        'pending': 0,
        'rejected': 1,
    }


def test_workflow_gantt_snapshot_writes_json_and_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    import pm_agent
    from agents import gantt_agent

    class _FakeGanttAgent:
        def __init__(self, project_key=None, **kwargs):
            self.project_key = project_key

        def run(self, input_data):
            return AgentResponse.success_response(
                content='# Gantt Snapshot\n\nSummary',
                metadata={
                    'planning_snapshot': {
                        'snapshot_id': 'snap-001',
                        'project_key': input_data['project_key'],
                        'created_at': '2026-03-15T12:00:00+00:00',
                        'planning_horizon_days': input_data['planning_horizon_days'],
                        'backlog_overview': {'total_issues': 2},
                        'milestones': [],
                        'risks': [],
                        'dependency_graph': {'edge_count': 0},
                    }
                },
            )

    monkeypatch.setattr(gantt_agent, 'GanttProjectPlannerAgent', _FakeGanttAgent)
    monkeypatch.setattr(pm_agent, 'output', lambda *args, **kwargs: None)
    monkeypatch.setenv('GANTT_SNAPSHOT_DIR', str(tmp_path / 'store'))

    output_path = tmp_path / 'snapshot.json'
    args = SimpleNamespace(
        project='STL',
        planning_horizon=90,
        limit=25,
        include_done=False,
        output=str(output_path),
    )

    exit_code = pm_agent._workflow_gantt_snapshot(args)

    assert exit_code == 0
    assert output_path.exists()
    assert (tmp_path / 'snapshot.md').exists()

    snapshot_data = json.loads(output_path.read_text(encoding='utf-8'))
    assert snapshot_data['project_key'] == 'STL'
    assert '# Gantt Snapshot' in (tmp_path / 'snapshot.md').read_text(encoding='utf-8')
    assert (tmp_path / 'store' / 'STL' / 'snap-001' / 'snapshot.json').exists()
    assert (tmp_path / 'store' / 'STL' / 'snap-001' / 'summary.md').exists()


def test_gantt_snapshot_store_save_load_and_list(tmp_path):
    from state.gantt_snapshot_store import GanttSnapshotStore

    store = GanttSnapshotStore(storage_dir=str(tmp_path / 'snapshots'))

    first_summary = store.save_snapshot(
        {
            'snapshot_id': 'snap-001',
            'project_key': 'STL',
            'created_at': '2026-03-14T12:00:00+00:00',
            'planning_horizon_days': 90,
            'backlog_overview': {
                'total_issues': 5,
                'blocked_issues': 2,
                'stale_issues': 1,
            },
            'milestones': [{'name': '12.1.0'}],
            'risks': [{'risk_type': 'blocked_work'}],
            'dependency_graph': {'edge_count': 3},
        },
        summary_markdown='# Snapshot 1',
    )
    store.save_snapshot(
        {
            'snapshot_id': 'snap-002',
            'project_key': 'STL',
            'created_at': '2026-03-15T12:00:00+00:00',
            'planning_horizon_days': 120,
            'backlog_overview': {
                'total_issues': 8,
                'blocked_issues': 1,
                'stale_issues': 0,
            },
            'milestones': [{'name': '12.2.0'}, {'name': 'Unscheduled Backlog'}],
            'risks': [],
            'dependency_graph': {'edge_count': 4},
        },
        summary_markdown='# Snapshot 2',
    )
    store.save_snapshot(
        {
            'snapshot_id': 'snap-003',
            'project_key': 'ABC',
            'created_at': '2026-03-13T12:00:00+00:00',
            'planning_horizon_days': 60,
            'backlog_overview': {'total_issues': 3},
            'milestones': [],
            'risks': [],
            'dependency_graph': {'edge_count': 0},
        },
        summary_markdown='# Snapshot 3',
    )

    record = store.get_snapshot('snap-001')
    assert record is not None
    assert record['snapshot']['project_key'] == 'STL'
    assert record['summary_markdown'] == '# Snapshot 1'
    assert first_summary['storage_dir'].endswith('STL/snap-001')

    listed = store.list_snapshots(project_key='STL')
    assert [item['snapshot_id'] for item in listed] == ['snap-002', 'snap-001']
    assert listed[0]['milestone_count'] == 2
    assert listed[1]['risk_count'] == 1


def test_workflow_gantt_snapshot_get_and_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    import pm_agent
    from state.gantt_snapshot_store import GanttSnapshotStore

    store = GanttSnapshotStore(storage_dir=str(tmp_path / 'store'))
    store.save_snapshot(
        {
            'snapshot_id': 'snap-010',
            'project_key': 'STL',
            'created_at': '2026-03-15T12:00:00+00:00',
            'planning_horizon_days': 90,
            'backlog_overview': {
                'total_issues': 6,
                'blocked_issues': 2,
                'stale_issues': 1,
            },
            'milestones': [{'name': '12.1.0'}],
            'risks': [{'risk_type': 'blocked_work'}],
            'dependency_graph': {'edge_count': 2},
            'summary_markdown': '# Stored Snapshot\n\nBody',
        },
        summary_markdown='# Stored Snapshot\n\nBody',
    )
    store.save_snapshot(
        {
            'snapshot_id': 'snap-011',
            'project_key': 'STL',
            'created_at': '2026-03-14T12:00:00+00:00',
            'planning_horizon_days': 60,
            'backlog_overview': {'total_issues': 2},
            'milestones': [],
            'risks': [],
            'dependency_graph': {'edge_count': 0},
        },
        summary_markdown='# Older Snapshot',
    )

    monkeypatch.setenv('GANTT_SNAPSHOT_DIR', str(tmp_path / 'store'))

    get_messages = []
    monkeypatch.setattr(pm_agent, 'output', lambda message='', **_kwargs: get_messages.append(str(message)))

    export_path = tmp_path / 'exported_snapshot.json'
    get_args = SimpleNamespace(
        snapshot_id='snap-010',
        project='STL',
        output=str(export_path),
    )

    get_exit_code = pm_agent._workflow_gantt_snapshot_get(get_args)

    assert get_exit_code == 0
    assert export_path.exists()
    assert (tmp_path / 'exported_snapshot.md').exists()
    exported = json.loads(export_path.read_text(encoding='utf-8'))
    assert exported['snapshot_id'] == 'snap-010'
    assert any('Stored in:' in message for message in get_messages)

    list_messages = []
    monkeypatch.setattr(pm_agent, 'output', lambda message='', **_kwargs: list_messages.append(str(message)))

    list_args = SimpleNamespace(project='STL', limit=10)
    list_exit_code = pm_agent._workflow_gantt_snapshot_list(list_args)

    assert list_exit_code == 0
    assert any('snap-010' in message for message in list_messages)
    assert any('snap-011' in message for message in list_messages)
