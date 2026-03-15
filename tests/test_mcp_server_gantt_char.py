import json

import pytest


def _payload(result):
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].type == 'text'
    return json.loads(result[0].text)


@pytest.mark.asyncio
async def test_create_gantt_snapshot_tool(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    from agents.gantt_models import DependencyGraph, PlanningSnapshot

    class _FakeGanttAgent:
        def __init__(self, project_key=None, **_kwargs):
            self.project_key = project_key

        def create_snapshot(self, request):
            snapshot = PlanningSnapshot(
                project_key=request.project_key,
                created_at='2026-03-15T12:00:00+00:00',
                planning_horizon_days=request.planning_horizon_days,
                backlog_overview={'total_issues': 3},
                dependency_graph=DependencyGraph(),
                summary_markdown='# Snapshot',
            )
            snapshot.snapshot_id = 'snap-401'
            return snapshot

    class _FakeStore:
        def save_snapshot(self, snapshot, summary_markdown=None):
            assert snapshot.snapshot_id == 'snap-401'
            return {
                'snapshot_id': snapshot.snapshot_id,
                'project_key': snapshot.project_key,
                'storage_dir': '/tmp/store/STL/snap-401',
            }

    monkeypatch.setattr(import_mcp_server, 'GanttProjectPlannerAgent', _FakeGanttAgent)
    monkeypatch.setattr(import_mcp_server, 'GanttSnapshotStore', _FakeStore)

    result = await import_mcp_server.create_gantt_snapshot(
        project_key='STL',
        planning_horizon_days=120,
        persist=True,
    )
    data = _payload(result)

    assert data['snapshot']['project_key'] == 'STL'
    assert data['stored']['snapshot_id'] == 'snap-401'


@pytest.mark.asyncio
async def test_get_gantt_snapshot_tool(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    class _FakeStore:
        def get_snapshot(self, snapshot_id, project_key=None):
            assert snapshot_id == 'snap-501'
            assert project_key == 'STL'
            return {
                'snapshot': {'snapshot_id': snapshot_id, 'project_key': project_key},
                'summary': {'snapshot_id': snapshot_id, 'project_key': project_key},
                'summary_markdown': '# Stored Snapshot',
            }

    monkeypatch.setattr(import_mcp_server, 'GanttSnapshotStore', _FakeStore)

    result = await import_mcp_server.get_gantt_snapshot('snap-501', project_key='STL')
    data = _payload(result)

    assert data['snapshot']['snapshot_id'] == 'snap-501'
    assert data['summary_markdown'] == '# Stored Snapshot'


@pytest.mark.asyncio
async def test_list_gantt_snapshots_tool(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    class _FakeStore:
        def list_snapshots(self, project_key=None, limit=20):
            assert project_key == 'STL'
            assert limit == 10
            return [
                {
                    'snapshot_id': 'snap-601',
                    'project_key': 'STL',
                    'created_at': '2026-03-15T12:00:00+00:00',
                    'total_issues': 5,
                }
            ]

    monkeypatch.setattr(import_mcp_server, 'GanttSnapshotStore', _FakeStore)

    result = await import_mcp_server.list_gantt_snapshots(project_key='STL', limit=10)
    data = _payload(result)

    assert data[0]['snapshot_id'] == 'snap-601'
    assert data[0]['project_key'] == 'STL'
