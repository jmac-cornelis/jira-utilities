##########################################################################################
#
# Module: tools/jira_tools.py
#
# Description: Jira tools for agent use.
#              Wraps jira_utils.py functionality as agent-callable tools.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from tools.base import BaseTool, ToolResult, tool
from core.tickets import issue_to_dict

# Load environment variables
load_dotenv()

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# Import from jira_utils.py - reuse existing functionality
try:
    import jira_utils
    from jira_utils import (
        connect_to_jira,
        get_connection,
        reset_connection,
        validate_project,
        get_project_workflows as _get_project_workflows,
        get_project_issue_types as _get_project_issue_types,
        get_project_versions,
        get_project_components as _get_project_components,
        _get_related_data,
        JIRA_URL,
        # UserResolver for transparent assignee resolution
        get_user_resolver,
        # --- New imports for expanded tool coverage ---
        list_filters as _ju_list_filters,
        run_filter as _ju_run_filter,
        run_jql_query as _ju_run_jql_query,
        get_children_hierarchy as _ju_get_children_hierarchy,
        get_project_versions as _ju_get_project_versions,
        get_ticket_totals as _ju_get_ticket_totals,
        list_dashboards as _ju_list_dashboards,
        get_dashboard as _ju_get_dashboard,
        create_dashboard as _ju_create_dashboard,
        bulk_update_tickets as _ju_bulk_update_tickets,
    )
    JIRA_UTILS_AVAILABLE = True
except ImportError as e:
    JIRA_UTILS_AVAILABLE = False
    log.warning(f'jira_utils.py not available: {e}')
    JIRA_URL = os.getenv('JIRA_URL', 'https://cornelisnetworks.atlassian.net')

def get_jira():
    '''
    Get or create Jira connection using jira_utils.

    Delegates to jira_utils.get_connection() for unified connection management.

    Output:
        JIRA object with active connection.

    Raises:
        RuntimeError: If jira_utils is not available or connection fails.
    '''
    if not JIRA_UTILS_AVAILABLE:
        raise RuntimeError('jira_utils.py is required but not available')

    return jira_utils.get_connection()


# ****************************************************************************************
# Tool Functions
# ****************************************************************************************

@tool(
    description='Get information about a Jira project including name, lead, and description'
)
def get_project_info(project_key: str) -> ToolResult:
    '''
    Get detailed information about a Jira project.
    
    Input:
        project_key: The project key (e.g., 'PROJ', 'ENG').
    
    Output:
        ToolResult with project information including name, lead, description.
    '''
    log.debug(f'get_project_info(project_key={project_key})')
    
    try:
        jira = get_jira()
        project = validate_project(jira, project_key)
        
        # Extract project information
        lead = getattr(project, 'lead', None)
        lead_info = {
            'displayName': lead.displayName if lead else 'N/A',
            'emailAddress': getattr(lead, 'emailAddress', 'N/A') if lead else 'N/A'
        } if lead else None
        
        result = {
            'key': project.key,
            'name': project.name,
            'description': getattr(project, 'description', ''),
            'lead': lead_info,
            'url': f'{JIRA_URL}/browse/{project.key}'
        }
        
        return ToolResult.success(result)
        
    except Exception as e:
        log.error(f'Failed to get project info: {e}')
        return ToolResult.failure(f'Failed to get project {project_key}: {e}')


@tool(
    description='Get the workflow statuses available for a Jira project'
)
def get_project_workflows(project_key: str) -> ToolResult:
    '''
    Get workflow statuses for a project.
    
    Input:
        project_key: The project key.
    
    Output:
        ToolResult with list of workflow statuses.
    '''
    log.debug(f'get_project_workflows(project_key={project_key})')
    
    try:
        jira = get_jira()
        
        # Validate project exists
        validate_project(jira, project_key)
        
        # Get all statuses using jira_utils pattern
        statuses = jira.statuses()
        
        status_list = []
        for status in statuses:
            status_list.append({
                'id': status.id,
                'name': status.name,
                'category': getattr(status, 'statusCategory', {}).name if hasattr(status, 'statusCategory') else 'Unknown'
            })
        
        return ToolResult.success(status_list)
        
    except Exception as e:
        log.error(f'Failed to get workflows: {e}')
        return ToolResult.failure(f'Failed to get workflows for {project_key}: {e}')


@tool(
    description='Get the issue types available for a Jira project'
)
def get_project_issue_types(project_key: str) -> ToolResult:
    '''
    Get issue types for a project.
    
    Input:
        project_key: The project key.
    
    Output:
        ToolResult with list of issue types.
    '''
    log.debug(f'get_project_issue_types(project_key={project_key})')
    
    try:
        jira = get_jira()
        project = validate_project(jira, project_key)
        
        issue_types = []
        for it in project.issueTypes:
            issue_types.append({
                'id': it.id,
                'name': it.name,
                'description': getattr(it, 'description', ''),
                'subtask': getattr(it, 'subtask', False)
            })
        
        return ToolResult.success(issue_types)
        
    except Exception as e:
        log.error(f'Failed to get issue types: {e}')
        return ToolResult.failure(f'Failed to get issue types for {project_key}: {e}')


@tool(
    description='Get releases (versions) for a Jira project, optionally filtered by pattern'
)
def get_releases(
    project_key: str,
    pattern: Optional[str] = None,
    include_released: bool = True,
    include_unreleased: bool = True
) -> ToolResult:
    '''
    Get releases/versions for a project.
    
    Input:
        project_key: The project key.
        pattern: Optional regex pattern to filter release names.
        include_released: Include already released versions.
        include_unreleased: Include unreleased versions.
    
    Output:
        ToolResult with list of releases.
    '''
    log.debug(f'get_releases(project_key={project_key}, pattern={pattern})')
    
    try:
        jira = get_jira()
        versions = jira.project_versions(project_key)
        
        releases = []
        for v in versions:
            # Filter by released status
            is_released = getattr(v, 'released', False)
            if is_released and not include_released:
                continue
            if not is_released and not include_unreleased:
                continue
            
            # Filter by pattern
            if pattern:
                import re
                if not re.search(pattern, v.name, re.IGNORECASE):
                    continue
            
            releases.append({
                'id': v.id,
                'name': v.name,
                'description': getattr(v, 'description', ''),
                'released': is_released,
                'releaseDate': getattr(v, 'releaseDate', None),
                'startDate': getattr(v, 'startDate', None),
                'archived': getattr(v, 'archived', False)
            })
        
        # Sort by name
        releases.sort(key=lambda x: x['name'])
        
        return ToolResult.success(releases, count=len(releases))
        
    except Exception as e:
        log.error(f'Failed to get releases: {e}')
        return ToolResult.failure(f'Failed to get releases for {project_key}: {e}')


