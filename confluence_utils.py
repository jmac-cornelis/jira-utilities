##########################################################################################
#
# Script name: confluence_utils.py
#
# Description: Confluence utilities for interacting with Cornelis Networks'
#              Atlassian Confluence instance.
#
# Author: Cornelis Networks
#
# Credentials:
#   This script uses Atlassian API tokens for authentication. To set up:
#   1. Generate an API token at: https://id.atlassian.com/manage-profile/security/api-tokens
#   2. Set environment variables:
#      export CONFLUENCE_EMAIL="your.email@cornelisnetworks.com"
#      export CONFLUENCE_API_TOKEN="your_api_token_here"
#
#   Compatibility fallbacks:
#      - CONFLUENCE_EMAIL falls back to JIRA_EMAIL
#      - CONFLUENCE_API_TOKEN falls back to JIRA_API_TOKEN
#      - CONFLUENCE_URL falls back to JIRA_URL + "/wiki"
#
#   Space selection:
#      - CONFLUENCE_SPACE_ID or CONFLUENCE_SPACE_KEY can be used as defaults
#      - --space overrides the environment for a single command
#
#   NEVER commit credentials to version control.
#
##########################################################################################

import argparse
import html
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import requests
from dotenv import load_dotenv
import yaml

# Load environment variables from the default .env if present.
#
# CLI users can override this at runtime with --env; see handle_args().
load_dotenv(override=False)

# ****************************************************************************************
# Global data and configuration
# ****************************************************************************************

DEFAULT_SITE_URL = 'https://cornelisnetworks.atlassian.net'

# Logging config
log = logging.getLogger(os.path.basename(sys.argv[0]))
log.setLevel(logging.DEBUG)

# File handler for logging
fh = logging.FileHandler('confluence_utils.log', mode='w')
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)-15s [%(funcName)25s:%(lineno)-5s] %(levelname)-8s %(message)s'
)
fh.setFormatter(formatter)
log.addHandler(fh)

# Output control - set by handle_args()
_quiet_mode = False

# Cached connection object
_connection: Optional['ConfluenceConnection'] = None

__all__ = [
    # Connection
    'connect_to_confluence', 'get_connection', 'reset_connection',
    'get_confluence_credentials', 'get_confluence_url',
    # Space helpers
    'resolve_space_id', 'resolve_space_key', 'resolve_parent_id',
    # Page operations
    'search_pages', 'get_page', 'create_page', 'update_page',
    'append_page', 'update_page_section',
    'list_page_children', 'build_page_tree', 'export_page_to_markdown',
    # Content helpers
    'read_markdown_file', 'parse_front_matter', 'load_markdown_document',
    'markdown_to_storage', 'storage_to_markdown',
    # Display
    'output',
    # Exceptions
    'Error', 'ConfluenceConnectionError', 'ConfluenceCredentialsError',
    'ConfluencePageError',
]


HEADING_RE = re.compile(r'<h([1-6])>(.*?)</h\1>', re.IGNORECASE | re.DOTALL)
LOCAL_LINK_RE = re.compile(r'(?<!\!)\[([^\]]+)\]\(([^)]+)\)')
IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')


@dataclass
class MarkdownDocument:
    '''
    Parsed Markdown source plus resolved publish metadata.
    '''
    input_file: str
    body_markdown: str
    body_storage: str
    front_matter: dict[str, Any]
    attachments: list[dict[str, str]]
    labels: list[str]
    title: Optional[str] = None
    space: Optional[str] = None
    parent_id: Optional[str] = None
    version_message: Optional[str] = None


def get_confluence_url() -> str:
    '''
    Return the Confluence base URL, ending in ``/wiki``.
    '''
    configured = os.getenv('CONFLUENCE_URL')
    if configured:
        return configured.rstrip('/')

    jira_url = os.getenv('JIRA_URL', DEFAULT_SITE_URL).rstrip('/')
    if jira_url.endswith('/wiki'):
        return jira_url
    return f'{jira_url}/wiki'


def get_site_url() -> str:
    '''
    Return the Atlassian site root without the ``/wiki`` path suffix.
    '''
    confluence_url = get_confluence_url()
    if confluence_url.endswith('/wiki'):
        return confluence_url[:-5]
    return confluence_url


log.debug('Global data and configuration for this script...')
log.debug(f'CONFLUENCE_URL: {get_confluence_url()}')


def output(message=''):
    '''
    Print user-facing output, respecting quiet mode.
    Always logs to file regardless of quiet mode.
    '''
    if message:
        record = logging.LogRecord(
            name=log.name,
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=f'OUTPUT: {message}',
            args=(),
            exc_info=None,
            func='output',
        )
        fh.emit(record)

    if not _quiet_mode:
        print(message)


class Error(Exception):
    '''Base exception for confluence_utils errors.'''


class ConfluenceConnectionError(Error):
    '''Raised when Confluence cannot be reached or authenticated.'''


class ConfluenceCredentialsError(Error):
    '''Raised when Confluence credentials are missing.'''


class ConfluencePageError(Error):
    '''Raised when a page operation fails.'''


@dataclass
class ConfluenceConnection:
    '''
    Lightweight requests-based Confluence connection wrapper.
    '''
    base_url: str
    email: str
    api_token: str

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip('/')
        self.site_url = self.base_url[:-5] if self.base_url.endswith('/wiki') else self.base_url
        self.session = requests.Session()
        self.session.auth = (self.email, self.api_token)
        self.session.headers.update({'Accept': 'application/json'})

    def request(self, method: str, path: str, retries: int = 3, **kwargs) -> requests.Response:
        '''
        Execute an authenticated request against the Confluence API.
        '''
        url = path if path.startswith('http') else f'{self.base_url}{path}'
        timeout = kwargs.pop('timeout', 30)

        for attempt in range(retries + 1):
            try:
                response = self.session.request(method, url, timeout=timeout, **kwargs)
            except requests.RequestException as exc:
                raise ConfluenceConnectionError(f'Confluence request failed: {exc}') from exc

            if response.status_code == 429 and attempt < retries:
                retry_after = int(response.headers.get('Retry-After', 1))
                log.warning(
                    f'Rate limited by Confluence. Waiting {retry_after}s '
                    f'(retry {attempt + 1}/{retries})...'
                )
                time.sleep(retry_after)
                continue

            if response.status_code >= 400:
                raise ConfluencePageError(
                    f'Confluence API error: {response.status_code} - '
                    f'{_response_message(response)}'
                )

            return response

        raise ConfluenceConnectionError('Confluence request failed after retries')


def get_confluence_credentials() -> tuple[str, str]:
    '''
    Return Confluence credentials from environment variables.
    '''
    email = os.getenv('CONFLUENCE_EMAIL') or os.getenv('JIRA_EMAIL')
    api_token = os.getenv('CONFLUENCE_API_TOKEN') or os.getenv('JIRA_API_TOKEN')

    if not email:
        raise ConfluenceCredentialsError(
            'Confluence email not configured. Set CONFLUENCE_EMAIL or JIRA_EMAIL.'
        )
    if not api_token:
        raise ConfluenceCredentialsError(
            'Confluence API token not configured. Set CONFLUENCE_API_TOKEN or JIRA_API_TOKEN.'
        )

    return email, api_token


def connect_to_confluence() -> ConfluenceConnection:
    '''
    Create a Confluence connection wrapper.
    '''
    email, api_token = get_confluence_credentials()
    return ConfluenceConnection(
        base_url=get_confluence_url(),
        email=email,
        api_token=api_token,
    )


def get_connection() -> ConfluenceConnection:
    '''
    Get or create the cached Confluence connection.
    '''
    global _connection

    if _connection is None:
        _connection = connect_to_confluence()

    return _connection


def reset_connection() -> None:
    '''
    Reset the cached Confluence connection.
    '''
    global _connection
    _connection = None


def _response_message(response: requests.Response) -> str:
    '''
    Extract the most useful error message from a Confluence response.
    '''
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or 'Unknown error'

    if isinstance(payload, dict):
        for key in ('message', 'error', 'detail'):
            if payload.get(key):
                return str(payload[key])
        if payload.get('errors'):
            return json.dumps(payload['errors'])

    return response.text.strip() or f'HTTP {response.status_code}'


