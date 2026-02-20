##########################################################################################
#
# Module: tools/web_search_tools.py
#
# Description: Web search tools for the Feature Planning Agent pipeline.
#              Tries the Cornelis MCP server first (looking for a web-search tool),
#              then falls back to a direct API call if configured.
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
    log.warning('requests library not available; web search tools will not function')

try:
    from tools.base import tool, ToolResult, BaseTool
except ImportError:
    log.warning('tools.base not available; web_search_tools will not register @tool decorators')

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

# Lazy import — mcp_tools may not be available in all environments
_mcp_tools = None


def _get_mcp_tools():
    '''Lazy-load mcp_tools to avoid circular imports.'''
    global _mcp_tools
    if _mcp_tools is None:
        try:
            from tools import mcp_tools as _mt
            _mcp_tools = _mt
        except ImportError:
            _mcp_tools = False  # type: ignore[assignment]
    return _mcp_tools if _mcp_tools is not False else None


# ---------------------------------------------------------------------------
# MCP-backed web search
# ---------------------------------------------------------------------------

def _search_via_mcp(query: str, max_results: int = 10) -> Optional[Dict[str, Any]]:
    '''
    Attempt to perform a web search through the Cornelis MCP server.

    Looks for MCP tools whose name contains "web", "search", "brave", or
    "tavily".  Returns None if no suitable tool is found or the MCP server
    is unreachable.
    '''
    mt = _get_mcp_tools()
    if mt is None:
        return None

    try:
        catalogue = mt._get_tool_catalogue()
    except Exception as e:
        log.debug(f'MCP catalogue unavailable for web search: {e}')
        return None

    # Find a web-search-like tool
    web_keywords = ('web_search', 'brave_search', 'tavily_search', 'search_web',
                    'internet_search', 'web_query')
    search_tool = None
    for t in catalogue:
        name = t.get('name', '').lower()
        if any(kw in name for kw in web_keywords):
            search_tool = t
            break

    if search_tool is None:
        log.debug('No web search tool found on MCP server')
        return None

    log.info(f"web_search: using MCP tool '{search_tool['name']}'")
    result = mt.mcp_call_tool(
        tool_name=search_tool['name'],
        arguments={'query': query, 'max_results': max_results},
    )

    # ToolResult has .data on success
    if hasattr(result, 'is_success') and result.is_success:
        return result.data
    if isinstance(result, dict) and 'error' not in result:
        return result
    return None


# ---------------------------------------------------------------------------
# Direct API fallback (Brave Search)
# ---------------------------------------------------------------------------

