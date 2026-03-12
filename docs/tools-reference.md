# Tools Reference

## Overview
Tools are `@tool`-decorated functions that wrap core logic. They are used by agents via the `BaseTool` framework and exposed through the MCP server.

## Tool Framework (`tools/base.py`)
- **`@tool` decorator usage**: Decorates a function to mark it as an agent tool. It extracts parameter information from type hints and docstrings, wraps the function to return a `ToolResult`, and adds tool metadata for agent registration.
- **`ToolResult` dataclass**: Represents the result of a tool execution. Contains `status` (`success`, `error`, `pending`), `data` (if successful), `error` (if failed), and `metadata`.
- **`ToolDefinition`**: Represents the definition of a tool for agent use. It includes the tool's `name`, `description`, `parameters` (list of `ToolParameter`s), `returns` description, and the `func` to execute. It can convert this definition to an OpenAI function calling schema.
- **`BaseTool` ABC**: An abstract base class for tool collections. Subclasses implement tool methods and register them for agent use via `_register_tools()`.

## Jira Tools (`tools/jira_tools.py`)

### Project

| Tool | Parameters | Description | Return Type |
| --- | --- | --- | --- |
| `get_project_info` | `project_key: str` | Get information about a Jira project including name, lead, and description. | `ToolResult` |
| `get_project_workflows` | `project_key: str` | Get the workflow statuses available for a Jira project. | `ToolResult` |
| `get_project_issue_types` | `project_key: str` | Get the issue types available for a Jira project. | `ToolResult` |
| `get_components` | `project_key: str` | Get components for a Jira project. | `ToolResult` |

### Releases

| Tool | Parameters | Description | Return Type |
| --- | --- | --- | --- |
| `get_releases` | `project_key: str`, `pattern: Optional[str] = None`, `include_released: bool = True`, `include_unreleased: bool = True` | Get releases (versions) for a Jira project, optionally filtered by pattern. | `ToolResult` |
| `get_release_tickets` | `project_key: str`, `release_name: str`, `issue_types: Optional[List[str]] = None`, `status: Optional[List[str]] = None`, `limit: int = 100` | Get tickets for a specific release version. | `ToolResult` |
| `create_release` | `project_key: str`, `name: str`, `description: Optional[str] = None`, `start_date: Optional[str] = None`, `release_date: Optional[str] = None` | Create a new release/version in a Jira project. | `ToolResult` |

### Tickets

| Tool | Parameters | Description | Return Type |
| --- | --- | --- | --- |
| `create_ticket` | `project_key: str`, `summary: str`, `issue_type: str`, `description: Optional[str] = None`, `assignee: Optional[str] = None` | Create a new Jira ticket. | `ToolResult` |
| `update_ticket` | `ticket_key: str`, `summary: Optional[str] = None`, `description: Optional[str] = None`, `assignee: Optional[str] = None`, `status: Optional[str] = None` | Update an existing Jira ticket. | `ToolResult` |
| `assign_ticket` | `ticket_key: str`, `assignee: str` | Assign a ticket to a user. | `ToolResult` |
| `link_tickets` | `from_key: str`, `to_key: str`, `link_type: str = 'Relates'` | Create a link between two Jira tickets. | `ToolResult` |

### Search

| Tool | Parameters | Description | Return Type |
| --- | --- | --- | --- |
| `search_tickets` | `jql: str`, `limit: int = 100`, `fields: Optional[List[str]] = None` | Search for Jira tickets using JQL query. | `ToolResult` |
| `run_jql_query` | `jql: str`, `limit: int = 50` | Run a JQL query and return matching tickets. | `ToolResult` |
| `list_filters` | `owner: Optional[str] = None`, `favourite_only: bool = False` | List Jira filters, optionally filtered by owner or favourites only. | `ToolResult` |
| `run_filter` | `filter_id: str`, `limit: int = 50` | Run a Jira filter by ID and return matching tickets. | `ToolResult` |

### Hierarchy

| Tool | Parameters | Description | Return Type |
| --- | --- | --- | --- |
| `get_children_hierarchy` | `root_key: str`, `limit: int = 100` | Get child tickets in a hierarchy tree starting from a root ticket. | `ToolResult` |
| `get_related_tickets` | `ticket_key: str`, `hierarchy_depth: int = 3`, `limit: int = 100` | Get related tickets using hierarchy traversal (wraps jira_utils --get-related). | `ToolResult` |

### Reporting

| Tool | Parameters | Description | Return Type |
| --- | --- | --- | --- |
| `get_ticket_totals` | `project_key: str`, `issue_types: Optional[str] = None`, `statuses: Optional[str] = None` | Get ticket count totals for a project, grouped by status and issue type. | `ToolResult` |
| `get_tickets_created_on` | `project_key: str`, `date: str = ''` | Find all tickets created on a specific date. | `ToolResult` |
| `find_bugs_missing_field` | `project_key: str`, `field: str = 'affectedVersion'`, `date: str = ''` | Find bugs missing a required field like Affects Version. | `ToolResult` |
| `get_status_changes` | `project_key: str`, `date: str = ''` | Get status transitions for a date, separated by automation vs human. | `ToolResult` |
| `daily_report` | `project_key: str`, `date: str = ''`, `dump_file: str = ''`, `dump_format: str = 'excel'` | Run a full daily report: created tickets, missing fields, automation changes. | `ToolResult` |

### Dashboards

| Tool | Parameters | Description | Return Type |
| --- | --- | --- | --- |
| `list_dashboards` | `owner: Optional[str] = None`, `shared: bool = False` | List Jira dashboards, optionally filtered by owner. | `ToolResult` |
| `get_dashboard` | `dashboard_id: str` | Get details of a specific Jira dashboard by ID. | `ToolResult` |
| `create_dashboard` | `name: str`, `description: str = ''` | Create a new Jira dashboard. | `ToolResult` |

### Bulk

| Tool | Parameters | Description | Return Type |
| --- | --- | --- | --- |
| `bulk_update_tickets` | `input_file: str`, `set_release: Optional[str] = None`, `set_labels: Optional[str] = None` | Bulk update tickets from a CSV file (set release, labels, etc.). | `ToolResult` |


## Excel Tools (`tools/excel_tools.py`)

| Tool | Parameters | Description | Return Type |
| --- | --- | --- | --- |
| `build_excel_map` | `ticket_keys: List[str]`, `hierarchy_depth: int = 1`, `limit: int | None = None`, `output_file: str | None = None` | Build a multi-sheet Excel workbook mapping one or more root tickets and all their related issues child hierarchies. | `ToolResult` |
| `concat_excel` | `input_files: List[str]`, `output_file: str`, `method: str = 'merge-sheet'` | Concatenate multiple Excel files into one using merge-sheet or add-sheet method. | `ToolResult` |
| `excel_to_csv` | `input_file: str`, `output_file: str | None = None` | Convert an Excel file to CSV format. | `ToolResult` |
| `csv_to_excel` | `input_file: str`, `output_file: str | None = None` | Convert a CSV file to Excel format with styling. | `ToolResult` |
| `diff_excel` | `input_files: List[str]`, `output_file: str | None = None` | Diff two Excel files and produce a comparison report. | `ToolResult` |

