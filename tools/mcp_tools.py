##########################################################################################
#
# Module: tools/mcp_tools.py
#
# Description: Cornelis MCP (Model Context Protocol) client tools.
#              Provides runtime discovery and invocation of tools exposed by the
#              Cornelis MCP server.  The server uses the Streamable HTTP transport
#              (MCP 2025-03-26 spec) so every request must accept both
#              application/json and text/event-stream.
#
# Author: Cornelis Networks
#
##########################################################################################

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]
    log.warning('requests library not available; MCP tools will not function')

try:
    from tools.base import tool, ToolResult, BaseTool
except ImportError:
    log.warning('tools.base not available; mcp_tools will not register @tool decorators')

    # Provide a no-op decorator so the module can still be imported
    def tool(**kwargs):  # type: ignore[misc]
        def decorator(func):
            return func
        return decorator

    class ToolResult:  # type: ignore[no-redef]
        @classmethod
        def success(cls, data):
            return data

        @classmethod
        def failure(cls, msg):
            return {'error': msg}

    class BaseTool:  # type: ignore[no-redef]
        pass


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_mcp_url() -> str:
    '''Return the Cornelis MCP server URL from environment or default.'''
    return os.environ.get(
        'CORNELIS_MCP_URL',
        'http://cn-ai-01.cornelisnetworks.com:50700/mcp',
    )


def _get_mcp_api_key() -> str:
    '''Return the MCP API key (bearer token) from environment.'''
    return os.environ.get('CORNELIS_AI_API_KEY', '')