@tool(
    description='Get tickets for a specific release version'
)
def get_release_tickets(
    project_key: str,
    release_name: str,
    issue_types: Optional[List[str]] = None,
    status: Optional[List[str]] = None,
    limit: int = 100
) -> ToolResult:
    '''
    Get tickets assigned to a release.
    
    Input:
        project_key: The project key.
        release_name: The release/version name.
        issue_types: Optional list of issue types to filter.
        status: Optional list of statuses to filter.
        limit: Maximum number of tickets to return.
    
    Output:
        ToolResult with list of tickets.
    '''
    log.debug(f'get_release_tickets(project_key={project_key}, release={release_name})')
    
    try:
        jira = get_jira()
        
        # Build JQL query
        jql_parts = [
            f'project = {project_key}',
            f'fixVersion = "{release_name}"'
        ]
        
        if issue_types:
            types_str = ', '.join(f'"{t}"' for t in issue_types)
            jql_parts.append(f'issuetype IN ({types_str})')
        
        if status:
            status_str = ', '.join(f'"{s}"' for s in status)
            jql_parts.append(f'status IN ({status_str})')
        
        jql = ' AND '.join(jql_parts) + ' ORDER BY created DESC'
        log.debug(f'JQL: {jql}')
        
        issues = jira.search_issues(jql, maxResults=limit)
        
        tickets = []
        for issue in issues:
            tickets.append(_issue_to_dict(issue))
        
        return ToolResult.success(tickets, count=len(tickets), jql=jql)
        
    except Exception as e:
        log.error(f'Failed to get release tickets: {e}')
        return ToolResult.failure(f'Failed to get tickets for release {release_name}: {e}')


@tool(
    description='Search for Jira tickets using JQL query'
)
def search_tickets(
    jql: str,
    limit: int = 100,
    fields: Optional[List[str]] = None
) -> ToolResult:
    '''
    Search for tickets using JQL.
    
    Input:
        jql: JQL query string.
        limit: Maximum number of results.
        fields: Optional list of fields to return.
    
    Output:
        ToolResult with list of matching tickets.
    '''
    log.debug(f'search_tickets(jql={jql}, limit={limit})')
    
    try:
        jira = get_jira()
        
        issues = jira.search_issues(jql, maxResults=limit, fields=fields)
        
        tickets = []
        for issue in issues:
            tickets.append(_issue_to_dict(issue))
        
        return ToolResult.success(tickets, count=len(tickets), jql=jql)
        
    except Exception as e:
        log.error(f'Failed to search tickets: {e}')
        return ToolResult.failure(f'JQL search failed: {e}')


@tool(
    description='Create a new Jira ticket'
)
def create_ticket(
    project_key: str,
    summary: str,
    issue_type: str,
    description: Optional[str] = None,
    assignee: Optional[str] = None,
    components: Optional[List[str]] = None,
    fix_versions: Optional[List[str]] = None,
    labels: Optional[List[str]] = None,
    parent_key: Optional[str] = None,
    product_family: Optional[List[str]] = None,
    custom_fields: Optional[Dict[str, Any]] = None
) -> ToolResult:
    '''
    Create a new Jira ticket.
    
    Input:
        project_key: The project key.
        summary: Ticket summary/title.
        issue_type: Issue type (Epic, Story, Task, Bug, etc.).
        description: Optional ticket description.
        assignee: Optional assignee account ID or email.
        components: Optional list of component names.
        fix_versions: Optional list of fix version names.
        labels: Optional list of labels.
        parent_key: Optional parent ticket key (for subtasks or stories under epics).
        product_family: Optional list of Product Family values (e.g. ['CN5000']).
            Maps to Jira custom field customfield_28434.
        custom_fields: Optional dictionary of custom field values.
    
    Output:
        ToolResult with created ticket information.
    '''
    log.debug(f'create_ticket(project={project_key}, summary={summary}, type={issue_type})')
    
    try:
        jira = get_jira()
        
        # Build issue fields
        fields = {
            'project': {'key': project_key},
            'summary': summary,
            'issuetype': {'name': issue_type},
        }
        
        if description:
            # Jira Cloud uses ADF format for description
            fields['description'] = {
                'type': 'doc',
                'version': 1,
                'content': [
                    {
                        'type': 'paragraph',
                        'content': [
                            {'type': 'text', 'text': description}
                        ]
                    }
                ]
            }
        
        if assignee:
            # Transparently resolve human-readable assignee strings (display
            # names, emails, usernames) to Jira Cloud accountIds.
            resolver = get_user_resolver()
            resolved_id = resolver.resolve(str(assignee), project_key=project_key)
            if resolved_id:
                fields['assignee'] = {'id': resolved_id}
            else:
                log.warning(
                    f'Assignee "{assignee}" could not be resolved to an '
                    f'accountId — ticket will be created unassigned'
                )
        
        if components:
            fields['components'] = [{'name': c} for c in components]
        
        if fix_versions:
            fields['fixVersions'] = [{'name': v} for v in fix_versions]
        
        if labels:
            fields['labels'] = labels
        
        if parent_key:
            # For subtasks, use parent field
            # For stories under epics, use epic link field
            if issue_type.lower() == 'sub-task':
                fields['parent'] = {'key': parent_key}
            else:
                # Epic link field - may vary by Jira configuration
                fields['parent'] = {'key': parent_key}
        
        # Product Family — the custom-field ID varies by Jira project:
        #   STLSB (sandbox) → customfield_28434
        #   STL  (production) → customfield_28382
        # We set the primary ID here and fall back to alternates on error.
        _PF_FIELD_IDS = ['customfield_28434', 'customfield_28382']
        _pf_values = None
        if product_family:
            pf_list = product_family if isinstance(product_family, list) else [product_family]
            _pf_values = [{'value': v} for v in pf_list]
            # Start with the first known ID; the retry loop below will try
            # alternates if the server rejects it.
            fields[_PF_FIELD_IDS[0]] = _pf_values

        if custom_fields:
            fields.update(custom_fields)
        
        log.info(f'Creating ticket: {summary}')
        try:
            issue = jira.create_issue(fields=fields)
        except Exception as field_err:
            err_text = str(field_err)
            _needs_retry = False

            # --- Handle missing description ---
            # Some Jira projects require a non-empty description.  If the
            # error says "Description is required" and we didn't set one,
            # auto-fill with the summary text and flag for retry.
            if 'Description is required' in err_text and 'description' not in fields:
                log.warning('Description required but not provided — using summary as description')
                fields['description'] = {
                    'type': 'doc',
                    'version': 1,
                    'content': [
                        {
                            'type': 'paragraph',
                            'content': [
                                {'type': 'text', 'text': summary}
                            ]
                        }
                    ]
                }
                _needs_retry = True

            # --- Handle Product Family field-ID mismatch ---
            # Two scenarios:
            #   1. The field we set is "not on the appropriate screen" → remove it.
            #   2. A *different* PF field ID is listed as required → add it.
            if _pf_values:
                _rejected_ids = [fid for fid in _PF_FIELD_IDS if fid in err_text and fid in fields]
                _required_ids = [fid for fid in _PF_FIELD_IDS if fid in err_text and fid not in fields]

                if _rejected_ids or _required_ids:
                    for fid in _rejected_ids:
                        log.warning(f'Product Family field ({fid}) rejected — removing')
                        del fields[fid]
                    for fid in _required_ids:
                        log.info(f'Product Family field ({fid}) required — adding')
                        fields[fid] = _pf_values
                    _needs_retry = True

                # If we only removed a field but the error didn't mention the
                # alternate, proactively try the next known ID.
                if _rejected_ids and not _required_ids:
                    for fid in _PF_FIELD_IDS:
                        if fid not in fields and fid not in _rejected_ids:
                            log.info(f'Trying alternate Product Family field: {fid}')
                            fields[fid] = _pf_values
                            break

            if _needs_retry:
                log.info('Retrying create_issue with corrected fields')
                try:
                    issue = jira.create_issue(fields=fields)
                except Exception as retry_err:
                    log.error(f'Failed to create ticket (retry): {retry_err}')
                    raise
            else:
                raise
        
        result = {
            'key': issue.key,
            'id': issue.id,
            'summary': summary,
            'url': f'{JIRA_URL}/browse/{issue.key}'
        }
        
        log.info(f'Created ticket: {issue.key}')
        return ToolResult.success(result)
        
    except Exception as e:
        log.error(f'Failed to create ticket: {e}')
        return ToolResult.failure(f'Failed to create ticket: {e}')


