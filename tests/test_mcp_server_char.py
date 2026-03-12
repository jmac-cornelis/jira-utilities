import sys
from types import SimpleNamespace
from typing import Any

import pytest


def test_issue_to_dict_shape(import_mcp_server):
    issue = {
        'key': 'STL-500',
        'fields': {
            'summary': 'Ticket summary',
            'issuetype': {'name': 'Bug'},
            'status': {'name': 'Open'},
            'priority': {'name': 'P1-Critical'},
            'assignee': {'displayName': 'Dev User'},
            'reporter': {'displayName': 'Reporter User'},
            'created': '2026-03-01T00:00:00.000+0000',
            'updated': '2026-03-02T00:00:00.000+0000',
            'fixVersions': [{'name': '12.1.1'}],
            'components': [{'name': 'Fabric'}],
            'labels': ['triage'],
            'description': 'Plain description',
        },
    }

    result = import_mcp_server._issue_to_dict(issue)

    assert result['key'] == 'STL-500'
    assert result['summary'] == 'Ticket summary'
    assert result['issue_type'] == 'Bug'
    assert result['status'] == 'Open'
    assert result['priority'] == 'P1-Critical'
    assert result['assignee'] == 'Dev User'
    assert result['fix_versions'] == ['12.1.1']


def test_extract_description_from_adf(import_mcp_server):
    adf = {
        'type': 'doc',
        'content': [
            {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'First'}]},
            {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Second'}]},
        ],
    }

    text = import_mcp_server._extract_description(adf)

    assert text == 'First\nSecond'


def test_extract_description_passthrough_string(import_mcp_server):
    assert import_mcp_server._extract_description('plain text') == 'plain text'


@pytest.mark.asyncio
async def test_search_tickets_tool_returns_json_text(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    fake_issue = {
        'key': 'STL-700',
        'fields': {
            'summary': 'Search result',
            'issuetype': {'name': 'Task'},
            'status': {'name': 'Open'},
            'priority': {'name': 'P2-Major'},
            'assignee': {'displayName': 'Dev'},
            'reporter': {'displayName': 'Rep'},
            'created': '2026-03-01T00:00:00.000+0000',
            'updated': '2026-03-02T00:00:00.000+0000',
            'fixVersions': [],
            'components': [],
            'labels': [],
            'description': 'Body',
        },
    }

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', lambda _jira, _jql, limit=50: [fake_issue])

    result = await import_mcp_server.search_tickets('project = STL', limit=1)

    assert isinstance(result, list)
    assert result[0].type == 'text'
    assert 'STL-700' in result[0].text


@pytest.mark.asyncio
async def test_get_ticket_not_found_shape(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', lambda _jira, _jql, limit=1: [])

    result = await import_mcp_server.get_ticket('STL-999999')

    assert isinstance(result, list)
    assert result[0].type == 'text'
    assert 'not found' in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_children_tool_shape(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    issue = {
        'key': 'STL-100',
        'fields': {
            'summary': 'Root',
            'issuetype': {'name': 'Story'},
            'status': {'name': 'Open'},
            'priority': {'name': 'P2-Major'},
            'assignee': {'displayName': 'Owner'},
            'reporter': {'displayName': 'Reporter'},
            'created': '2026-03-01T00:00:00.000+0000',
            'updated': '2026-03-02T00:00:00.000+0000',
            'fixVersions': [],
            'components': [],
            'labels': [],
            'description': 'Body',
        },
    }

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(
        import_mcp_server.jira_utils,
        '_get_children_data',
        lambda _jira, _root_key, limit=50: [{'issue': issue, 'depth': 0}],
    )

    result = await import_mcp_server.get_children('STL-100', limit=10)

    assert isinstance(result, list)
    assert 'depth' in result[0].text


def test_main_entrypoint_exists(import_mcp_server):
    assert callable(import_mcp_server.main)
    assert callable(import_mcp_server.run)


def test_import_path_uses_stubbed_mcp_modules(import_mcp_server):
    assert 'mcp' in sys.modules
    assert isinstance(import_mcp_server.server, (SimpleNamespace, object))
