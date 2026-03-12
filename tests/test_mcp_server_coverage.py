import contextlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests


class _Response:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def _payload(result):
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].type == 'text'
    return json.loads(result[0].text)


def _issue(
    key='STL-1',
    summary='Summary',
    issue_type='Bug',
    status='Open',
    priority='P1-Critical',
    assignee='Dev User',
    reporter='Reporter User',
    description='Body',
):
    return {
        'key': key,
        'fields': {
            'summary': summary,
            'issuetype': {'name': issue_type},
            'status': {'name': status},
            'priority': {'name': priority},
            'assignee': {'displayName': assignee} if assignee is not None else None,
            'reporter': {'displayName': reporter} if reporter is not None else None,
            'created': '2026-03-01T00:00:00.000+0000',
            'updated': '2026-03-02T00:00:00.000+0000',
            'fixVersions': [{'name': '12.1.1'}],
            'components': [{'name': 'Fabric'}],
            'labels': ['triage'],
            'description': description,
        },
    }


def test_json_result_formats_payload(import_mcp_server):
    result = import_mcp_server._json_result({'ok': True})
    data = _payload(result)
    assert data == {'ok': True}


def test_json_result_uses_default_str(import_mcp_server):
    result = import_mcp_server._json_result({'value': SimpleNamespace(name='x')})
    data = _payload(result)
    assert 'namespace' in data['value']


def test_error_result_formats_payload(import_mcp_server):
    result = import_mcp_server._error_result('failed')
    data = _payload(result)
    assert data == {'error': 'failed'}


def test_issue_to_dict_with_resource_object(import_mcp_server):
    issue = _issue(key='STL-501', description='Resource body')
    resource = SimpleNamespace(key='STL-501', raw={'fields': issue['fields']})

    result = import_mcp_server._issue_to_dict(resource)

    assert result['key'] == 'STL-501'
    assert result['issue_type'] == 'Bug'
    assert result['status'] == 'Open'
    assert result['description'] == 'Resource body'


def test_issue_to_dict_with_unknown_shape(import_mcp_server):
    result = import_mcp_server._issue_to_dict(object())
    assert 'raw' in result
    assert 'object object' in result['raw']


def test_issue_to_dict_missing_fields_defaults(import_mcp_server):
    result = import_mcp_server._issue_to_dict({'key': 'STL-9', 'fields': {}})
    assert result['assignee'] == 'Unassigned'
    assert result['reporter'] == 'Unknown'
    assert result['issue_type'] == 'N/A'
    assert result['status'] == 'N/A'


def test_extract_description_variants(import_mcp_server):
    adf = {
        'type': 'doc',
        'content': [
            {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'First'}]},
            {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Second'}]},
        ],
    }

    assert import_mcp_server._extract_description(None) == ''
    assert import_mcp_server._extract_description('plain') == 'plain'
    assert import_mcp_server._extract_description(adf) == 'First\nSecond'
    assert import_mcp_server._extract_description(42) == '42'


def test_tool_decorator_passthrough_when_server_lacks_tool(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server, 'server', SimpleNamespace())

    decorator = import_mcp_server._tool_decorator()

    def sample():
        return 'ok'

    wrapped = decorator(sample)
    assert wrapped is sample
    assert wrapped() == 'ok'


def test_main_runs_transport_stdio(import_mcp_server, monkeypatch):
    fake_server = MagicMock()
    fake_server.tool = MagicMock()

    monkeypatch.setattr(import_mcp_server, 'server', fake_server)
    monkeypatch.setenv('JIRA_URL', 'https://jira.example.test')
    monkeypatch.setenv('JIRA_EMAIL', 'tester@example.test')

    import_mcp_server.main()

    fake_server.run.assert_called_once_with(transport='stdio')


def test_main_runs_lowlevel_server(import_mcp_server, monkeypatch):
    class LowLevelServer:
        def __init__(self):
            self.run_calls = []

        async def run(self, read_stream, write_stream, options):
            self.run_calls.append((read_stream, write_stream, options))

        def create_initialization_options(self):
            return {'hello': 'world'}

    @contextlib.asynccontextmanager
    async def fake_stdio_server():
        yield ('reader', 'writer')

    low_server = LowLevelServer()

    monkeypatch.setattr(import_mcp_server, 'server', low_server)
    monkeypatch.setattr(import_mcp_server, 'stdio_server', fake_stdio_server)

    import_mcp_server.main()

    assert low_server.run_calls == [('reader', 'writer', {'hello': 'world'})]