@tool(
    description='Update an existing Jira ticket'
)
def update_ticket(
    ticket_key: str,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    assignee: Optional[str] = None,
    status: Optional[str] = None,
    fix_versions: Optional[List[str]] = None,
    components: Optional[List[str]] = None,
    labels: Optional[List[str]] = None,
    custom_fields: Optional[Dict[str, Any]] = None
) -> ToolResult:
    '''
    Update an existing Jira ticket.
    
    Input:
        ticket_key: The ticket key (e.g., 'PROJ-123').
        summary: New summary (optional).
        description: New description (optional).
        assignee: New assignee account ID (optional).
        status: New status - will trigger transition (optional).
        fix_versions: New fix versions (optional).
        components: New components (optional).
        labels: New labels (optional).
        custom_fields: Custom field updates (optional).
    
    Output:
        ToolResult with updated ticket information.
    '''
    log.debug(f'update_ticket(ticket_key={ticket_key})')
    
    try:
        jira = get_jira()
        issue = jira.issue(ticket_key)
        
        # Build update fields
        fields = {}
        
        if summary:
            fields['summary'] = summary
        
        if description:
            fields['description'] = {
                'type': 'doc',
                'version': 1,
                'content': [
                    {
                        'type': 'paragraph',
                        'content': [
                            {'type': 'text', 'text': description}
                        ]
                    }
                ]
            }
        
        if assignee:
            fields['assignee'] = {'id': assignee}
        
        if fix_versions is not None:
            fields['fixVersions'] = [{'name': v} for v in fix_versions]
        
        if components is not None:
            fields['components'] = [{'name': c} for c in components]
        
        if labels is not None:
            fields['labels'] = labels
        
        if custom_fields:
            fields.update(custom_fields)
        
        # Update fields
        if fields:
            issue.update(fields=fields)
            log.info(f'Updated ticket fields: {ticket_key}')
        
        # Handle status transition
        if status:
            transitions = jira.transitions(issue)
            for t in transitions:
                if t['name'].lower() == status.lower():
                    jira.transition_issue(issue, t['id'])
                    log.info(f'Transitioned {ticket_key} to {status}')
                    break
            else:
                log.warning(f'Transition to {status} not available for {ticket_key}')
        
        # Fetch updated issue
        updated_issue = jira.issue(ticket_key)
        
        return ToolResult.success(_issue_to_dict(updated_issue))
        
    except Exception as e:
        log.error(f'Failed to update ticket: {e}')
        return ToolResult.failure(f'Failed to update {ticket_key}: {e}')


@tool(
    description='Create a new release/version in a Jira project'
)
def create_release(
    project_key: str,
    name: str,
    description: Optional[str] = None,
    start_date: Optional[str] = None,
    release_date: Optional[str] = None
) -> ToolResult:
    '''
    Create a new release/version.
    
    Input:
        project_key: The project key.
        name: Release name.
        description: Optional release description.
        start_date: Optional start date (YYYY-MM-DD).
        release_date: Optional release date (YYYY-MM-DD).
    
    Output:
        ToolResult with created release information.
    '''
    log.debug(f'create_release(project={project_key}, name={name})')
    
    try:
        jira = get_jira()
        
        version = jira.create_version(
            name=name,
            project=project_key,
            description=description,
            startDate=start_date,
            releaseDate=release_date
        )
        
        result = {
            'id': version.id,
            'name': version.name,
            'description': getattr(version, 'description', ''),
            'startDate': getattr(version, 'startDate', None),
            'releaseDate': getattr(version, 'releaseDate', None)
        }
        
        log.info(f'Created release: {name}')
        return ToolResult.success(result)
        
    except Exception as e:
        log.error(f'Failed to create release: {e}')
        return ToolResult.failure(f'Failed to create release {name}: {e}')


@tool(
    description='Create a link between two Jira tickets'
)
def link_tickets(
    from_key: str,
    to_key: str,
    link_type: str = 'Relates'
) -> ToolResult:
    '''
    Create a link between two tickets.
    
    Input:
        from_key: Source ticket key.
        to_key: Target ticket key.
        link_type: Link type (Relates, Blocks, Clones, etc.).
    
    Output:
        ToolResult confirming link creation.
    '''
    log.debug(f'link_tickets(from={from_key}, to={to_key}, type={link_type})')
    
    try:
        jira = get_jira()
        
        jira.create_issue_link(
            type=link_type,
            inwardIssue=from_key,
            outwardIssue=to_key
        )
        
        log.info(f'Created link: {from_key} -{link_type}-> {to_key}')
        return ToolResult.success({
            'from': from_key,
            'to': to_key,
            'type': link_type
        })
        
    except Exception as e:
        log.error(f'Failed to link tickets: {e}')
        return ToolResult.failure(f'Failed to link {from_key} to {to_key}: {e}')