def _json(response: requests.Response) -> dict[str, Any]:
    '''
    Return a JSON payload, defaulting to an empty dict for blank responses.
    '''
    if not response.text:
        return {}
    return response.json()


def _is_numeric_id(value: str) -> bool:
    return bool(re.fullmatch(r'\d+', value.strip()))


def _default_space_value() -> Optional[str]:
    return os.getenv('CONFLUENCE_SPACE_ID') or os.getenv('CONFLUENCE_SPACE_KEY')


def resolve_space_id(confluence: ConfluenceConnection, space: Optional[str] = None) -> str:
    '''
    Resolve a Confluence space key or ID into a numeric space ID string.
    '''
    raw_value = (space or _default_space_value() or '').strip()
    if not raw_value:
        raise ConfluencePageError(
            'A Confluence space is required. Use --space or set '
            'CONFLUENCE_SPACE_ID / CONFLUENCE_SPACE_KEY.'
        )

    if _is_numeric_id(raw_value):
        return raw_value

    response = confluence.request(
        'GET',
        '/api/v2/spaces',
        params={'keys': raw_value, 'limit': 1},
    )
    payload = _json(response)
    spaces = payload.get('results', [])
    if not spaces:
        raise ConfluencePageError(f'Confluence space "{raw_value}" not found.')

    return str(spaces[0].get('id'))


def resolve_space_key(confluence: ConfluenceConnection, space: Optional[str] = None) -> Optional[str]:
    '''
    Resolve a Confluence space key or ID into a space key string.
    '''
    raw_value = (space or _default_space_value() or '').strip()
    if not raw_value:
        return None

    if not _is_numeric_id(raw_value):
        return raw_value

    response = confluence.request('GET', f'/api/v2/spaces/{raw_value}')
    payload = _json(response)
    key = payload.get('key')
    if not key:
        raise ConfluencePageError(f'Confluence space ID "{raw_value}" did not return a space key.')

    return str(key)


def resolve_parent_id(
    confluence: ConfluenceConnection,
    parent: Optional[str] = None,
    space: Optional[str] = None,
) -> Optional[str]:
    '''
    Resolve a parent page ID or exact title into a page ID string.
    '''
    raw_value = (parent or '').strip()
    if not raw_value:
        return None
    if _is_numeric_id(raw_value):
        return raw_value
    return str(_resolve_page_identifier(confluence, raw_value, space=space).get('id') or '')


def _dedupe_string_list(values: Any) -> list[str]:
    '''
    Normalize a scalar or list-like value into a unique ordered string list.
    '''
    if values is None:
        return []
    if isinstance(values, str):
        items = [values]
    elif isinstance(values, (list, tuple, set)):
        items = list(values)
    else:
        items = [str(values)]

    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def parse_front_matter(markdown_text: str) -> tuple[dict[str, Any], str]:
    '''
    Parse YAML front matter from the beginning of a Markdown document.
    '''
    normalized = markdown_text.replace('\r\n', '\n').replace('\r', '\n')
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n?', normalized, re.DOTALL)
    if not match:
        return {}, normalized

    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ConfluencePageError(f'Invalid Markdown front matter: {exc}') from exc

    if not isinstance(data, dict):
        raise ConfluencePageError('Markdown front matter must be a YAML mapping/object.')

    return data, normalized[match.end():]


def _is_remote_target(target: str) -> bool:
    '''
    Return True when the link target points to a remote URL.
    '''
    lowered = target.lower()
    return lowered.startswith('http://') or lowered.startswith('https://')


def _normalize_markdown_target(target: str) -> str:
    '''
    Clean up Markdown link/image targets.
    '''
    normalized = target.strip()
    if normalized.startswith('<') and normalized.endswith('>'):
        normalized = normalized[1:-1].strip()
    return normalized


def _attachment_filename(target: str) -> str:
    '''
    Derive a Confluence attachment filename from a path or URL.
    '''
    if _is_remote_target(target):
        parsed = urlparse(target)
        return unquote(Path(parsed.path).name or 'image')
    return Path(target).name


def _add_attachment(
    attachments: list[dict[str, str]],
    source_path: str,
    filename: Optional[str] = None,
) -> None:
    '''
    Add an attachment source, rejecting conflicting duplicate filenames.
    '''
    resolved = str(Path(source_path).resolve())
    file_name = filename or Path(resolved).name

    for existing in attachments:
        if existing['filename'] != file_name:
            continue
        if existing['source_path'] != resolved:
            raise ConfluencePageError(
                f'Attachment filename collision for "{file_name}". '
                'Use unique filenames for uploaded attachments.'
            )
        return

    attachments.append({
        'source_path': resolved,
        'filename': file_name,
    })


def _image_fragment(target: str) -> str:
    '''
    Build a Confluence storage fragment for an image target.
    '''
    if _is_remote_target(target):
        return (
            '<ac:image>'
            f'<ri:url ri:value="{html.escape(target, quote=True)}" />'
            '</ac:image>'
        )

    return (
        '<ac:image>'
        f'<ri:attachment ri:filename="{html.escape(_attachment_filename(target), quote=True)}" />'
        '</ac:image>'
    )


def _attachment_link_fragment(label: str, target: str) -> str:
    '''
    Build a Confluence storage fragment for a local attachment link.
    '''
    if _is_remote_target(target):
        return f'<a href="{html.escape(target, quote=True)}">{html.escape(label)}</a>'

    return (
        '<ac:link>'
        f'<ri:attachment ri:filename="{html.escape(_attachment_filename(target), quote=True)}" />'
        f'<ac:plain-text-link-body><![CDATA[{label}]]></ac:plain-text-link-body>'
        '</ac:link>'
    )


