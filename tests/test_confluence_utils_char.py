import json
from pathlib import Path
from typing import Any, Optional

import pytest

import confluence_utils


class _Response:
    def __init__(
        self,
        payload: Optional[dict[str, Any]] = None,
        status_code: int = 200,
        text: Optional[str] = None,
    ):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(self._payload)
        self.headers: dict[str, str] = {}

    def json(self) -> dict[str, Any]:
        return self._payload


class _Confluence:
    def __init__(self, responses: list[_Response]):
        self.base_url = 'https://example.atlassian.net/wiki'
        self.site_url = 'https://example.atlassian.net'
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, path: str, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._responses.pop(0)


def test_get_confluence_credentials_falls_back_to_jira_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv('CONFLUENCE_EMAIL', raising=False)
    monkeypatch.delenv('CONFLUENCE_API_TOKEN', raising=False)
    monkeypatch.setenv('JIRA_EMAIL', 'engineer@cornelisnetworks.com')
    monkeypatch.setenv('JIRA_API_TOKEN', 'token-123')

    email, token = confluence_utils.get_confluence_credentials()

    assert email == 'engineer@cornelisnetworks.com'
    assert token == 'token-123'


def test_markdown_to_storage_supports_common_blocks():
    storage = confluence_utils.markdown_to_storage(
        '# Release Notes\n\n'
        '- Item one\n'
        '- Item two\n\n'
        '```python\n'
        'print("hello")\n'
        '```\n'
    )

    assert '<h1>Release Notes</h1>' in storage
    assert '<ul><li>Item one</li><li>Item two</li></ul>' in storage
    assert 'ac:structured-macro ac:name="code"' in storage
    assert 'print("hello")' in storage


def test_storage_to_markdown_converts_code_macros():
    markdown = confluence_utils.storage_to_markdown(
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">python</ac:parameter>'
        '<ac:plain-text-body><![CDATA[print("hello")]]></ac:plain-text-body>'
        '</ac:structured-macro>'
    )

    assert markdown == '```python\nprint("hello")\n```\n'


def test_load_markdown_document_parses_front_matter_and_assets(tmp_path: Path):
    image_file = tmp_path / 'diagram.png'
    image_file.write_bytes(b'png')
    attachment_file = tmp_path / 'notes.pdf'
    attachment_file.write_bytes(b'pdf')
    markdown_file = tmp_path / 'page.md'
    markdown_file.write_text(
        '---\n'
        'title: Release Notes\n'
        'space: ENG\n'
        'parent: 12345\n'
        'version_message: refresh docs\n'
        'labels:\n'
        '  - release\n'
        'attachments:\n'
        '  - notes.pdf\n'
        '---\n\n'
        '# Header\n\n'
        '![Diagram](diagram.png)\n\n'
        '[Spec](notes.pdf)\n',
        encoding='utf-8',
    )

    document = confluence_utils.load_markdown_document(str(markdown_file))

    assert document.title == 'Release Notes'
    assert document.space == 'ENG'
    assert document.parent_id == '12345'
    assert document.version_message == 'refresh docs'
    assert document.labels == ['release']
    assert {item['filename'] for item in document.attachments} == {'diagram.png', 'notes.pdf'}
    assert 'ri:attachment ri:filename="diagram.png"' in document.body_storage
    assert 'ri:attachment ri:filename="notes.pdf"' in document.body_storage


def test_search_pages_returns_links_and_page_ids(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'output', lambda *_args, **_kwargs: None)

    confluence = _Confluence([
        _Response({
            'results': [
                {
                    'content': {
                        'id': '12345',
                        'title': 'Roadmap',
                        '_links': {'webui': '/spaces/ENG/pages/12345/Roadmap'},
                        'space': {'key': 'ENG', 'name': 'Engineering'},
                    }
                }
            ]
        })
    ])

    pages = confluence_utils.search_pages(confluence, 'Road', limit=5)

    assert pages == [
        {
            'id': '12345',
            'page_id': '12345',
            'title': 'Roadmap',
            'link': 'https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Roadmap',
            'url': 'https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Roadmap',
            'space_key': 'ENG',
            'space_name': 'Engineering',
        }
    ]
    assert confluence.calls[0][1] == '/rest/api/content/search'


def test_search_pages_accepts_space_filter(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'output', lambda *_args, **_kwargs: None)

    confluence = _Confluence([_Response({'results': []})])

    confluence_utils.search_pages(confluence, 'Road', limit=5, space='ENG')

    assert 'space = "ENG"' in confluence.calls[0][2]['params']['cql']


