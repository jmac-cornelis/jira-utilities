# Tools Reference

## Overview
Brief: Tools are `@tool`-decorated functions wrapping core logic. Used by agents and exposed via MCP server.

## Tool Framework (tools/base.py)

The framework provides a consistent interface for defining and executing tools.

### `@tool` Decorator
Marks a function as an agent tool. It extracts parameter information from type hints and the docstring, wraps the function to return a `ToolResult`, and adds metadata for agent registration.

```python
from tools.base import tool, ToolResult

@tool(description='Search for Jira tickets')
def search_tickets(jql: str, limit: int = 50) -> ToolResult:
    # Logic goes here
    return ToolResult.success({'count': 0})
```

### `ToolResult`
A dataclass representing the outcome of a tool execution.
- `status`: Execution status (`ToolStatus.SUCCESS`, `ToolStatus.ERROR`, `ToolStatus.PENDING`).
- `data`: The result data if successful.
- `error`: Error message if failed.
- `metadata`: Additional execution metadata.

Use `ToolResult.success(data)` and `ToolResult.failure(error)` to construct results.

### `ToolDefinition` and `BaseTool`
`ToolDefinition` defines a tool for agent use, containing the name, description, parameters, and the callable function. `BaseTool` is an abstract base class for grouping tools. Subclasses register their decorated methods automatically.

## Jira Tools (tools/jira_tools.py)

### Connection
None explicitly listed. `get_jira()` is internal.

### Project
* `get_project_info(project_key: str) -> ToolResult`
  Get information about a Jira project including name, lead, and description.
* `get_project_workflows(project_key: str) -> ToolResult`
  Get the workflow statuses available for a Jira project.
* `get_project_issue_types(project_key: str) -> ToolResult`
  Get the issue types available for a Jira project.
* `get_components(project_key: str) -> ToolResult`
  Get components for a Jira project.

### Releases
* `get_releases(project_key: str, pattern: Optional[str] = None, include_released: bool = True, include_unreleased: bool = True) -> ToolResult`
  Get releases (versions) for a Jira project, optionally filtered by pattern.
* `get_release_tickets(project_key: str, release_name: str, issue_types: Optional[List[str]] = None, status: Optional[List[str]] = None, limit: int = 100) -> ToolResult`
  Get tickets for a specific release version.
* `create_release(project_key: str, name: str, description: Optional[str] = None, start_date: Optional[str] = None, release_date: Optional[str] = None) -> ToolResult`
  Create a new release/version in a Jira project.
* `get_project_versions_tool(project_key: str) -> ToolResult`
  Get all versions/releases defined for a Jira project.

### Tickets
* `create_ticket(project_key: str, summary: str, issue_type: str, description: Optional[str] = None, assignee: Optional[str] = None, components: Optional[List[str]] = None, fix_versions: Optional[List[str]] = None, labels: Optional[List[str]] = None, parent_key: Optional[str] = None, product_family: Optional[List[str]] = None, custom_fields: Optional[Dict[str, Any]] = None) -> ToolResult`
  Create a new Jira ticket.
* `update_ticket(ticket_key: str, summary: Optional[str] = None, description: Optional[str] = None, assignee: Optional[str] = None, status: Optional[str] = None, fix_versions: Optional[List[str]] = None, components: Optional[List[str]] = None, labels: Optional[List[str]] = None, custom_fields: Optional[Dict[str, Any]] = None) -> ToolResult`
  Update an existing Jira ticket.
* `assign_ticket(ticket_key: str, assignee: str) -> ToolResult`
  Assign a ticket to a user.
* `link_tickets(from_key: str, to_key: str, link_type: str = 'Relates') -> ToolResult`
  Create a link between two Jira tickets.

### Search
* `search_tickets(jql: str, limit: int = 100, fields: Optional[List[str]] = None) -> ToolResult`
  Search for Jira tickets using JQL query.
* `run_jql_query(jql: str, limit: int = 50) -> ToolResult`
  Run a JQL query and return matching tickets.
