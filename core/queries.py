from __future__ import annotations

from typing import Any, Optional, Union


def _quote_values(values: list[str]) -> str:
    return ', '.join([f'"{value}"' for value in values])


def _build_status_jql(
    statuses: Optional[Union[list[str], dict[str, list[str]]]]
) -> str:
    if not statuses:
        return ''

    clauses = []

    if isinstance(statuses, dict):
        includes = statuses.get('include', [])
        excludes = statuses.get('exclude', [])

        if includes:
            clauses.append(f'status IN ({_quote_values(includes)})')

        if excludes:
            clauses.append(f'status NOT IN ({_quote_values(excludes)})')
    else:
        clauses.append(f'status IN ({_quote_values(statuses)})')

    return ' AND '.join(clauses)


def build_tickets_jql(
    project: str,
    issue_types: Optional[list[str]] = None,
    statuses: Optional[Union[list[str], dict[str, list[str]]]] = None,
    date_filter: Optional[str] = None,
    jql_extra: Optional[str] = None,
) -> str:
    jql_parts = [f'project = "{project}"']

    if jql_extra:
        jql_parts.append(jql_extra)

    if issue_types:
        jql_parts.append(f'issuetype IN ({_quote_values(issue_types)})')

    status_clause = _build_status_jql(statuses)
    if status_clause:
        jql_parts.append(status_clause)

    jql = ' AND '.join(jql_parts)
    if date_filter:
        jql = f'{jql} {date_filter}'

    return f'{jql} ORDER BY created DESC'


def build_release_tickets_jql(
    project: str,
    release: str,
    issue_types: Optional[list[str]] = None,
    statuses: Optional[Union[list[str], dict[str, list[str]]]] = None,
) -> str:
    return build_tickets_jql(
        project,
        issue_types=issue_types,
        statuses=statuses,
        jql_extra=f'fixVersion = "{release}"',
    )


def build_releases_tickets_jql(
    project: str,
    releases: list[str],
    issue_types: Optional[list[str]] = None,
    statuses: Optional[Union[list[str], dict[str, list[str]]]] = None,
    date_filter: Optional[str] = None,
) -> str:
    jql = build_tickets_jql(
        project,
        issue_types=issue_types,
        statuses=statuses,
        date_filter=date_filter,
        jql_extra=f'fixVersion IN ({_quote_values(releases)})',
    )
    return jql.replace('ORDER BY created DESC', 'ORDER BY fixVersion DESC, created DESC', 1)


def build_no_release_jql(
    project: str,
    issue_types: Optional[list[str]] = None,
    statuses: Optional[Union[list[str], dict[str, list[str]]]] = None,
) -> str:
    return build_tickets_jql(
        project,
        issue_types=issue_types,
        statuses=statuses,
        jql_extra='fixVersion is EMPTY',
    )


def paginated_jql_search(
    jira_connection: Any,
    jql: str,
    max_results: Optional[int] = None,
    fields: Optional[list[str]] = None,
    page_size: int = 100,
) -> list[Any]:
    """Paginated JQL search with automatic fallback.

    Tries ``enhanced_search_issues`` first (required for Jira Cloud after the
    ``search`` API deprecation).  Falls back to the legacy ``search_issues``
    for on-prem / older library versions.

    Note: ``enhanced_search_issues`` uses ``nextPageToken`` for pagination
    (not ``startAt``), so we handle both pagination styles.
    """
    import logging
    log = logging.getLogger(__name__)

    all_issues: list[Any] = []
    effective_page_size = max(1, page_size)

    # Decide which search method to use — prefer enhanced_search_issues
    # on Jira Cloud (jira-python >= 3.9).
    _use_enhanced = hasattr(jira_connection, 'enhanced_search_issues')

    # State for legacy (startAt) pagination
    start_at = 0
    # State for enhanced (nextPageToken) pagination
    next_page_token: Optional[str] = None

    while True:
        if max_results is not None:
            remaining = max_results - len(all_issues)
            if remaining <= 0:
                break
            current_page_size = min(effective_page_size, remaining)
        else:
            current_page_size = effective_page_size

        # Try enhanced first, fall back to legacy on any error.
        if _use_enhanced:
            try:
                # enhanced_search_issues uses nextPageToken, not startAt
                enhanced_kwargs: dict[str, Any] = {
                    'maxResults': current_page_size,
                }
                if next_page_token is not None:
                    enhanced_kwargs['nextPageToken'] = next_page_token
                if fields is not None:
                    enhanced_kwargs['fields'] = list(fields)

                issues_page = jira_connection.enhanced_search_issues(
                    jql, **enhanced_kwargs
                )

                # Extract nextPageToken for subsequent pages.
                # The ResultList may carry it as an attribute, or we can
                # check the underlying JSON response.
                next_page_token = getattr(issues_page, 'nextPageToken', None)

            except Exception as exc:
                log.debug(
                    'enhanced_search_issues failed (%s), falling back to search_issues',
                    exc,
                )
                _use_enhanced = False
                # Fall through to legacy search below
                legacy_kwargs: dict[str, Any] = {
                    'startAt': start_at,
                    'maxResults': current_page_size,
                }
                if fields is not None:
                    legacy_kwargs['fields'] = list(fields)
                issues_page = jira_connection.search_issues(jql, **legacy_kwargs)
                next_page_token = None
        else:
            legacy_kwargs = {
                'startAt': start_at,
                'maxResults': current_page_size,
            }
            if fields is not None:
                legacy_kwargs['fields'] = list(fields)
            issues_page = jira_connection.search_issues(jql, **legacy_kwargs)

        page_items = list(issues_page or [])
        if not page_items:
            break

        all_issues.extend(page_items)

        # For legacy pagination, advance startAt
        start_at += len(page_items)

        # Stop conditions: fewer items than requested, or no next token
        if len(page_items) < current_page_size:
            break
        if _use_enhanced and next_page_token is None:
            break

    if max_results is not None and len(all_issues) > max_results:
        return all_issues[:max_results]

    return all_issues
