#!/usr/bin/env python3
##########################################################################################
#
# Module: mcp_server.py
#
# Description: Cornelis Jira MCP Server.
#              Exposes Jira tools via the Model Context Protocol (MCP) so that
#              AI assistants (Claude Desktop, Cursor, Windsurf, etc.) can interact
#              with Jira through a standardised tool-calling interface.
#
#              Transport: stdio (JSON-RPC 2.0 over stdin/stdout).
#
# Architecture:
#   MCP Client (Claude Desktop / Cursor / etc.)
#       ↓ stdio (JSON-RPC 2.0)
#   mcp_server.py
#       ↓ function calls
#   jira_utils.py (deterministic Jira API)
#       ↓ REST API
#   Jira Cloud
#
# Usage:
#   python3 mcp_server.py                    # Run as stdio MCP server
#   jira-mcp-server                          # After pipx install
#
# Author: Cornelis Networks
#
##########################################################################################

import json
import logging
import os
import sys
from typing import Any, Optional, cast

from dotenv import load_dotenv

# Load environment variables before importing jira_utils
load_dotenv()

# ---------------------------------------------------------------------------
# Logging — stdout is reserved for MCP JSON-RPC, so ALL logging goes to stderr.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s %(message)s',
    stream=sys.stderr,
)
log = logging.getLogger('jira-mcp-server')

# ---------------------------------------------------------------------------
# MCP SDK imports
# ---------------------------------------------------------------------------
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent
    try:
        from mcp.server import FastMCP
    except ImportError:
        FastMCP = None
except ImportError:
    log.error('MCP SDK not installed. Install with: pip install "mcp[cli]"')
    sys.exit(1)

# ---------------------------------------------------------------------------
# jira_utils — suppress stdout output so it doesn't corrupt the MCP channel.
# The output() function in jira_utils checks _quiet_mode before printing.
# ---------------------------------------------------------------------------
import jira_utils

# CRITICAL: Suppress all stdout output from jira_utils.  The MCP protocol
# uses stdout exclusively for JSON-RPC 2.0 messages; any stray print()
# would corrupt the transport.
jira_utils._quiet_mode = True

# ---------------------------------------------------------------------------
# MCP Server instance
# ---------------------------------------------------------------------------
if FastMCP is not None:
    server = FastMCP("cornelis-jira")
else:
    server = Server("cornelis-jira")


def _tool_decorator():
    if hasattr(server, 'tool'):
        dynamic_server = cast(Any, server)
        return dynamic_server.tool()

    def _passthrough(func):
        return func

    return _passthrough


# ---------------------------------------------------------------------------
# Helper: format results as JSON text for MCP responses
# ---------------------------------------------------------------------------

def _json_result(data: Any) -> list[Any]:
    """Format *data* as a JSON ``TextContent`` list for MCP tool responses."""
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _error_result(message: str) -> list[Any]:
    """Format an error message as a ``TextContent`` list."""
    return [TextContent(type="text", text=json.dumps({"error": message}, indent=2))]


