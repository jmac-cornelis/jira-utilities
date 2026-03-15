import importlib


def test_import_jira_utils():
    mod = importlib.import_module("jira_utils")
    assert mod is not None


def test_import_confluence_utils():
    mod = importlib.import_module("confluence_utils")
    assert mod is not None


def test_import_excel_utils():
    mod = importlib.import_module("excel_utils")
    assert mod is not None


def test_import_mcp_server(import_mcp_server):
    assert import_mcp_server is not None


def test_import_jira_tools_class():
    from tools.jira_tools import JiraTools

    assert JiraTools is not None


def test_import_confluence_tools_class():
    from tools.confluence_tools import ConfluenceTools

    assert ConfluenceTools is not None


def test_import_gantt_tools_class():
    from tools.gantt_tools import GanttTools

    assert GanttTools is not None


def test_import_excel_tools_class():
    from tools.excel_tools import ExcelTools

    assert ExcelTools is not None


def test_import_file_tools_class():
    from tools.file_tools import FileTools

    assert FileTools is not None


def test_import_knowledge_tools_class():
    from tools.knowledge_tools import KnowledgeTools

    assert KnowledgeTools is not None


def test_import_web_search_tools_class():
    from tools.web_search_tools import WebSearchTools

    assert WebSearchTools is not None


def test_import_mcp_tools_class():
    from tools.mcp_tools import MCPTools

    assert MCPTools is not None


def test_import_gantt_agent_class():
    from agents.gantt_agent import GanttProjectPlannerAgent

    assert GanttProjectPlannerAgent is not None


def test_import_gantt_components():
    from agents.gantt_components import (
        BacklogInterpreter,
        DependencyMapper,
        MilestonePlanner,
        PlanningSummarizer,
        RiskProjector,
    )

    assert BacklogInterpreter is not None
    assert DependencyMapper is not None
    assert MilestonePlanner is not None
    assert PlanningSummarizer is not None
    assert RiskProjector is not None


def test_import_gantt_snapshot_store():
    from state.gantt_snapshot_store import GanttSnapshotStore

    assert GanttSnapshotStore is not None


def test_import_tools_package_exports():
    from tools import (
        GanttTools,
        KnowledgeTools,
        WebSearchTools,
        MCPTools,
        create_gantt_snapshot,
        search_knowledge,
        web_search,
        mcp_discover_tools,
    )

    assert GanttTools is not None
    assert KnowledgeTools is not None
    assert WebSearchTools is not None
    assert MCPTools is not None
    assert callable(create_gantt_snapshot)
    assert callable(search_knowledge)
    assert callable(web_search)
    assert callable(mcp_discover_tools)
