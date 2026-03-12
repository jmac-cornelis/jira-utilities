import csv
import inspect
import logging
import re
from itertools import combinations
from typing import Any, Optional


def output(message: str = '', quiet_mode: bool = False) -> None:
    caller_globals: dict[str, Any] = {}
    caller_locals: dict[str, Any] = {}
    caller_file = __file__

    frame = inspect.currentframe()
    try:
        caller = frame.f_back if frame else None
        if caller is not None:
            caller_globals = caller.f_globals
            caller_locals = caller.f_locals
            caller_file = caller_globals.get('__file__', __file__)
    finally:
        del frame

    effective_quiet = bool(caller_globals.get('_quiet_mode', quiet_mode))
    logger = caller_globals.get('log')
    file_handler = caller_globals.get('fh')

    if '_quiet_mode' not in caller_globals:
        module_candidates = []
        seen_ids = set()
        for namespace in (caller_locals, caller_globals):
            for value in namespace.values():
                if not inspect.ismodule(value):
                    continue
                module_id = id(value)
                if module_id in seen_ids:
                    continue
                seen_ids.add(module_id)
                if getattr(value, 'output', None) is output:
                    module_candidates.append(value)

        for module in module_candidates:
            module_quiet = getattr(module, '_quiet_mode', None)
            module_logger = getattr(module, 'log', None)
            module_handler = getattr(module, 'fh', None)
            if module_quiet is not None or module_logger is not None or module_handler is not None:
                effective_quiet = bool(module_quiet if module_quiet is not None else quiet_mode)
                logger = module_logger if module_logger is not None else logger
                file_handler = module_handler if module_handler is not None else file_handler
                caller_file = getattr(module, '__file__', caller_file)
                break

    if message and logger is not None and file_handler is not None:
        try:
            record = logging.LogRecord(
                name=getattr(logger, 'name', __name__),
                level=logging.INFO,
                pathname=caller_file,
                lineno=0,
                msg=f'OUTPUT: {message}',
                args=(),
                exc_info=None,
                func='output',
            )
            file_handler.emit(record)
        except Exception:
            pass

    if not effective_quiet:
        print(message)


def validate_and_repair_csv(input_file: str, output_file: Optional[str] = None) -> tuple[bool, dict[str, int]]:
    with open(input_file, 'r', encoding='utf-8', newline='') as f:
        raw_rows = list(csv.reader(f))

    if len(raw_rows) < 2:
        row_count = max(len(raw_rows) - 1, 0)
        return False, {
            'total_rows': row_count,
            'ok_rows': row_count,
            'repaired_rows': 0,
            'padded_rows': 0,
            'unfixable_rows': 0,
        }

    header = raw_rows[0]
    expected = len(header)

    jira_key_re = re.compile(r'^[A-Z]{2,10}-\d+$')
    known_values = {
        'issue_type': {
            'bug', 'story', 'task', 'epic', 'sub-task', 'subtask',
            'improvement', 'new feature', 'change request',
        },
        'status': {
            'open', 'in progress', 'closed', 'verify', 'ready',
            'to do', 'done', 'resolved', 'reopened', 'in review',
        },
        'priority': {
            'p0-stopper', 'p1-critical', 'p2-major', 'p3-minor',
            'p4-trivial', 'blocker', 'critical', 'major', 'minor', 'trivial',
        },
        'project': {'stl', 'stlsb', 'cn', 'opx'},
        'product': {'nic', 'switch'},
        'module': {'driver', 'bts', 'fw', 'opx', 'gpu'},
    }

    def score_alignment(fields: list[str], header_list: list[str]) -> int:
        score = 0
        for i, hdr in enumerate(header_list):
            if i >= len(fields):
                break
            val = (fields[i] or '').strip()
            hdr_low = hdr.strip().lower()

            if hdr_low == 'key' and jira_key_re.match(val):
                score += 10
            elif hdr_low in known_values and val.lower() in known_values[hdr_low]:
                score += 5
            elif hdr_low == 'updated' and re.match(r'^\d{4}-\d{2}-\d{2}', val):
                score += 5
            elif val and hdr_low in ('customer', 'summary', 'assignee', 'fix_version'):
                score += 1
        return score

    stats = {
        'total_rows': len(raw_rows) - 1,
        'ok_rows': 0,
        'repaired_rows': 0,
        'padded_rows': 0,
        'unfixable_rows': 0,
    }
    any_changed = False

    for row_idx in range(1, len(raw_rows)):
        fields = raw_rows[row_idx]
        n = len(fields)

        if n == expected:
            stats['ok_rows'] += 1
            continue

        if n < expected:
            fields.extend([''] * (expected - n))
            raw_rows[row_idx] = fields
            stats['padded_rows'] += 1
            any_changed = True
            continue

        extra = n - expected
        best_score = -1
        best_fields = None

        if extra <= 4:
            merge_candidates = list(range(n - 1))
            for merge_points in combinations(merge_candidates, extra):
                candidate: list[str] = []
                i = 0
                while i < n:
                    if i in merge_points:
                        merged = fields[i]
                        while i in merge_points:
                            i += 1
                            if i < n:
                                merged += ',' + fields[i]
                        candidate.append(merged)
                    else:
                        candidate.append(fields[i])
                    i += 1

                if len(candidate) != expected:
                    continue

                score = score_alignment(candidate, header)
                if score > best_score:
                    best_score = score
                    best_fields = candidate
        else:
            best_fields = fields[: expected - 1]
            best_fields.append(','.join(fields[expected - 1 :]))

        if best_fields and len(best_fields) == expected:
            raw_rows[row_idx] = best_fields
            stats['repaired_rows'] += 1
            any_changed = True
        else:
            stats['unfixable_rows'] += 1

    target_file = output_file or input_file
    should_write = any_changed or (output_file is not None and output_file != input_file)

    if should_write:
        with open(target_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(raw_rows)

    return any_changed, stats


def extract_text_from_adf(adf_content: Any) -> str:
    if adf_content is None:
        return ''

    if isinstance(adf_content, str):
        return adf_content

    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get('type') == 'text':
                parts.append(node.get('text', ''))
            for child in node.get('content', []):
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(adf_content)

    return '\n'.join(parts) if parts else str(adf_content)
