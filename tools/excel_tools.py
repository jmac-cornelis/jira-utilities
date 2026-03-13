##########################################################################################
#
# Module: tools/excel_tools.py
#
# Description: Agent tool wrappers for Excel map building and Excel utility operations.
#              Wraps the build-excel-map pipeline from pm_agent.py and excel_utils.py
#              functions as agent-callable tools.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys

log = logging.getLogger(os.path.basename(sys.argv[0]))

from typing import List, Optional

from tools.base import tool, ToolResult, BaseTool

_excel_utils_available = False
excel_utils = None

try:
    import excel_utils as _excel_utils_module
    excel_utils = _excel_utils_module
    _excel_utils_available = True
except ImportError:
    log.debug('excel_utils not available for excel_tools')


def _require_excel_utils():
    if excel_utils is None:
        raise RuntimeError('excel_utils is not available')
    return excel_utils


def _excel_attr(name):
    excel_mod = _require_excel_utils()
    return getattr(excel_mod, name)


def _failure_result(message):
    return ToolResult.failure(message)


def _success_result(data):
    return ToolResult.success(data)


# ****************************************************************************************
# Agent tools
# ****************************************************************************************

@tool(
    description='Build a multi-sheet Excel workbook mapping one or more root tickets and '
                'all their related issues child hierarchies.  Sheet 1 ("Tickets") is a '
                'flat overview of root + first-level children.  Sheets 2..N are per-ticket '
                'children with unlimited depth (indented format).',
    parameters={
        'ticket_keys': 'List of root Jira ticket keys (e.g., ["STL-74071", "STL-76297"])',
        'limit': 'Optional max tickets per step',
        'output_file': 'Output filename (default: {ticket_key}.xlsx)',
    }
)
def build_excel_map(
    ticket_keys: List[str],
    hierarchy_depth: int = 1,
    limit: Optional[int] = None,
    output_file: Optional[str] = None,
) -> ToolResult:
    if not _excel_utils_available:
        return ToolResult.failure('excel_utils is not available')

    try:
        build_excel_map_fn = _excel_attr('build_excel_map')
        result = build_excel_map_fn(
            ticket_keys=ticket_keys,
            hierarchy_depth=hierarchy_depth,
            limit=limit,
            output_file=output_file,
        )
        return ToolResult.success(result)
    except Exception as e:
        log.error(f'build_excel_map failed: {e}', exc_info=True)
        return ToolResult.failure(str(e))


@tool(
    description='Concatenate multiple Excel files into one using merge-sheet or add-sheet method.',
    parameters={
        'input_files': 'List of Excel file paths to concatenate',
        'output_file': 'Output Excel file path',
        'method': 'Concatenation method: merge-sheet or add-sheet',
    }
)
def concat_excel(
    input_files: List[str],
    output_file: str,
    method: str = 'merge-sheet',
) -> ToolResult:
    '''
    Concatenate multiple Excel files into one workbook.

    Input:
        input_files: List of Excel file paths.
        output_file: Output file path.
        method: 'merge-sheet' (combine all into one sheet) or 'add-sheet' (each file as a sheet).

    Output:
        ToolResult with the output file path.
    '''
    if not _excel_utils_available:
        return ToolResult.failure('excel_utils is not available')

    try:
        concat_merge_sheet_fn = _excel_attr('concat_merge_sheet')
        concat_add_sheet_fn = _excel_attr('concat_add_sheet')
        if method == 'merge-sheet':
            concat_merge_sheet_fn(input_files, output_file)
        elif method == 'add-sheet':
            concat_add_sheet_fn(input_files, output_file)
        else:
            return _failure_result(f'Unknown method: {method}. Use merge-sheet or add-sheet.')

        return _success_result({
            'output_file': output_file,
            'input_count': len(input_files),
            'method': method,
        })
    except Exception as e:
        log.error(f'concat_excel failed: {e}', exc_info=True)
        return ToolResult.failure(str(e))


