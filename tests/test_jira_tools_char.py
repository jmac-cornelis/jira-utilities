from unittest.mock import MagicMock

import pytest

from tools.jira_tools import JiraTools


def test_get_ticket_tool_returns_comments_and_transitions(
    monkeypatch: pytest.MonkeyPatch,
    fake_issue_resource_factory,
):
    from tools import jira_tools

    jira = MagicMock()
    issue = fake_issue_resource_factory(
        key='STL-800',
        comments=[
            {
                'id': '1',
                'author': {'displayName': 'Dev User', 'accountId': 'acct-dev'},
                'created': '2026-03-14T10:00:00.000+0000',
                'updated': '2026-03-14T10:00:00.000+0000',
                'body': 'Looks good',
            }
        ],
    )
    jira.issue.return_value = issue
    jira.transitions.return_value = [
        {
            'id': '21',
            'name': 'Start Progress',
            'to': {'name': 'In Progress'},
            'fields': {
                'resolution': {
                    'name': 'Resolution',
                    'required': True,
                    'schema': {'type': 'string'},
                }
            },
        }
    ]

    monkeypatch.setattr(jira_tools, 'get_jira', lambda: jira)

    result = jira_tools.get_ticket(
        'STL-800',
        include_comments=True,
        include_transitions=True,
    )

    assert result.is_success
    assert result.data['key'] == 'STL-800'
    assert result.data['comments'][0]['body'] == 'Looks good'
    assert result.data['transitions'][0]['to'] == 'In Progress'
    assert result.data['transitions'][0]['fields'][0]['key'] == 'resolution'


def test_get_project_fields_tool_delegates(monkeypatch: pytest.MonkeyPatch):
    from tools import jira_tools

    jira = object()
    monkeypatch.setattr(jira_tools, 'get_jira', lambda: jira)
    monkeypatch.setattr(
        jira_tools,
        '_ju_get_project_fields',
        lambda _jira, project_key, issue_type_names=None: {
            'project': project_key,
            'issue_types': [{'name': 'Bug', 'create_fields': [], 'edit_fields': [], 'transitions': []}],
            'selected_issue_types': issue_type_names,
        },
    )

    result = jira_tools.get_project_fields('STL', issue_types=['Bug'])

    assert result.is_success
    assert result.data['project'] == 'STL'
    assert result.data['selected_issue_types'] == ['Bug']


def test_transition_ticket_tool_applies_transition_and_comment(
    monkeypatch: pytest.MonkeyPatch,
    fake_issue_resource_factory,
):
    from tools import jira_tools

    jira = MagicMock()
    issue = fake_issue_resource_factory(key='STL-801')
    jira.issue.return_value = issue
    jira.transitions.return_value = [
        {'id': '11', 'name': 'In Progress', 'to': {'name': 'In Progress'}, 'fields': {}}
    ]

    monkeypatch.setattr(jira_tools, 'get_jira', lambda: jira)

    result = jira_tools.transition_ticket(
        'STL-801',
        'In Progress',
        comment='Started work',
        fields={'resolution': {'name': 'Fixed'}},
    )

    assert result.is_success
    jira.transition_issue.assert_called_once_with(
        issue,
        '11',
        fields={'resolution': {'name': 'Fixed'}},
    )
    jira.add_comment.assert_called_once_with(issue, 'Started work')
    assert result.data['transition']['to'] == 'In Progress'
    assert result.data['comment_added'] is True


def test_jira_tools_collection_registers_new_methods():
    tools = JiraTools()

    assert tools.get_tool('get_ticket') is not None
    assert tools.get_tool('get_project_fields') is not None
    assert tools.get_tool('list_transitions') is not None
    assert tools.get_tool('transition_ticket') is not None
    assert tools.get_tool('add_ticket_comment') is not None