def _rewrite_markdown_assets(
    markdown_text: str,
    base_dir: Path,
) -> tuple[str, dict[str, str], list[dict[str, str]]]:
    '''
    Replace Markdown image/local-link syntax with Confluence storage fragments.
    '''
    extra_fragments: dict[str, str] = {}
    attachments: list[dict[str, str]] = []

    def _token(prefix: str, index: int) -> str:
        return f'@@CF{prefix}{index}@@'

    def _replace_image(match: re.Match[str]) -> str:
        target = _normalize_markdown_target(match.group(2))
        if not _is_remote_target(target):
            resolved = base_dir / target
            if not resolved.exists():
                raise FileNotFoundError(f'Attachment image not found: {resolved}')
            _add_attachment(attachments, str(resolved))

        token = _token('IMAGE', len(extra_fragments))
        extra_fragments[token] = _image_fragment(target)
        return token

    rewritten = IMAGE_RE.sub(_replace_image, markdown_text)

    def _replace_link(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        target = _normalize_markdown_target(match.group(2))

        if _is_remote_target(target) or target.startswith('#'):
            return match.group(0)

        resolved = base_dir / target
        if not resolved.exists():
            return match.group(0)

        _add_attachment(attachments, str(resolved))
        token = _token('ATTACH', len(extra_fragments))
        extra_fragments[token] = _attachment_link_fragment(label, target)
        return token

    rewritten = LOCAL_LINK_RE.sub(_replace_link, rewritten)
    return rewritten, extra_fragments, attachments


def load_markdown_document(input_file: str) -> MarkdownDocument:
    '''
    Load a Markdown file, parse front matter, and prepare Confluence storage XHTML.
    '''
    raw_markdown = read_markdown_file(input_file)
    front_matter, body_markdown = parse_front_matter(raw_markdown)
    base_dir = Path(input_file).resolve().parent

    rewritten_markdown, extra_fragments, attachments = _rewrite_markdown_assets(
        body_markdown,
        base_dir,
    )

    for attachment in _dedupe_string_list(front_matter.get('attachments')):
        resolved = base_dir / attachment
        if not resolved.exists():
            raise FileNotFoundError(f'Front matter attachment not found: {resolved}')
        _add_attachment(attachments, str(resolved))

    return MarkdownDocument(
        input_file=input_file,
        body_markdown=rewritten_markdown,
        body_storage=markdown_to_storage(rewritten_markdown, extra_fragments=extra_fragments),
        front_matter=front_matter,
        attachments=attachments,
        labels=_dedupe_string_list(front_matter.get('labels')),
        title=front_matter.get('title'),
        space=front_matter.get('space'),
        parent_id=str(front_matter.get('parent_id') or front_matter.get('parentId') or front_matter.get('parent') or '').strip() or None,
        version_message=(
            str(front_matter.get('version_message') or front_matter.get('versionMessage') or '').strip()
            or None
        ),
    )


def _escape_cql_string(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _page_url(
    confluence: ConfluenceConnection,
    page_id: str,
    webui_path: Optional[str] = None,
) -> str:
    '''
    Build a user-facing page URL.
    '''
    if webui_path:
        if webui_path.startswith('http'):
            return webui_path
        if webui_path.startswith('/wiki/'):
            return f'{confluence.site_url}{webui_path}'
        if webui_path.startswith('/'):
            return f'{confluence.base_url}{webui_path}'
        return f'{confluence.base_url}/{webui_path.lstrip("/")}'

    return f'{confluence.base_url}/pages/viewpage.action?pageId={page_id}'


def _normalize_page_search_result(
    confluence: ConfluenceConnection,
    result: dict[str, Any],
) -> dict[str, Any]:
    '''
    Normalize a page search result into a small serialisable payload.
    '''
    page = result.get('content') if isinstance(result.get('content'), dict) else result
    links = page.get('_links') or result.get('_links') or {}
    page_id = str(page.get('id') or result.get('id') or '')
    title = page.get('title') or result.get('title') or ''
    space = page.get('space') or result.get('space') or {}
    url = _page_url(confluence, page_id, links.get('webui'))

    return {
        'id': page_id,
        'page_id': page_id,
        'title': title,
        'link': url,
        'url': url,
        'space_key': space.get('key', ''),
        'space_name': space.get('name', ''),
    }


def _normalize_page_entity(
    confluence: ConfluenceConnection,
    page: dict[str, Any],
) -> dict[str, Any]:
    '''
    Normalize a v2 page payload into a tool-friendly payload.
    '''
    links = page.get('_links') or {}
    page_id = str(page.get('id') or '')
    url = _page_url(confluence, page_id, links.get('webui'))

    return {
        'id': page_id,
        'page_id': page_id,
        'title': page.get('title', ''),
        'status': page.get('status', ''),
        'space_id': str(page.get('spaceId') or ''),
        'link': url,
        'url': url,
        'version': (page.get('version') or {}).get('number'),
    }


def _print_page_results(pages: list[dict[str, Any]], heading: str) -> None:
    '''
    Print a simple table of page results.
    '''
    output('')
    output('=' * 140)
    output(heading)
    output('=' * 140)
    output(f'{"Page ID":<14} {"Title":<54} {"Link":<70}')
    output('-' * 140)

    for page in pages:
        title = page.get('title', '') or ''
        link = page.get('link', '') or ''
        if len(title) > 52:
            title = title[:52] + '..'
        output(f'{page.get("page_id", ""):<14} {title:<54} {link:<70}')

    output('=' * 140)
    output(f'Total: {len(pages)} page(s)')
    output('')


def _collect_paginated_results(
    confluence: ConfluenceConnection,
    path: str,
    params: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    '''
    Collect paginated Confluence ``results`` arrays by following ``_links.next``.
    '''
    results: list[dict[str, Any]] = []
    current_path: Optional[str] = path
    current_params = params

    while current_path:
        response = confluence.request('GET', current_path, params=current_params)
        payload = _json(response)
        results.extend(payload.get('results', []))

        next_link = (payload.get('_links') or {}).get('next')
        current_path = next_link if next_link else None
        current_params = None

    return results


def search_pages(
    confluence: ConfluenceConnection,
    pattern: str,
    limit: int = 25,
    space: Optional[str] = None,
) -> list[dict[str, Any]]:
    '''
    Search Confluence pages by title pattern using CQL search.
    '''
    log.debug(f'search_pages(pattern={pattern}, limit={limit}, space={space})')

    escaped = _escape_cql_string(pattern)
    cql = f'type = page AND title ~ "{escaped}"'
    space_key = resolve_space_key(confluence, space)
    if space_key:
        cql += f' AND space = "{_escape_cql_string(space_key)}"'
    response = confluence.request(
        'GET',
        '/rest/api/content/search',
        params={
            'cql': cql,
            'limit': limit,
            'expand': 'space',
        },
    )
    payload = _json(response)
    results = payload.get('results', [])

    pages = [_normalize_page_search_result(confluence, result) for result in results]

    if pages:
        _print_page_results(pages, f'Confluence Search Results: {pattern}')
    else:
        output('')
        output(f'No Confluence pages found matching: {pattern}')
        output('')

    return pages


def _find_pages_by_exact_title(
    confluence: ConfluenceConnection,
    title: str,
    space: Optional[str] = None,
) -> list[dict[str, Any]]:
    '''
    Find exact-title matches, optionally scoped to a Confluence space.
    '''
    cql = f'type = page AND title = "{_escape_cql_string(title)}"'
    space_key = resolve_space_key(confluence, space)
    if space_key:
        cql += f' AND space = "{_escape_cql_string(space_key)}"'

    response = confluence.request(
        'GET',
        '/rest/api/content/search',
        params={'cql': cql, 'limit': 10, 'expand': 'space'},
    )
    payload = _json(response)

    matches = []
    for result in payload.get('results', []):
        normalized = _normalize_page_search_result(confluence, result)
        if normalized['title'].casefold() == title.casefold():
            matches.append(normalized)

    return matches


def _get_page_by_id(confluence: ConfluenceConnection, page_id: str) -> dict[str, Any]:
    '''
    Fetch a page payload from the v2 page endpoint.
    '''
    response = confluence.request(
        'GET',
        f'/api/v2/pages/{page_id}',
        params={'body-format': 'storage', 'include-labels': 'true'},
    )
    return _json(response)


def _extract_storage_body(page: dict[str, Any]) -> str:
    '''
    Extract the storage-format page body from a v2 page payload.
    '''
    body = page.get('body') or {}
    if isinstance(body, dict):
        if isinstance(body.get('storage'), dict):
            return str(body['storage'].get('value') or '')
        if body.get('representation') == 'storage':
            return str(body.get('value') or '')
        if 'value' in body:
            return str(body.get('value') or '')
    return ''


def _extract_labels(page: dict[str, Any]) -> list[str]:
    '''
    Extract label names from a page payload when present.
    '''
    labels = page.get('labels')
    if isinstance(labels, dict):
        return [str(item.get('name')) for item in labels.get('results', []) if item.get('name')]
    if isinstance(labels, list):
        return [str(item.get('name')) for item in labels if isinstance(item, dict) and item.get('name')]
    return []


def _resolve_page_identifier(
    confluence: ConfluenceConnection,
    page_id_or_title: str,
    space: Optional[str] = None,
) -> dict[str, Any]:
    '''
    Resolve a page ID or title into a current page payload.
    '''
    raw_value = page_id_or_title.strip()
    if _is_numeric_id(raw_value):
        return _get_page_by_id(confluence, raw_value)

    matches = _find_pages_by_exact_title(confluence, raw_value, space=space)
    if not matches:
        raise ConfluencePageError(f'No Confluence page found with title "{raw_value}".')

    if len(matches) > 1:
        options = ', '.join(f'{page["page_id"]}:{page["title"]}' for page in matches)
        raise ConfluencePageError(
            f'Multiple Confluence pages matched "{raw_value}". '
            f'Use the page ID instead. Matches: {options}'
        )

    return _get_page_by_id(confluence, matches[0]['page_id'])


def get_page(
    confluence: ConfluenceConnection,
    page_id_or_title: str,
    space: Optional[str] = None,
    include_body: bool = False,
) -> dict[str, Any]:
    '''
    Get page metadata and optionally the storage/Markdown body.
    '''
    page = _resolve_page_identifier(confluence, page_id_or_title, space=space)
    result = _normalize_page_entity(confluence, page)
    result['labels'] = _extract_labels(page)

    if include_body:
        storage = _extract_storage_body(page)
        result['body_storage'] = storage
        result['body_markdown'] = storage_to_markdown(storage)

    return result


def _print_page_detail(page: dict[str, Any], include_body: bool = False) -> None:
    '''
    Print a detailed page summary.
    '''
    output('')
    output('=' * 100)
    output(f'Confluence Page: {page.get("title", "")}')
    output('=' * 100)
    output(f'  Page ID: {page.get("page_id", "")}')
    output(f'  Status:  {page.get("status", "")}')
    output(f'  Space:   {page.get("space_id", "")}')
    output(f'  Version: {page.get("version", "")}')
    output(f'  Link:    {page.get("link", "")}')
    if page.get('labels'):
        output(f'  Labels:  {", ".join(page["labels"])}')

    if include_body:
        output('-' * 100)
        output(page.get('body_markdown') or page.get('body_storage') or '')
    output('=' * 100)
    output('')


def _list_page_children_from_root(
    confluence: ConfluenceConnection,
    root: dict[str, Any],
    recursive: bool = False,
    max_depth: Optional[int] = None,
) -> list[dict[str, Any]]:
    '''
    List child pages starting from a resolved root page payload.
    '''
    root_id = str(root.get('id') or '')

    rows: list[dict[str, Any]] = []

    def _walk(parent_id: str, depth: int) -> None:
        if max_depth is not None and depth > max_depth:
            return

        children = _collect_paginated_results(
            confluence,
            f'/api/v2/pages/{parent_id}/children',
            params={'limit': 100},
        )

        for child in children:
            normalized = _normalize_page_entity(confluence, child)
            normalized['depth'] = depth
            normalized['parent_id'] = parent_id
            rows.append(normalized)

            if recursive:
                child_id = str(child.get('id') or '')
                if child_id:
                    _walk(child_id, depth + 1)

    _walk(root_id, 1)
    return rows


def list_page_children(
    confluence: ConfluenceConnection,
    page_id_or_title: str,
    space: Optional[str] = None,
    recursive: bool = False,
    max_depth: Optional[int] = None,
) -> list[dict[str, Any]]:
    '''
    List a page's children, optionally recursing into a tree.
    '''
    root = _resolve_page_identifier(confluence, page_id_or_title, space=space)
    return _list_page_children_from_root(
        confluence,
        root=root,
        recursive=recursive,
        max_depth=max_depth,
    )


def build_page_tree(
    confluence: ConfluenceConnection,
    page_id_or_title: str,
    space: Optional[str] = None,
    max_depth: Optional[int] = None,
) -> list[dict[str, Any]]:
    '''
    Return the root page plus recursively discovered child pages.
    '''
    root_page = _resolve_page_identifier(confluence, page_id_or_title, space=space)
    root = _normalize_page_entity(confluence, root_page)
    root['labels'] = _extract_labels(root_page)
    root['depth'] = 0
    root['parent_id'] = None
    return [root] + _list_page_children_from_root(
        confluence,
        root=root_page,
        recursive=True,
        max_depth=max_depth,
    )


def _print_children(rows: list[dict[str, Any]], root_title: str, recursive: bool = False) -> None:
    '''
    Print children or tree output.
    '''
    output('')
    output('=' * 120)
    output(f'Confluence {"Tree" if recursive else "Children"}: {root_title}')
    output('=' * 120)

    if recursive:
        for row in rows:
            indent = '  ' * int(row.get('depth', 0))
            output(f'{indent}- {row.get("title", "")} ({row.get("page_id", "")})')
    else:
        output(f'{"Page ID":<14} {"Title":<60} {"Link":<44}')
        output('-' * 120)
        for row in rows:
            title = row.get('title', '') or ''
            link = row.get('link', '') or ''
            if len(title) > 58:
                title = title[:58] + '..'
            if len(link) > 42:
                link = link[:42] + '..'
            output(f'{row.get("page_id", ""):<14} {title:<60} {link:<44}')

    output('=' * 120)
    output(f'Total: {len(rows)} page(s)')
    output('')


def read_markdown_file(input_file: str) -> str:
    '''
    Read a Markdown file and return its contents.
    '''
    path = Path(input_file)
    if not path.exists():
        raise FileNotFoundError(f'Markdown file not found: {input_file}')
    return path.read_text(encoding='utf-8')


def _inline_markdown_to_storage(
    text: str,
    extra_fragments: Optional[dict[str, str]] = None,
) -> str:
    '''
    Convert a small subset of inline Markdown to Confluence storage XHTML.
    '''
    placeholders: dict[str, str] = {}

    def _store(fragment: str) -> str:
        token = f'@@CFPLACEHOLDER{len(placeholders)}@@'
        placeholders[token] = fragment
        return token

    text = re.sub(
        r'`([^`]+)`',
        lambda m: _store(f'<code>{html.escape(m.group(1))}</code>'),
        text,
    )
    text = re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        lambda m: _store(
            f'<a href="{html.escape(m.group(2), quote=True)}">'
            f'{html.escape(m.group(1))}</a>'
        ),
        text,
    )

    escaped = html.escape(text)
    escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    escaped = re.sub(r'__(.+?)__', r'<strong>\1</strong>', escaped)
    escaped = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', escaped)
    escaped = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'<em>\1</em>', escaped)

    for token, fragment in placeholders.items():
        escaped = escaped.replace(token, fragment)

    for token, fragment in (extra_fragments or {}).items():
        escaped = escaped.replace(token, fragment)

    return escaped


def _code_block_to_storage(language: str, code: list[str]) -> str:
    '''
    Render a fenced code block as a Confluence code macro.
    '''
    body = '\n'.join(code)
    language_xml = (
        f'<ac:parameter ac:name="language">{html.escape(language)}</ac:parameter>'
        if language else ''
    )
    return (
        '<ac:structured-macro ac:name="code">'
        f'{language_xml}'
        f'<ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body>'
        '</ac:structured-macro>'
    )


def markdown_to_storage(
    markdown_text: str,
    extra_fragments: Optional[dict[str, str]] = None,
) -> str:
    '''
    Convert a lightweight subset of Markdown into Confluence storage XHTML.

    This is intentionally conservative: headings, paragraphs, single-level
    ordered/unordered lists, fenced code blocks, inline links, bold, italics,
    and inline code are supported. More advanced Markdown constructs are left
    as plain text so page creation remains predictable.
    '''
    normalized = markdown_text.replace('\r\n', '\n').replace('\r', '\n')
    lines = normalized.split('\n')
    blocks: list[str] = []
    paragraph: list[str] = []
    i = 0

    def _flush_paragraph() -> None:
        if not paragraph:
            return
        blocks.append(f'<p>{"<br />".join(paragraph)}</p>')
        paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            _flush_paragraph()
            i += 1
            continue

        fence = re.match(r'^```([\w+-]*)\s*$', stripped)
        if fence:
            _flush_paragraph()
            language = fence.group(1)
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not re.match(r'^```\s*$', lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            blocks.append(_code_block_to_storage(language, code_lines))
            i += 1
            continue

        heading = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading:
            _flush_paragraph()
            level = len(heading.group(1))
            text = _inline_markdown_to_storage(heading.group(2).strip(), extra_fragments)
            blocks.append(f'<h{level}>{text}</h{level}>')
            i += 1
            continue

        if re.fullmatch(r'[-*_]{3,}', stripped):
            _flush_paragraph()
            blocks.append('<hr />')
            i += 1
            continue

        unordered = re.match(r'^\s*[-*+]\s+(.+)$', line)
        if unordered:
            _flush_paragraph()
            items: list[str] = []
            while i < len(lines):
                match = re.match(r'^\s*[-*+]\s+(.+)$', lines[i])
                if not match:
                    break
                items.append(
                    f'<li>{_inline_markdown_to_storage(match.group(1).strip(), extra_fragments)}</li>'
                )
                i += 1
            blocks.append(f'<ul>{"".join(items)}</ul>')
            continue

        ordered = re.match(r'^\s*\d+\.\s+(.+)$', line)
        if ordered:
            _flush_paragraph()
            items = []
            while i < len(lines):
                match = re.match(r'^\s*\d+\.\s+(.+)$', lines[i])
                if not match:
                    break
                items.append(
                    f'<li>{_inline_markdown_to_storage(match.group(1).strip(), extra_fragments)}</li>'
                )
                i += 1
            blocks.append(f'<ol>{"".join(items)}</ol>')
            continue

        paragraph.append(_inline_markdown_to_storage(stripped, extra_fragments))
        i += 1

    _flush_paragraph()

    return ''.join(blocks) if blocks else '<p></p>'


def _strip_storage_tags(value: str) -> str:
    '''
    Strip storage XHTML tags while preserving readable text.
    '''
    text = re.sub(r'<br\s*/?>', '\n', value, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def storage_to_markdown(storage_text: str) -> str:
    '''
    Convert a limited subset of Confluence storage XHTML back to Markdown.
    '''
    markdown = storage_text

    def _code_macro_to_markdown(match: re.Match[str]) -> str:
        params = match.group(1)
        code_body = match.group(2)
        language_match = re.search(
            r'<ac:parameter ac:name="language">(.*?)</ac:parameter>',
            params,
            re.DOTALL,
        )
        language = language_match.group(1) if language_match else ''
        return f'```{language}\n{code_body}\n```'

    markdown = re.sub(
        r'<ac:structured-macro ac:name="code">(.*?)<ac:plain-text-body><!\[CDATA\[(.*?)\]\]></ac:plain-text-body></ac:structured-macro>',
        _code_macro_to_markdown,
        markdown,
        flags=re.DOTALL,
    )

    markdown = re.sub(
        r'<ac:image>\s*<ri:attachment ri:filename="([^"]+)"\s*/>\s*</ac:image>',
        lambda m: f'![]({html.unescape(m.group(1))})',
        markdown,
        flags=re.DOTALL,
    )
    markdown = re.sub(
        r'<ac:image>\s*<ri:url ri:value="([^"]+)"\s*/>\s*</ac:image>',
        lambda m: f'![]({html.unescape(m.group(1))})',
        markdown,
        flags=re.DOTALL,
    )
    markdown = re.sub(
        r'<ac:link>\s*<ri:attachment ri:filename="([^"]+)"\s*/>\s*<ac:plain-text-link-body><!\[CDATA\[(.*?)\]\]></ac:plain-text-link-body>\s*</ac:link>',
        lambda m: f'[{m.group(2)}]({html.unescape(m.group(1))})',
        markdown,
        flags=re.DOTALL,
    )
    markdown = re.sub(
        r'<a href="([^"]+)">(.*?)</a>',
        lambda m: f'[{_strip_storage_tags(m.group(2))}]({html.unescape(m.group(1))})',
        markdown,
        flags=re.DOTALL,
    )
    markdown = re.sub(
        r'<strong>(.*?)</strong>',
        lambda m: f'**{_strip_storage_tags(m.group(1))}**',
        markdown,
        flags=re.DOTALL,
    )
    markdown = re.sub(
        r'<em>(.*?)</em>',
        lambda m: f'*{_strip_storage_tags(m.group(1))}*',
        markdown,
        flags=re.DOTALL,
    )

    for level in range(6, 0, -1):
        markdown = re.sub(
            rf'<h{level}>(.*?)</h{level}>',
            lambda m, lvl=level: f'{"#" * lvl} {_strip_storage_tags(m.group(1))}\n\n',
            markdown,
            flags=re.DOTALL | re.IGNORECASE,
        )

    markdown = re.sub(
        r'<ul>(.*?)</ul>',
        lambda m: ''.join(
            f'- {_strip_storage_tags(item)}\n'
            for item in re.findall(r'<li>(.*?)</li>', m.group(1), flags=re.DOTALL | re.IGNORECASE)
        ) + '\n',
        markdown,
        flags=re.DOTALL | re.IGNORECASE,
    )
    markdown = re.sub(
        r'<ol>(.*?)</ol>',
        lambda m: ''.join(
            f'{idx}. {_strip_storage_tags(item)}\n'
            for idx, item in enumerate(
                re.findall(r'<li>(.*?)</li>', m.group(1), flags=re.DOTALL | re.IGNORECASE),
                1,
            )
        ) + '\n',
        markdown,
        flags=re.DOTALL | re.IGNORECASE,
    )
    markdown = re.sub(
        r'<p>(.*?)</p>',
        lambda m: f'{_strip_storage_tags(m.group(1))}\n\n',
        markdown,
        flags=re.DOTALL | re.IGNORECASE,
    )
    markdown = re.sub(r'<hr\s*/?>', '\n---\n\n', markdown, flags=re.IGNORECASE)
    markdown = re.sub(r'<br\s*/?>', '\n', markdown, flags=re.IGNORECASE)
    markdown = re.sub(r'<[^>]+>', '', markdown)
    markdown = html.unescape(markdown)
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)
    return markdown.strip() + ('\n' if markdown.strip() else '')


def _storage_heading_text(fragment: str) -> str:
    '''
    Convert storage XHTML heading content into comparable plain text.
    '''
    return _strip_storage_tags(fragment).casefold()


def _merge_front_matter_value(cli_value: Optional[str], document_value: Optional[str]) -> Optional[str]:
    '''
    Prefer the explicit CLI value, falling back to Markdown front matter.
    '''
    return cli_value if cli_value not in (None, '') else document_value


def _publish_preview(
    mode: str,
    title: str,
    body_storage: str,
    space: Optional[str] = None,
    page_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    version_number: Optional[int] = None,
    attachments: Optional[list[dict[str, str]]] = None,
    labels: Optional[list[str]] = None,
) -> dict[str, Any]:
    '''
    Build a dry-run preview payload.
    '''
    return {
        'dry_run': True,
        'mode': mode,
        'title': title,
        'page_id': page_id,
        'space': space,
        'parent_id': parent_id,
        'version': version_number,
        'attachments': attachments or [],
        'labels': labels or [],
        'body_storage': body_storage,
        'body_markdown': storage_to_markdown(body_storage),
    }


def _print_preview(preview: dict[str, Any]) -> None:
    '''
    Print a dry-run preview for a page publish operation.
    '''
    output('')
    output('=' * 100)
    output(f'Confluence Dry Run: {preview.get("mode", "").upper()}')
    output('=' * 100)
    output(f'Title:      {preview.get("title", "")}')
    if preview.get('page_id'):
        output(f'Page ID:    {preview.get("page_id", "")}')
    if preview.get('space'):
        output(f'Space:      {preview.get("space", "")}')
    if preview.get('parent_id'):
        output(f'Parent ID:  {preview.get("parent_id", "")}')
    if preview.get('version') is not None:
        output(f'Version:    {preview.get("version", "")}')
    if preview.get('labels'):
        output(f'Labels:     {", ".join(preview["labels"])}')
    if preview.get('attachments'):
        output(f'Attachments: {", ".join(item["filename"] for item in preview["attachments"])}')
    output('-' * 100)
    output(preview.get('body_markdown') or preview.get('body_storage') or '')
    output('=' * 100)
    output('')


def _print_publish_result(action: str, page: dict[str, Any]) -> None:
    '''
    Print a concise publish/update result summary.
    '''
    output('')
    output('=' * 80)
    output(f'Confluence Page {action}')
    output('=' * 80)
    output(f'Title:   {page.get("title", "")}')
    output(f'Page ID: {page.get("page_id", "")}')
    output(f'Link:    {page.get("link", "")}')
    if page.get('version') is not None:
        output(f'Version: {page.get("version", "")}')
    if page.get('attachments'):
        output(f'Attachments: {", ".join(item["filename"] for item in page["attachments"])}')
    output('=' * 80)
    output('')


def _apply_page_labels(
    confluence: ConfluenceConnection,
    page_id: str,
    labels: list[str],
) -> None:
    '''
    Add global labels to a page.
    '''
    if not labels:
        return

    payload = [{'prefix': 'global', 'name': label} for label in labels]
    confluence.request(
        'POST',
        f'/rest/api/content/{page_id}/label',
        json=payload,
        headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
    )


def _upload_attachments(
    confluence: ConfluenceConnection,
    page_id: str,
    attachments: list[dict[str, str]],
) -> list[dict[str, str]]:
    '''
    Upload local attachments to a Confluence page.
    '''
    uploaded: list[dict[str, str]] = []
    for attachment in attachments:
        source_path = attachment['source_path']
        filename = attachment['filename']
        with open(source_path, 'rb') as handle:
            response = confluence.request(
                'PUT',
                f'/rest/api/content/{page_id}/child/attachment',
                files={'file': (filename, handle)},
                data={'minorEdit': 'true'},
                headers={'X-Atlassian-Token': 'nocheck', 'Accept': 'application/json'},
            )
        payload = _json(response)
        uploaded.append({
            'filename': filename,
            'source_path': source_path,
            'id': str((payload.get('results') or [{}])[0].get('id') or ''),
        })
    return uploaded


def _resolve_publish_inputs(
    confluence: ConfluenceConnection,
    input_file: str,
    title: Optional[str] = None,
    space: Optional[str] = None,
    parent_id: Optional[str] = None,
    version_message: Optional[str] = None,
) -> tuple[MarkdownDocument, str, Optional[str], Optional[str], Optional[str]]:
    '''
    Merge CLI arguments with Markdown front matter.
    '''
    document = load_markdown_document(input_file)
    resolved_title = _merge_front_matter_value(title, document.title)
    if not resolved_title:
        raise ConfluencePageError(
            'A page title is required. Pass it on the CLI or set `title:` in Markdown front matter.'
        )

    resolved_space = _merge_front_matter_value(space, document.space)
    resolved_parent = _merge_front_matter_value(parent_id, document.parent_id)
    if resolved_parent and not _is_numeric_id(resolved_parent):
        resolved_parent = resolve_parent_id(confluence, resolved_parent, space=resolved_space)

    resolved_version_message = _merge_front_matter_value(version_message, document.version_message)
    return document, resolved_title, resolved_space, resolved_parent, resolved_version_message


def _with_uploaded_assets(
    result: dict[str, Any],
    uploaded_attachments: list[dict[str, str]],
) -> dict[str, Any]:
    '''
    Attach uploaded attachment metadata to a page result payload.
    '''
    if uploaded_attachments:
        result['attachments'] = uploaded_attachments
    return result


def _replace_page_body_section(
    existing_storage: str,
    heading: str,
    new_section_storage: str,
) -> str:
    '''
    Replace the section contents under a heading with new storage XHTML.
    '''
    matches = list(HEADING_RE.finditer(existing_storage))
    target_heading = heading.casefold()

    for index, match in enumerate(matches):
        level = int(match.group(1))
        heading_text = _storage_heading_text(match.group(2))
        if heading_text != target_heading:
            continue

        section_start = match.end()
        section_end = len(existing_storage)
        for next_match in matches[index + 1:]:
            if int(next_match.group(1)) <= level:
                section_end = next_match.start()
                break

        return (
            existing_storage[:section_start]
            + new_section_storage
            + existing_storage[section_end:]
        )

    raise ConfluencePageError(f'Heading "{heading}" not found in the target page.')


def _append_page_body(existing_storage: str, appended_storage: str) -> str:
    '''
    Append storage XHTML to the end of an existing page body.
    '''
    if not existing_storage.strip():
        return appended_storage
    return f'{existing_storage}{appended_storage}'


def create_page(
    confluence: ConfluenceConnection,
    title: str,
    input_file: str,
    space: Optional[str] = None,
    parent_id: Optional[str] = None,
    version_message: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    '''
    Create a Confluence page from a Markdown file.
    '''
    log.debug(
        f'create_page(title={title}, input_file={input_file}, '
        f'space={space}, parent_id={parent_id}, version_message={version_message}, dry_run={dry_run})'
    )

    document, resolved_title, resolved_space, resolved_parent_id, resolved_version_message = _resolve_publish_inputs(
        confluence,
        input_file,
        title=title,
        space=space,
        parent_id=parent_id,
        version_message=version_message,
    )
    space_id = resolve_space_id(confluence, resolved_space)

    if dry_run:
        preview = _publish_preview(
            mode='create',
            title=resolved_title,
            body_storage=document.body_storage,
            space=resolved_space or space_id,
            parent_id=resolved_parent_id,
            attachments=document.attachments,
            labels=document.labels,
        )
        _print_preview(preview)
        return preview

    payload: dict[str, Any] = {
        'spaceId': space_id,
        'status': 'current',
        'title': resolved_title,
        'body': {
            'representation': 'storage',
            'value': document.body_storage,
        },
    }
    if resolved_parent_id:
        payload['parentId'] = str(resolved_parent_id)

    request_kwargs: dict[str, Any] = {'json': payload}
    if not resolved_parent_id:
        request_kwargs['params'] = {'root-level': 'true'}

    response = confluence.request('POST', '/api/v2/pages', **request_kwargs)
    created = _normalize_page_entity(confluence, _json(response))
    page_id = created['page_id']

    uploaded_attachments = _upload_attachments(confluence, page_id, document.attachments)
    _apply_page_labels(confluence, page_id, document.labels)
    created = _with_uploaded_assets(created, uploaded_attachments)
    if resolved_version_message:
        created['version_message'] = resolved_version_message

    output('')
    output('=' * 80)
    output('Confluence Page Created')
    output('=' * 80)
    output(f'Title:   {created["title"]}')
    output(f'Page ID: {created["page_id"]}')
    output(f'Link:    {created["link"]}')
    output('=' * 80)
    output('')

    return created


def update_page(
    confluence: ConfluenceConnection,
    page_id_or_title: str,
    input_file: str,
    space: Optional[str] = None,
    version_message: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    '''
    Update an existing Confluence page from a Markdown file.
    '''
    log.debug(
        f'update_page(page_id_or_title={page_id_or_title}, input_file={input_file}, '
        f'space={space}, version_message={version_message}, dry_run={dry_run})'
    )

    current_page = _resolve_page_identifier(confluence, page_id_or_title, space=space)
    page_id = str(current_page.get('id') or '')
    if not page_id:
        raise ConfluencePageError(f'Could not resolve page: {page_id_or_title}')

    document, _resolved_title, _resolved_space, _resolved_parent_id, resolved_version_message = _resolve_publish_inputs(
        confluence,
        input_file,
        title=current_page.get('title', ''),
        space=space,
        version_message=version_message,
    )
    current_version = int((current_page.get('version') or {}).get('number') or 0)

    if dry_run:
        preview = _publish_preview(
            mode='update',
            title=current_page.get('title', ''),
            body_storage=document.body_storage,
            page_id=page_id,
            space=space or str(current_page.get('spaceId') or ''),
            version_number=current_version + 1,
            attachments=document.attachments,
            labels=document.labels,
        )
        _print_preview(preview)
        return preview

    payload: dict[str, Any] = {
        'id': page_id,
        'status': current_page.get('status', 'current') or 'current',
        'title': current_page.get('title', ''),
        'body': {
            'representation': 'storage',
            'value': document.body_storage,
        },
        'version': {
            'number': current_version + 1,
        },
    }
    if current_page.get('spaceId'):
        payload['spaceId'] = current_page.get('spaceId')
    if resolved_version_message:
        payload['version']['message'] = resolved_version_message

    response = confluence.request('PUT', f'/api/v2/pages/{page_id}', json=payload)
    updated = _normalize_page_entity(confluence, _json(response))
    uploaded_attachments = _upload_attachments(confluence, page_id, document.attachments)
    _apply_page_labels(confluence, page_id, document.labels)
    updated = _with_uploaded_assets(updated, uploaded_attachments)

    output('')
    output('=' * 80)
    output('Confluence Page Updated')
    output('=' * 80)
    output(f'Title:   {updated["title"]}')
    output(f'Page ID: {updated["page_id"]}')
    output(f'Link:    {updated["link"]}')
    output(f'Version: {updated.get("version", "")}')
    output('=' * 80)
    output('')

    return updated


def append_page(
    confluence: ConfluenceConnection,
    page_id_or_title: str,
    input_file: str,
    space: Optional[str] = None,
    version_message: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    '''
    Append Markdown content to the end of an existing page.
    '''
    current_page = _resolve_page_identifier(confluence, page_id_or_title, space=space)
    page_id = str(current_page.get('id') or '')
    current_version = int((current_page.get('version') or {}).get('number') or 0)
    existing_storage = _extract_storage_body(current_page)

    document, _resolved_title, _resolved_space, _resolved_parent_id, resolved_version_message = _resolve_publish_inputs(
        confluence,
        input_file,
        title=current_page.get('title', ''),
        space=space,
        version_message=version_message,
    )
    merged_storage = _append_page_body(existing_storage, document.body_storage)

    if dry_run:
        preview = _publish_preview(
            mode='append',
            title=current_page.get('title', ''),
            body_storage=merged_storage,
            page_id=page_id,
            space=space or str(current_page.get('spaceId') or ''),
            version_number=current_version + 1,
            attachments=document.attachments,
            labels=document.labels,
        )
        _print_preview(preview)
        return preview

    payload: dict[str, Any] = {
        'id': page_id,
        'status': current_page.get('status', 'current') or 'current',
        'title': current_page.get('title', ''),
        'body': {'representation': 'storage', 'value': merged_storage},
        'version': {'number': current_version + 1},
    }
    if current_page.get('spaceId'):
        payload['spaceId'] = current_page.get('spaceId')
    if resolved_version_message:
        payload['version']['message'] = resolved_version_message

    response = confluence.request('PUT', f'/api/v2/pages/{page_id}', json=payload)
    updated = _normalize_page_entity(confluence, _json(response))
    uploaded_attachments = _upload_attachments(confluence, page_id, document.attachments)
    _apply_page_labels(confluence, page_id, document.labels)
    return _with_uploaded_assets(updated, uploaded_attachments)


def update_page_section(
    confluence: ConfluenceConnection,
    page_id_or_title: str,
    heading: str,
    input_file: str,
    space: Optional[str] = None,
    version_message: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    '''
    Replace the body under a specific heading within an existing page.
    '''
    current_page = _resolve_page_identifier(confluence, page_id_or_title, space=space)
    page_id = str(current_page.get('id') or '')
    current_version = int((current_page.get('version') or {}).get('number') or 0)
    existing_storage = _extract_storage_body(current_page)

    document, _resolved_title, _resolved_space, _resolved_parent_id, resolved_version_message = _resolve_publish_inputs(
        confluence,
        input_file,
        title=current_page.get('title', ''),
        space=space,
        version_message=version_message,
    )
    merged_storage = _replace_page_body_section(existing_storage, heading, document.body_storage)

    if dry_run:
        preview = _publish_preview(
            mode='update-section',
            title=current_page.get('title', ''),
            body_storage=merged_storage,
            page_id=page_id,
            space=space or str(current_page.get('spaceId') or ''),
            version_number=current_version + 1,
            attachments=document.attachments,
            labels=document.labels,
        )
        _print_preview(preview)
        return preview

    payload: dict[str, Any] = {
        'id': page_id,
        'status': current_page.get('status', 'current') or 'current',
        'title': current_page.get('title', ''),
        'body': {'representation': 'storage', 'value': merged_storage},
        'version': {'number': current_version + 1},
    }
    if current_page.get('spaceId'):
        payload['spaceId'] = current_page.get('spaceId')
    if resolved_version_message:
        payload['version']['message'] = resolved_version_message

    response = confluence.request('PUT', f'/api/v2/pages/{page_id}', json=payload)
    updated = _normalize_page_entity(confluence, _json(response))
    uploaded_attachments = _upload_attachments(confluence, page_id, document.attachments)
    _apply_page_labels(confluence, page_id, document.labels)
    return _with_uploaded_assets(updated, uploaded_attachments)


def export_page_to_markdown(
    confluence: ConfluenceConnection,
    page_id_or_title: str,
    output_file: str,
    space: Optional[str] = None,
) -> dict[str, Any]:
    '''
    Export a Confluence page to a Markdown file with YAML front matter.
    '''
    page = get_page(confluence, page_id_or_title, space=space, include_body=True)
    front_matter = {
        'title': page.get('title'),
        'space': space or resolve_space_key(confluence, page.get('space_id')),
        'page_id': page.get('page_id'),
    }
    if page.get('labels'):
        front_matter['labels'] = page['labels']

    markdown = page.get('body_markdown') or ''
    front_matter_text = yaml.safe_dump(front_matter, sort_keys=False).strip()
    content = f'---\n{front_matter_text}\n---\n\n{markdown}'
    Path(output_file).write_text(content, encoding='utf-8')

    result = {
        'page_id': page.get('page_id'),
        'title': page.get('title'),
        'output_file': output_file,
        'link': page.get('link'),
    }

    output('')
    output('=' * 80)
    output('Confluence Page Exported')
    output('=' * 80)
    output(f'Title:      {result["title"]}')
    output(f'Page ID:    {result["page_id"]}')
    output(f'Output:     {result["output_file"]}')
    output(f'Link:       {result["link"]}')
    output('=' * 80)
    output('')

    return result


def _normalize_action_args(
    parser: argparse.ArgumentParser,
    values: Optional[list[str]],
    action_name: str,
    allowed_lengths: set[int],
    usage: str,
    supports_inline_space: bool = False,
    current_space: Optional[str] = None,
    inline_space_index: int = 1,
) -> tuple[Optional[list[str]], Optional[str]]:
    '''
    Normalize action arguments, optionally extracting an inline space operand.
    '''
    if not values:
        return None, current_space

    if len(values) not in allowed_lengths:
        parser.error(f'{action_name} requires {usage}')

    normalized = list(values)
    inline_space = current_space

    if supports_inline_space and len(normalized) == max(allowed_lengths):
        inline_space = normalized[inline_space_index]
        if current_space and current_space != inline_space:
            parser.error(
                f'--space conflicts with the SPACE value supplied to {action_name}'
            )
        normalized = [value for idx, value in enumerate(normalized) if idx != inline_space_index]

    return normalized, inline_space


def handle_args():
    '''
    Parse and validate CLI arguments.
    '''
    global _quiet_mode

    parser = argparse.ArgumentParser(
        description='Confluence utilities for Cornelis Networks Atlassian pages.'
    )

    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        '--search',
        nargs='+',
        metavar='ARG',
        help='Search Confluence page titles. Supported forms: --search PATTERN or --search PATTERN SPACE.',
    )
    action_group.add_argument(
        '--get',
        nargs='+',
        metavar='ARG',
        help='Get a page by ID or exact title. Supported forms: --get PAGE or --get PAGE SPACE.',
    )
    action_group.add_argument(
        '--create',
        nargs='+',
        metavar='ARG',
        help=(
            'Create a Confluence page from a Markdown file. '
            'Supported forms: --create INPUT_MD_FILE, --create TITLE INPUT_MD_FILE, or '
            '--create TITLE SPACE INPUT_MD_FILE.'
        ),
    )
    action_group.add_argument(
        '--update',
        nargs='+',
        metavar='ARG',
        help='Update a Confluence page. Supported forms: --update PAGE INPUT_MD_FILE or --update PAGE SPACE INPUT_MD_FILE.',
    )
    action_group.add_argument(
        '--append',
        nargs='+',
        metavar='ARG',
        help='Append Markdown to a page. Supported forms: --append PAGE INPUT_MD_FILE or --append PAGE SPACE INPUT_MD_FILE.',
    )
    action_group.add_argument(
        '--update-section',
        nargs='+',
        metavar='ARG',
        help=(
            'Replace a section under a heading. Supported forms: '
            '--update-section PAGE HEADING INPUT_MD_FILE or '
            '--update-section PAGE SPACE HEADING INPUT_MD_FILE.'
        ),
    )
    action_group.add_argument(
        '--export',
        nargs='+',
        metavar='ARG',
        help='Export a page to Markdown. Supported forms: --export PAGE OUTPUT_MD_FILE or --export PAGE SPACE OUTPUT_MD_FILE.',
    )
    action_group.add_argument(
        '--children',
        nargs='+',
        metavar='ARG',
        help='List direct child pages. Supported forms: --children PAGE or --children PAGE SPACE.',
    )
    action_group.add_argument(
        '--tree',
        nargs='+',
        metavar='ARG',
        help='Show a recursive page tree. Supported forms: --tree PAGE or --tree PAGE SPACE.',
    )

    parser.add_argument(
        '--space',
        help='Optional Confluence space key or numeric ID.',
    )
    parser.add_argument(
        '--parent-id',
        help='Optional parent page ID for create.',
    )
    parser.add_argument(
        '--version-message',
        help='Optional version message to store with an update.',
    )
    parser.add_argument(
        '--body',
        action='store_true',
        help='Include page body content when using --get.',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Emit JSON instead of table/text output.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview create/update/append/section-update operations without publishing.',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=25,
        help='Maximum number of search results to return (default: 25).',
    )
    parser.add_argument(
        '--env',
        default='.env',
        help='dotenv file to load before connecting (default: .env).',
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress stdout output.',
    )
    parser.add_argument(
        '--max-depth',
        type=int,
        help='Maximum recursion depth for --tree.',
    )

    args = parser.parse_args()

    args.search, args.space = _normalize_action_args(
        parser,
        args.search,
        '--search',
        {1, 2},
        'PATTERN or PATTERN SPACE',
        supports_inline_space=True,
        current_space=args.space,
        inline_space_index=1,
    )
    args.get, args.space = _normalize_action_args(
        parser,
        args.get,
        '--get',
        {1, 2},
        'PAGE or PAGE SPACE',
        supports_inline_space=True,
        current_space=args.space,
        inline_space_index=1,
    )
    args.children, args.space = _normalize_action_args(
        parser,
        args.children,
        '--children',
        {1, 2},
        'PAGE or PAGE SPACE',
        supports_inline_space=True,
        current_space=args.space,
        inline_space_index=1,
    )
    args.tree, args.space = _normalize_action_args(
        parser,
        args.tree,
        '--tree',
        {1, 2},
        'PAGE or PAGE SPACE',
        supports_inline_space=True,
        current_space=args.space,
        inline_space_index=1,
    )
    args.export, args.space = _normalize_action_args(
        parser,
        args.export,
        '--export',
        {2, 3},
        'PAGE OUTPUT_MD_FILE or PAGE SPACE OUTPUT_MD_FILE',
        supports_inline_space=True,
        current_space=args.space,
        inline_space_index=1,
    )
    args.update, args.space = _normalize_action_args(
        parser,
        args.update,
        '--update',
        {2, 3},
        'PAGE INPUT_MD_FILE or PAGE SPACE INPUT_MD_FILE',
        supports_inline_space=True,
        current_space=args.space,
        inline_space_index=1,
    )
    args.append, args.space = _normalize_action_args(
        parser,
        args.append,
        '--append',
        {2, 3},
        'PAGE INPUT_MD_FILE or PAGE SPACE INPUT_MD_FILE',
        supports_inline_space=True,
        current_space=args.space,
        inline_space_index=1,
    )
    args.update_section, args.space = _normalize_action_args(
        parser,
        getattr(args, 'update_section'),
        '--update-section',
        {3, 4},
        'PAGE HEADING INPUT_MD_FILE or PAGE SPACE HEADING INPUT_MD_FILE',
        supports_inline_space=True,
        current_space=args.space,
        inline_space_index=1,
    )

    if args.create:
        if len(args.create) not in (1, 2, 3):
            parser.error(
                '--create requires INPUT_MD_FILE, TITLE INPUT_MD_FILE, or '
                'TITLE SPACE INPUT_MD_FILE'
            )
        if len(args.create) == 3:
            title, create_space, input_file = args.create
            if args.space and args.space != create_space:
                parser.error(
                    '--space conflicts with the SPACE value supplied to --create'
                )
            args.space = args.space or create_space
            args.create = [title, input_file]

    active_publish_action = any([args.create, args.update, args.append, args.update_section])

    if args.env != '.env' and not os.path.exists(args.env):
        parser.error(f'--env file not found: {args.env}')
    if os.path.exists(args.env):
        load_dotenv(args.env, override=True)
        reset_connection()

    if args.limit <= 0:
        parser.error('--limit must be greater than zero')
    if args.max_depth is not None and args.max_depth < 0:
        parser.error('--max-depth must be zero or greater')
    if args.body and not args.get:
        parser.error('--body requires --get')
    if args.dry_run and not active_publish_action:
        parser.error('--dry-run requires --create, --update, --append, or --update-section')
    if args.parent_id and not args.create:
        parser.error('--parent-id requires --create')
    if args.max_depth is not None and not args.tree:
        parser.error('--max-depth requires --tree')

    _quiet_mode = args.quiet or args.json
    return args


def main():
    '''
    CLI entry point.
    '''
    args = handle_args()

    try:
        confluence = get_connection()
        result: Any = None

        if args.search:
            result = search_pages(confluence, args.search[0], limit=args.limit, space=args.space)
        elif args.get:
            result = get_page(
                confluence,
                args.get[0],
                space=args.space,
                include_body=args.body,
            )
        elif args.create:
            if len(args.create) == 1:
                title = None
                input_file = args.create[0]
            else:
                title, input_file = args.create
            result = create_page(
                confluence,
                title=title or '',
                input_file=input_file,
                space=args.space,
                parent_id=args.parent_id,
                version_message=args.version_message,
                dry_run=args.dry_run,
            )
        elif args.update:
            page_id_or_title, input_file = args.update
            result = update_page(
                confluence,
                page_id_or_title=page_id_or_title,
                input_file=input_file,
                space=args.space,
                version_message=args.version_message,
                dry_run=args.dry_run,
            )
        elif args.append:
            page_id_or_title, input_file = args.append
            result = append_page(
                confluence,
                page_id_or_title=page_id_or_title,
                input_file=input_file,
                space=args.space,
                version_message=args.version_message,
                dry_run=args.dry_run,
            )
        elif args.update_section:
            page_id_or_title, heading, input_file = args.update_section
            result = update_page_section(
                confluence,
                page_id_or_title=page_id_or_title,
                heading=heading,
                input_file=input_file,
                space=args.space,
                version_message=args.version_message,
                dry_run=args.dry_run,
            )
        elif args.export:
            page_id_or_title, output_file = args.export
            result = export_page_to_markdown(
                confluence,
                page_id_or_title=page_id_or_title,
                output_file=output_file,
                space=args.space,
            )
        elif args.children:
            root_page = get_page(confluence, args.children[0], space=args.space, include_body=False)
            result = list_page_children(
                confluence,
                page_id_or_title=args.children[0],
                space=args.space,
                recursive=False,
            )
            if not args.json:
                _print_children(result, root_page['title'], recursive=False)
        elif args.tree:
            result = build_page_tree(
                confluence,
                page_id_or_title=args.tree[0],
                space=args.space,
                max_depth=args.max_depth,
            )
            if not args.json:
                _print_children(result, result[0]['title'] if result else args.tree[0], recursive=True)
        if args.get and not args.json:
            _print_page_detail(result, include_body=args.body)
        elif args.json and not args.quiet:
            print(json.dumps(result, indent=2, default=str))
        elif args.append and not args.dry_run:
            _print_publish_result('Appended', result)
        elif args.update_section and not args.dry_run:
            _print_publish_result('Section Updated', result)

        return 0

    except Error as exc:
        output(f'ERROR: {exc}')
        return 1
    except Exception as exc:
        log.error(f'Unexpected failure: {exc}', exc_info=True)
        output(f'ERROR: {exc}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
