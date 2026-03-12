from types import SimpleNamespace

from core.tickets import extract_text_from_adf, issue_to_dict


def test_issue_to_dict_resource_object_basic_fields():
    issue = SimpleNamespace(
        key='STL-501',
        id='501',
        fields=SimpleNamespace(
            summary='Resource summary',
            description='Resource description',
            issuetype=SimpleNamespace(name='Story'),
            status=SimpleNamespace(name='In Progress'),
            priority=SimpleNamespace(name='P1-Critical'),
            assignee=SimpleNamespace(displayName='Dev A', accountId='acct-dev-a'),
            reporter=SimpleNamespace(displayName='Reporter A', accountId='acct-reporter-a'),
            created='2026-02-01T10:11:12.000+0000',
            updated='2026-02-02T10:11:12.000+0000',
            resolutiondate='2026-02-03T10:11:12.000+0000',
            project=SimpleNamespace(key='STL'),
            fixVersions=[SimpleNamespace(name='12.2.0')],
            versions=[SimpleNamespace(name='12.1.0')],
            components=[SimpleNamespace(name='Fabric')],
            labels=['x', 'y'],
            customfield_12345=['A', 'B'],
        ),
    )

    result = issue_to_dict(issue)

    assert result['key'] == 'STL-501'
    assert result['id'] == '501'
    assert result['summary'] == 'Resource summary'
    assert result['description'] == 'Resource description'
    assert result['issue_type'] == 'Story'
    assert result['type'] == 'Story'
    assert result['status'] == 'In Progress'
    assert result['priority'] == 'P1-Critical'
    assert result['assignee'] == 'Dev A'
    assert result['assignee_id'] == 'acct-dev-a'
    assert result['reporter'] == 'Reporter A'
    assert result['project'] == 'STL'
    assert result['fix_versions'] == ['12.2.0']
    assert result['affects_versions'] == ['12.1.0']
    assert result['components'] == ['Fabric']
    assert result['labels'] == ['x', 'y']
    assert result['fix_version'] == '12.2.0'
    assert result['affects_version'] == '12.1.0'
    assert result['component'] == 'Fabric'
    assert result['labels_csv'] == 'x, y'
    assert result['created'] == '2026-02-01T10:11:12.000+0000'
    assert result['updated'] == '2026-02-02T10:11:12.000+0000'
    assert result['resolved'] == '2026-02-03T10:11:12.000+0000'
    assert result['created_date'] == '2026-02-01'
    assert result['updated_date'] == '2026-02-02'
    assert result['resolved_date'] == '2026-02-03'
    assert result['created_ts'] == '2026-02-01T10:11:12.000+0000'
    assert result['customfield_12345'] == ['A', 'B']


def test_issue_to_dict_raw_rest_dict_with_adf_description():
    issue = {
        'key': 'STL-777',
        'id': '777',
        'fields': {
            'summary': 'Raw summary',
            'description': {
                'type': 'doc',
                'content': [
                    {
                        'type': 'paragraph',
                        'content': [
                            {'type': 'text', 'text': 'Line one'},
                            {'type': 'text', 'text': ' line two'},
                        ],
                    },
                    {
                        'type': 'paragraph',
                        'content': [
                            {'type': 'text', 'text': 'Line three'},
                        ],
                    },
                ],
            },
            'issuetype': {'name': 'Bug'},
            'status': {'name': 'Open'},
            'priority': {'name': 'P0-Stopper'},
            'assignee': {'displayName': 'Dev B', 'accountId': 'acct-dev-b'},
            'reporter': {'displayName': 'Reporter B'},
            'project': {'key': 'STL'},
            'fixVersions': [{'name': '12.3.0'}],
            'versions': [{'name': '12.2.0'}],
            'components': [{'name': 'Driver'}, {'name': 'FW'}],
            'labels': ['alpha', 'beta'],
            'created': '2026-03-01T01:02:03.000+0000',
            'updated': '2026-03-04T01:02:03.000+0000',
            'resolutiondate': None,
            'customfield_20000': [{'value': 'CN5000'}],
        },
    }

    result = issue_to_dict(issue)

    assert result['key'] == 'STL-777'
    assert result['issue_type'] == 'Bug'
    assert result['description'] == 'Line one\n line two\nLine three'
    assert result['fix_versions'] == ['12.3.0']
    assert result['affects_versions'] == ['12.2.0']
    assert result['components'] == ['Driver', 'FW']
    assert result['labels'] == ['alpha', 'beta']
    assert result['url'].endswith('/browse/STL-777')
    assert result['customfield_20000'] == [{'value': 'CN5000'}]


def test_issue_to_dict_missing_fields_defaults():
    issue = {
        'key': 'STL-888',
        'fields': {
            'summary': 'Missing data',
            'assignee': None,
            'reporter': None,
            'components': [],
            'fixVersions': [],
            'versions': [],
            'labels': [],
            'description': None,
            'issuetype': None,
            'status': None,
            'priority': None,
        },
    }

    result = issue_to_dict(issue)

    assert result['issue_type'] == 'N/A'
    assert result['status'] == 'N/A'
    assert result['priority'] == 'N/A'
    assert result['assignee'] == 'Unassigned'
    assert result['reporter'] == 'Unknown'
    assert result['description'] == ''
    assert result['components'] == []
    assert result['fix_versions'] == []
    assert result['affects_versions'] == []
    assert result['labels'] == []
    assert result['fix_version'] == ''
    assert result['affects_version'] == ''
    assert result['component'] == ''


def test_extract_text_from_adf_plain_text_passthrough():
    assert extract_text_from_adf('plain body') == 'plain body'
    assert extract_text_from_adf(None) == ''


def test_extract_text_from_adf_nested_nodes():
    adf = {
        'type': 'doc',
        'content': [
            {
                'type': 'paragraph',
                'content': [
                    {'type': 'text', 'text': 'Top'},
                    {'type': 'text', 'text': ' level'},
                ],
            },
            {
                'type': 'bulletList',
                'content': [
                    {
                        'type': 'listItem',
                        'content': [
                            {
                                'type': 'paragraph',
                                'content': [
                                    {'type': 'text', 'text': 'Nested item'},
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
    }

    assert extract_text_from_adf(adf) == 'Top\n level\nNested item'