def test_run_calls_main(import_mcp_server, monkeypatch):
    called = {'count': 0}

    def fake_main():
        called['count'] += 1

    monkeypatch.setattr(import_mcp_server, 'main', fake_main)

    import_mcp_server.run()

    assert called['count'] == 1


@pytest.mark.asyncio
async def test_search_tickets_success(import_mcp_server, monkeypatch):
    jira = object()
    issue = _issue(key='STL-700')

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    run_query = MagicMock(return_value=[issue])
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', run_query)

    result = await import_mcp_server.search_tickets('project = STL', limit=10)
    data = _payload(result)

    run_query.assert_called_once_with(jira, 'project = STL', limit=10)
    assert data[0]['key'] == 'STL-700'


@pytest.mark.asyncio
async def test_search_tickets_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: (_ for _ in ()).throw(RuntimeError('boom')))

    result = await import_mcp_server.search_tickets('project = STL')
    data = _payload(result)

    assert 'boom' in data['error']


@pytest.mark.asyncio
async def test_get_ticket_success(import_mcp_server, monkeypatch):
    jira = object()
    issue = _issue(key='STL-701')

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    run_query = MagicMock(return_value=[issue])
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', run_query)

    result = await import_mcp_server.get_ticket('STL-701')
    data = _payload(result)

    run_query.assert_called_once_with(jira, 'key = "STL-701"', limit=1)
    assert data['key'] == 'STL-701'


@pytest.mark.asyncio
async def test_get_ticket_not_found(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', lambda _jira, _jql, limit=1: [])

    result = await import_mcp_server.get_ticket('STL-999')
    data = _payload(result)

    assert data['error'] == 'Ticket STL-999 not found'


@pytest.mark.asyncio
async def test_create_ticket_success_with_key_lookup(import_mcp_server, monkeypatch):
    jira = object()
    issue = _issue(key='STL-710')
    create_ticket_mock = MagicMock()
    run_query = MagicMock(return_value=[issue])

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'create_ticket', create_ticket_mock)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', run_query)

    result = await import_mcp_server.create_ticket(
        project_key='STL',
        summary='New ticket',
        issue_type='Bug',
        description='Body',
        assignee='acct-1',
        priority='High',
        fix_version='12.1.1',
        labels='backend, urgent',
        parent_key='STL-100',
    )
    data = _payload(result)

    create_ticket_mock.assert_called_once_with(
        jira,
        project_key='STL',
        summary='New ticket',
        issue_type='Bug',
        description='Body',
        assignee='acct-1',
        fix_versions=['12.1.1'],
        labels=['backend', 'urgent'],
        parent_key='STL-100',
        dry_run=False,
    )
    run_query.assert_called_once_with(
        jira,
        'project = "STL" AND summary ~ "New ticket" ORDER BY created DESC',
        limit=1,
    )
    assert data['key'] == 'STL-710'
    assert data['message'] == 'Ticket created successfully'


@pytest.mark.asyncio
async def test_create_ticket_success_without_lookup_result(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'create_ticket', MagicMock())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', lambda _jira, _jql, limit=1: [])

    result = await import_mcp_server.create_ticket(
        project_key='STL',
        summary='New ticket',
        issue_type='Task',
    )
    data = _payload(result)

    assert data['message'] == 'Ticket created successfully (could not retrieve key)'


@pytest.mark.asyncio
async def test_update_ticket_updates_fields_and_transitions(import_mcp_server, monkeypatch):
    jira = MagicMock()
    issue_resource = MagicMock()
    jira.issue.return_value = issue_resource
    jira.transitions.return_value = [
        {'id': '11', 'name': 'In Progress', 'to': {'name': 'In Progress'}},
    ]

    run_query = MagicMock(return_value=[_issue(key='STL-720')])

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, '_adf_from_text', lambda text: {'adf': text})
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', run_query)

    result = await import_mcp_server.update_ticket(
        ticket_key='STL-720',
        summary='Updated summary',
        status='In Progress',
        assignee='acct-user',
        priority='High',
        fix_version='12.1.2',
        labels='alpha, beta',
        description='Updated body',
    )
    data = _payload(result)

    issue_resource.update.assert_called_once_with(
        fields={
            'summary': 'Updated summary',
            'priority': {'name': 'High'},
            'assignee': {'accountId': 'acct-user'},
            'fixVersions': [{'name': '12.1.2'}],
            'labels': ['alpha', 'beta'],
            'description': {'adf': 'Updated body'},
        }
    )
    jira.transition_issue.assert_called_once_with(issue_resource, '11')
    run_query.assert_called_once_with(jira, 'key = "STL-720"', limit=1)
    assert data['key'] == 'STL-720'
    assert data['message'] == 'Ticket updated successfully'


