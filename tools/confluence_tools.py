##########################################################################################
#
# Module: tools/confluence_tools.py
#
# Description: Confluence tools for agent use.
#              Wraps confluence_utils.py functionality as agent-callable tools.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from typing import Optional

from dotenv import load_dotenv

from tools.base import BaseTool, ToolResult, tool

# Load environment variables
load_dotenv()

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

try:
    import confluence_utils
    from confluence_utils import (
        get_connection as get_confluence_connection,
        reset_connection as reset_confluence_connection,
        search_pages as _cu_search_pages,
        get_page as _cu_get_page,
        create_page as _cu_create_page,
        update_page as _cu_update_page,
        append_page as _cu_append_page,
        update_page_section as _cu_update_page_section,
        list_page_children as _cu_list_page_children,
        build_page_tree as _cu_build_page_tree,
        export_page_to_markdown as _cu_export_page_to_markdown,
    )

    CONFLUENCE_UTILS_AVAILABLE = True
except ImportError as e:
    CONFLUENCE_UTILS_AVAILABLE = False
    log.warning(f'confluence_utils.py not available: {e}')


def get_confluence():
    '''
    Get or create a Confluence connection using confluence_utils.
    '''
    if not CONFLUENCE_UTILS_AVAILABLE:
        raise RuntimeError('confluence_utils.py is required but not available')

    return get_confluence_connection()


def reset_confluence() -> None:
    '''
    Reset the cached Confluence connection.
    '''
    if CONFLUENCE_UTILS_AVAILABLE:
        reset_confluence_connection()


@tool(
    description='Search Confluence pages by title pattern'
)
def search_confluence_pages(
    pattern: str,
    limit: int = 25,
    space: Optional[str] = None,
) -> ToolResult:
    '''
    Search Confluence pages by title pattern.

    Input:
        pattern: Search pattern to match against page titles.
        limit: Maximum number of matching pages to return.

    Output:
        ToolResult with page IDs, titles, and links.
    '''
    log.debug(f'search_confluence_pages(pattern={pattern}, limit={limit}, space={space})')

    try:
        confluence = get_confluence()
        pages = _cu_search_pages(confluence, pattern=pattern, limit=limit, space=space)
        return ToolResult.success(pages, count=len(pages))
    except Exception as e:
        log.error(f'Failed to search Confluence pages: {e}')
        return ToolResult.failure(f'Confluence search failed: {e}')


@tool(
    description='Get a Confluence page by page ID or exact title'
)
def get_confluence_page(
    page_id_or_title: str,
    space: Optional[str] = None,
    include_body: bool = False,
) -> ToolResult:
    '''
    Get a Confluence page by page ID or exact title.
    '''
    log.debug(
        f'get_confluence_page(page_id_or_title={page_id_or_title}, '
        f'space={space}, include_body={include_body})'
    )

    try:
        confluence = get_confluence()
        page = _cu_get_page(
            confluence,
            page_id_or_title=page_id_or_title,
            space=space,
            include_body=include_body,
        )
        return ToolResult.success(page)
    except Exception as e:
        log.error(f'Failed to get Confluence page: {e}')
        return ToolResult.failure(f'Confluence get failed: {e}')


@tool(
    description='Create a Confluence page from a Markdown file'
)
def create_confluence_page(
    title: str,
    input_file: str,
    space: Optional[str] = None,
    parent_id: Optional[str] = None,
    version_message: Optional[str] = None,
    dry_run: bool = False,
) -> ToolResult:
    '''
    Create a Confluence page from a Markdown file.

    Input:
        title: Title for the new page.
        input_file: Path to the Markdown file to publish.
        space: Optional Confluence space key or numeric ID.
        parent_id: Optional parent page ID.
        version_message: Optional Confluence version history message.
        dry_run: Return a publish preview without creating the page.

    Output:
        ToolResult with created page metadata.
    '''
    log.debug(
        f'create_confluence_page(title={title}, input_file={input_file}, '
        f'space={space}, parent_id={parent_id}, version_message={version_message}, '
        f'dry_run={dry_run})'
    )

    try:
        confluence = get_confluence()
        page = _cu_create_page(
            confluence,
            title=title,
            input_file=input_file,
            space=space,
            parent_id=parent_id,
            version_message=version_message,
            dry_run=dry_run,
        )
        return ToolResult.success(page)
    except Exception as e:
        log.error(f'Failed to create Confluence page: {e}')
        return ToolResult.failure(f'Confluence create failed: {e}')


