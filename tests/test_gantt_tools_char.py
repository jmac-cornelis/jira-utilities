import pytest

from agents.gantt_models import DependencyGraph, PlanningSnapshot
from tools.gantt_tools import GanttTools, create_gantt_snapshot


def test_create_gantt_snapshot_tool_persists_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    from agents import gantt_agent as gantt_agent_module

    class _FakeGanttAgent:
        def __init__(self, project_key=None, **_kwargs):
            self.project_key = project_key

        def create_snapshot(self, request):
            snapshot = PlanningSnapshot(
                project_key=request.project_key,
                created_at='2026-03-15T12:00:00+00:00',
                planning_horizon_days=request.planning_horizon_days,
                backlog_overview={'total_issues': 2},
                dependency_graph=DependencyGraph(),
                summary_markdown='# Gantt Snapshot\n\nSummary',
            )
            snapshot.snapshot_id = 'snap-201'
            return snapshot

    monkeypatch.setattr(gantt_agent_module, 'GanttProjectPlannerAgent', _FakeGanttAgent)
    monkeypatch.setenv('GANTT_SNAPSHOT_DIR', str(tmp_path / 'store'))

    result = create_gantt_snapshot('STL', planning_horizon_days=120, persist=True)

    assert result.is_success
    assert result.data['snapshot']['project_key'] == 'STL'
    assert result.data['stored']['snapshot_id'] == 'snap-201'
    assert (tmp_path / 'store' / 'STL' / 'snap-201' / 'snapshot.json').exists()
    assert result.metadata['persisted'] is True


def test_get_and_list_gantt_snapshots_tools(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from state.gantt_snapshot_store import GanttSnapshotStore
    from tools import gantt_tools

    store = GanttSnapshotStore(storage_dir=str(tmp_path / 'store'))
    store.save_snapshot(
        {
            'snapshot_id': 'snap-301',
            'project_key': 'STL',
            'created_at': '2026-03-15T12:00:00+00:00',
            'planning_horizon_days': 90,
            'backlog_overview': {'total_issues': 4, 'blocked_issues': 1, 'stale_issues': 0},
            'milestones': [],
            'risks': [],
            'dependency_graph': {'edge_count': 1},
            'summary_markdown': '# Stored Snapshot',
        },
        summary_markdown='# Stored Snapshot',
    )

    monkeypatch.setenv('GANTT_SNAPSHOT_DIR', str(tmp_path / 'store'))

    get_result = gantt_tools.get_gantt_snapshot('snap-301', project_key='STL')
    list_result = gantt_tools.list_gantt_snapshots(project_key='STL', limit=5)

    assert get_result.is_success
    assert get_result.data['snapshot']['snapshot_id'] == 'snap-301'
    assert get_result.data['summary_markdown'] == '# Stored Snapshot'

    assert list_result.is_success
    assert list_result.data[0]['snapshot_id'] == 'snap-301'
    assert list_result.metadata['count'] == 1


def test_gantt_tools_collection_registers_methods():
    tools = GanttTools()

    assert tools.get_tool('create_gantt_snapshot') is not None
    assert tools.get_tool('get_gantt_snapshot') is not None
    assert tools.get_tool('list_gantt_snapshots') is not None
