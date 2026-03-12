import contextlib
import io
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, cast

import pytest
from openpyxl import Workbook
from unittest.mock import MagicMock


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: Optional[Dict[str, Any]] = None
    text: str = ""
    headers: Optional[Dict[str, str]] = None

    def json(self) -> Dict[str, Any]:
        return self.payload or {}


class FakeIssueResource:
    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.key = raw.get("key", "")
        self.updated_fields: List[Dict[str, Any]] = []

    def update(self, fields: Optional[Dict[str, Any]] = None) -> None:
        self.updated_fields.append(fields or {})


@pytest.fixture
def fake_response_factory():
    def _make(
        status_code: int = 200,
        payload: Optional[Dict[str, Any]] = None,
        text: str = "",
        headers: Optional[Dict[str, str]] = None,
    ) -> FakeResponse:
        return FakeResponse(
            status_code=status_code,
            payload=payload,
            text=text,
            headers=headers or {},
        )

    return _make


@pytest.fixture
def issue_factory():
    def _make(
        key: str = "STL-1",
        summary: str = "Sample summary",
        issue_type: str = "Bug",
        status: str = "Open",
        priority: str = "P1-Critical",
        assignee: Optional[str] = "Jane Dev",
        reporter: Optional[str] = "John Reporter",
        project_key: str = "STL",
        fix_versions: Optional[Iterable[str]] = None,
        affects_versions: Optional[Iterable[str]] = None,
        components: Optional[Iterable[str]] = None,
        labels: Optional[Iterable[str]] = None,
        created: str = "2026-01-02T03:04:05.000+0000",
        updated: str = "2026-01-03T04:05:06.000+0000",
        resolutiondate: Optional[str] = "2026-01-04T05:06:07.000+0000",
        customer_ids: Optional[Iterable[str]] = None,
        product_family: Optional[Iterable[str]] = None,
        description: Any = "Plain description",
        issuelinks: Optional[List[Dict[str, Any]]] = None,
        comments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        fix_versions = list(fix_versions or ["12.1.0"])
        affects_versions = list(affects_versions or ["12.0.0"])
        components = list(components or ["Fabric"])
        labels = list(labels or ["triage"])
        customer_ids = list(customer_ids or ["CN-001"])
        product_family = list(product_family or ["CN5000"])
        issuelinks = list(issuelinks or [])

        fields: Dict[str, Any] = {
            "summary": summary,
            "issuetype": {"name": issue_type},
            "status": {"name": status},
            "priority": {"name": priority},
            "created": created,
            "updated": updated,
            "project": {"key": project_key},
            "fixVersions": [{"name": name} for name in fix_versions],
            "versions": [{"name": name} for name in affects_versions],
            "components": [{"name": name} for name in components],
            "labels": labels,
            "customfield_17504": customer_ids,
            "customfield_28434": [{"value": name} for name in product_family],
            "issuelinks": issuelinks,
            "description": description,
        }

        if assignee is not None:
            fields["assignee"] = {
                "displayName": assignee,
                "accountId": "acct-assignee",
            }
        else:
            fields["assignee"] = None

        if reporter is not None:
            fields["reporter"] = {"displayName": reporter}
        else:
            fields["reporter"] = None

        if resolutiondate:
            fields["resolutiondate"] = resolutiondate

        if comments is not None:
            fields["comment"] = {"comments": comments}

        return {
            "key": key,
            "id": key.replace("-", ""),
            "fields": fields,
        }

    return _make


@pytest.fixture
def fake_issue_resource_factory(issue_factory):
    def _make(**kwargs: Any) -> FakeIssueResource:
        return FakeIssueResource(issue_factory(**kwargs))

    return _make


@pytest.fixture
def mock_jira(issue_factory):
    jira = MagicMock(name="mock_jira")

    issue_types = [
        SimpleNamespace(name="Bug", id="1", subtask=False, description="Bug work item"),
        SimpleNamespace(name="Task", id="2", subtask=False, description="Task work item"),
        SimpleNamespace(name="Story", id="3", subtask=False, description="Story work item"),
        SimpleNamespace(name="Sub-task", id="4", subtask=True, description="Sub-task work item"),
    ]

    project = SimpleNamespace(
        key="STL",
        name="Storage Team",
        issueTypes=issue_types,
        lead=SimpleNamespace(displayName="Lead Engineer"),
    )

    versions = [
        SimpleNamespace(name="12.1.0", id="1001", released=False, archived=False, releaseDate="2026-01-01"),
        SimpleNamespace(name="12.1.1", id="1002", released=False, archived=False, releaseDate="2026-02-01"),
        SimpleNamespace(name="11.9.0", id="1003", released=True, archived=False, releaseDate="2025-12-01"),
    ]

    statuses = [
        SimpleNamespace(name="Open", id="1", statusCategory=SimpleNamespace(name="To Do")),
        SimpleNamespace(name="In Progress", id="2", statusCategory=SimpleNamespace(name="In Progress")),
        SimpleNamespace(name="Closed", id="3", statusCategory=SimpleNamespace(name="Done")),
        SimpleNamespace(name="Verify", id="4", statusCategory=SimpleNamespace(name="In Progress")),
    ]

    user_candidates = [
        SimpleNamespace(
            accountId="acct-jdoe",
            displayName="John Doe",
            emailAddress="john.doe@cornelisnetworks.com",
        ),
        SimpleNamespace(
            accountId="acct-jane",
            displayName="Jane Smith",
            emailAddress="jane.smith@cornelisnetworks.com",
        ),
    ]

    issue_store: Dict[str, Dict[str, Any]] = {}

    def _issue_lookup(issue_key: str, fields: Optional[str] = None) -> FakeIssueResource:
        raw = issue_store.get(issue_key)
        if raw is None:
            raw = issue_factory(key=issue_key)
            issue_store[issue_key] = raw
        return FakeIssueResource(raw)

    jira.project.return_value = project
    jira.project_versions.return_value = versions
    jira.statuses.return_value = statuses
    jira.search_assignable_users_for_issues.return_value = user_candidates
    jira.search_users.return_value = user_candidates
    jira.search_issues.return_value = []
    jira.issue.side_effect = _issue_lookup
    jira.create_issue.return_value = SimpleNamespace(key="STL-999")
    jira.server_url = "https://cornelisnetworks.atlassian.net"

    jira._issue_store = issue_store
    jira._project = project
    jira._versions = versions
    jira._statuses = statuses

    return jira


@pytest.fixture
def mock_filters() -> List[Dict[str, Any]]:
    return [
        {
            "id": "12345",
            "name": "Open Bugs",
            "jql": 'project = "STL" AND issuetype = Bug AND status = Open',
            "favourite": True,
            "owner": {
                "displayName": "Filter Owner",
                "emailAddress": "owner@cornelisnetworks.com",
            },
        },
        {
            "id": "23456",
            "name": "Recent Stories",
            "jql": 'project = "STL" AND issuetype = Story ORDER BY created DESC',
            "favourite": False,
            "owner": {
                "displayName": "Analyst",
                "emailAddress": "analyst@cornelisnetworks.com",
            },
        },
    ]


@pytest.fixture
def temp_csv_file(tmp_path: Path):
    def _make(name: str, content: str) -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    return _make


@pytest.fixture
def temp_excel_file(tmp_path: Path):
    def _make(name: str, headers: List[str], rows: List[List[Any]]) -> Path:
        path = tmp_path / name
        wb = Workbook()
        ws = cast(Any, wb.active)
        ws.title = "Data"
        ws.append(headers)
        for row in rows:
            ws.append(row)
        wb.save(path)
        return path

    return _make


@pytest.fixture
def capture_stdout():
    @contextlib.contextmanager
    def _capture():
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            yield stream

    return _capture


@pytest.fixture(autouse=True)
def reset_jira_utils_state():
    try:
        import jira_utils
    except Exception:
        yield
        return

    jira_state = cast(Any, jira_utils)

    if hasattr(jira_state, "reset_connection"):
        jira_state.reset_connection()
    if hasattr(jira_state, "reset_user_resolver"):
        jira_state.reset_user_resolver()
    jira_state._quiet_mode = False
    jira_state._show_jql = False
    jira_state._last_jql = None
    jira_state._include_comments = None
    jira_state._no_formatting = False

    yield

    if hasattr(jira_state, "reset_connection"):
        jira_state.reset_connection()
    if hasattr(jira_state, "reset_user_resolver"):
        jira_state.reset_user_resolver()
    jira_state._quiet_mode = False
    jira_state._show_jql = False
    jira_state._last_jql = None
    jira_state._include_comments = None
    jira_state._no_formatting = False


@pytest.fixture
def import_mcp_server(monkeypatch):
    fake_mcp = cast(Any, ModuleType("mcp"))
    fake_mcp_server = cast(Any, ModuleType("mcp.server"))
    fake_mcp_stdio = cast(Any, ModuleType("mcp.server.stdio"))
    fake_mcp_types = cast(Any, ModuleType("mcp.types"))

    class FakeServer:
        def __init__(self, name: str):
            self.name = name

        def tool(self):
            def _decorator(func):
                return func

            return _decorator

        async def run(self, *_args, **_kwargs):
            return None

        def create_initialization_options(self):
            return {}

    @contextlib.asynccontextmanager
    async def fake_stdio_server():
        yield (None, None)

    class FakeTool:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class FakeTextContent:
        def __init__(self, type: str, text: str):
            self.type = type
            self.text = text

    fake_mcp_server.Server = FakeServer
    fake_mcp_stdio.stdio_server = fake_stdio_server
    fake_mcp_types.Tool = FakeTool
    fake_mcp_types.TextContent = FakeTextContent

    fake_mcp.server = fake_mcp_server
    fake_mcp.types = fake_mcp_types

    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.stdio", fake_mcp_stdio)
    monkeypatch.setitem(sys.modules, "mcp.types", fake_mcp_types)

    if "mcp_server" in sys.modules:
        del sys.modules["mcp_server"]

    import importlib

    module = importlib.import_module("mcp_server")
    return importlib.reload(module)