@tool(
    description='Update a Confluence page from a Markdown file'
)
def update_confluence_page(
    page_id_or_title: str,
    input_file: str,
    space: Optional[str] = None,
    version_message: Optional[str] = None,
    dry_run: bool = False,
) -> ToolResult:
    '''
    Update a Confluence page by page ID or exact title.

    Input:
        page_id_or_title: Existing page ID or exact page title.
        input_file: Path to the Markdown file to publish.
        space: Optional Confluence space key or numeric ID, used to disambiguate titles.
        version_message: Optional version history message.

    Output:
        ToolResult with updated page metadata.
    '''
    log.debug(
        f'update_confluence_page(page_id_or_title={page_id_or_title}, '
        f'input_file={input_file}, space={space}, version_message={version_message}, '
        f'dry_run={dry_run})'
    )

    try:
        confluence = get_confluence()
        page = _cu_update_page(
            confluence,
            page_id_or_title=page_id_or_title,
            input_file=input_file,
            space=space,
            version_message=version_message,
            dry_run=dry_run,
        )
        return ToolResult.success(page)
    except Exception as e:
        log.error(f'Failed to update Confluence page: {e}')
        return ToolResult.failure(f'Confluence update failed: {e}')


@tool(
    description='Append Markdown content to an existing Confluence page'
)
def append_to_confluence_page(
    page_id_or_title: str,
    input_file: str,
    space: Optional[str] = None,
    version_message: Optional[str] = None,
    dry_run: bool = False,
) -> ToolResult:
    '''
    Append Markdown content to an existing Confluence page.
    '''
    log.debug(
        f'append_to_confluence_page(page_id_or_title={page_id_or_title}, '
        f'input_file={input_file}, space={space}, version_message={version_message}, '
        f'dry_run={dry_run})'
    )

    try:
        confluence = get_confluence()
        page = _cu_append_page(
            confluence,
            page_id_or_title=page_id_or_title,
            input_file=input_file,
            space=space,
            version_message=version_message,
            dry_run=dry_run,
        )
        return ToolResult.success(page)
    except Exception as e:
        log.error(f'Failed to append to Confluence page: {e}')
        return ToolResult.failure(f'Confluence append failed: {e}')


@tool(
    description='Replace a section under a heading in a Confluence page'
)
def update_confluence_section(
    page_id_or_title: str,
    heading: str,
    input_file: str,
    space: Optional[str] = None,
    version_message: Optional[str] = None,
    dry_run: bool = False,
) -> ToolResult:
    '''
    Replace a section under a heading in a Confluence page.
    '''
    log.debug(
        f'update_confluence_section(page_id_or_title={page_id_or_title}, '
        f'heading={heading}, input_file={input_file}, space={space}, '
        f'version_message={version_message}, dry_run={dry_run})'
    )

    try:
        confluence = get_confluence()
        page = _cu_update_page_section(
            confluence,
            page_id_or_title=page_id_or_title,
            heading=heading,
            input_file=input_file,
            space=space,
            version_message=version_message,
            dry_run=dry_run,
        )
        return ToolResult.success(page)
    except Exception as e:
        log.error(f'Failed to update Confluence section: {e}')
        return ToolResult.failure(f'Confluence section update failed: {e}')


