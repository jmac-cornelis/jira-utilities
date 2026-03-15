from pathlib import Path

from tools.file_tools import FileTools, find_in_files, read_file


def test_read_file_supports_line_ranges(tmp_path: Path):
    sample = tmp_path / 'sample.txt'
    sample.write_text('alpha\nbeta\ngamma\ndelta', encoding='utf-8')

    result = read_file(str(sample), start_line=2, end_line=3)

    assert result.is_success
    assert result.data['content'] == 'beta\ngamma'
    assert result.data['selected_start_line'] == 2
    assert result.data['selected_end_line'] == 3


def test_read_file_supports_tail_and_max_chars(tmp_path: Path):
    sample = tmp_path / 'tail.txt'
    sample.write_text('one\ntwo\nthree\nfour', encoding='utf-8')

    result = read_file(str(sample), tail_lines=2, max_chars=7)

    assert result.is_success
    assert result.data['content'] == 'three\nf'
    assert result.data['truncated'] is True


def test_find_in_files_returns_matching_lines(tmp_path: Path):
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'alpha.py').write_text('needle here\nother line\n', encoding='utf-8')
    (src / 'beta.py').write_text('nothing\nneedle again\n', encoding='utf-8')

    result = find_in_files('needle', root=str(src), glob='*.py', limit=10)

    assert result.is_success
    matches = result.data['matches']
    assert len(matches) == 2
    assert {match['path'] for match in matches} == {'alpha.py', 'beta.py'}
    assert any(match['path'] == 'beta.py' and match['line_number'] == 2 for match in matches)


def test_file_tools_collection_registers_find_in_files():
    tools = FileTools()

    assert tools.get_tool('find_in_files') is not None
