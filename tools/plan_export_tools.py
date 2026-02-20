##########################################################################################
#
# Module: tools/plan_export_tools.py
#
# Description: Converts a feature-plan JSON (as produced by FeaturePlanBuilderAgent) into
#              the standard CSV / Excel format used by jira_utils.dump_tickets_to_file().
#
#              Works as:
#                1. An @tool()-decorated function usable inside the agentic pipeline.
#                2. A standalone CLI:  python -m tools.plan_export_tools plan.json [-o out.csv]
#
# Author: Cornelis Networks
#
##########################################################################################

import csv
import json
import logging
import os
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful import of the @tool decorator (mirrors pattern in excel_tools.py)
# ---------------------------------------------------------------------------
try:
    from tools.base import tool, ToolResult, BaseTool
except ImportError:
    log.warning('tools.base not available; plan_export_tools will not register @tool decorators')

    def tool(**kwargs):  # type: ignore[misc]
        '''No-op decorator fallback when tools.base is unavailable.'''
        def _identity(fn):
            return fn
        return _identity

    class ToolResult:  # type: ignore[no-redef]
        '''Minimal stub so the module can still be imported standalone.'''
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        @classmethod
        def success(cls, data=None, message=''):
            return cls(status='success', data=data or {}, message=message, error=None)

        @classmethod
        def error(cls, error='', data=None):
            return cls(status='error', data=data or {}, message='', error=error)

    class BaseTool:  # type: ignore[no-redef]
        pass


# ---------------------------------------------------------------------------
# Constants — base CSV columns matching jira_utils.dump_tickets_to_file()
# ---------------------------------------------------------------------------
BASE_FIELDS: List[str] = [
    'key', 'project', 'issue_type', 'status', 'priority', 'summary',
    'assignee', 'reporter', 'created', 'updated', 'resolved',
    'fix_version', 'affects_version', 'component', 'customer',
]

# Extra columns specific to feature-plan exports (appended after base fields)
PLAN_EXTRA_FIELDS: List[str] = [
    'depth',
    'complexity',
    'confidence',
    'labels',
    'acceptance_criteria',
    'dependencies',
    'parent_epic',
]


# ============================================================================
# Core conversion logic (pure function — no I/O)
# ============================================================================

def plan_json_to_rows(
    plan: Dict[str, Any],
    *,
    include_description: bool = False,
) -> List[Dict[str, str]]:
    '''Convert a feature-plan dict into a flat list of row dicts.

    Each row uses the same column vocabulary as jira_utils.dump_tickets_to_file()
    so the output can be consumed by bulk_update_tickets, convert_from_csv (Excel),
    or any other downstream tool that expects that schema.

    Args:
        plan: The feature-plan dict (as stored in feature_plan.json).
        include_description: If True, add a ``description`` extra column with the
            full ticket description text.  Defaults to False because descriptions
            can be very long and make the CSV unwieldy.

    Returns:
        List of row dicts keyed by column name.
    '''
    rows: List[Dict[str, str]] = []
    project_key = plan.get('project_key', '')

    for epic_idx, epic in enumerate(plan.get('epics', [])):
        # ----- Epic row -----
        epic_row: Dict[str, str] = {
            'key':              epic.get('key') or '',
            'project':          project_key,
            'issue_type':       'Epic',
            'status':           '',          # not yet created
            'priority':         '',
            'summary':          epic.get('summary', ''),
            'assignee':         '',
            'reporter':         '',
            'created':          '',
            'updated':          '',
            'resolved':         '',
            'fix_version':      '',
            'affects_version':  '',
            'component':        '; '.join(epic.get('components') or []),
            'customer':         '',
            # Plan-specific extras
            'depth':            '0',
            'complexity':       '',
            'confidence':       '',
            'labels':           '; '.join(epic.get('labels') or []),
            'acceptance_criteria': '',
            'dependencies':     '',
            'parent_epic':      '',
        }
        if include_description:
            epic_row['description'] = epic.get('description', '')

        rows.append(epic_row)

        # ----- Story rows under this Epic -----
        for story in epic.get('stories', []):
            story_row: Dict[str, str] = {
                'key':              story.get('key') or '',
                'project':          project_key,
                'issue_type':       'Story',
                'status':           '',
                'priority':         '',
                'summary':          story.get('summary', ''),
                'assignee':         story.get('assignee') or '',
                'reporter':         '',
                'created':          '',
                'updated':          '',
                'resolved':         '',
                'fix_version':      '',
                'affects_version':  '',
                'component':        '; '.join(story.get('components') or []),
                'customer':         '',
                # Plan-specific extras
                'depth':            '1',
                'complexity':       story.get('complexity', ''),
                'confidence':       story.get('confidence', ''),
                'labels':           '; '.join(story.get('labels') or []),
                'acceptance_criteria': '; '.join(story.get('acceptance_criteria') or []),
                'dependencies':     '; '.join(story.get('dependencies') or []),
                'parent_epic':      epic.get('summary', ''),
            }
            if include_description:
                story_row['description'] = story.get('description', '')

            rows.append(story_row)

    return rows