@pytest.mark.asyncio
async def test_update_ticket_matches_transition_destination_name(import_mcp_server, monkeypatch):
    jira = MagicMock()
    issue_resource = MagicMock()
    jira.issue.return_value = issue_resource
    jira.transitions.return_value = [
        {'id': '33', 'name': 'Start Verify', 'to': {'name': 'Verify'}},
    ]

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', lambda _jira, _jql, limit=1: [_issue(key='STL-721')])

    result = await import_mcp_server.update_ticket(ticket_key='STL-721', status='verify')
    data = _payload(result)

    jira.transition_issue.assert_called_once_with(issue_resource, '33')
    assert data['message'] == 'Ticket updated successfully'


@pytest.mark.asyncio
async def test_update_ticket_returns_error_when_transition_not_available(import_mcp_server, monkeypatch):
    jira = MagicMock()
    issue_resource = MagicMock()
    jira.issue.return_value = issue_resource
    jira.transitions.return_value = [
        {'id': '9', 'name': 'Open', 'to': {'name': 'Open'}},
        {'id': '10', 'name': 'Done', 'to': {'name': 'Done'}},
    ]

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)

    result = await import_mcp_server.update_ticket(ticket_key='STL-722', status='Closed')
    data = _payload(result)

    assert 'Cannot transition to "Closed"' in data['error']
    assert 'Open' in data['error']
    assert 'Done' in data['error']


@pytest.mark.asyncio
async def test_list_filters_success_for_search_endpoint(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_jira_credentials', lambda: ('user@example.test', 'token'))

    calls = []

    def fake_get(url, auth=None, headers=None, params=None):
        calls.append({'url': url, 'auth': auth, 'headers': headers, 'params': params})
        return _Response(
            status_code=200,
            payload={
                'values': [
                    {
                        'id': '123',
                        'name': 'Open Bugs',
                        'owner': {'displayName': 'Owner Name'},
                        'jql': 'project = STL',
                        'description': 'Desc',
                        'favourite': True,
                    }
                ]
            },
        )

    monkeypatch.setattr(requests, 'get', fake_get)

    result = await import_mcp_server.list_filters(favourite_only=False)
    data = _payload(result)

    assert calls[0]['url'].endswith('/rest/api/3/filter/search')
    assert calls[0]['params'] == {'maxResults': 100, 'expand': 'description,jql,owner'}
    assert data == [
        {
            'id': '123',
            'name': 'Open Bugs',
            'owner': 'Owner Name',
            'jql': 'project = STL',
            'description': 'Desc',
            'favourite': True,
        }
    ]


@pytest.mark.asyncio
async def test_list_filters_success_for_favourite_endpoint(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_jira_credentials', lambda: ('user@example.test', 'token'))

    calls = []

    def fake_get(url, auth=None, headers=None, params=None):
        calls.append({'url': url, 'params': params})
        return _Response(
            status_code=200,
            payload=[
                {
                    'id': '999',
                    'name': 'Fav Filter',
                    'owner': {'displayName': 'Fav Owner'},
                    'jql': 'project = STL',
                    'description': '',
                    'favourite': True,
                }
            ],
        )

    monkeypatch.setattr(requests, 'get', fake_get)

    result = await import_mcp_server.list_filters(favourite_only=True)
    data = _payload(result)

    assert calls[0]['url'].endswith('/rest/api/3/filter/favourite')
    assert calls[0]['params'] is None
    assert data[0]['id'] == '999'


@pytest.mark.asyncio
async def test_list_filters_api_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_jira_credentials', lambda: ('user@example.test', 'token'))
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: _Response(status_code=500, payload={}, text='bad gateway'))

    result = await import_mcp_server.list_filters()
    data = _payload(result)

    assert data['error'] == 'Jira API error: 500 - bad gateway'


@pytest.mark.asyncio
async def test_run_filter_success(import_mcp_server, monkeypatch):
    jira = object()
    run_query = MagicMock(return_value=[_issue(key='STL-730')])

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_jira_credentials', lambda: ('user@example.test', 'token'))
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', run_query)
    monkeypatch.setattr(
        requests,
        'get',
        lambda *args, **kwargs: _Response(status_code=200, payload={'name': 'Open Bugs', 'jql': 'project = STL'}),
    )

    result = await import_mcp_server.run_filter('12345', limit=15)
    data = _payload(result)

    run_query.assert_called_once_with(jira, 'project = STL', limit=15)
    assert data['filter_id'] == '12345'
    assert data['filter_name'] == 'Open Bugs'
    assert data['tickets'][0]['key'] == 'STL-730'


@pytest.mark.asyncio
async def test_run_filter_not_found(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_jira_credentials', lambda: ('user@example.test', 'token'))
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: _Response(status_code=404, payload={} ))

    result = await import_mcp_server.run_filter('404')
    data = _payload(result)

    assert data['error'] == 'Filter 404 not found'


@pytest.mark.asyncio
async def test_run_filter_missing_jql(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_jira_credentials', lambda: ('user@example.test', 'token'))
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: _Response(status_code=200, payload={'name': 'No JQL'}))

    result = await import_mcp_server.run_filter('777')
    data = _payload(result)

    assert data['error'] == 'Filter 777 has no JQL query'


@pytest.mark.asyncio
async def test_run_filter_api_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_jira_credentials', lambda: ('user@example.test', 'token'))
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: _Response(status_code=401, payload={}, text='unauthorized'))

    result = await import_mcp_server.run_filter('12345')
    data = _payload(result)

    assert data['error'] == 'Jira API error: 401 - unauthorized'


