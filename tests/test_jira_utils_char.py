import os
import sys
from types import SimpleNamespace
from typing import Any, Optional

import pytest

import jira_utils


class _Response:
    def __init__(
        self,
        status_code: int = 200,
        payload: Optional[dict[str, Any]] = None,
        text: str = '',
        headers: Optional[dict[str, str]] = None,
    ):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self._payload


def _silent_output(_message: str = '') -> None:
    return None


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jira_utils, 'output', _silent_output)
    monkeypatch.setattr(jira_utils, 'show_jql', lambda _jql: None)


def test_get_jira_credentials_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('JIRA_EMAIL', 'engineer@cornelisnetworks.com')
    monkeypatch.setenv('JIRA_API_TOKEN', 'token-123')

    email, token = jira_utils.get_jira_credentials()

    assert email == 'engineer@cornelisnetworks.com'
    assert token == 'token-123'


def test_get_jira_credentials_missing_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('JIRA_EMAIL', 'engineer@cornelisnetworks.com')
    monkeypatch.delenv('JIRA_API_TOKEN', raising=False)

    with pytest.raises(jira_utils.JiraCredentialsError):
        jira_utils.get_jira_credentials()


def test_get_connection_caches_and_reset(monkeypatch: pytest.MonkeyPatch):
    sentinel = object()
    call_count = {'count': 0}

    def _fake_connect():
        call_count['count'] += 1
        return sentinel

    monkeypatch.setattr(jira_utils, 'connect_to_jira', _fake_connect)
    jira_utils.reset_connection()

    conn1 = jira_utils.get_connection()
    conn2 = jira_utils.get_connection()

    assert conn1 is sentinel
    assert conn2 is sentinel
    assert call_count['count'] == 1

    jira_utils.reset_connection()
    _ = jira_utils.get_connection()
    assert call_count['count'] == 2


def test_normalize_issue_types_case_insensitive(mock_jira):
    result = jira_utils.normalize_issue_types(mock_jira, 'STL', ['bug', 'STORY'])
    assert result == ['Bug', 'Story']


def test_normalize_statuses_supports_exclusions(mock_jira):
    result = jira_utils.normalize_statuses(mock_jira, ['open', '^closed'])
    assert isinstance(result, dict)
    assert result['include'] == ['Open']
    assert result['exclude'] == ['Closed']


def test_parse_date_filter_keywords_and_range():
    assert jira_utils.parse_date_filter('today') == 'AND created >= startOfDay()'
    assert jira_utils.parse_date_filter('week') == 'AND created >= -7d'

    clause = jira_utils.parse_date_filter('01-01-2026:01-31-2026')
    assert clause == 'AND created >= "2026-01-01" AND created <= "2026-01-31"'


def test_match_pattern_with_exclusions():
    assert jira_utils.match_pattern_with_exclusions('12.1.0', '12.*') is True
    assert jira_utils.match_pattern_with_exclusions('12.1.0 Samples', '12.*,^*Samples*') is False


def test_user_resolver_passthrough_account_id(mock_jira):
    resolver = jira_utils.UserResolver(jira=mock_jira)

    account_id = resolver.resolve('712020:daf767ac-1111-2222-3333-abcdef123456', project_key='STL')

    assert account_id == '712020:daf767ac-1111-2222-3333-abcdef123456'


def test_user_resolver_resolves_assignable_user(mock_jira):
    resolver = jira_utils.UserResolver(jira=mock_jira)

    resolved = resolver.resolve('John Doe', project_key='STL')

    assert resolved == 'acct-jdoe'


def test_user_resolver_returns_none_for_ambiguous(mock_jira, monkeypatch: pytest.MonkeyPatch):
    resolver = jira_utils.UserResolver(jira=mock_jira)

    users = [
        SimpleNamespace(accountId='acct-a', displayName='Alex Kim', emailAddress='alex.kim@cornelisnetworks.com'),
        SimpleNamespace(accountId='acct-b', displayName='Alex King', emailAddress='alex.king@cornelisnetworks.com'),
    ]
    mock_jira.search_assignable_users_for_issues.return_value = users

    resolved = resolver.resolve('Alex Ki', project_key='STL')

    assert resolved is None


def test_list_projects_returns_rows(mock_jira, monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)

    proj_a = SimpleNamespace(key='STL', name='Storage', lead=SimpleNamespace(displayName='Lead A'))
    proj_b = SimpleNamespace(key='CN', name='Cornelis', lead=SimpleNamespace(displayName='Lead B'))
    mock_jira.projects.return_value = [proj_a, proj_b]

    rows = jira_utils.list_projects(mock_jira)

    assert rows == [
        {'key': 'CN', 'name': 'Cornelis', 'lead': 'Lead B'},
        {'key': 'STL', 'name': 'Storage', 'lead': 'Lead A'},
    ]


def test_get_project_workflows_returns_status_payload(mock_jira, monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)

    result = jira_utils.get_project_workflows(mock_jira, 'STL')

    assert result['project'] == 'STL'
    assert result['project_name'] == 'Storage Team'
    assert any(item['name'] == 'Open' for item in result['statuses'])


