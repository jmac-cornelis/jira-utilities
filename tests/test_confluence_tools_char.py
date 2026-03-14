import pytest

from tools.confluence_tools import ConfluenceTools, search_confluence_pages


def test_search_confluence_pages_tool_returns_toolresult(monkeypatch: pytest.MonkeyPatch):
    from tools import confluence_tools

    monkeypatch.setattr(confluence_tools, 'get_confluence', lambda: object())
    monkeypatch.setattr(
        confluence_tools,
        '_cu_search_pages',
        lambda _confluence, pattern, limit=25, space=None: [
            {'page_id': '123', 'title': 'Roadmap', 'link': 'https://example.test/page'}
        ],
    )

    result = search_confluence_pages('Road', limit=5)

    assert result.is_success
    assert result.data[0]['page_id'] == '123'
    assert result.metadata['count'] == 1


def test_get_confluence_page_tool_returns_toolresult(monkeypatch: pytest.MonkeyPatch):
    from tools import confluence_tools

    monkeypatch.setattr(confluence_tools, 'get_confluence', lambda: object())
    monkeypatch.setattr(
        confluence_tools,
        '_cu_get_page',
        lambda _confluence, page_id_or_title, space=None, include_body=False: {
            'page_id': '123',
            'title': 'Roadmap',
            'body_markdown': '# Roadmap\n',
        },
    )

    result = confluence_tools.get_confluence_page('123', include_body=True)

    assert result.is_success
    assert result.data['page_id'] == '123'
    assert '# Roadmap' in result.data['body_markdown']


def test_confluence_tools_collection_registers_methods():
    tools = ConfluenceTools()

    assert tools.get_tool('search_confluence_pages') is not None
    assert tools.get_tool('get_confluence_page') is not None
    assert tools.get_tool('create_confluence_page') is not None
    assert tools.get_tool('update_confluence_page') is not None
    assert tools.get_tool('append_to_confluence_page') is not None
    assert tools.get_tool('update_confluence_section') is not None
    assert tools.get_tool('list_confluence_children') is not None