@pytest.mark.asyncio
async def test_get_releases_success_with_pattern(import_mcp_server, monkeypatch):
    jira = MagicMock()
    jira.project_versions.return_value = [
        SimpleNamespace(name='12.1.0', id='1001', released=False, archived=False, releaseDate='2026-01-01', description='A'),
        SimpleNamespace(name='11.9.0', id='1002', released=True, archived=False, releaseDate='2025-12-01', description='B'),
    ]

    validate_project = MagicMock()
    match_pattern = MagicMock(side_effect=lambda name, pattern: name.startswith('12.'))

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'validate_project', validate_project)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'match_pattern_with_exclusions', match_pattern)

    result = await import_mcp_server.get_releases('STL', pattern='12.*')
    data = _payload(result)

    validate_project.assert_called_once_with(jira, 'STL')
    assert len(data) == 1
    assert data[0]['name'] == '12.1.0'
    assert match_pattern.call_count == 2


@pytest.mark.asyncio
async def test_get_releases_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: (_ for _ in ()).throw(RuntimeError('no jira')))

    result = await import_mcp_server.get_releases('STL')
    data = _payload(result)

    assert 'no jira' in data['error']


@pytest.mark.asyncio
async def test_get_release_tickets_success(import_mcp_server, monkeypatch):
    jira = object()
    run_query = MagicMock(return_value=[_issue(key='STL-740')])

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', run_query)

    result = await import_mcp_server.get_release_tickets('STL', '12.1.1', limit=5)
    data = _payload(result)

    run_query.assert_called_once_with(
        jira,
        'project = "STL" AND fixVersion = "12.1.1" ORDER BY key ASC',
        limit=5,
    )
    assert data['project'] == 'STL'
    assert data['release'] == '12.1.1'
    assert data['tickets'][0]['key'] == 'STL-740'


@pytest.mark.asyncio
async def test_get_release_tickets_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'run_jql_query', lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('query failed')))

    result = await import_mcp_server.get_release_tickets('STL', '12.1.1')
    data = _payload(result)

    assert data['error'] == 'query failed'


@pytest.mark.asyncio
async def test_get_children_success(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(
        import_mcp_server.jira_utils,
        '_get_children_data',
        lambda _jira, _root_key, limit=50: [
            {'issue': _issue(key='STL-100'), 'depth': 0},
            {'issue': _issue(key='STL-101'), 'depth': 1},
        ],
    )

    result = await import_mcp_server.get_children('STL-100', limit=10)
    data = _payload(result)

    assert [item['key'] for item in data] == ['STL-100', 'STL-101']
    assert [item['depth'] for item in data] == [0, 1]


@pytest.mark.asyncio
async def test_get_children_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, '_get_children_data', lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('children failed')))

    result = await import_mcp_server.get_children('STL-100')
    data = _payload(result)

    assert data['error'] == 'children failed'