def test_get_project_issue_types_returns_payload(mock_jira, monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)

    result = jira_utils.get_project_issue_types(mock_jira, 'STL')

    assert result['project'] == 'STL'
    assert any(item['name'] == 'Bug' for item in result['issue_types'])


def test_get_project_versions_returns_payload(mock_jira, monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)

    result = jira_utils.get_project_versions(mock_jira, 'STL')

    assert result['project'] == 'STL'
    assert len(result['versions']) == 3
    assert result['versions'][0]['name'] in {'11.9.0', '12.1.0', '12.1.1'}


def test_get_tickets_returns_issue_dicts(mock_jira, issue_factory, monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(jira_utils, 'get_jira_credentials', lambda: ('e', 't'))

    issue = issue_factory(key='STL-100', summary='A ticket')

    def _fake_post(_url: str, auth=None, headers=None, json=None):
        return _Response(status_code=200, payload={'issues': [issue], 'nextPageToken': None})

    monkeypatch.setattr(jira_utils.requests, 'post', _fake_post)

    issues = jira_utils.get_tickets(mock_jira, 'STL', limit=10)

    assert isinstance(issues, list)
    assert issues[0]['key'] == 'STL-100'


def test_get_release_tickets_returns_issue_dicts(mock_jira, issue_factory, monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(jira_utils, 'get_jira_credentials', lambda: ('e', 't'))

    issue = issue_factory(key='STL-101')

    def _fake_post(_url: str, auth=None, headers=None, json=None):
        return _Response(status_code=200, payload={'issues': [issue], 'nextPageToken': None})

    monkeypatch.setattr(jira_utils.requests, 'post', _fake_post)

    issues = jira_utils.get_release_tickets(mock_jira, 'STL', '12.1.0', limit=25)

    assert isinstance(issues, list)
    assert issues[0]['key'] == 'STL-101'


def test_get_releases_tickets_returns_issue_dicts(mock_jira, issue_factory, monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(jira_utils, 'get_jira_credentials', lambda: ('e', 't'))

    issue = issue_factory(key='STL-102')

    def _fake_post(_url: str, auth=None, headers=None, json=None):
        return _Response(status_code=200, payload={'issues': [issue], 'nextPageToken': None})

    monkeypatch.setattr(jira_utils.requests, 'post', _fake_post)

    issues = jira_utils.get_releases_tickets(mock_jira, 'STL', '12.*', limit=25)

    assert isinstance(issues, list)
    assert issues[0]['key'] == 'STL-102'


def test_get_no_release_tickets_returns_issue_dicts(mock_jira, issue_factory, monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(jira_utils, 'get_jira_credentials', lambda: ('e', 't'))

    issue = issue_factory(key='STL-103')

    def _fake_post(_url: str, auth=None, headers=None, json=None):
        return _Response(status_code=200, payload={'issues': [issue], 'nextPageToken': None})

    monkeypatch.setattr(jira_utils.requests, 'post', _fake_post)

    issues = jira_utils.get_no_release_tickets(mock_jira, 'STL', limit=25)

    assert isinstance(issues, list)
    assert issues[0]['key'] == 'STL-103'


def test_get_ticket_totals_returns_count_dict(mock_jira, monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(jira_utils, 'get_jira_credentials', lambda: ('e', 't'))

    def _fake_post(_url: str, auth=None, headers=None, json=None):
        return _Response(status_code=200, payload={'count': 37})

    monkeypatch.setattr(jira_utils.requests, 'post', _fake_post)

    result = jira_utils.get_ticket_totals(mock_jira, 'STL')

    assert result['project'] == 'STL'
    assert result['count'] == 37


def test_handle_args_legacy_get_tickets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, 'argv', ['jira_utils.py', '--project', 'STL', '--get-tickets'])

    args = jira_utils.handle_args()

    assert args.project == 'STL'
    assert args.get_tickets is True


def test_handle_args_requires_project_for_get_tickets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, 'argv', ['jira_utils.py', '--get-tickets'])

    with pytest.raises(SystemExit):
        jira_utils.handle_args()


def test_output_respects_quiet_mode(monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setattr(jira_utils, '_quiet_mode', False)
    jira_utils.output('visible message')
    out_visible = capsys.readouterr().out

    monkeypatch.setattr(jira_utils, '_quiet_mode', True)
    jira_utils.output('hidden message')
    out_hidden = capsys.readouterr().out

    assert 'visible message' in out_visible
    assert out_hidden == ''


def test_display_jql_writes_file(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(jira_utils, '_show_jql', True)
    monkeypatch.setattr(jira_utils, '_last_jql', 'project = "STL" ORDER BY created DESC')

    jira_utils.display_jql()

    assert (tmp_path / 'jql.txt').read_text(encoding='utf-8') == 'project = "STL" ORDER BY created DESC'