def _resolve_output_path(input_path: str, output_path: Optional[str], fmt: str) -> str:
    '''Derive the output file path from the input path when not explicitly given.'''
    if output_path:
        return output_path
    base, _ = os.path.splitext(input_path)
    return f'{base}.csv' if fmt == 'csv' else f'{base}.xlsx'


# ============================================================================
# CSV / Excel writers
# ============================================================================

def write_plan_csv(
    rows: List[Dict[str, str]],
    output_path: str,
    *,
    table_format: str = 'flat',
) -> str:
    '''Write plan rows to a CSV file using the jira_utils column convention.

    Args:
        rows: List of row dicts (from plan_json_to_rows).
        output_path: Destination file path.
        table_format: ``'flat'`` (default) keeps depth as a regular column;
            ``'indented'`` replaces the key column with per-depth columns
            (Depth 0, Depth 1, …) matching jira_utils indented format.

    Returns:
        The resolved output path.
    '''
    if not rows:
        # Write header-only CSV
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(BASE_FIELDS)
        log.info(f'Wrote empty CSV (headers only) to: {output_path}')
        return output_path

    # Determine which extra columns are actually populated
    all_keys = set(BASE_FIELDS)
    for r in rows:
        all_keys.update(r.keys())
    extra_columns = sorted(k for k in all_keys if k not in BASE_FIELDS)

    # ------------------------------------------------------------------
    # Indented table format: replace key + depth with Depth N columns
    # ------------------------------------------------------------------
    if table_format == 'indented' and any(r.get('depth') for r in rows):
        max_depth = 0
        for r in rows:
            try:
                max_depth = max(max_depth, int(r.get('depth', 0)))
            except (ValueError, TypeError):
                pass

        depth_columns = [f'Depth {i}' for i in range(max_depth + 1)]
        content_fields = [f for f in BASE_FIELDS if f != 'key']
        # Remove 'depth' from extras since it is represented by depth columns
        indented_extras = [c for c in extra_columns if c != 'depth']
        fieldnames = depth_columns + content_fields + indented_extras

        indented_rows: List[Dict[str, str]] = []
        for r in rows:
            new_row: Dict[str, str] = {}
            d = 0
            try:
                d = int(r.get('depth', 0))
            except (ValueError, TypeError):
                d = 0
            for col in depth_columns:
                new_row[col] = ''
            new_row[f'Depth {d}'] = r.get('key', '') or r.get('summary', '')

            for f in content_fields:
                new_row[f] = r.get(f, '')
            for col in indented_extras:
                new_row[col] = r.get(col, '')
            indented_rows.append(new_row)

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(indented_rows)

        log.info(f'Wrote {len(indented_rows)} rows (indented, max depth {max_depth}) to: {output_path}')
        return output_path

    # ------------------------------------------------------------------
    # Flat table format (default)
    # ------------------------------------------------------------------
    fieldnames = BASE_FIELDS + extra_columns
    # Ensure every row has all fields
    for r in rows:
        for col in fieldnames:
            r.setdefault(col, '')

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    log.info(f'Wrote {len(rows)} rows (flat) to: {output_path}')
    return output_path


