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

# Load environment variables
load_dotenv()

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# Import from jira_utils.py - reuse existing functionality
try:
    import jira_utils
    from jira_utils import (
        connect_to_jira,
        validate_project,
        get_project_workflows as _get_project_workflows,
        get_project_issue_types as _get_project_issue_types,
        get_project_versions,
        get_project_components as _get_project_components,
        JIRA_URL,
    )
    JIRA_UTILS_AVAILABLE = True
except ImportError as e:
    JIRA_UTILS_AVAILABLE = False
    log.warning(f'jira_utils.py not available: {e}')
    JIRA_URL = os.getenv('JIRA_URL', 'https://cornelisnetworks.atlassian.net')

# Jira connection cache
_jira_connection = None


def get_jira():
    '''
    Get or create Jira connection using jira_utils.
    
    Output:
        JIRA object with active connection.
    
    Raises:
        RuntimeError: If jira_utils is not available or connection fails.
    '''
    global _jira_connection
    
    if not JIRA_UTILS_AVAILABLE:
        raise RuntimeError('jira_utils.py is required but not available')
    
    if _jira_connection is None:
        _jira_connection = connect_to_jira()
    
    return _jira_connection


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
            fields['assignee'] = {'id': assignee}
        
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
        
        if custom_fields:
            fields.update(custom_fields)
        
        log.info(f'Creating ticket: {summary}')
        issue = jira.create_issue(fields=fields)
        
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
    Get related tickets by traversing links.
    
    This wraps the jira_utils.py --get-related functionality.
    
    Input:
        ticket_key: The root ticket key to start from.
        hierarchy_depth: Maximum depth to traverse (default: 3).
        limit: Maximum number of tickets to return.
    
    Output:
        ToolResult with list of related tickets.
    '''
    log.debug(f'get_related_tickets(ticket_key={ticket_key}, depth={hierarchy_depth})')
    
    try:
        if not JIRA_UTILS_AVAILABLE:
            return ToolResult.failure('jira_utils.py is required for get_related_tickets')
        
        jira = get_jira()
        
        # Use jira_utils get_related_issues function if available
        # For now, implement basic link traversal
        visited = set()
        tickets = []
        
        def traverse(key: str, depth: int):
            if depth > hierarchy_depth or key in visited or len(tickets) >= limit:
                return
            
            visited.add(key)
            
            try:
                issue = jira.issue(key, expand='changelog')
                tickets.append(_issue_to_dict(issue))
                
                # Get linked issues
                if hasattr(issue.fields, 'issuelinks'):
                    for link in issue.fields.issuelinks:
                        linked_key = None
                        if hasattr(link, 'outwardIssue'):
                            linked_key = link.outwardIssue.key
                        elif hasattr(link, 'inwardIssue'):
                            linked_key = link.inwardIssue.key
                        
                        if linked_key and linked_key not in visited:
                            traverse(linked_key, depth + 1)
            except Exception as e:
                log.warning(f'Failed to get issue {key}: {e}')
        
        traverse(ticket_key, 0)
        
        return ToolResult.success(tickets, count=len(tickets), root_ticket=ticket_key)
        
    except Exception as e:
        log.error(f'Failed to get related tickets: {e}')
        return ToolResult.failure(f'Failed to get related tickets for {ticket_key}: {e}')


# ****************************************************************************************
# Helper Functions
# ****************************************************************************************

def _issue_to_dict(issue) -> Dict[str, Any]:
    '''Convert a Jira issue to a dictionary.'''
    fields = issue.fields
    
    # Extract common fields safely
    issue_type = getattr(fields, 'issuetype', None)
    status = getattr(fields, 'status', None)
    priority = getattr(fields, 'priority', None)
    assignee = getattr(fields, 'assignee', None)
    reporter = getattr(fields, 'reporter', None)
    
    fix_versions = getattr(fields, 'fixVersions', []) or []
    components = getattr(fields, 'components', []) or []
    labels = getattr(fields, 'labels', []) or []
    
    return {
        'key': issue.key,
        'id': issue.id,
        'summary': getattr(fields, 'summary', ''),
        'description': _extract_description(getattr(fields, 'description', None)),
        'type': issue_type.name if issue_type else None,
        'status': status.name if status else None,
        'priority': priority.name if priority else None,
        'assignee': assignee.displayName if assignee else None,
        'assignee_id': assignee.accountId if assignee else None,
        'reporter': reporter.displayName if reporter else None,
        'created': getattr(fields, 'created', None),
        'updated': getattr(fields, 'updated', None),
        'fix_versions': [v.name for v in fix_versions],
        'components': [c.name for c in components],
        'labels': labels,
        'url': f'{JIRA_URL}/browse/{issue.key}'
    }


def _extract_description(description) -> str:
    '''Extract plain text from ADF description.'''
    if not description:
        return ''
    
    if isinstance(description, str):
        return description
    
    # Handle ADF format
    if isinstance(description, dict):
        content = description.get('content', [])
        text_parts = []
        for block in content:
            if block.get('type') == 'paragraph':
                for item in block.get('content', []):
                    if item.get('type') == 'text':
                        text_parts.append(item.get('text', ''))
        return '\n'.join(text_parts)
    
    return str(description)


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