* `list_filters(owner: Optional[str] = None, favourite_only: bool = False) -> ToolResult`
  List Jira filters, optionally filtered by owner or favourites only.
* `run_filter(filter_id: str, limit: int = 50) -> ToolResult`
  Run a Jira filter by ID and return matching tickets.

### Hierarchy
* `get_related_tickets(ticket_key: str, hierarchy_depth: int = 3, limit: int = 100) -> ToolResult`
  Get related tickets using hierarchy traversal (wraps jira_utils --get-related).
* `get_children_hierarchy(root_key: str, limit: int = 100) -> ToolResult`
  Get child tickets in a hierarchy tree starting from a root ticket.

### Reporting
* `get_ticket_totals(project_key: str, issue_types: Optional[str] = None, statuses: Optional[str] = None) -> ToolResult`
  Get ticket count totals for a project, grouped by status and issue type.
* `get_tickets_created_on(project_key: str, date: str = '') -> ToolResult`
  Find all tickets created on a specific date.
* `find_bugs_missing_field(project_key: str, field: str = 'affectedVersion', date: str = '') -> ToolResult`
  Find bugs missing a required field like Affects Version.
* `get_status_changes(project_key: str, date: str = '') -> ToolResult`
  Get status transitions for a date, separated by automation vs human.
* `run_daily_report(project_key: str, release_name: str, output_file: str = '') -> ToolResult`
  Run a full daily report with optional export.

### Dashboards
* `list_dashboards(owner: Optional[str] = None, shared: bool = False) -> ToolResult`
  List Jira dashboards, optionally filtered by owner.
* `get_dashboard(dashboard_id: str) -> ToolResult`
  Get details of a specific Jira dashboard by ID.
* `create_dashboard(name: str, description: str = '') -> ToolResult`
  Create a new Jira dashboard.

### Bulk Operations
* `bulk_update_tickets(input_file: str, set_release: Optional[str] = None, set_labels: Optional[str] = None) -> ToolResult`
  Bulk update tickets from a CSV file (set release, labels, etc.).

## Excel Tools (tools/excel_tools.py)

* `build_excel_map(ticket_keys: List[str], hierarchy_depth: int = 1, limit: int | None = None, output_file: str | None = None) -> ToolResult`
  Build a multi-sheet Excel workbook mapping one or more root tickets and all their related issues child hierarchies. Sheet 1 ("Tickets") is a flat overview of root + first-level children. Sheets 2..N are per-ticket children with unlimited depth (indented format).
* `concat_excel(input_files: List[str], output_file: str, method: str = 'merge-sheet') -> ToolResult`
  Concatenate multiple Excel files into one using merge-sheet or add-sheet method.
* `excel_to_csv(input_file: str, output_file: str | None = None) -> ToolResult`
  Convert an Excel file to CSV format.
* `csv_to_excel(input_file: str, output_file: str | None = None) -> ToolResult`
  Convert a CSV file to Excel format with styling.
* `diff_excel(input_files: List[str], output_file: str | None = None) -> ToolResult`
  Diff two Excel files and produce a comparison report.

## Draw.io Tools (tools/drawio_tools.py)

* `parse_org_chart(file_path: str) -> ToolResult`
  Parse an org chart from a draw.io file and extract the organizational structure.
* `get_responsibilities(file_path: str) -> ToolResult`
  Extract responsibility mappings from an org chart - who owns what areas.
* `create_ticket_diagram(csv_file: str, output_path: str, title: Optional[str] = None) -> ToolResult`
  Create a draw.io diagram from a Jira ticket hierarchy CSV (wraps drawio_utilities --create-map).
* `create_diagram_from_tickets(tickets: List[Dict[str, Any]], output_path: str, title: str = 'Ticket Hierarchy') -> ToolResult`
  Create a draw.io diagram from ticket data (programmatic, not from CSV).

## Vision Tools (tools/vision_tools.py)

* `analyze_image(image_path: str, prompt: str = 'Describe this image in detail.', extract_text: bool = True) -> ToolResult`
  Analyze an image using vision LLM to extract information.
