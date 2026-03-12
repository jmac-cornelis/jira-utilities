from types import SimpleNamespace

from core import queries


def test_quote_values_single_value():
    assert queries._quote_values(['Open']) == '"Open"'


def test_quote_values_multiple_values_and_special_chars():
    values = ['In Progress', 'R&D', 'A, B']
    assert queries._quote_values(values) == '"In Progress", "R&D", "A, B"'


def test_build_status_jql_with_empty_inputs():
    assert queries._build_status_jql(None) == ''
    assert queries._build_status_jql([]) == ''
    assert queries._build_status_jql({}) == ''


def test_build_status_jql_with_list_statuses():
    status_jql = queries._build_status_jql(['Open', 'Verify'])
    assert status_jql == 'status IN ("Open", "Verify")'


def test_build_status_jql_with_include_and_exclude_dict():
    status_jql = queries._build_status_jql(
        {
            'include': ['In Progress', 'Verify'],
            'exclude': ['Closed'],
        }
    )
    assert status_jql == 'status IN ("In Progress", "Verify") AND status NOT IN ("Closed")'


def test_build_status_jql_with_exclude_only_dict():
    status_jql = queries._build_status_jql({'exclude': ['Closed', 'Done']})
    assert status_jql == 'status NOT IN ("Closed", "Done")'


def test_build_tickets_jql_project_only():
    jql = queries.build_tickets_jql('STL')
    assert jql == 'project = "STL" ORDER BY created DESC'


def test_build_tickets_jql_with_issue_types():
    jql = queries.build_tickets_jql('STL', issue_types=['Bug', 'Task'])
    assert jql == 'project = "STL" AND issuetype IN ("Bug", "Task") ORDER BY created DESC'


def test_build_tickets_jql_with_statuses_and_date_filter():
    jql = queries.build_tickets_jql(
        'STL',
        statuses=['Open', 'In Progress'],
        date_filter='AND created >= -14d',
    )
    assert jql == (
        'project = "STL" AND status IN ("Open", "In Progress") '
        'AND created >= -14d ORDER BY created DESC'
    )


def test_build_tickets_jql_with_jql_extra_only():
    jql = queries.build_tickets_jql('STL', jql_extra='fixVersion is EMPTY')
    assert jql == 'project = "STL" AND fixVersion is EMPTY ORDER BY created DESC'


def test_build_tickets_jql_all_parameters_combined():
    jql = queries.build_tickets_jql(
        project='STL',
        issue_types=['Story', 'Task'],
        statuses={'include': ['Open'], 'exclude': ['Closed']},
        date_filter='AND updated >= -30d',
        jql_extra='component = "Fabric"',
    )
    assert jql == (
        'project = "STL" AND component = "Fabric" AND issuetype IN ("Story", "Task") '
        'AND status IN ("Open") AND status NOT IN ("Closed") '
        'AND updated >= -30d ORDER BY created DESC'
    )


def test_build_release_tickets_jql_without_optionals():
    jql = queries.build_release_tickets_jql('STL', '12.1.1')
    assert jql == 'project = "STL" AND fixVersion = "12.1.1" ORDER BY created DESC'


def test_build_release_tickets_jql_with_issue_types_and_statuses():
    jql = queries.build_release_tickets_jql(
        'STL',
        '12.1.1',
        issue_types=['Bug'],
        statuses=['Open'],
    )
    assert jql == (
        'project = "STL" AND fixVersion = "12.1.1" AND issuetype IN ("Bug") '
        'AND status IN ("Open") ORDER BY created DESC'
    )


def test_build_releases_tickets_jql_with_multiple_releases():
    jql = queries.build_releases_tickets_jql('STL', ['12.1.0', '12.1.1'])
    assert jql == (
        'project = "STL" AND fixVersion IN ("12.1.0", "12.1.1") '
        'ORDER BY fixVersion DESC, created DESC'
    )