@tool(
    description='List child pages for a Confluence page, optionally recursively'
)
def list_confluence_children(
    page_id_or_title: str,
    space: Optional[str] = None,
    recursive: bool = False,
    max_depth: Optional[int] = None,
) -> ToolResult:
    '''
    List child pages for a Confluence page.
    '''
    log.debug(
        f'list_confluence_children(page_id_or_title={page_id_or_title}, '
        f'space={space}, recursive={recursive}, max_depth={max_depth})'
    )

    try:
        confluence = get_confluence()
        rows = (
            _cu_build_page_tree(
                confluence,
                page_id_or_title=page_id_or_title,
                space=space,
                max_depth=max_depth,
            )
            if recursive else
            _cu_list_page_children(
                confluence,
                page_id_or_title=page_id_or_title,
                space=space,
                recursive=False,
            )
        )
        return ToolResult.success(rows, count=len(rows))
    except Exception as e:
        log.error(f'Failed to list Confluence children: {e}')
        return ToolResult.failure(f'Confluence children lookup failed: {e}')


@tool(
    description='Export a Confluence page to a Markdown file with front matter'
)
def export_confluence_page(
    page_id_or_title: str,
    output_file: str,
    space: Optional[str] = None,
) -> ToolResult:
    '''
    Export a Confluence page to Markdown.
    '''
    log.debug(
        f'export_confluence_page(page_id_or_title={page_id_or_title}, '
        f'output_file={output_file}, space={space})'
    )

    try:
        confluence = get_confluence()
        page = _cu_export_page_to_markdown(
            confluence,
            page_id_or_title=page_id_or_title,
            output_file=output_file,
            space=space,
        )
        return ToolResult.success(page)
    except Exception as e:
        log.error(f'Failed to export Confluence page: {e}')
        return ToolResult.failure(f'Confluence export failed: {e}')


class ConfluenceTools(BaseTool):
    '''
    Collection of Confluence tools for agent use.
    '''

    @tool(description='Search Confluence pages by title pattern')
    def search_confluence_pages(
        self,
        pattern: str,
        limit: int = 25,
        space: Optional[str] = None,
    ) -> ToolResult:
        return search_confluence_pages(pattern, limit, space)

    @tool(description='Get a Confluence page by page ID or exact title')
    def get_confluence_page(
        self,
        page_id_or_title: str,
        space: Optional[str] = None,
        include_body: bool = False,
    ) -> ToolResult:
        return get_confluence_page(page_id_or_title, space, include_body)

    @tool(description='Create a Confluence page from a Markdown file')
    def create_confluence_page(
        self,
        title: str,
        input_file: str,
        space: Optional[str] = None,
        parent_id: Optional[str] = None,
        version_message: Optional[str] = None,
        dry_run: bool = False,
    ) -> ToolResult:
        return create_confluence_page(title, input_file, space, parent_id, version_message, dry_run)

    @tool(description='Update a Confluence page from a Markdown file')
    def update_confluence_page(
        self,
        page_id_or_title: str,
        input_file: str,
        space: Optional[str] = None,
        version_message: Optional[str] = None,
        dry_run: bool = False,
    ) -> ToolResult:
        return update_confluence_page(page_id_or_title, input_file, space, version_message, dry_run)

    @tool(description='Append Markdown content to an existing Confluence page')
    def append_to_confluence_page(
        self,
        page_id_or_title: str,
        input_file: str,
        space: Optional[str] = None,
        version_message: Optional[str] = None,
        dry_run: bool = False,
    ) -> ToolResult:
        return append_to_confluence_page(page_id_or_title, input_file, space, version_message, dry_run)

    @tool(description='Replace a section under a heading in a Confluence page')
    def update_confluence_section(
        self,
        page_id_or_title: str,
        heading: str,
        input_file: str,
        space: Optional[str] = None,
        version_message: Optional[str] = None,
        dry_run: bool = False,
    ) -> ToolResult:
        return update_confluence_section(page_id_or_title, heading, input_file, space, version_message, dry_run)

    @tool(description='List child pages for a Confluence page')
    def list_confluence_children(
        self,
        page_id_or_title: str,
        space: Optional[str] = None,
        recursive: bool = False,
        max_depth: Optional[int] = None,
    ) -> ToolResult:
        return list_confluence_children(page_id_or_title, space, recursive, max_depth)

    @tool(description='Export a Confluence page to Markdown')
    def export_confluence_page(
        self,
        page_id_or_title: str,
        output_file: str,
        space: Optional[str] = None,
    ) -> ToolResult:
        return export_confluence_page(page_id_or_title, output_file, space)