@tool(
    description='Convert an Excel file to CSV format.',
    parameters={
        'input_file': 'Excel file path to convert',
        'output_file': 'Optional output CSV file path',
    }
)
def excel_to_csv(
    input_file: str,
    output_file: Optional[str] = None,
) -> ToolResult:
    '''
    Convert an Excel file to CSV.

    Input:
        input_file: Path to the .xlsx file.
        output_file: Optional output path (default: replaces .xlsx with .csv).

    Output:
        ToolResult with the output file path.
    '''
    if not _excel_utils_available:
        return ToolResult.failure('excel_utils is not available')

    try:
        convert_to_csv_fn = _excel_attr('convert_to_csv')
        result_path = convert_to_csv_fn(input_file, output_file)
        return _success_result({'output_file': result_path})
    except Exception as e:
        log.error(f'excel_to_csv failed: {e}', exc_info=True)
        return ToolResult.failure(str(e))


@tool(
    description='Convert a CSV file to Excel format with styling.',
    parameters={
        'input_file': 'CSV file path to convert',
        'output_file': 'Optional output Excel file path',
    }
)
def csv_to_excel(
    input_file: str,
    output_file: Optional[str] = None,
) -> ToolResult:
    '''
    Convert a CSV file to Excel with header styling and auto-fit columns.

    Input:
        input_file: Path to the .csv file.
        output_file: Optional output path (default: replaces .csv with .xlsx).

    Output:
        ToolResult with the output file path.
    '''
    if not _excel_utils_available:
        return ToolResult.failure('excel_utils is not available')

    try:
        convert_from_csv_fn = _excel_attr('convert_from_csv')
        result_path = convert_from_csv_fn(input_file, output_file)
        return _success_result({'output_file': result_path})
    except Exception as e:
        log.error(f'csv_to_excel failed: {e}', exc_info=True)
        return ToolResult.failure(str(e))


@tool(
    description='Diff two Excel files and produce a comparison report.',
    parameters={
        'input_files': 'List of two Excel file paths to compare',
        'output_file': 'Optional output file path for the diff report',
    }
)
def diff_excel(
    input_files: List[str],
    output_file: Optional[str] = None,
) -> ToolResult:
    '''
    Compare two Excel files and produce a diff report.

    Input:
        input_files: List of exactly two Excel file paths.
        output_file: Optional output path for the diff report.

    Output:
        ToolResult with the diff summary.
    '''
    if not _excel_utils_available:
        return ToolResult.failure('excel_utils is not available')

    if len(input_files) != 2:
        return ToolResult.failure('diff_excel requires exactly 2 input files')

    try:
        diff_files_fn = _excel_attr('diff_files')
        result_path = diff_files_fn(input_files, output_file)
        return _success_result({'output_file': result_path})
    except Exception as e:
        log.error(f'diff_excel failed: {e}', exc_info=True)
        return ToolResult.failure(str(e))


# ****************************************************************************************
# Tool class for registration with agent framework
# ****************************************************************************************

class ExcelTools(BaseTool):
    '''Collection of Excel-related agent tools.'''

    @tool(description='Build a multi-sheet Excel map from one or more root tickets')
    def build_excel_map(
        self, ticket_keys: List[str], hierarchy_depth: int = 1,
        limit: Optional[int] = None, output_file: Optional[str] = None
    ) -> ToolResult:
        return build_excel_map(ticket_keys, hierarchy_depth, limit, output_file)

    @tool(description='Concatenate Excel files')
    def concat_excel(
        self, input_files: List[str], output_file: str, method: str = 'merge-sheet'
    ) -> ToolResult:
        return concat_excel(input_files, output_file, method)

    @tool(description='Convert Excel to CSV')
    def excel_to_csv(self, input_file: str, output_file: Optional[str] = None) -> ToolResult:
        return excel_to_csv(input_file, output_file)

    @tool(description='Convert CSV to Excel')
    def csv_to_excel(self, input_file: str, output_file: Optional[str] = None) -> ToolResult:
        return csv_to_excel(input_file, output_file)

    @tool(description='Diff two Excel files')
    def diff_excel(self, input_files: List[str], output_file: Optional[str] = None) -> ToolResult:
        return diff_excel(input_files, output_file)