def write_plan_excel(
    rows: List[Dict[str, str]],
    output_path: str,
    *,
    table_format: str = 'flat',
) -> str:
    '''Write plan rows to an Excel file, delegating to jira_utils._write_excel().

    Falls back to CSV if openpyxl / jira_utils is unavailable.

    Returns:
        The resolved output path.
    '''
    try:
        from jira_utils import _write_excel
        _write_excel(rows, output_path, extra_fields=None, table_format=table_format)
        log.info(f'Wrote {len(rows)} rows (Excel, {table_format}) to: {output_path}')
        return output_path
    except ImportError:
        log.warning('jira_utils._write_excel not available; falling back to CSV')
        csv_path = output_path.replace('.xlsx', '.csv')
        return write_plan_csv(rows, csv_path, table_format=table_format)


# ============================================================================
# @tool-decorated entry point for the agentic pipeline
# ============================================================================

@tool(
    name='plan_to_csv',
    description=(
        'Convert a feature-plan JSON file (as produced by the Feature Planning pipeline) '
        'into a CSV file matching the standard Jira CSV format used by dump_tickets_to_file(). '
        'Supports flat and indented table formats. Returns the output file path.'
    ),
    parameters={
        'input_path': 'Path to the feature-plan JSON file (e.g. feature_plan.json)',
        'output_path': 'Optional output CSV path. Defaults to <input_basename>.csv',
        'table_format': "Table layout: 'flat' (default) or 'indented'",
        'include_description': 'Include full description column (default: false)',
        'output_format': "Output format: 'csv' (default) or 'excel'",
    },
)
def plan_to_csv(
    input_path: str,
    output_path: str = '',
    table_format: str = 'flat',
    include_description: bool = False,
    output_format: str = 'csv',
) -> ToolResult:
    '''Convert a feature-plan JSON to the standard Jira CSV/Excel format.

    Args:
        input_path: Path to the feature-plan JSON file.
        output_path: Destination file path (auto-derived if empty).
        table_format: 'flat' or 'indented'.
        include_description: Whether to include the description column.
        output_format: 'csv' or 'excel'.

    Returns:
        ToolResult with the output file path and row count.
    '''
    # --- Validate input ---
    if not os.path.exists(input_path):
        return ToolResult.error(error=f'Input file not found: {input_path}')

    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            plan = json.load(f)
    except json.JSONDecodeError as e:
        return ToolResult.error(error=f'Invalid JSON in {input_path}: {e}')

    # --- Convert ---
    rows = plan_json_to_rows(plan, include_description=include_description)
    if not rows:
        return ToolResult.error(error='Plan contains no epics or stories')

    # --- Resolve output path ---
    fmt = output_format.lower().strip()
    resolved = _resolve_output_path(input_path, output_path or None, fmt)

    # --- Write ---
    try:
        if fmt == 'excel':
            written_path = write_plan_excel(rows, resolved, table_format=table_format)
        else:
            written_path = write_plan_csv(rows, resolved, table_format=table_format)
    except Exception as e:
        return ToolResult.error(error=f'Failed to write output: {e}')

    return ToolResult.success(
        data={
            'output_path': written_path,
            'total_rows': len(rows),
            'epics': sum(1 for r in rows if r.get('issue_type') == 'Epic'),
            'stories': sum(1 for r in rows if r.get('issue_type') == 'Story'),
            'format': fmt,
            'table_format': table_format,
        },
        message=f'Exported {len(rows)} rows to {written_path}',
    )