@tool(
    description='Get components for a Jira project'
)
def get_components(project_key: str) -> ToolResult:
    '''
    Get components for a project.
    
    Input:
        project_key: The project key.
    
    Output:
        ToolResult with list of components.
    '''
    log.debug(f'get_components(project_key={project_key})')
    
    try:
        jira = get_jira()
        components = jira.project_components(project_key)
        
        result = []
        for c in components:
            lead = getattr(c, 'lead', None)
            result.append({
                'id': c.id,
                'name': c.name,
                'description': getattr(c, 'description', ''),
                'lead': lead.displayName if lead else None
            })
        
        return ToolResult.success(result, count=len(result))
        
    except Exception as e:
        log.error(f'Failed to get components: {e}')
        return ToolResult.failure(f'Failed to get components for {project_key}: {e}')


@tool(
    description='Assign a ticket to a user'
)
def assign_ticket(ticket_key: str, assignee: str) -> ToolResult:
    '''
    Assign a ticket to a user.
    
    Input:
        ticket_key: The ticket key.
        assignee: Assignee account ID or email.
    
    Output:
        ToolResult confirming assignment.
    '''
    log.debug(f'assign_ticket(ticket_key={ticket_key}, assignee={assignee})')
    
    try:
        jira = get_jira()
        issue = jira.issue(ticket_key)
        
        jira.assign_issue(issue, assignee)
        
        log.info(f'Assigned {ticket_key} to {assignee}')
        return ToolResult.success({
            'ticket': ticket_key,
            'assignee': assignee
        })
        
    except Exception as e:
        log.error(f'Failed to assign ticket: {e}')
        return ToolResult.failure(f'Failed to assign {ticket_key}: {e}')


@tool(
    description='Get related tickets using hierarchy traversal (wraps jira_utils --get-related)'
)
def get_related_tickets(
    ticket_key: str,
    hierarchy_depth: int = 3,
    limit: int = 100
) -> ToolResult:
    '''
    Get related tickets by traversing links and children.

    Delegates to jira_utils._get_related_data() which handles cycle-safe
    graph traversal across both issue links and parent/child relationships.

    Input:
        ticket_key: The root ticket key to start from.
        hierarchy_depth: Maximum depth to traverse (default: 3).
            Use -1 for unlimited depth, or a positive int for depth limit.
        limit: Maximum number of tickets to return (including root).

    Output:
        ToolResult with list of related tickets.
    '''
    log.debug(f'get_related_tickets(ticket_key={ticket_key}, depth={hierarchy_depth})')

    try:
        if not JIRA_UTILS_AVAILABLE:
            return ToolResult.failure('jira_utils.py is required for get_related_tickets')

        jira = get_jira()

        # Delegate to jira_utils._get_related_data() for cycle-safe traversal.
        # hierarchy_depth maps to the hierarchy parameter:
        #   None  → direct links + direct children only
        #   -1    → unlimited recursive depth
        #   n > 0 → depth-limited recursive traversal
        ordered = _get_related_data(
            jira,
            ticket_key,
            hierarchy=hierarchy_depth,
            limit=limit,
        )

        tickets = []
        for item in ordered:
            raw = item.get('issue', {})
            ticket = issue_to_dict(raw)
            ticket['depth'] = item.get('depth', 0)
            ticket['via'] = item.get('via')
            ticket['relation'] = item.get('relation')
            ticket['from_key'] = item.get('from_key')
            tickets.append(ticket)

        return ToolResult.success(tickets, count=len(tickets), root_ticket=ticket_key)

    except Exception as e:
        log.error(f'Failed to get related tickets: {e}')
        return ToolResult.failure(f'Failed to get related tickets for {ticket_key}: {e}')


# ****************************************************************************************
# New Tool Wrappers (expanded coverage of jira_utils.py)
# ****************************************************************************************

@tool(
    name='list_filters',
    description='List Jira filters, optionally filtered by owner or favourites only'
)
def list_filters(owner: Optional[str] = None, favourite_only: bool = False) -> ToolResult:
    '''
    List accessible Jira saved filters.

    Delegates to jira_utils.list_filters() which queries the Jira REST API
    for saved filters visible to the authenticated user.

    Input:
        owner: Optional owner display name or email to filter by ("me" for current user).
        favourite_only: If True, return only the user's favourite/starred filters.

    Output:
        ToolResult with list of filter dicts containing id, name, jql, owner, etc.
    '''
    log.debug(f'list_filters(owner={owner}, favourite_only={favourite_only})')

    try:
        jira = get_jira()

        # Delegate to jira_utils.list_filters — returns a list of raw filter dicts
        filters = _ju_list_filters(jira, owner=owner, favourite_only=favourite_only)

        # Normalise each filter into a clean dict for tool consumers
        result = []
        for f in (filters or []):
            result.append({
                'id': str(f.get('id', '')),
                'name': f.get('name', ''),
                'jql': f.get('jql', ''),
                'owner': f.get('owner', {}).get('displayName', '') if f.get('owner') else '',
                'favourite': f.get('favourite', False),
                'description': f.get('description', '') or '',
                'viewUrl': f.get('viewUrl', ''),
            })

        return ToolResult.success(result, count=len(result))

    except Exception as e:
        log.error(f'Failed to list filters: {e}')
        return ToolResult.failure(f'Failed to list filters: {e}')


@tool(
    name='run_filter',
    description='Run a Jira filter by ID and return matching tickets'
)
def run_filter(filter_id: str, limit: int = 50) -> ToolResult:
    '''
    Run a saved Jira filter and return matching tickets.

    Delegates to jira_utils.run_filter() which fetches the filter's JQL
    and executes it via run_jql_query().

    Input:
        filter_id: The saved filter ID (string or numeric).
        limit: Maximum number of tickets to return (default 50).

    Output:
        ToolResult with list of matching ticket dicts.
    '''
    log.debug(f'run_filter(filter_id={filter_id}, limit={limit})')

    try:
        jira = get_jira()

        # Delegate — returns list of raw issue dicts (REST API format).
        # Do NOT pass dump_file/dump_format so data stays in memory.
        issues = _ju_run_filter(jira, filter_id, limit=limit)

        tickets = [issue_to_dict(iss) for iss in (issues or [])]

        return ToolResult.success(tickets, count=len(tickets), filter_id=filter_id)

    except Exception as e:
        log.error(f'Failed to run filter {filter_id}: {e}')
        return ToolResult.failure(f'Failed to run filter {filter_id}: {e}')