def _search_via_brave(query: str, max_results: int = 10) -> Optional[Dict[str, Any]]:
    '''
    Perform a web search using the Brave Search API directly.

    Requires BRAVE_SEARCH_API_KEY in the environment.
    '''
    if requests is None:
        return None

    api_key = os.environ.get('BRAVE_SEARCH_API_KEY', '')
    if not api_key:
        log.debug('BRAVE_SEARCH_API_KEY not set; Brave Search fallback unavailable')
        return None

    url = 'https://api.search.brave.com/res/v1/web/search'
    headers = {
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip',
        'X-Subscription-Token': api_key,
    }
    params = {
        'q': query,
        'count': min(max_results, 20),
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Normalize Brave response into a common format
        results = []
        for item in data.get('web', {}).get('results', []):
            results.append({
                'title': item.get('title', ''),
                'url': item.get('url', ''),
                'snippet': item.get('description', ''),
            })

        return {
            'query': query,
            'result_count': len(results),
            'results': results,
            'source': 'brave_search',
        }

    except Exception as e:
        log.warning(f'Brave Search API error: {e}')
        return None


# ---------------------------------------------------------------------------
# Direct API fallback (Tavily Search)
# ---------------------------------------------------------------------------

def _search_via_tavily(query: str, max_results: int = 10) -> Optional[Dict[str, Any]]:
    '''
    Perform a web search using the Tavily Search API directly.

    Requires TAVILY_API_KEY in the environment.
    '''
    if requests is None:
        return None

    api_key = os.environ.get('TAVILY_API_KEY', '')
    if not api_key:
        log.debug('TAVILY_API_KEY not set; Tavily Search fallback unavailable')
        return None

    url = 'https://api.tavily.com/search'
    payload = {
        'api_key': api_key,
        'query': query,
        'max_results': min(max_results, 20),
        'include_answer': True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get('results', []):
            results.append({
                'title': item.get('title', ''),
                'url': item.get('url', ''),
                'snippet': item.get('content', ''),
            })

        return {
            'query': query,
            'result_count': len(results),
            'results': results,
            'answer': data.get('answer', ''),
            'source': 'tavily_search',
        }

    except Exception as e:
        log.warning(f'Tavily Search API error: {e}')
        return None


# ---------------------------------------------------------------------------
# Public @tool functions
# ---------------------------------------------------------------------------

@tool(
    name='web_search',
    description='Search the web for information about a topic. '
                'Tries Cornelis MCP, then Brave Search, then Tavily as fallbacks.',
)
def web_search(query: str, max_results: int = 10) -> ToolResult:
    '''
    Search the web for information.

    Tries multiple backends in order:
      1. Cornelis MCP server (if a web search tool is available)
      2. Brave Search API (if BRAVE_SEARCH_API_KEY is set)
      3. Tavily Search API (if TAVILY_API_KEY is set)

    Input:
        query:       The search query string.
        max_results: Maximum number of results to return (default 10).

    Output:
        ToolResult with search results including title, url, and snippet.
    '''
    log.info(f'web_search: "{query}" (max_results={max_results})')

    # Strategy 1: MCP
    result = _search_via_mcp(query, max_results)
    if result is not None:
        log.info('web_search: results from MCP')
        return ToolResult.success(result)

    # Strategy 2: Brave Search
    result = _search_via_brave(query, max_results)
    if result is not None:
        log.info('web_search: results from Brave Search')
        return ToolResult.success(result)

    # Strategy 3: Tavily Search
    result = _search_via_tavily(query, max_results)
    if result is not None:
        log.info('web_search: results from Tavily Search')
        return ToolResult.success(result)

    # All backends failed
    return ToolResult.failure(
        'Web search unavailable. No MCP web search tool found, and neither '
        'BRAVE_SEARCH_API_KEY nor TAVILY_API_KEY is set in the environment. '
        'Set one of these to enable web search.'
    )


@tool(
    name='web_search_multi',
    description='Run multiple web searches and aggregate results',
)
def web_search_multi(
    queries: List[str],
    max_results_per_query: int = 5,
) -> ToolResult:
    '''
    Run multiple web searches and return aggregated results.

    Useful for researching a topic from multiple angles (e.g. searching for
    specs, implementations, and tutorials separately).

    Input:
        queries:                List of search query strings.
        max_results_per_query:  Max results per individual query.

    Output:
        ToolResult with results grouped by query.
    '''
    log.info(f'web_search_multi: {len(queries)} queries')

    all_results: Dict[str, Any] = {
        'query_count': len(queries),
        'results_by_query': {},
        'total_results': 0,
        'errors': [],
    }

    for query in queries:
        result = web_search(query, max_results=max_results_per_query)

        if hasattr(result, 'is_success') and result.is_success:
            data = result.data
            all_results['results_by_query'][query] = data
            all_results['total_results'] += data.get('result_count', 0)
        elif isinstance(result, dict) and 'error' not in result:
            all_results['results_by_query'][query] = result
        else:
            error_msg = getattr(result, 'error', str(result))
            all_results['errors'].append({'query': query, 'error': error_msg})

    return ToolResult.success(all_results)


# ---------------------------------------------------------------------------
# BaseTool collection (for agent registration)
# ---------------------------------------------------------------------------

class WebSearchTools(BaseTool):
    '''Collection of web search tools for agent use.'''

    @tool(description='Search the web for information')
    def search(self, query: str, max_results: int = 10) -> ToolResult:
        return web_search(query=query, max_results=max_results)

    @tool(description='Run multiple web searches and aggregate results')
    def search_multi(self, queries: List[str],
                     max_results_per_query: int = 5) -> ToolResult:
        return web_search_multi(
            queries=queries,
            max_results_per_query=max_results_per_query,
        )
