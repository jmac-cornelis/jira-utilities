import importlib


def test_import_jira_utils():
    mod = importlib.import_module("jira_utils")
    assert mod is not None


def test_import_excel_utils():
    mod = importlib.import_module("excel_utils")
    assert mod is not None


def test_import_mcp_server(import_mcp_server):
    assert import_mcp_server is not None


def test_import_jira_tools_class():
    from tools.jira_tools import JiraTools

    assert JiraTools is not None


def test_import_excel_tools_class():
    from tools.excel_tools import ExcelTools

    assert ExcelTools is not None