@tool(
    name='run_jql_query',
    description='Run a JQL query and return matching tickets'
)
def run_jql_query(jql: str, limit: int = 50) -> ToolResult:
    '''
    Run an arbitrary JQL query and return matching tickets.

    Delegates to jira_utils.run_jql_query() which handles pagination
    against the Jira REST API.

    Input:
        jql: JQL query string.
        limit: Maximum number of tickets to return (default 50).

    Output:
        ToolResult with list of matching ticket dicts.
    '''
    log.debug(f'run_jql_query(jql={jql}, limit={limit})')

    try:
        jira = get_jira()

        # Delegate — returns list of raw issue dicts.
        # Do NOT pass dump_file/dump_format so data stays in memory.
        issues = _ju_run_jql_query(jira, jql, limit=limit)

        tickets = [issue_to_dict(iss) for iss in (issues or [])]

        return ToolResult.success(tickets, count=len(tickets), jql=jql)

    except Exception as e:
        log.error(f'Failed to run JQL query: {e}')
        return ToolResult.failure(f'JQL query failed: {e}')


@tool(
    name='get_children_hierarchy',
    description='Get child tickets in a hierarchy tree starting from a root ticket'
)
def get_children_hierarchy(root_key: str, limit: int = 100) -> ToolResult:
    '''
    Recursively retrieve the full child hierarchy for a given ticket.

    Delegates to jira_utils.get_children_hierarchy() which performs
    depth-first traversal of parent/child relationships.

    Input:
        root_key: The root ticket key to start from (e.g., 'PROJ-100').
        limit: Maximum number of tickets to return including root (default 100).

    Output:
        ToolResult with list of ticket dicts including depth metadata.
    '''
    log.debug(f'get_children_hierarchy(root_key={root_key}, limit={limit})')

    try:
        jira = get_jira()

        # Delegate — the function prints to stdout and returns None.
        # We call the underlying _get_children_data helper directly for
        # structured data, but it is a private function. Instead, we use
        # the public API and also call the internal data helper if available.
        from jira_utils import _get_children_data
        ordered = _get_children_data(jira, root_key, limit=limit)

        tickets = []
        for item in ordered:
            raw = item.get('issue', {})
            fields = raw.get('fields', {})
            issue_type = fields.get('issuetype', {}) or {}
            status = fields.get('status', {}) or {}
            priority = fields.get('priority', {}) or {}
            assignee = fields.get('assignee', {}) or {}
            fix_versions = fields.get('fixVersions', []) or []
            components = fields.get('components', []) or []
            labels = fields.get('labels', []) or []

            tickets.append({
                'key': raw.get('key', ''),
                'id': raw.get('id', ''),
                'summary': fields.get('summary', ''),
                'type': issue_type.get('name'),
                'status': status.get('name'),
                'priority': priority.get('name'),
                'assignee': assignee.get('displayName') if assignee else None,
                'fix_versions': [v.get('name', '') for v in fix_versions],
                'components': [c.get('name', '') for c in components],
                'labels': labels,
                'url': f'{JIRA_URL}/browse/{raw.get("key", "")}',
                'depth': item.get('depth', 0),
            })

        return ToolResult.success(tickets, count=len(tickets), root_key=root_key)

    except Exception as e:
        log.error(f'Failed to get children hierarchy: {e}')
        return ToolResult.failure(f'Failed to get children hierarchy for {root_key}: {e}')


@tool(
    name='get_project_versions',
    description='Get all versions/releases defined for a Jira project'
)
def get_project_versions_tool(project_key: str) -> ToolResult:
    '''
    Get all versions (releases) defined for a Jira project.

    Delegates to jira_utils.get_project_versions() which queries the
    Jira REST API for project version metadata.

    Input:
        project_key: The project key (e.g., 'PROJ').

    Output:
        ToolResult with list of version dicts (id, name, released, releaseDate, etc.).
    '''
    log.debug(f'get_project_versions_tool(project_key={project_key})')

    try:
        jira = get_jira()

        # get_project_versions prints to stdout and returns None.
        # We fetch versions directly via the jira library for structured data.
        versions = jira.project_versions(project_key)

        result = []
        for v in versions:
            result.append({
                'id': v.id,
                'name': v.name,
                'description': getattr(v, 'description', ''),
                'released': getattr(v, 'released', False),
                'releaseDate': getattr(v, 'releaseDate', None),
                'startDate': getattr(v, 'startDate', None),
                'archived': getattr(v, 'archived', False),
            })

        # Sort by release date then name (matching jira_utils pattern)
        result.sort(key=lambda x: (
            not x['released'],
            x.get('releaseDate') or '9999-99-99',
            x['name'],
        ))

        return ToolResult.success(result, count=len(result))

    except Exception as e:
        log.error(f'Failed to get project versions: {e}')
        return ToolResult.failure(f'Failed to get versions for {project_key}: {e}')