* `extract_roadmap_from_ppt(file_path: str, slide_numbers: Optional[List[int]] = None) -> ToolResult`
  Extract roadmap information from a PowerPoint presentation.
* `extract_roadmap_from_excel(file_path: str, sheet_name: Optional[str] = None) -> ToolResult`
  Extract roadmap information from an Excel spreadsheet.
* `extract_text_from_image(image_path: str) -> ToolResult`
  Extract text from an image using OCR or vision LLM.

## File Tools (tools/file_tools.py)

* `read_file(file_path: str, encoding: str = 'utf-8', max_size_mb: float = 10.0) -> ToolResult`
  Read the contents of a file.
* `write_file(file_path: str, content: str, encoding: str = 'utf-8', create_dirs: bool = True, overwrite: bool = False) -> ToolResult`
  Write content to a file.
* `list_directory(dir_path: str = '.', pattern: Optional[str] = None, recursive: bool = False, include_hidden: bool = False) -> ToolResult`
  List files and directories in a path.
* `read_json(file_path: str) -> ToolResult`
  Read a JSON file and parse its contents.
* `write_json(file_path: str, data: Any, indent: int = 2, overwrite: bool = False) -> ToolResult`
  Write data to a JSON file.
* `read_yaml(file_path: str) -> ToolResult`
  Read a YAML file and parse its contents.

## Web Search Tools (tools/web_search_tools.py)

* `web_search(query: str, max_results: int = 10) -> ToolResult`
  Search the web for information about a topic. Tries Cornelis MCP, then Brave Search, then Tavily as fallbacks.
* `web_search_multi(queries: List[str], max_results_per_query: int = 5) -> ToolResult`
  Run multiple web searches and aggregate results.

## Knowledge Tools (tools/knowledge_tools.py)

* `search_knowledge(query: str, max_results: int = 10) -> ToolResult`
  Search the local Cornelis knowledge base for information. Searches data/knowledge/ Markdown files by keyword.
* `list_knowledge_files() -> ToolResult`
  List all files in the local Cornelis knowledge base.
* `read_knowledge_file(file_path: str) -> ToolResult`
  Read the full contents of a specific knowledge base file.
* `read_document(file_path: str) -> ToolResult`
  Read and extract text from a document (PDF, DOCX, Markdown, TXT).

## MCP Tools (tools/mcp_tools.py)

* `mcp_discover_tools(force_refresh: bool = False) -> ToolResult`
  List all tools available on the Cornelis MCP server.
* `mcp_call_tool(tool_name: str, arguments: Optional[Dict[str, Any]] = None, timeout: int = 60) -> ToolResult`
  Call a specific tool on the Cornelis MCP server by name.
* `mcp_search(query: str, tool_hint: Optional[str] = None) -> ToolResult`
  Search for information using the Cornelis MCP server (convenience wrapper).

## Plan Export Tools (tools/plan_export_tools.py)

* `plan_to_csv(input_path: str, output_path: str = '', table_format: str = 'indented', include_description: bool = False, output_format: str = 'csv') -> ToolResult`
  Convert a feature-plan JSON file (as produced by the Feature Planning pipeline) into a CSV file matching the standard Jira CSV format used by dump_tickets_to_file(). Supports flat and indented table formats. Returns the output file path.
* `plan_json_to_dict_rows(plan_or_path, include_description: bool = False) -> ToolResult`
  Convert a feature-plan JSON (dict or file path) into a list of flat row dicts matching the standard Jira CSV schema. Useful for in-memory pipeline processing without writing to disk.
* `plan_file_to_plan_json(input_path: str, output_path: str = '', project_key: str = '', product_family: str = '', feature_name: str = '') -> ToolResult`
  Convert a feature-plan CSV or Excel file (flat or indented table format) into the standard feature-plan JSON dict used by the execution pipeline. Auto-detects flat vs indented format from the column headers. Optionally writes the JSON to disk.