@pytest.mark.asyncio
async def test_get_related_success(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(
        import_mcp_server.jira_utils,
        '_get_related_data',
        lambda _jira, _root_key, hierarchy=None, limit=50: [
            {'issue': _issue(key='STL-200'), 'depth': 0, 'via': 'root', 'relation': 'self', 'from_key': ''},
            {'issue': _issue(key='STL-201'), 'depth': 1, 'via': 'issuelink', 'relation': 'blocks', 'from_key': 'STL-200'},
        ],
    )

    result = await import_mcp_server.get_related('STL-200', depth=2, limit=20)
    data = _payload(result)

    assert data[0]['key'] == 'STL-200'
    assert data[1]['via'] == 'issuelink'
    assert data[1]['relation'] == 'blocks'
    assert data[1]['from_key'] == 'STL-200'


@pytest.mark.asyncio
async def test_get_related_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, '_get_related_data', lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('related failed')))

    result = await import_mcp_server.get_related('STL-200')
    data = _payload(result)

    assert data['error'] == 'related failed'


@pytest.mark.asyncio
async def test_get_project_info_success_with_issue_types(import_mcp_server, monkeypatch):
    jira = MagicMock()
    jira.createmeta.return_value = {
        'projects': [
            {
                'issuetypes': [
                    {'name': 'Bug'},
                    {'name': 'Task'},
                ]
            }
        ]
    }
    project = SimpleNamespace(
        key='STL',
        name='Storage Team',
        lead={'displayName': 'Project Lead'},
        description='Project description',
        projectTypeKey='software',
    )

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'validate_project', lambda _jira, _key: project)

    result = await import_mcp_server.get_project_info('STL')
    data = _payload(result)

    assert data['key'] == 'STL'
    assert data['name'] == 'Storage Team'
    assert data['lead'] == 'Project Lead'
    assert data['issue_types'] == ['Bug', 'Task']


@pytest.mark.asyncio
async def test_get_project_info_when_createmeta_fails(import_mcp_server, monkeypatch):
    jira = MagicMock()
    jira.createmeta.side_effect = RuntimeError('createmeta failed')
    project = SimpleNamespace(
        key='STL',
        name='Storage Team',
        lead='Lead String',
        description='',
        projectTypeKey='software',
    )

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'validate_project', lambda _jira, _key: project)

    result = await import_mcp_server.get_project_info('STL')
    data = _payload(result)

    assert data['key'] == 'STL'
    assert data['lead'] == 'Lead String'
    assert 'issue_types' not in data


@pytest.mark.asyncio
async def test_get_project_info_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'validate_project', lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('invalid project')))

    result = await import_mcp_server.get_project_info('BAD')
    data = _payload(result)

    assert data['error'] == 'invalid project'


@pytest.mark.asyncio
async def test_get_components_success(import_mcp_server, monkeypatch):
    jira = MagicMock()
    jira.project_components.return_value = [
        SimpleNamespace(name='Fabric', id='c1', lead={'displayName': 'Lead A'}, description='Component A'),
        SimpleNamespace(name='Driver', id='c2', lead='Lead B', description=None),
    ]

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'validate_project', lambda _jira, _project_key: True)

    result = await import_mcp_server.get_components('STL')
    data = _payload(result)

    assert data == [
        {'name': 'Fabric', 'id': 'c1', 'lead': 'Lead A', 'description': 'Component A'},
        {'name': 'Driver', 'id': 'c2', 'lead': 'Lead B', 'description': ''},
    ]


@pytest.mark.asyncio
async def test_get_components_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: (_ for _ in ()).throw(RuntimeError('no connection')))

    result = await import_mcp_server.get_components('STL')
    data = _payload(result)

    assert data['error'] == 'no connection'


@pytest.mark.asyncio
async def test_assign_ticket_unassigned(import_mcp_server, monkeypatch):
    jira = MagicMock()
    issue = MagicMock()
    jira.issue.return_value = issue

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)

    result = await import_mcp_server.assign_ticket('STL-800', 'unassigned')
    data = _payload(result)

    issue.update.assert_called_once_with(fields={'assignee': None})
    assert data['key'] == 'STL-800'
    assert data['assignee'] == 'unassigned'


