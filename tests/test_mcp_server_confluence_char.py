import json

import pytest


def _payload(result):
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].type == 'text'
    return json.loads(result[0].text)


@pytest.mark.asyncio
async def test_search_confluence_pages_tool(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(import_mcp_server.confluence_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(
        import_mcp_server.confluence_utils,
        'search_pages',
        lambda _confluence, pattern, limit=25, space=None: [
            {'page_id': '123', 'title': 'Roadmap', 'link': 'https://example.test/page'}
        ],
    )

    result = await import_mcp_server.search_confluence_pages('Road', limit=5)
    data = _payload(result)

    assert data[0]['page_id'] == '123'
    assert data[0]['title'] == 'Roadmap'


@pytest.mark.asyncio
async def test_get_confluence_page_tool(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(import_mcp_server.confluence_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(
        import_mcp_server.confluence_utils,
        'get_page',
        lambda _confluence, page_id_or_title, space=None, include_body=False: {
            'page_id': '123',
            'title': 'Roadmap',
            'body_markdown': '# Roadmap\n',
            'labels': ['release'],
        },
    )

    result = await import_mcp_server.get_confluence_page('123', include_body=True)
    data = _payload(result)

    assert data['page_id'] == '123'
    assert data['labels'] == ['release']
    assert '# Roadmap' in data['body_markdown']


@pytest.mark.asyncio
async def test_create_confluence_page_tool(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(import_mcp_server.confluence_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(
        import_mcp_server.confluence_utils,
        'create_page',
        lambda _confluence, title, input_file, space=None, parent_id=None, version_message=None, dry_run=False: {
            'page_id': '456',
            'title': title,
            'link': 'https://example.test/page',
            'version': 1,
            'dry_run': dry_run,
        },
    )

    result = await import_mcp_server.create_confluence_page(
        title='Roadmap',
        input_file='plan.md',
        space='ENG',
    )
    data = _payload(result)

    assert data['page_id'] == '456'
    assert data['message'] == 'Page created successfully'


@pytest.mark.asyncio
async def test_create_confluence_page_dry_run_tool(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(import_mcp_server.confluence_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(
        import_mcp_server.confluence_utils,
        'create_page',
        lambda _confluence, title, input_file, space=None, parent_id=None, version_message=None, dry_run=False: {
            'page_id': 'preview',
            'title': title,
            'dry_run': dry_run,
        },
    )

    result = await import_mcp_server.create_confluence_page(
        title='Roadmap',
        input_file='plan.md',
        dry_run=True,
    )
    data = _payload(result)

    assert data['dry_run'] is True
    assert data['message'] == 'Page preview generated successfully'


@pytest.mark.asyncio
async def test_list_confluence_children_tool(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(import_mcp_server.confluence_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(
        import_mcp_server.confluence_utils,
        'build_page_tree',
        lambda _confluence, page_id_or_title, space=None, max_depth=None: [
            {'page_id': '100', 'title': 'Root', 'depth': 0},
            {'page_id': '101', 'title': 'Child', 'depth': 1},
        ],
    )

    result = await import_mcp_server.list_confluence_children('100', recursive=True, max_depth=1)
    data = _payload(result)

    assert data[0]['page_id'] == '100'
    assert data[1]['depth'] == 1


@pytest.mark.asyncio
async def test_update_confluence_page_tool_error(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(import_mcp_server.confluence_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(
        import_mcp_server.confluence_utils,
        'update_page',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('update failed')),
    )

    result = await import_mcp_server.update_confluence_page(
        page_id_or_title='123',
        input_file='plan.md',
    )
    data = _payload(result)

    assert 'update failed' in data['error']


@pytest.mark.asyncio
async def test_export_confluence_page_tool(import_mcp_server, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(import_mcp_server.confluence_utils, 'get_connection', lambda: object())
    monkeypatch.setattr(
        import_mcp_server.confluence_utils,
        'export_page_to_markdown',
        lambda _confluence, page_id_or_title, output_file, space=None: {
            'page_id': '123',
            'title': 'Roadmap',
            'output_file': output_file,
        },
    )

    result = await import_mcp_server.export_confluence_page('123', 'roadmap.md', space='ENG')
    data = _payload(result)

    assert data['output_file'] == 'roadmap.md'
    assert data['message'] == 'Page exported successfully'