@tool(
    name='get_ticket_totals',
    description='Get ticket count totals for a project, grouped by status and issue type'
)
def get_ticket_totals(
    project_key: str,
    issue_types: Optional[str] = None,
    statuses: Optional[str] = None
) -> ToolResult:
    '''
    Get ticket count totals for a project.

    Delegates to jira_utils.get_ticket_totals() which builds a JQL query
    and uses the Jira approximate-count API for efficiency.

    Input:
        project_key: The project key (e.g., 'PROJ').
        issue_types: Optional comma-separated issue type names to filter.
        statuses: Optional comma-separated status names to filter.

    Output:
        ToolResult with ticket count information.
    '''
    log.debug(f'get_ticket_totals(project_key={project_key}, issue_types={issue_types}, statuses={statuses})')

    try:
        jira = get_jira()

        # Parse comma-separated strings into lists for jira_utils
        type_list = [t.strip() for t in issue_types.split(',')] if issue_types else None
        status_list = [s.strip() for s in statuses.split(',')] if statuses else None

        # get_ticket_totals prints to stdout and returns None.
        # We replicate the count logic here for structured return data.
        from jira_utils import normalize_issue_types, normalize_statuses, _build_status_jql
        validate_project(jira, project_key)

        normalized_types = normalize_issue_types(jira, project_key, type_list) if type_list else None
        normalized_statuses = normalize_statuses(jira, status_list) if status_list else None

        jql_parts = [f'project = "{project_key}"']
        if normalized_types:
            type_jql = ', '.join([f'"{t}"' for t in normalized_types])
            jql_parts.append(f'issuetype IN ({type_jql})')
        status_clause = _build_status_jql(normalized_statuses)
        if status_clause:
            jql_parts.append(status_clause)
        jql = ' AND '.join(jql_parts).strip()

        # Use the Jira approximate-count endpoint
        from jira_utils import get_jira_credentials, JIRA_URL as _JIRA_URL
        import requests
        email, api_token = get_jira_credentials()
        response = requests.post(
            f'{_JIRA_URL}/rest/api/3/search/approximate-count',
            auth=(email, api_token),
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            json={'jql': jql},
        )
        if response.status_code != 200:
            raise Exception(f'Jira API error: {response.status_code} - {response.text}')

        total_count = response.json().get('count', 0)

        result = {
            'project_key': project_key,
            'total_count': total_count,
            'jql': jql,
            'issue_types': normalized_types,
            'statuses': normalized_statuses,
        }

        return ToolResult.success(result)

    except Exception as e:
        log.error(f'Failed to get ticket totals: {e}')
        return ToolResult.failure(f'Failed to get ticket totals for {project_key}: {e}')


@tool(
    name='list_dashboards',
    description='List Jira dashboards, optionally filtered by owner'
)
def list_dashboards(owner: Optional[str] = None, shared: bool = False) -> ToolResult:
    '''
    List accessible Jira dashboards.

    Delegates to jira_utils.list_dashboards() which queries the Jira
    dashboard search REST API.

    Input:
        owner: Optional owner username/email to filter by ("me" for current user).
        shared: If True, show only dashboards shared with current user.

    Output:
        ToolResult with list of dashboard dicts.
    '''
    log.debug(f'list_dashboards(owner={owner}, shared={shared})')

    try:
        jira = get_jira()

        # list_dashboards prints to stdout and returns None.
        # We replicate the API call for structured data.
        from jira_utils import get_jira_credentials, JIRA_URL as _JIRA_URL
        import requests
        email, api_token = get_jira_credentials()

        params = {'maxResults': 100}
        if owner:
            if owner.lower() == 'me':
                params['accountId'] = 'me'
            else:
                params['owner'] = owner
        if shared:
            params['filter'] = 'sharedWithMe'

        all_dashboards = []
        start_at = 0

        while True:
            params['startAt'] = start_at
            response = requests.get(
                f'{_JIRA_URL}/rest/api/3/dashboard/search',
                auth=(email, api_token),
                headers={'Accept': 'application/json'},
                params=params,
            )
            if response.status_code != 200:
                raise Exception(f'Jira API error: {response.status_code} - {response.text}')

            data = response.json()
            dashboards = data.get('values', [])
            all_dashboards.extend(dashboards)

            total = data.get('total', 0)
            if start_at + len(dashboards) >= total:
                break
            start_at += len(dashboards)

        result = []
        for d in all_dashboards:
            owner_info = d.get('owner', {}) or {}
            result.append({
                'id': str(d.get('id', '')),
                'name': d.get('name', ''),
                'owner': owner_info.get('displayName', ''),
                'isFavourite': d.get('isFavourite', False),
                'view': d.get('view', ''),
            })

        return ToolResult.success(result, count=len(result))

    except Exception as e:
        log.error(f'Failed to list dashboards: {e}')
        return ToolResult.failure(f'Failed to list dashboards: {e}')


@tool(
    name='get_dashboard',
    description='Get details of a specific Jira dashboard by ID'
)
def get_dashboard(dashboard_id: str) -> ToolResult:
    '''
    Get details of a specific Jira dashboard.

    Delegates to jira_utils.get_dashboard() which fetches dashboard
    metadata from the Jira REST API.

    Input:
        dashboard_id: The dashboard ID (string or numeric).

    Output:
        ToolResult with dashboard detail dict.
    '''
    log.debug(f'get_dashboard(dashboard_id={dashboard_id})')

    try:
        jira = get_jira()

        # get_dashboard prints to stdout and returns None.
        # We call the REST API directly for structured data.
        from jira_utils import get_jira_credentials, JIRA_URL as _JIRA_URL
        import requests
        email, api_token = get_jira_credentials()

        response = requests.get(
            f'{_JIRA_URL}/rest/api/3/dashboard/{dashboard_id}',
            auth=(email, api_token),
            headers={'Accept': 'application/json'},
        )

        if response.status_code == 404:
            return ToolResult.failure(f'Dashboard {dashboard_id} not found')
        if response.status_code != 200:
            raise Exception(f'Jira API error: {response.status_code} - {response.text}')

        d = response.json()
        owner_info = d.get('owner', {}) or {}

        result = {
            'id': str(d.get('id', '')),
            'name': d.get('name', ''),
            'description': d.get('description', '') or '',
            'owner': owner_info.get('displayName', ''),
            'isFavourite': d.get('isFavourite', False),
            'view': d.get('view', ''),
            'sharePermissions': d.get('sharePermissions', []),
        }

        return ToolResult.success(result)

    except Exception as e:
        log.error(f'Failed to get dashboard {dashboard_id}: {e}')
        return ToolResult.failure(f'Failed to get dashboard {dashboard_id}: {e}')


@tool(
    name='create_dashboard',
    description='Create a new Jira dashboard'
)
def create_dashboard(name: str, description: str = '') -> ToolResult:
    '''
    Create a new Jira dashboard.

    Delegates to jira_utils.create_dashboard() which POSTs to the
    Jira REST API to create a dashboard.

    Input:
        name: Name for the new dashboard.
        description: Optional description for the dashboard.

    Output:
        ToolResult with created dashboard details (id, name, view URL).
    '''
    log.debug(f'create_dashboard(name={name}, description={description})')

    try:
        jira = get_jira()

        # create_dashboard prints to stdout and returns None.
        # We call the REST API directly for structured return data.
        from jira_utils import get_jira_credentials, JIRA_URL as _JIRA_URL
        import requests
        email, api_token = get_jira_credentials()

        payload = {
            'name': name,
            'sharePermissions': [],
        }
        if description:
            payload['description'] = description

        response = requests.post(
            f'{_JIRA_URL}/rest/api/3/dashboard',
            auth=(email, api_token),
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            json=payload,
        )

        if response.status_code not in (200, 201):
            raise Exception(f'Jira API error: {response.status_code} - {response.text}')

        d = response.json()
        result = {
            'id': str(d.get('id', '')),
            'name': d.get('name', ''),
            'description': d.get('description', '') or '',
            'view': d.get('view', ''),
        }

        log.info(f'Created dashboard: {result["id"]} - {result["name"]}')
        return ToolResult.success(result)

    except Exception as e:
        log.error(f'Failed to create dashboard: {e}')
        return ToolResult.failure(f'Failed to create dashboard "{name}": {e}')