def _issue_to_dict(issue: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw Jira issue dict (from REST API) to a clean serialisable dict.

    The Jira REST API returns issues as nested dicts with a ``key`` and
    ``fields`` sub-dict.  This helper flattens the most useful fields into
    a simple dict suitable for returning to MCP clients.
    """
    if isinstance(issue, dict):
        key = issue.get('key', '')
        fields = issue.get('fields', {})
    elif hasattr(issue, 'key'):
        # jira-python Resource object
        key = issue.key
        fields = issue.raw.get('fields', {}) if hasattr(issue, 'raw') else {}
    else:
        return {'raw': str(issue)}

    # Extract nested field values safely
    issue_type = (fields.get('issuetype') or {}).get('name', 'N/A')
    status = (fields.get('status') or {}).get('name', 'N/A')
    priority = (fields.get('priority') or {}).get('name', 'N/A')
    assignee_obj = fields.get('assignee') or {}
    assignee = assignee_obj.get('displayName', 'Unassigned')
    reporter_obj = fields.get('reporter') or {}
    reporter = reporter_obj.get('displayName', 'Unknown')
    fix_versions = [v.get('name', '') for v in (fields.get('fixVersions') or [])]
    components = [c.get('name', '') for c in (fields.get('components') or [])]
    labels = fields.get('labels') or []

    return {
        'key': key,
        'summary': fields.get('summary', ''),
        'status': status,
        'issue_type': issue_type,
        'priority': priority,
        'assignee': assignee,
        'reporter': reporter,
        'created': (fields.get('created') or '')[:10],
        'updated': (fields.get('updated') or '')[:10],
        'fix_versions': fix_versions,
        'components': components,
        'labels': labels,
        'description': _extract_description(fields.get('description')),
    }


def _extract_description(desc: Any) -> str:
    """Best-effort extraction of plain text from a Jira description field.

    Jira Cloud uses ADF (Atlassian Document Format) for descriptions.  This
    helper walks the ADF tree and concatenates text nodes.  If the description
    is already a plain string it is returned as-is.
    """
    if desc is None:
        return ''
    if isinstance(desc, str):
        return desc

    # ADF document — walk content nodes
    parts: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get('type') == 'text':
                parts.append(node.get('text', ''))
            for child in node.get('content', []):
                _walk(child)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(desc)
    return '\n'.join(parts) if parts else str(desc)


# ---------------------------------------------------------------------------
# Tool 1: search_tickets — Run a JQL query
# ---------------------------------------------------------------------------

@_tool_decorator()
async def search_tickets(jql: str, limit: int = 50) -> list[Any]:
    """Search Jira tickets using a JQL query.

    Args:
        jql: JQL query string (e.g. 'project = STL AND status = Open').
        limit: Maximum number of tickets to return (default: 50).
    """
    try:
        jira = jira_utils.get_connection()
        issues = jira_utils.run_jql_query(jira, jql, limit=limit)
        result = [_issue_to_dict(issue) for issue in (issues or [])]
        return _json_result(result)
    except Exception as e:
        log.error(f'search_tickets failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 2: get_ticket — Get a single ticket's details
# ---------------------------------------------------------------------------

@_tool_decorator()
async def get_ticket(ticket_key: str) -> list[Any]:
    """Get detailed information for a single Jira ticket.

    Args:
        ticket_key: The Jira issue key (e.g. 'STL-1234').
    """
    try:
        jira = jira_utils.get_connection()
        # Use JQL to fetch a single issue so we get the same dict format
        issues = jira_utils.run_jql_query(jira, f'key = "{ticket_key}"', limit=1)
        if not issues:
            return _error_result(f'Ticket {ticket_key} not found')
        return _json_result(_issue_to_dict(issues[0]))
    except Exception as e:
        log.error(f'get_ticket failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 3: create_ticket — Create a new Jira ticket
# ---------------------------------------------------------------------------

@_tool_decorator()
async def create_ticket(
    project_key: str,
    summary: str,
    issue_type: str,
    description: Optional[str] = None,
    assignee: Optional[str] = None,
    priority: Optional[str] = None,
    fix_version: Optional[str] = None,
    labels: Optional[str] = None,
    parent_key: Optional[str] = None,
) -> list[Any]:
    """Create a new Jira ticket.

    Args:
        project_key: Jira project key (e.g. 'STL').
        summary: Issue summary / title.
        issue_type: Issue type name (e.g. Task, Bug, Story, Epic).
        description: Optional plain-text description.
        assignee: Optional assignee accountId.
        priority: Optional priority name (e.g. 'High', 'Medium').
        fix_version: Optional fix-version name to set.
        labels: Optional comma-separated label string (e.g. 'backend,urgent').
        parent_key: Optional parent issue key for sub-tasks or child issues.
    """
    try:
        jira = jira_utils.get_connection()

        # Convert comma-separated labels to list
        labels_list = [l.strip() for l in labels.split(',')] if labels else None

        # Convert fix_version to list
        fix_versions_list = [fix_version] if fix_version else None

        # Call jira_utils.create_ticket with dry_run=False so it actually creates
        jira_utils.create_ticket(
            jira,
            project_key=project_key,
            summary=summary,
            issue_type=issue_type,
            description=description,
            assignee=assignee,
            fix_versions=fix_versions_list,
            labels=labels_list,
            parent_key=parent_key,
            dry_run=False,
        )

        # jira_utils.create_ticket prints the key but doesn't return it.
        # Search for the just-created ticket by summary to return its key.
        # Use a targeted JQL query.
        issues = jira_utils.run_jql_query(
            jira,
            f'project = "{project_key}" AND summary ~ "{summary}" ORDER BY created DESC',
            limit=1,
        )
        if issues:
            result = _issue_to_dict(issues[0])
            result['message'] = 'Ticket created successfully'
            return _json_result(result)
        return _json_result({'message': 'Ticket created successfully (could not retrieve key)'})
    except Exception as e:
        log.error(f'create_ticket failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 4: update_ticket — Update fields on an existing ticket
# ---------------------------------------------------------------------------

@_tool_decorator()
async def update_ticket(
    ticket_key: str,
    summary: Optional[str] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    priority: Optional[str] = None,
    fix_version: Optional[str] = None,
    labels: Optional[str] = None,
    description: Optional[str] = None,
) -> list[Any]:
    """Update fields on an existing Jira ticket.

    Only the fields you provide will be changed; others are left untouched.

    Args:
        ticket_key: The Jira issue key (e.g. 'STL-1234').
        summary: New summary text.
        status: New status name to transition to (e.g. 'In Progress').
        assignee: New assignee accountId.
        priority: New priority name (e.g. 'High').
        fix_version: Fix-version name to set (replaces existing).
        labels: Comma-separated labels to set (replaces existing).
        description: New plain-text description.
    """
    try:
        jira = jira_utils.get_connection()
        issue = jira.issue(ticket_key)

        # Build the update fields dict
        update_fields: dict[str, Any] = {}
        if summary is not None:
            update_fields['summary'] = summary
        if priority is not None:
            update_fields['priority'] = {'name': priority}
        if assignee is not None:
            update_fields['assignee'] = {'accountId': assignee}
        if fix_version is not None:
            update_fields['fixVersions'] = [{'name': fix_version}]
        if labels is not None:
            update_fields['labels'] = [l.strip() for l in labels.split(',')]
        if description is not None:
            update_fields['description'] = jira_utils._adf_from_text(description)

        # Apply field updates
        if update_fields:
            issue.update(fields=update_fields)

        # Handle status transition separately (requires workflow transition)
        if status is not None:
            transitions = jira.transitions(issue)
            target = None
            for t in transitions:
                if t['name'].lower() == status.lower():
                    target = t
                    break
                # Also match by destination status name
                to_status = t.get('to', {}).get('name', '')
                if to_status.lower() == status.lower():
                    target = t
                    break
            if target:
                jira.transition_issue(issue, target['id'])
            else:
                available = [t['name'] for t in transitions]
                return _error_result(
                    f'Cannot transition to "{status}". '
                    f'Available transitions: {available}'
                )

        # Fetch the updated issue to return current state
        issues = jira_utils.run_jql_query(jira, f'key = "{ticket_key}"', limit=1)
        result = _issue_to_dict(issues[0]) if issues else {'key': ticket_key}
        result['message'] = 'Ticket updated successfully'
        return _json_result(result)
    except Exception as e:
        log.error(f'update_ticket failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 5: list_filters — List Jira saved filters
# ---------------------------------------------------------------------------

@_tool_decorator()
async def list_filters(favourite_only: bool = False) -> list[Any]:
    """List accessible Jira saved filters.

    Args:
        favourite_only: If true, return only the user's starred/favourite filters.
    """
    try:
        jira = jira_utils.get_connection()
        # list_filters prints to stdout (suppressed) but doesn't return data.
        # We need to call the REST API directly to get structured data.
        email, api_token = jira_utils.get_jira_credentials()

        if favourite_only:
            import requests
            response = requests.get(
                f'{jira_utils.JIRA_URL}/rest/api/3/filter/favourite',
                auth=(email, api_token),
                headers={'Accept': 'application/json'},
            )
        else:
            import requests
            response = requests.get(
                f'{jira_utils.JIRA_URL}/rest/api/3/filter/search',
                auth=(email, api_token),
                headers={'Accept': 'application/json'},
                params={'maxResults': 100, 'expand': 'description,jql,owner'},
            )

        if response.status_code != 200:
            return _error_result(f'Jira API error: {response.status_code} - {response.text}')

        data = response.json()
        filters_raw = data if isinstance(data, list) else data.get('values', [])

        result = []
        for f in filters_raw:
            result.append({
                'id': f.get('id'),
                'name': f.get('name', ''),
                'owner': (f.get('owner') or {}).get('displayName', 'Unknown'),
                'jql': f.get('jql', ''),
                'description': f.get('description', ''),
                'favourite': f.get('favourite', False),
            })
        return _json_result(result)
    except Exception as e:
        log.error(f'list_filters failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 6: run_filter — Run a saved Jira filter by ID
# ---------------------------------------------------------------------------

@_tool_decorator()
async def run_filter(filter_id: str, limit: int = 50) -> list[Any]:
    """Run a saved Jira filter by its ID and return matching tickets.

    Args:
        filter_id: The numeric filter ID (e.g. '12345').
        limit: Maximum number of tickets to return (default: 50).
    """
    try:
        jira = jira_utils.get_connection()
        # Fetch the filter's JQL first
        email, api_token = jira_utils.get_jira_credentials()
        import requests
        response = requests.get(
            f'{jira_utils.JIRA_URL}/rest/api/3/filter/{filter_id}',
            auth=(email, api_token),
            headers={'Accept': 'application/json'},
        )
        if response.status_code == 404:
            return _error_result(f'Filter {filter_id} not found')
        if response.status_code != 200:
            return _error_result(f'Jira API error: {response.status_code} - {response.text}')

        filter_data = response.json()
        jql = filter_data.get('jql', '')
        if not jql:
            return _error_result(f'Filter {filter_id} has no JQL query')

        # Execute the JQL
        issues = jira_utils.run_jql_query(jira, jql, limit=limit)
        result = {
            'filter_id': filter_id,
            'filter_name': filter_data.get('name', ''),
            'jql': jql,
            'tickets': [_issue_to_dict(issue) for issue in (issues or [])],
        }
        return _json_result(result)
    except Exception as e:
        log.error(f'run_filter failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 7: get_releases — Get project releases/versions
# ---------------------------------------------------------------------------

@_tool_decorator()
async def get_releases(project_key: str, pattern: Optional[str] = None) -> list[Any]:
    """Get releases (versions) for a Jira project.

    Args:
        project_key: Jira project key (e.g. 'STL').
        pattern: Optional glob pattern to filter releases (e.g. '12.*').
    """
    try:
        jira = jira_utils.get_connection()
        jira_utils.validate_project(jira, project_key)
        versions = jira.project_versions(project_key)

        # Apply pattern filtering if provided
        if pattern:
            filtered = []
            for v in versions:
                if jira_utils.match_pattern_with_exclusions(v.name, pattern):
                    filtered.append(v)
            versions = filtered

        result = []
        for v in versions:
            result.append({
                'name': v.name,
                'id': v.id,
                'released': getattr(v, 'released', False),
                'archived': getattr(v, 'archived', False),
                'release_date': getattr(v, 'releaseDate', None) or '',
                'description': getattr(v, 'description', '') or '',
            })
        return _json_result(result)
    except Exception as e:
        log.error(f'get_releases failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 8: get_release_tickets — Get tickets for a specific release
# ---------------------------------------------------------------------------

@_tool_decorator()
async def get_release_tickets(
    project_key: str,
    release_name: str,
    limit: int = 50,
) -> list[Any]:
    """Get tickets associated with a specific release/version.

    Args:
        project_key: Jira project key (e.g. 'STL').
        release_name: Release/version name (case-insensitive) or glob pattern (e.g. '12.1*').
        limit: Maximum number of tickets to return (default: 50).
    """
    try:
        jira = jira_utils.get_connection()
        # Build JQL for the release
        jql = f'project = "{project_key}" AND fixVersion = "{release_name}" ORDER BY key ASC'
        issues = jira_utils.run_jql_query(jira, jql, limit=limit)
        result = {
            'project': project_key,
            'release': release_name,
            'tickets': [_issue_to_dict(issue) for issue in (issues or [])],
        }
        return _json_result(result)
    except Exception as e:
        log.error(f'get_release_tickets failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 9: get_children — Get child ticket hierarchy
# ---------------------------------------------------------------------------

@_tool_decorator()
async def get_children(root_key: str, limit: int = 50) -> list[Any]:
    """Get the child ticket hierarchy for a given Jira issue.

    Recursively retrieves all child issues (sub-tasks, stories under epics, etc.).

    Args:
        root_key: The parent issue key to start from (e.g. 'STL-100').
        limit: Maximum number of tickets to return including the root (default: 50).
    """
    try:
        jira = jira_utils.get_connection()
        # Use the internal _get_children_data for structured data
        ordered = jira_utils._get_children_data(jira, root_key, limit=limit)
        result = []
        for item in ordered:
            entry = _issue_to_dict(item['issue'])
            entry['depth'] = item.get('depth', 0)
            result.append(entry)
        return _json_result(result)
    except Exception as e:
        log.error(f'get_children failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 10: get_related — Get related tickets via link traversal
# ---------------------------------------------------------------------------

@_tool_decorator()
async def get_related(root_key: str, depth: Optional[int] = None, limit: int = 50) -> list[Any]:
    """Get related tickets for a given issue via link and child traversal.

    Related includes linked issues (issuelinks) and children discovered
    via JQL ``parent = "<key>"``.

    Args:
        root_key: The issue key to start from (e.g. 'STL-100').
        depth: Traversal depth (None for direct-only, -1 for unlimited).
        limit: Maximum number of tickets to return including the root (default: 50).
    """
    try:
        jira = jira_utils.get_connection()
        # Use the internal _get_related_data for structured data
        ordered = jira_utils._get_related_data(jira, root_key, hierarchy=depth, limit=limit)
        result = []
        for item in ordered:
            entry = _issue_to_dict(item['issue'])
            entry['depth'] = item.get('depth', 0)
            entry['via'] = item.get('via', '')
            entry['relation'] = item.get('relation', '')
            entry['from_key'] = item.get('from_key', '')
            result.append(entry)
        return _json_result(result)
    except Exception as e:
        log.error(f'get_related failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 11: get_project_info — Get project metadata
# ---------------------------------------------------------------------------

@_tool_decorator()
async def get_project_info(project_key: str) -> list[Any]:
    """Get metadata for a Jira project (name, lead, description, issue types, etc.).

    Args:
        project_key: Jira project key (e.g. 'STL').
    """
    try:
        jira = jira_utils.get_connection()
        project = jira_utils.validate_project(jira, project_key)

        result = {
            'key': project.key,
            'name': project.name,
            'lead': getattr(project, 'lead', {}).get('displayName', 'Unknown')
                    if isinstance(getattr(project, 'lead', None), dict)
                    else str(getattr(project, 'lead', 'Unknown')),
            'description': getattr(project, 'description', '') or '',
            'project_type': getattr(project, 'projectTypeKey', ''),
        }

        # Fetch issue types for this project
        try:
            meta = jira.createmeta(
                projectKeys=project_key,
                expand='projects.issuetypes',
            )
            projects = meta.get('projects', [])
            if projects:
                issue_types = [it.get('name', '') for it in projects[0].get('issuetypes', [])]
                result['issue_types'] = issue_types
        except Exception:
            # createmeta may not be available; skip gracefully
            pass

        return _json_result(result)
    except Exception as e:
        log.error(f'get_project_info failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 12: get_components — Get project components
# ---------------------------------------------------------------------------

@_tool_decorator()
async def get_components(project_key: str) -> list[Any]:
    """Get the components defined for a Jira project.

    Args:
        project_key: Jira project key (e.g. 'STL').
    """
    try:
        jira = jira_utils.get_connection()
        jira_utils.validate_project(jira, project_key)
        components = jira.project_components(project_key)

        result = []
        for c in components:
            result.append({
                'name': c.name,
                'id': c.id,
                'lead': getattr(c, 'lead', {}).get('displayName', '')
                        if isinstance(getattr(c, 'lead', None), dict)
                        else str(getattr(c, 'lead', '')),
                'description': getattr(c, 'description', '') or '',
            })
        return _json_result(result)
    except Exception as e:
        log.error(f'get_components failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 13: assign_ticket — Assign a ticket to a user
# ---------------------------------------------------------------------------

@_tool_decorator()
async def assign_ticket(ticket_key: str, assignee: str) -> list[Any]:
    """Assign a Jira ticket to a user.

    Args:
        ticket_key: The Jira issue key (e.g. 'STL-1234').
        assignee: The accountId, display name, email, or username of the user
                  to assign, or 'unassigned' to clear.  Human-readable values
                  are automatically resolved to accountIds via UserResolver.
    """
    try:
        jira = jira_utils.get_connection()
        issue = jira.issue(ticket_key)

        if assignee.lower() == 'unassigned':
            issue.update(fields={'assignee': None})
        else:
            # Resolve human-readable assignee to accountId if needed
            resolver = jira_utils.get_user_resolver()
            # Extract project key from the ticket key (e.g. "STL" from "STL-1234")
            project_key = ticket_key.split('-')[0] if '-' in ticket_key else ''
            resolved_id = resolver.resolve(assignee, project_key=project_key)
            if resolved_id:
                issue.update(fields={'assignee': {'accountId': resolved_id}})
            else:
                return _error_result(
                    f'Could not resolve assignee "{assignee}" to a Jira accountId'
                )

        return _json_result({
            'key': ticket_key,
            'assignee': assignee,
            'message': f'Ticket {ticket_key} assigned to {assignee}',
        })
    except Exception as e:
        log.error(f'assign_ticket failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 14: link_tickets — Link two Jira tickets
# ---------------------------------------------------------------------------

@_tool_decorator()
async def link_tickets(from_key: str, to_key: str, link_type: str = 'Relates') -> list[Any]:
    """Create a link between two Jira tickets.

    Args:
        from_key: Source issue key (e.g. 'STL-100').
        to_key: Target issue key (e.g. 'STL-200').
        link_type: Link type name (e.g. 'Relates', 'Blocks', 'is blocked by',
                   'Cloners', 'Duplicate'). Default: 'Relates'.
    """
    try:
        jira = jira_utils.get_connection()
        jira.create_issue_link(
            type=link_type,
            inwardIssue=from_key,
            outwardIssue=to_key,
        )
        return _json_result({
            'from_key': from_key,
            'to_key': to_key,
            'link_type': link_type,
            'message': f'Linked {from_key} → {to_key} ({link_type})',
        })
    except Exception as e:
        log.error(f'link_tickets failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 15: list_dashboards — List Jira dashboards
# ---------------------------------------------------------------------------

@_tool_decorator()
async def list_dashboards() -> list[Any]:
    """List accessible Jira dashboards."""
    try:
        jira = jira_utils.get_connection()
        email, api_token = jira_utils.get_jira_credentials()

        import requests
        all_dashboards = []
        start_at = 0

        while True:
            response = requests.get(
                f'{jira_utils.JIRA_URL}/rest/api/3/dashboard/search',
                auth=(email, api_token),
                headers={'Accept': 'application/json'},
                params={'maxResults': 100, 'startAt': start_at},
            )
            if response.status_code != 200:
                return _error_result(f'Jira API error: {response.status_code} - {response.text}')

            data = response.json()
            dashboards = data.get('values', [])
            all_dashboards.extend(dashboards)

            # Check for more pages
            if data.get('startAt', 0) + len(dashboards) >= data.get('total', 0):
                break
            start_at += len(dashboards)

        result = []
        for d in all_dashboards:
            owner = d.get('owner', {})
            result.append({
                'id': d.get('id'),
                'name': d.get('name', ''),
                'owner': owner.get('displayName', 'Unknown') if isinstance(owner, dict) else str(owner),
                'view_url': d.get('view', ''),
            })
        return _json_result(result)
    except Exception as e:
        log.error(f'list_dashboards failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 16: get_tickets_created_on — Tickets created on a specific date
# ---------------------------------------------------------------------------

@_tool_decorator()
async def get_tickets_created_on(project_key: str, date: str = '') -> list[Any]:
    """Get all tickets created on a specific date.

    Args:
        project_key: Jira project key (e.g. 'STL').
        date: Target date YYYY-MM-DD (defaults to today if empty).
    """
    try:
        from datetime import date as _date
        from core.reporting import tickets_created_on

        jira = jira_utils.get_connection()
        target_date = date or _date.today().isoformat()
        tickets = tickets_created_on(jira, project_key, target_date)
        return _json_result({
            'date': target_date,
            'project': project_key,
            'count': len(tickets),
            'tickets': tickets,
        })
    except Exception as e:
        log.error(f'get_tickets_created_on failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 17: find_bugs_missing_field — Bugs missing a required field
# ---------------------------------------------------------------------------

@_tool_decorator()
async def find_bugs_missing_field(
    project_key: str,
    field: str = 'affectedVersion',
    date: str = '',
) -> list[Any]:
    """Find bugs missing a required field (e.g. affectedVersion, fixVersion).

    Args:
        project_key: Jira project key (e.g. 'STL').
        field: JQL field name to check (default: affectedVersion).
        date: If given, only flag bugs created on this date (YYYY-MM-DD).
    """
    try:
        from core.reporting import bugs_missing_field

        jira = jira_utils.get_connection()
        target_date = date or None
        result = bugs_missing_field(jira, project_key, field=field,
                                    target_date=target_date)
        return _json_result(result)
    except Exception as e:
        log.error(f'find_bugs_missing_field failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 18: get_status_changes — Status transitions by actor type
# ---------------------------------------------------------------------------

@_tool_decorator()
async def get_status_changes(project_key: str, date: str = '') -> list[Any]:
    """Get status transitions for a date, split by automation vs human.

    Args:
        project_key: Jira project key (e.g. 'STL').
        date: Target date YYYY-MM-DD (defaults to today if empty).
    """
    try:
        from datetime import date as _date
        from core.reporting import status_changes_by_actor

        target_date = date or _date.today().isoformat()
        result = status_changes_by_actor(project_key, target_date)
        return _json_result(result)
    except Exception as e:
        log.error(f'get_status_changes failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Tool 19: daily_report — Full composite daily report
# ---------------------------------------------------------------------------

@_tool_decorator()
async def daily_report(
    project_key: str,
    date: str = '',
    export_path: str = '',
    export_format: str = 'excel',
) -> list[Any]:
    """Run a full daily report: created tickets, missing fields, status changes.

    Args:
        project_key: Jira project key (e.g. 'STL').
        date: Target date YYYY-MM-DD (defaults to today if empty).
        export_path: If provided, export report to this file path.
        export_format: Export format: 'excel' or 'csv' (default: excel).
    """
    try:
        from datetime import date as _date
        from core.reporting import daily_report as _daily_report
        from core.reporting import export_daily_report

        jira = jira_utils.get_connection()
        target_date = date or _date.today().isoformat()
        report = _daily_report(jira, project_key, target_date)

        response: dict[str, Any] = {
            'date': target_date,
            'project': project_key,
            'created_count': len(report.get('created_tickets', [])),
            'flagged_bugs_count': len(report.get('bugs_missing_field', {}).get('flagged', [])),
            'automation_changes': len(report.get('status_changes', {}).get('automation', [])),
            'human_changes': len(report.get('status_changes', {}).get('human', [])),
            'report': report,
        }

        if export_path:
            path = export_daily_report(report, export_path, fmt=export_format)
            response['export_path'] = path

        return _json_result(response)
    except Exception as e:
        log.error(f'daily_report failed: {e}')
        return _error_result(str(e))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Run the Cornelis Jira MCP server over stdio."""
    log.info('Starting Cornelis Jira MCP server...')

    jira_url = os.environ.get('JIRA_URL', '')
    jira_email = os.environ.get('JIRA_EMAIL', '')
    if not jira_url or not jira_email:
        log.warning('JIRA_URL or JIRA_EMAIL not set — tools will fail until configured')
    else:
        log.info(f'Jira URL: {jira_url}')
        log.info(f'Jira user: {jira_email}')

    if hasattr(server, 'tool'):
        dynamic_server = cast(Any, server)
        dynamic_server.run(transport='stdio')
        return

    import asyncio

    async def _run_lowlevel() -> None:
        lowlevel_server = cast(Any, server)
        async with stdio_server() as (read_stream, write_stream):
            await lowlevel_server.run(read_stream, write_stream, lowlevel_server.create_initialization_options())

    asyncio.run(_run_lowlevel())


def run():
    """Synchronous entry point for console_scripts (pyproject.toml)."""
    main()


if __name__ == '__main__':
    run()