def test_create_page_resolves_space_and_posts_storage_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(confluence_utils, 'output', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(confluence_utils, '_upload_attachments', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(confluence_utils, '_apply_page_labels', lambda *_args, **_kwargs: None)
    input_file = tmp_path / 'page.md'
    input_file.write_text('# Title\n\nBody text\n', encoding='utf-8')

    confluence = _Confluence([
        _Response({'results': [{'id': '42'}]}),
        _Response({
            'id': '123',
            'title': 'Roadmap',
            'status': 'current',
            'spaceId': '42',
            'version': {'number': 1},
        }),
    ])

    page = confluence_utils.create_page(
        confluence,
        title='Roadmap',
        input_file=str(input_file),
        space='ENG',
    )

    assert page['page_id'] == '123'
    assert page['link'].endswith('pageId=123')

    create_call = confluence.calls[1]
    assert create_call[0] == 'POST'
    assert create_call[1] == '/api/v2/pages'
    assert create_call[2]['params'] == {'root-level': 'true'}
    assert create_call[2]['json']['spaceId'] == '42'
    assert create_call[2]['json']['body']['representation'] == 'storage'
    assert '<h1>Title</h1>' in create_call[2]['json']['body']['value']


def test_update_page_resolves_title_and_increments_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(confluence_utils, 'output', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(confluence_utils, '_upload_attachments', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(confluence_utils, '_apply_page_labels', lambda *_args, **_kwargs: None)
    input_file = tmp_path / 'page.md'
    input_file.write_text('Updated **body**\n', encoding='utf-8')

    confluence = _Confluence([
        _Response({
            'results': [
                {
                    'content': {
                        'id': '123',
                        'title': 'Roadmap',
                        '_links': {'webui': '/spaces/ENG/pages/123/Roadmap'},
                        'space': {'key': 'ENG'},
                    }
                }
            ]
        }),
        _Response({
            'id': '123',
            'title': 'Roadmap',
            'status': 'current',
            'spaceId': '42',
            'version': {'number': 7},
        }),
        _Response({
            'id': '123',
            'title': 'Roadmap',
            'status': 'current',
            'spaceId': '42',
            'version': {'number': 8},
        }),
    ])

    page = confluence_utils.update_page(
        confluence,
        page_id_or_title='Roadmap',
        input_file=str(input_file),
        space='ENG',
        version_message='refresh page',
    )

    assert page['page_id'] == '123'
    assert page['version'] == 8

    search_call = confluence.calls[0]
    assert 'title = "Roadmap"' in search_call[2]['params']['cql']
    assert 'space = "ENG"' in search_call[2]['params']['cql']

    update_call = confluence.calls[2]
    assert update_call[0] == 'PUT'
    assert update_call[1] == '/api/v2/pages/123'
    assert update_call[2]['json']['version']['number'] == 8
    assert update_call[2]['json']['version']['message'] == 'refresh page'
    assert '<strong>body</strong>' in update_call[2]['json']['body']['value']


def test_get_page_include_body_converts_storage(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'output', lambda *_args, **_kwargs: None)

    confluence = _Confluence([
        _Response({
            'id': '123',
            'title': 'Roadmap',
            'status': 'current',
            'spaceId': '42',
            'version': {'number': 2},
            'body': {'storage': {'value': '<h1>Roadmap</h1><p>Hello <strong>team</strong></p>'}},
            'labels': {'results': [{'name': 'release'}]},
        })
    ])

    page = confluence_utils.get_page(confluence, '123', include_body=True)

    assert page['page_id'] == '123'
    assert page['labels'] == ['release']
    assert page['body_storage'].startswith('<h1>Roadmap</h1>')
    assert '# Roadmap' in page['body_markdown']
    assert '**team**' in page['body_markdown']


def test_append_page_dry_run_returns_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'output', lambda *_args, **_kwargs: None)
    input_file = tmp_path / 'append.md'
    input_file.write_text('## Updates\n\nExtra text\n', encoding='utf-8')

    confluence = _Confluence([
        _Response({
            'id': '123',
            'title': 'Roadmap',
            'status': 'current',
            'spaceId': '42',
            'version': {'number': 2},
            'body': {'storage': {'value': '<h1>Roadmap</h1><p>Existing</p>'}},
        })
    ])

    preview = confluence_utils.append_page(
        confluence,
        page_id_or_title='123',
        input_file=str(input_file),
        dry_run=True,
    )

    assert preview['dry_run'] is True
    assert preview['version'] == 3
    assert 'Existing' in preview['body_markdown']
    assert '## Updates' in preview['body_markdown']
    assert len(confluence.calls) == 1


def test_update_page_section_replaces_target_heading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'output', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(confluence_utils, '_upload_attachments', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(confluence_utils, '_apply_page_labels', lambda *_args, **_kwargs: None)
    input_file = tmp_path / 'section.md'
    input_file.write_text('Replacement body\n', encoding='utf-8')

    confluence = _Confluence([
        _Response({
            'id': '123',
            'title': 'Roadmap',
            'status': 'current',
            'spaceId': '42',
            'version': {'number': 4},
            'body': {
                'storage': {
                    'value': '<h1>Intro</h1><p>Old intro</p><h2>Status</h2><p>Old status</p><h2>Next</h2><p>Keep me</p>'
                }
            },
        }),
        _Response({
            'id': '123',
            'title': 'Roadmap',
            'status': 'current',
            'spaceId': '42',
            'version': {'number': 5},
        }),
    ])

    page = confluence_utils.update_page_section(
        confluence,
        page_id_or_title='123',
        heading='Status',
        input_file=str(input_file),
        dry_run=False,
    )

    assert page['page_id'] == '123'
    update_call = confluence.calls[1]
    assert '<h2>Status</h2><p>Replacement body</p><h2>Next</h2>' in update_call[2]['json']['body']['value']
    assert 'Old status' not in update_call[2]['json']['body']['value']


def test_export_page_to_markdown_writes_front_matter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'output', lambda *_args, **_kwargs: None)

    confluence = _Confluence([
        _Response({
            'id': '123',
            'title': 'Roadmap',
            'status': 'current',
            'spaceId': '42',
            'version': {'number': 2},
            'body': {'storage': {'value': '<h1>Roadmap</h1><p>Hello</p>'}},
            'labels': {'results': [{'name': 'release'}]},
        }),
        _Response({'key': 'ENG'}),
    ])
    output_file = tmp_path / 'roadmap.md'

    result = confluence_utils.export_page_to_markdown(
        confluence,
        page_id_or_title='123',
        output_file=str(output_file),
    )

    content = output_file.read_text(encoding='utf-8')
    assert result['output_file'] == str(output_file)
    assert 'title: Roadmap' in content
    assert 'space: ENG' in content
    assert '# Roadmap' in content


def test_build_page_tree_returns_root_and_children(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'output', lambda *_args, **_kwargs: None)

    confluence = _Confluence([
        _Response({
            'id': '100',
            'title': 'Root',
            'status': 'current',
            'spaceId': '42',
            'version': {'number': 1},
        })
    ])
    monkeypatch.setattr(
        confluence_utils,
        '_collect_paginated_results',
        lambda _confluence, path, params=None: (
            [
                {'id': '101', 'title': 'Child', 'status': 'current', 'spaceId': '42', 'version': {'number': 1}}
            ]
            if path.endswith('/100/children') else []
        ),
    )

    tree = confluence_utils.build_page_tree(confluence, '100', max_depth=1)

    assert tree[0]['title'] == 'Root'
    assert tree[0]['depth'] == 0
    assert tree[1]['title'] == 'Child'
    assert tree[1]['depth'] == 1


def test_handle_args_create_accepts_inline_space(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'load_dotenv', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        confluence_utils.sys,
        'argv',
        ['confluence_utils.py', '--create', 'Roadmap', 'ENG', 'page.md'],
    )

    args = confluence_utils.handle_args()

    assert args.create == ['Roadmap', 'page.md']
    assert args.space == 'ENG'


def test_handle_args_create_accepts_front_matter_only_file(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'load_dotenv', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        confluence_utils.sys,
        'argv',
        ['confluence_utils.py', '--create', 'page.md'],
    )

    args = confluence_utils.handle_args()

    assert args.create == ['page.md']


def test_handle_args_create_keeps_space_flag_compatibility(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'load_dotenv', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        confluence_utils.sys,
        'argv',
        ['confluence_utils.py', '--create', 'Roadmap', 'page.md', '--space', 'ENG'],
    )

    args = confluence_utils.handle_args()

    assert args.create == ['Roadmap', 'page.md']
    assert args.space == 'ENG'


def test_handle_args_search_accepts_inline_space(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'load_dotenv', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        confluence_utils.sys,
        'argv',
        ['confluence_utils.py', '--search', 'Roadmap', 'ENG'],
    )

    args = confluence_utils.handle_args()

    assert args.search == ['Roadmap']
    assert args.space == 'ENG'


def test_handle_args_get_rejects_body_without_get(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'load_dotenv', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        confluence_utils.sys,
        'argv',
        ['confluence_utils.py', '--search', 'Roadmap', '--body'],
    )

    with pytest.raises(SystemExit):
        confluence_utils.handle_args()


def test_handle_args_rejects_conflicting_create_space(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(confluence_utils, 'load_dotenv', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        confluence_utils.sys,
        'argv',
        [
            'confluence_utils.py',
            '--create',
            'Roadmap',
            'ENG',
            'page.md',
            '--space',
            'DOCS',
        ],
    )

    with pytest.raises(SystemExit):
        confluence_utils.handle_args()