@tool(
    name='bulk_update_tickets',
    description='Bulk update tickets from a CSV file (set release, labels, etc.)'
)
def bulk_update_tickets(
    input_file: str,
    set_release: Optional[str] = None,
    set_labels: Optional[str] = None
) -> ToolResult:
    '''
    Bulk update tickets loaded from a CSV file.

    Delegates to jira_utils.bulk_update_tickets() which reads ticket keys
    from a CSV and applies the requested operations.

    Input:
        input_file: Path to the CSV file containing ticket keys.
        set_release: Optional release/version name to set on all tickets.
        set_labels: Optional comma-separated labels to set on tickets.

    Output:
        ToolResult confirming the bulk update operation.
    '''
    log.debug(f'bulk_update_tickets(input_file={input_file}, set_release={set_release}, set_labels={set_labels})')

    try:
        jira = get_jira()

        # Validate input file exists
        if not os.path.isfile(input_file):
            return ToolResult.failure(f'Input file not found: {input_file}')

        # Delegate to jira_utils.bulk_update_tickets.
        # Note: dry_run=False to actually execute; the tool caller is
        # responsible for confirming intent before invoking this tool.
        _ju_bulk_update_tickets(
            jira,
            input_file,
            set_release=set_release,
            dry_run=False,
        )

        result = {
            'input_file': input_file,
            'set_release': set_release,
            'set_labels': set_labels,
            'status': 'completed',
        }

        return ToolResult.success(result)

    except Exception as e:
        log.error(f'Failed to bulk update tickets: {e}')
        return ToolResult.failure(f'Bulk update failed: {e}')


# ****************************************************************************************
# Daily Report / Reporting Tools
# ****************************************************************************************

@tool(
    name='get_tickets_created_on',
    description='Find all tickets created on a specific date'
)
def get_tickets_created_on(project_key: str, date: str = '') -> ToolResult:
    '''
    Find all tickets created on a specific date.

    Input:
        project_key: Jira project key (e.g. "STL").
        date: Target date YYYY-MM-DD (defaults to today if empty).

    Output:
        ToolResult with list of ticket dicts.
    '''
    from datetime import date as _date
    from core.reporting import tickets_created_on

    log.debug(f'get_tickets_created_on(project_key={project_key}, date={date})')

    try:
        jira = get_jira()
        target_date = date or _date.today().isoformat()
        tickets = tickets_created_on(jira, project_key, target_date)
        return ToolResult.success(tickets, count=len(tickets), date=target_date)
    except Exception as e:
        log.error(f'Failed to get tickets created on {date}: {e}')
        return ToolResult.failure(f'Query failed: {e}')


@tool(
    name='find_bugs_missing_field',
    description='Find bugs missing a required field like Affects Version'
)
def find_bugs_missing_field(
    project_key: str,
    field: str = 'affectedVersion',
    date: str = '',
) -> ToolResult:
    '''
    Find bugs missing a required field.

    Input:
        project_key: Jira project key (e.g. "STL").
        field: JQL field name to check (affectedVersion, fixVersion, component, etc.).
        date: If given, only bugs created on this date.  Otherwise all open bugs.

    Output:
        ToolResult with {flagged: [...], total_open_count: int, field: str}.
    '''
    from core.reporting import bugs_missing_field

    log.debug(f'find_bugs_missing_field(project_key={project_key}, field={field}, date={date})')

    try:
        jira = get_jira()
        target_date = date if date else None
        result = bugs_missing_field(jira, project_key, field=field,
                                    target_date=target_date)
        return ToolResult.success(
            result,
            flagged_count=len(result['flagged']),
            total_open_count=result['total_open_count'],
        )
    except Exception as e:
        log.error(f'Failed to find bugs missing {field}: {e}')
        return ToolResult.failure(f'Query failed: {e}')


@tool(
    name='get_status_changes',
    description='Get status transitions for a date, separated by automation vs human'
)
def get_status_changes(project_key: str, date: str = '') -> ToolResult:
    '''
    Get status transitions for a date, split by automation vs human.

    Input:
        project_key: Jira project key (e.g. "STL").
        date: Target date YYYY-MM-DD (defaults to today if empty).

    Output:
        ToolResult with {automation: [...], human: [...], total: int}.
    '''
    from datetime import date as _date
    from core.reporting import status_changes_by_actor

    log.debug(f'get_status_changes(project_key={project_key}, date={date})')

    try:
        target_date = date or _date.today().isoformat()
        result = status_changes_by_actor(project_key, target_date)
        return ToolResult.success(
            result,
            automation_count=len(result['automation']),
            human_count=len(result['human']),
            total=result['total'],
        )
    except Exception as e:
        log.error(f'Failed to get status changes: {e}')
        return ToolResult.failure(f'Query failed: {e}')


@tool(
    name='daily_report',
    description='Run a full daily report: created tickets, missing fields, automation changes'
)
def daily_report_tool(
    project_key: str,
    date: str = '',
    dump_file: str = '',
    dump_format: str = 'excel',
) -> ToolResult:
    '''
    Run a full daily report with optional export.

    Input:
        project_key: Jira project key (e.g. "STL").
        date: Target date YYYY-MM-DD (defaults to today if empty).
        dump_file: If provided, export report to this file path.
        dump_format: Export format: "excel" or "csv" (default: excel).

    Output:
        ToolResult with full report dict.  If dump_file is given, includes
        the export path.
    '''
    from datetime import date as _date
    from core.reporting import daily_report, export_daily_report

    log.debug(f'daily_report_tool(project_key={project_key}, date={date}, '
              f'dump_file={dump_file}, dump_format={dump_format})')

    try:
        jira = get_jira()
        target_date = date or _date.today().isoformat()
        report = daily_report(jira, project_key, target_date)

        extra_meta: Dict[str, Any] = {
            'created_count': len(report['created_tickets']),
            'flagged_bugs_count': len(report['bugs_missing_field']['flagged']),
            'automation_changes': len(report['status_changes']['automation']),
        }

        if dump_file:
            export_path = export_daily_report(report, dump_file, fmt=dump_format)
            extra_meta['export_path'] = export_path

        return ToolResult.success(report, **extra_meta)

    except Exception as e:
        log.error(f'Failed to run daily report: {e}')
        return ToolResult.failure(f'Daily report failed: {e}')


