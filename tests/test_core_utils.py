import csv
from typing import Any, cast

from core import utils as core_utils


def test_output_respects_quiet_mode_and_module_quiet_flag(capture_stdout):
    setattr(cast(Any, core_utils), '_quiet_mode', False)

    with capture_stdout() as out_visible:
        core_utils.output('visible')

    setattr(cast(Any, core_utils), '_quiet_mode', True)
    with capture_stdout() as out_hidden:
        core_utils.output('hidden')

    delattr(cast(Any, core_utils), '_quiet_mode')

    assert out_visible.getvalue().strip() == 'visible'
    assert out_hidden.getvalue() == ''


def test_validate_and_repair_csv_repairs_extra_and_short_rows(tmp_path):
    csv_path = tmp_path / 'bad.csv'
    csv_path.write_text(
        'key,summary,status\n'
        'STL-1,Hello, world,Open\n'
        'STL-2,Short\n',
        encoding='utf-8',
    )

    repaired, stats = core_utils.validate_and_repair_csv(str(csv_path))

    assert repaired is True
    assert stats['repaired_rows'] == 1
    assert stats['padded_rows'] == 1

    with csv_path.open('r', encoding='utf-8', newline='') as handle:
        rows = list(csv.reader(handle))

    assert rows[1] == ['STL-1', 'Hello, world', 'Open']
    assert rows[2] == ['STL-2', 'Short', '']


def test_validate_and_repair_csv_supports_output_file(tmp_path):
    source = tmp_path / 'source.csv'
    target = tmp_path / 'fixed.csv'
    source.write_text(
        'key,summary,status\n'
        'STL-1,Hello, world,Open\n',
        encoding='utf-8',
    )

    repaired, stats = core_utils.validate_and_repair_csv(str(source), str(target))

    assert repaired is True
    assert stats['repaired_rows'] == 1
    assert target.exists()

    with target.open('r', encoding='utf-8', newline='') as handle:
        rows = list(csv.reader(handle))
    assert rows[1] == ['STL-1', 'Hello, world', 'Open']


def test_extract_text_from_adf_handles_dict_string_none():
    adf = {
        'type': 'doc',
        'content': [
            {
                'type': 'paragraph',
                'content': [
                    {'type': 'text', 'text': 'First'},
                    {'type': 'text', 'text': ' second'},
                ],
            },
            {
                'type': 'paragraph',
                'content': [
                    {'type': 'text', 'text': 'Third'},
                ],
            },
        ],
    }

    assert core_utils.extract_text_from_adf(adf) == 'First\n second\nThird'
    assert core_utils.extract_text_from_adf('plain') == 'plain'
    assert core_utils.extract_text_from_adf(None) == ''