def _mcp_headers() -> Dict[str, str]:
    '''Build HTTP headers required by the Cornelis MCP server.'''
    api_key = _get_mcp_api_key()
    headers: Dict[str, str] = {
        'Content-Type': 'application/json',
        # The Streamable HTTP transport requires the client to accept both
        # application/json (for simple responses) and text/event-stream (for
        # streaming / SSE responses).
        'Accept': 'application/json, text/event-stream',
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    return headers


# ---------------------------------------------------------------------------
# Low-level MCP JSON-RPC helpers
# ---------------------------------------------------------------------------

def _mcp_request(method: str, params: Optional[Dict[str, Any]] = None,
                 timeout: int = 60) -> Dict[str, Any]:
    '''
    Send a JSON-RPC 2.0 request to the Cornelis MCP server.

    The response may arrive as plain JSON or as a Server-Sent Events stream.
    In the SSE case we extract the first ``data:`` line that contains valid JSON.

    Input:
        method:  JSON-RPC method name (e.g. "tools/list", "tools/call").
        params:  Optional parameters dict.
        timeout: HTTP timeout in seconds.

    Output:
        Parsed JSON-RPC result dict.

    Raises:
        RuntimeError on transport or protocol errors.
    '''
    if requests is None:
        raise RuntimeError('requests library is required for MCP tools')

    url = _get_mcp_url()
    payload: Dict[str, Any] = {
        'jsonrpc': '2.0',
        'id': 1,
        'method': method,
    }
    if params:
        payload['params'] = params

    log.debug(f'MCP request: {method} -> {url}')

    try:
        resp = requests.post(url, json=payload, headers=_mcp_headers(), timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f'MCP HTTP error: {e}') from e

    content_type = resp.headers.get('Content-Type', '')

    # --- Plain JSON response ------------------------------------------------
    if 'application/json' in content_type:
        data = resp.json()
        if 'error' in data:
            err = data['error']
            raise RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")
        return data.get('result', data)

    # --- SSE (text/event-stream) response -----------------------------------
    # Each event is on a line prefixed with "data: ".  We look for the first
    # line that parses as valid JSON containing a "result" key.
    if 'text/event-stream' in content_type:
        for line in resp.text.splitlines():
            if not line.startswith('data:'):
                continue
            json_str = line[len('data:'):].strip()
            if not json_str:
                continue
            try:
                data = json.loads(json_str)
                if 'error' in data:
                    err = data['error']
                    raise RuntimeError(
                        f"MCP error {err.get('code')}: {err.get('message')}"
                    )
                return data.get('result', data)
            except json.JSONDecodeError:
                continue
        raise RuntimeError('MCP SSE response contained no valid JSON data lines')

    # --- Unknown content type -----------------------------------------------
    raise RuntimeError(f'Unexpected MCP response Content-Type: {content_type}')


# ---------------------------------------------------------------------------
# Cached tool catalogue
# ---------------------------------------------------------------------------

_tool_cache: Optional[List[Dict[str, Any]]] = None


def _get_tool_catalogue(force_refresh: bool = False) -> List[Dict[str, Any]]:
    '''
    Fetch and cache the list of tools from the MCP server.

    Output:
        List of tool descriptors, each with at least "name" and "description".
    '''
    global _tool_cache
    if _tool_cache is not None and not force_refresh:
        return _tool_cache

    result = _mcp_request('tools/list')
    # The MCP spec returns {"tools": [...]}.
    tools_list = result.get('tools', []) if isinstance(result, dict) else []
    _tool_cache = tools_list
    log.info(f'MCP tool discovery: found {len(tools_list)} tools')
    for t in tools_list:
        log.debug(f"  MCP tool: {t.get('name')} — {t.get('description', '')[:80]}")
    return tools_list


# ---------------------------------------------------------------------------
# Public @tool functions
# ---------------------------------------------------------------------------

@tool(
    name='mcp_discover_tools',
    description='List all tools available on the Cornelis MCP server',
)
def mcp_discover_tools(force_refresh: bool = False) -> ToolResult:
    '''
    Discover tools exposed by the Cornelis MCP server.

    Input:
        force_refresh: If True, bypass the cache and re-query the server.

    Output:
        ToolResult with a list of tool descriptors (name, description, inputSchema).
    '''
    try:
        tools_list = _get_tool_catalogue(force_refresh=force_refresh)
        return ToolResult.success({
            'tool_count': len(tools_list),
            'tools': tools_list,
        })
    except Exception as e:
        log.error(f'MCP tool discovery failed: {e}')
        return ToolResult.failure(f'MCP tool discovery failed: {e}')


@tool(
    name='mcp_call_tool',
    description='Call a specific tool on the Cornelis MCP server by name',
)
def mcp_call_tool(
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
) -> ToolResult:
    '''
    Invoke a tool on the Cornelis MCP server.

    Input:
        tool_name: Name of the MCP tool to call (as returned by mcp_discover_tools).
        arguments: Dictionary of arguments to pass to the tool.
        timeout:   HTTP timeout in seconds.

    Output:
        ToolResult with the tool's response data.
    '''
    log.info(f'MCP tool call: {tool_name}')
    log.debug(f'  arguments: {arguments}')

    params: Dict[str, Any] = {'name': tool_name}
    if arguments:
        params['arguments'] = arguments

    try:
        result = _mcp_request('tools/call', params=params, timeout=timeout)
        return ToolResult.success(result)
    except Exception as e:
        log.error(f'MCP tool call failed ({tool_name}): {e}')
        return ToolResult.failure(f'MCP tool call failed ({tool_name}): {e}')


@tool(
    name='mcp_search',
    description='Search for information using the Cornelis MCP server (convenience wrapper)',
)
def mcp_search(query: str, tool_hint: Optional[str] = None) -> ToolResult:
    '''
    High-level search that tries to find the best MCP tool for a query.

    Strategy:
      1. If tool_hint is provided, call that tool directly.
      2. Otherwise, discover available tools and look for one whose name
         contains "search", "query", or "find".
      3. Fall back to calling the first available tool with the query.

    Input:
        query:     The search query string.
        tool_hint: Optional explicit MCP tool name to use.

    Output:
        ToolResult with search results.
    '''
    try:
        # If the caller knows which tool to use, call it directly
        if tool_hint:
            return mcp_call_tool(tool_name=tool_hint, arguments={'query': query})

        # Discover tools and find a search-like tool
        catalogue = _get_tool_catalogue()
        search_tools = [
            t for t in catalogue
            if any(kw in t.get('name', '').lower()
                   for kw in ('search', 'query', 'find', 'lookup'))
        ]

        if search_tools:
            chosen = search_tools[0]
            log.info(f"mcp_search: using tool '{chosen['name']}' for query")
            return mcp_call_tool(
                tool_name=chosen['name'],
                arguments={'query': query},
            )

        # No search tool found — report available tools
        tool_names = [t.get('name', '?') for t in catalogue]
        return ToolResult.failure(
            f'No search-like MCP tool found. Available tools: {tool_names}'
        )

    except Exception as e:
        log.error(f'mcp_search failed: {e}')
        return ToolResult.failure(f'mcp_search failed: {e}')


# ---------------------------------------------------------------------------
# BaseTool collection (for agent registration)
# ---------------------------------------------------------------------------

class MCPTools(BaseTool):
    '''Collection of Cornelis MCP tools for agent use.'''

    @tool(description='Discover tools on the Cornelis MCP server')
    def discover_tools(self, force_refresh: bool = False) -> ToolResult:
        return mcp_discover_tools(force_refresh=force_refresh)

    @tool(description='Call a tool on the Cornelis MCP server')
    def call_tool(self, tool_name: str,
                  arguments: Optional[Dict[str, Any]] = None) -> ToolResult:
        return mcp_call_tool(tool_name=tool_name, arguments=arguments)

    @tool(description='Search using the Cornelis MCP server')
    def search(self, query: str, tool_hint: Optional[str] = None) -> ToolResult:
        return mcp_search(query=query, tool_hint=tool_hint)