@pytest.mark.asyncio
async def test_assign_ticket_resolved_via_user_resolver(import_mcp_server, monkeypatch):
    jira = MagicMock()
    issue = MagicMock()
    jira.issue.return_value = issue

    resolver = MagicMock()
    resolver.resolve.return_value = 'acct-jane'

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_user_resolver', lambda: resolver)

    result = await import_mcp_server.assign_ticket('STL-801', 'Jane Smith')
    data = _payload(result)

    resolver.resolve.assert_called_once_with('Jane Smith', project_key='STL')
    issue.update.assert_called_once_with(fields={'assignee': {'accountId': 'acct-jane'}})
    assert data['assignee'] == 'Jane Smith'


@pytest.mark.asyncio
async def test_assign_ticket_unresolved_user(import_mcp_server, monkeypatch):
    jira = MagicMock()
    jira.issue.return_value = MagicMock()

    resolver = MagicMock()
    resolver.resolve.return_value = None

    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_user_resolver', lambda: resolver)

    result = await import_mcp_server.assign_ticket('STL-802', 'Unknown User')
    data = _payload(result)

    assert data['error'] == 'Could not resolve assignee "Unknown User" to a Jira accountId'


@pytest.mark.asyncio
async def test_assign_ticket_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: (_ for _ in ()).throw(RuntimeError('assign failed')))

    result = await import_mcp_server.assign_ticket('STL-803', 'someone')
    data = _payload(result)

    assert data['error'] == 'assign failed'


@pytest.mark.asyncio
async def test_link_tickets_success(import_mcp_server, monkeypatch):
    jira = MagicMock()
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: jira)

    result = await import_mcp_server.link_tickets('STL-810', 'STL-811', link_type='Blocks')
    data = _payload(result)

    jira.create_issue_link.assert_called_once_with(
        type='Blocks',
        inwardIssue='STL-810',
        outwardIssue='STL-811',
    )
    assert data['from_key'] == 'STL-810'
    assert data['to_key'] == 'STL-811'
    assert data['link_type'] == 'Blocks'


@pytest.mark.asyncio
async def test_link_tickets_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: (_ for _ in ()).throw(RuntimeError('link failed')))

    result = await import_mcp_server.link_tickets('STL-810', 'STL-811')
    data = _payload(result)

    assert data['error'] == 'link failed'


@pytest.mark.asyncio
async def test_list_dashboards_success_with_pagination(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_jira_credentials', lambda: ('user@example.test', 'token'))

    calls = []
    responses = [
        _Response(
            status_code=200,
            payload={
                'startAt': 0,
                'total': 3,
                'values': [
                    {'id': '1', 'name': 'Dashboard One', 'owner': {'displayName': 'Owner A'}, 'view': 'https://a'},
                    {'id': '2', 'name': 'Dashboard Two', 'owner': 'Owner B', 'view': 'https://b'},
                ],
            },
        ),
        _Response(
            status_code=200,
            payload={
                'startAt': 2,
                'total': 3,
                'values': [
                    {'id': '3', 'name': 'Dashboard Three', 'owner': {'displayName': 'Owner C'}, 'view': 'https://c'},
                ],
            },
        ),
    ]

    def fake_get(url, auth=None, headers=None, params=None):
        calls.append({'url': url, 'params': params, 'auth': auth, 'headers': headers})
        return responses.pop(0)

    monkeypatch.setattr(requests, 'get', fake_get)

    result = await import_mcp_server.list_dashboards()
    data = _payload(result)

    assert len(data) == 3
    assert data[0]['owner'] == 'Owner A'
    assert data[1]['owner'] == 'Owner B'
    assert calls[0]['params'] == {'maxResults': 100, 'startAt': 0}
    assert calls[1]['params'] == {'maxResults': 100, 'startAt': 2}


@pytest.mark.asyncio
async def test_list_dashboards_api_error(import_mcp_server, monkeypatch):
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(import_mcp_server.jira_utils, 'get_jira_credentials', lambda: ('user@example.test', 'token'))
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: _Response(status_code=503, payload={}, text='service unavailable'))

    result = await import_mcp_server.list_dashboards()
    data = _payload(result)

    assert data['error'] == 'Jira API error: 503 - service unavailable'