@tool(
    name='plan_json_to_dict_rows',
    description=(
        'Convert a feature-plan JSON (dict or file path) into a list of flat row dicts '
        'matching the standard Jira CSV schema. Useful for in-memory pipeline processing '
        'without writing to disk.'
    ),
    parameters={
        'plan_or_path': 'Either a dict (the plan) or a string file path to the JSON',
        'include_description': 'Include full description text (default: false)',
    },
)
def plan_json_to_dict_rows(
    plan_or_path,
    include_description: bool = False,
) -> ToolResult:
    '''Return plan rows as a list of dicts (no file I/O).

    Args:
        plan_or_path: A dict (the plan itself) or a string path to a JSON file.
        include_description: Whether to include the description column.

    Returns:
        ToolResult whose data['rows'] is the list of row dicts.
    '''
    # Accept either a dict or a file path
    if isinstance(plan_or_path, str):
        if not os.path.exists(plan_or_path):
            return ToolResult.error(error=f'File not found: {plan_or_path}')
        try:
            with open(plan_or_path, 'r', encoding='utf-8') as f:
                plan = json.load(f)
        except json.JSONDecodeError as e:
            return ToolResult.error(error=f'Invalid JSON: {e}')
    elif isinstance(plan_or_path, dict):
        plan = plan_or_path
    else:
        return ToolResult.error(error=f'Expected dict or file path, got {type(plan_or_path).__name__}')

    rows = plan_json_to_rows(plan, include_description=include_description)
    return ToolResult.success(
        data={
            'rows': rows,
            'total_rows': len(rows),
            'epics': sum(1 for r in rows if r.get('issue_type') == 'Epic'),
            'stories': sum(1 for r in rows if r.get('issue_type') == 'Story'),
        },
        message=f'Converted plan to {len(rows)} rows',
    )


# ============================================================================
# BaseTool class for agent registration
# ============================================================================

class PlanExportTools(BaseTool):
    '''Collection of plan-export tools for agent use.'''

    @tool(description='Convert a feature-plan JSON to Jira-compatible CSV')
    def plan_to_csv(self, input_path: str, output_path: str = '',
                    table_format: str = 'flat', include_description: bool = False,
                    output_format: str = 'csv') -> ToolResult:
        return plan_to_csv(input_path, output_path, table_format,
                           include_description, output_format)

    @tool(description='Convert a feature-plan JSON to flat row dicts (in-memory)')
    def plan_json_to_dict_rows(self, plan_or_path, include_description: bool = False) -> ToolResult:
        return plan_json_to_dict_rows(plan_or_path, include_description)


# ============================================================================
# Standalone CLI entry point
# ============================================================================

def _cli_main() -> None:
    '''CLI entry point: python -m tools.plan_export_tools <input.json> [options]'''
    import argparse

    parser = argparse.ArgumentParser(
        prog='plan_export_tools',
        description='Convert a feature-plan JSON to Jira-compatible CSV/Excel.',
    )
    parser.add_argument(
        'input',
        help='Path to the feature-plan JSON file',
    )
    parser.add_argument(
        '-o', '--output',
        default='',
        help='Output file path (default: <input_basename>.csv)',
    )
    parser.add_argument(
        '-f', '--format',
        choices=['csv', 'excel'],
        default='csv',
        help='Output format (default: csv)',
    )
    parser.add_argument(
        '-t', '--table-format',
        choices=['flat', 'indented'],
        default='flat',
        help="Table layout: 'flat' (default) or 'indented'",
    )
    parser.add_argument(
        '--include-description',
        action='store_true',
        default=False,
        help='Include the full description column',
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        default=False,
        help='Enable verbose logging',
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)-8s %(message)s',
    )

    result = plan_to_csv(
        input_path=args.input,
        output_path=args.output,
        table_format=args.table_format,
        include_description=args.include_description,
        output_format=args.format,
    )

    # Print result (works with both real ToolResult and stub)
    if hasattr(result, 'error') and result.error:
        print(f'ERROR: {result.error}')
        raise SystemExit(1)

    data = result.data if hasattr(result, 'data') else {}
    print(f'Output:  {data.get("output_path", "?")}')
    print(f'Rows:    {data.get("total_rows", 0)}')
    print(f'Epics:   {data.get("epics", 0)}')
    print(f'Stories: {data.get("stories", 0)}')
    print(f'Format:  {data.get("format", "?")} ({data.get("table_format", "?")})')


if __name__ == '__main__':
    _cli_main()