# ****************************************************************************************
# Helper Functions
# ****************************************************************************************

def _issue_to_dict(issue) -> Dict[str, Any]:
    return issue_to_dict(issue)


def _raw_issue_to_dict(raw: dict[str, Any]) -> Dict[str, Any]:
    return issue_to_dict(raw)


# ****************************************************************************************
# Tool Collection Class
# ****************************************************************************************

class JiraTools(BaseTool):
    '''
    Collection of Jira tools for agent use.
    
    Provides all Jira operations as a unified tool collection,
    wrapping jira_utils.py functionality.
    '''
    
    @tool(description='Get information about a Jira project')
    def get_project_info(self, project_key: str) -> ToolResult:
        return get_project_info(project_key)
    
    @tool(description='Get workflow statuses for a project')
    def get_project_workflows(self, project_key: str) -> ToolResult:
        return get_project_workflows(project_key)
    
    @tool(description='Get issue types for a project')
    def get_project_issue_types(self, project_key: str) -> ToolResult:
        return get_project_issue_types(project_key)
    
    @tool(description='Get releases for a project')
    def get_releases(
        self,
        project_key: str,
        pattern: Optional[str] = None
    ) -> ToolResult:
        return get_releases(project_key, pattern)
    
    @tool(description='Get tickets for a release')
    def get_release_tickets(
        self,
        project_key: str,
        release_name: str,
        limit: int = 100
    ) -> ToolResult:
        return get_release_tickets(project_key, release_name, limit=limit)
    
    @tool(description='Search tickets using JQL')
    def search_tickets(self, jql: str, limit: int = 100) -> ToolResult:
        return search_tickets(jql, limit)
    
    @tool(description='Create a new ticket')
    def create_ticket(
        self,
        project_key: str,
        summary: str,
        issue_type: str,
        description: Optional[str] = None
    ) -> ToolResult:
        return create_ticket(project_key, summary, issue_type, description)
    
    @tool(description='Update an existing ticket')
    def update_ticket(
        self,
        ticket_key: str,
        summary: Optional[str] = None,
        description: Optional[str] = None
    ) -> ToolResult:
        return update_ticket(ticket_key, summary, description)
    
    @tool(description='Create a new release')
    def create_release(
        self,
        project_key: str,
        name: str,
        description: Optional[str] = None
    ) -> ToolResult:
        return create_release(project_key, name, description)
    
    @tool(description='Link two tickets')
    def link_tickets(
        self,
        from_key: str,
        to_key: str,
        link_type: str = 'Relates'
    ) -> ToolResult:
        return link_tickets(from_key, to_key, link_type)
    
    @tool(description='Get components for a project')
    def get_components(self, project_key: str) -> ToolResult:
        return get_components(project_key)
    
    @tool(description='Assign a ticket to a user')
    def assign_ticket(self, ticket_key: str, assignee: str) -> ToolResult:
        return assign_ticket(ticket_key, assignee)
    
    @tool(description='Get related tickets by traversing links')
    def get_related_tickets(
        self,
        ticket_key: str,
        hierarchy_depth: int = 3
    ) -> ToolResult:
        return get_related_tickets(ticket_key, hierarchy_depth)
    
    # --- New delegate methods for expanded tool coverage ---

    @tool(description='List Jira filters, optionally filtered by owner or favourites')
    def list_filters(self, owner: Optional[str] = None, favourite_only: bool = False) -> ToolResult:
        return list_filters(owner, favourite_only)
    
    @tool(description='Run a Jira filter by ID and return matching tickets')
    def run_filter(self, filter_id: str, limit: int = 50) -> ToolResult:
        return run_filter(filter_id, limit)
    
    @tool(description='Run a JQL query and return matching tickets')
    def run_jql_query(self, jql: str, limit: int = 50) -> ToolResult:
        return run_jql_query(jql, limit)
    
    @tool(description='Get child tickets in a hierarchy tree from a root ticket')
    def get_children_hierarchy(self, root_key: str, limit: int = 100) -> ToolResult:
        return get_children_hierarchy(root_key, limit)
    
    @tool(description='Get all versions/releases defined for a Jira project')
    def get_project_versions(self, project_key: str) -> ToolResult:
        return get_project_versions_tool(project_key)
    
    @tool(description='Get ticket count totals for a project')
    def get_ticket_totals(
        self,
        project_key: str,
        issue_types: Optional[str] = None,
        statuses: Optional[str] = None
    ) -> ToolResult:
        return get_ticket_totals(project_key, issue_types, statuses)
    
    @tool(description='List Jira dashboards, optionally filtered by owner')
    def list_dashboards(self, owner: Optional[str] = None, shared: bool = False) -> ToolResult:
        return list_dashboards(owner, shared)
    
    @tool(description='Get details of a specific Jira dashboard by ID')
    def get_dashboard(self, dashboard_id: str) -> ToolResult:
        return get_dashboard(dashboard_id)
    
    @tool(description='Create a new Jira dashboard')
    def create_dashboard(self, name: str, description: str = '') -> ToolResult:
        return create_dashboard(name, description)
    
    @tool(description='Bulk update tickets from a CSV file')
    def bulk_update_tickets(
        self,
        input_file: str,
        set_release: Optional[str] = None,
        set_labels: Optional[str] = None
    ) -> ToolResult:
        return bulk_update_tickets(input_file, set_release, set_labels)

    # --- Daily reporting delegates ---

    @tool(description='Get all tickets created on a specific date')
    def get_tickets_created_on(self, project_key: str, date: str = '') -> ToolResult:
        return get_tickets_created_on(project_key, date)

    @tool(description='Find bugs missing a required field (e.g. affectedVersion)')
    def find_bugs_missing_field(
        self,
        project_key: str,
        field: str = 'affectedVersion',
        date: str = '',
    ) -> ToolResult:
        return find_bugs_missing_field(project_key, field, date)

    @tool(description='Get status transitions split by automation vs human')
    def get_status_changes(self, project_key: str, date: str = '') -> ToolResult:
        return get_status_changes(project_key, date)

    @tool(description='Run a full daily report with optional export')
    def daily_report(
        self,
        project_key: str,
        date: str = '',
        dump_file: str = '',
        dump_format: str = 'excel',
    ) -> ToolResult:
        return daily_report_tool(project_key, date, dump_file, dump_format)