def test_build_releases_tickets_jql_with_date_filter_and_statuses():
    jql = queries.build_releases_tickets_jql(
        project='STL',
        releases=['12.1.0', '12.1.1'],
        issue_types=['Bug'],
        statuses={'include': ['Open'], 'exclude': ['Closed']},
        date_filter='AND created >= -7d',
    )
    assert jql == (
        'project = "STL" AND fixVersion IN ("12.1.0", "12.1.1") AND issuetype IN ("Bug") '
        'AND status IN ("Open") AND status NOT IN ("Closed") '
        'AND created >= -7d ORDER BY fixVersion DESC, created DESC'
    )


def test_build_no_release_jql_without_optionals():
    jql = queries.build_no_release_jql('STL')
    assert jql == 'project = "STL" AND fixVersion is EMPTY ORDER BY created DESC'


def test_build_no_release_jql_with_issue_types_and_statuses():
    jql = queries.build_no_release_jql(
        project='STL',
        issue_types=['Story'],
        statuses={'include': ['Open'], 'exclude': ['Done']},
    )
    assert jql == (
        'project = "STL" AND fixVersion is EMPTY AND issuetype IN ("Story") '
        'AND status IN ("Open") AND status NOT IN ("Done") ORDER BY created DESC'
    )


def test_paginated_jql_search_prefers_enhanced_search_when_available():
    from types import SimpleNamespace as NS

    class _ResultPage(list):
        def __init__(self, items, next_token=None):
            super().__init__(items)
            self.nextPageToken = next_token

    calls = []

    def _enhanced(jql, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _ResultPage(['STL-1', 'STL-2'], next_token='page2')
        return _ResultPage(['STL-3'], next_token=None)

    mock_jira = NS(enhanced_search_issues=_enhanced, search_issues=None)

    issues = queries.paginated_jql_search(mock_jira, 'project = "STL"', page_size=2)

    assert issues == ['STL-1', 'STL-2', 'STL-3']
    assert len(calls) == 2


def test_paginated_jql_search_falls_back_when_enhanced_raises():
    jira = SimpleNamespace()

    def _enhanced(*_args, **_kwargs):
        raise RuntimeError('enhanced unavailable')

    jira.enhanced_search_issues = _enhanced
    jira.search_calls = []

    def _legacy(_jql, **kwargs):
        jira.search_calls.append(kwargs)
        return ['STL-9']

    jira.search_issues = _legacy

    issues = queries.paginated_jql_search(jira, 'project = "STL"', page_size=2)

    assert issues == ['STL-9']
    assert jira.search_calls == [{'startAt': 0, 'maxResults': 2}]


def test_paginated_jql_search_honors_max_results_and_fields():
    jira = SimpleNamespace()
    jira.calls = []

    def _legacy(_jql, **kwargs):
        jira.calls.append(kwargs)
        if kwargs['startAt'] == 0:
            return ['STL-1', 'STL-2']
        return ['STL-3']

    jira.search_issues = _legacy

    issues = queries.paginated_jql_search(
        jira,
        'project = "STL"',
        max_results=3,
        fields=['summary', 'status'],
        page_size=2,
    )

    assert issues == ['STL-1', 'STL-2', 'STL-3']
    assert jira.calls == [
        {'startAt': 0, 'maxResults': 2, 'fields': ['summary', 'status']},
        {'startAt': 2, 'maxResults': 1, 'fields': ['summary', 'status']},
    ]


def test_paginated_jql_search_uses_minimum_page_size_of_one():
    jira = SimpleNamespace()
    jira.calls = []

    def _legacy(_jql, **kwargs):
        jira.calls.append(kwargs)
        if kwargs['startAt'] == 0:
            return ['STL-1']
        return []

    jira.search_issues = _legacy

    issues = queries.paginated_jql_search(jira, 'project = "STL"', page_size=0)

    assert issues == ['STL-1']
    assert jira.calls[0]['maxResults'] == 1
