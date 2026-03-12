# Standalone Utilities

These standalone CLIs provide quick access to Jira data, Excel file manipulation, and Draw.io diagram generation. They don't require LLM configuration and run directly on your machine. The `jira-utils` tool requires valid Jira credentials in your `.env` file, while `excel-utils` and `drawio-utils` work purely with local files.

## jira-utils (jira_utils.py)

The `jira-utils` CLI is a fast, powerful way to query Jira, manipulate tickets, handle bulk updates, and manage dashboards and filters directly from the terminal.

### Installation

Can be run as `jira-utils` if installed via pip, or `python jira_utils.py` directly from the repository.

### Global Options

| Flag | Description | Default |
|------|-------------|---------|
| `-v, --verbose` | Enable verbose output to stdout. | |
| `-q, --quiet` | Minimal stdout. | |
| `--env FILE` | Path to dotenv file to load. | `.env` |

### Project Discovery

Get information about available projects, workflows, issue types, and components.

| Flag | Description | Default |
|------|-------------|---------|
| `--list` | List all available Jira projects. | |
| `--project KEY` | Project key to operate on (e.g., PROJ). | |
| `--get-workflow` | Display workflow statuses for the specified project. | |
| `--get-issue-types` | Display issue types for the specified project. | |
| `--get-fields [TYPE ...]` | Display create/edit/transition fields. Optionally filter by issue types. | |
| `--get-versions` | Display versions (releases) with detailed info for the specified project. | |
| `--get-components` | List all components for the specified project. | |

**Examples:**
```bash
jira-utils --list
jira-utils --project STL --get-workflow
jira-utils --project STL --get-fields Bug Story
jira-utils --project STL --get-components
```

### Ticket Querying & Extraction

Search for tickets, get related tickets, and export them to different formats.

| Flag | Description | Default |
|------|-------------|---------|
| `--jql QUERY` | Run a custom JQL query and display results. | |
| `--get-tickets` | Get tickets. Use `--issue-types` to filter by specific issue types. | |
| `--get-children KEY` | Display full child hierarchy for the given ticket (recurses via parent links). | |
| `--get-related KEY` | Display related issues for the given ticket (linked issues + children). | |
| `--hierarchy [DEPTH]` | Used with `--get-related` to recursively traverse linked issues and children. Omit DEPTH for unlimited depth. | `-1` |
| `--table-format FORMAT` | Table layout for hierarchy CSV output: `flat` or `indented`. | `flat` |
| `--releases [PATTERN]` | List releases for the specified project. Optional glob pattern with exclusions. | `*` |
| `--release-tickets RELEASE` | Get tickets for a release. Supports glob patterns (e.g., "12.1*"). | |
| `--no-release` | Get tickets with no release assigned. | |
| `--issue-types [TYPE ...]` | Filter by issue types (e.g., Bug Story Task Sub-task). | |
| `--status [STATUS ...]` | Filter by status (case-insensitive). Use `^` prefix to exclude. | |
| `--date FILTER` | Date filter: today, week, month, year, all, or MM-DD-YYYY:MM-DD-YYYY range. | |
| `--limit N` | Limit the number of tickets to retrieve. | |
| `--total` | Show ticket count. | |
| `--get-comments {all,latest}` | Include comments in ticket output. Forces `--dump-format` to json. | |
| `--dump-file FILE` | Output filename for dumping tickets. | `out` |
| `--dump-format FORMAT` | Output format for dump: `csv`, `json`, or `excel`. | `csv` |

**Examples:**
```bash
# Get open bugs
jira-utils --project STL --get-tickets --issue-types Bug --status Open --dump-file open_bugs

# Get tickets for a specific release pattern
jira-utils --project STL --release-tickets "12.1*" --issue-types Bug Story Task

# Get related tickets with unlimited hierarchy depth
jira-utils --get-related STL-1234 --hierarchy --dump-file related --dump-format excel

# Run custom JQL and export to JSON
jira-utils --jql "project = STL AND status = 'In Progress'" --dump-file progress --dump-format json
```

### Ticket Creation

Create new tickets directly or from a JSON file.

| Flag | Description | Default |
|------|-------------|---------|
| `--create-ticket [FILE]` | Create a new ticket. If FILE provided, load fields from JSON. Dry-run by default. | |
| `--execute` | Execute the creation (disables dry-run). | |
| `--summary TEXT` | Ticket summary (required). | |
| `--issue-type TYPE` | Issue type name (required). | |
| `--ticket-description TEXT`| Plain-text description. | |
| `--assignee-id ACCOUNT_ID` | Assignee accountId. | |
| `--components [NAME ...]` | Component names to set. | |
| `--fix-versions [VERSION ...]` | Fix version(s) to set. | |
| `--labels [LABEL ...]` | Labels to set. | |
| `--parent KEY` | Parent ticket key. | |

**Examples:**
```bash
# Preview creation
jira-utils --project STL --create-ticket --summary "Fix login issue" --issue-type Bug --components "Auth"

# Execute creation
jira-utils --project STL --create-ticket --summary "Fix login issue" --issue-type Bug --execute

# Create from JSON file
jira-utils --create-ticket ticket_data.json --execute
```

### Bulk Operations

Update or delete multiple tickets using a CSV file as input.

| Flag | Description | Default |
|------|-------------|---------|
| `--bulk-update` | Perform bulk update on tickets from input file. | |
| `--bulk-delete` | Perform bulk delete on tickets from input file. | |
| `--input-file FILE` | Input CSV file containing ticket keys. | |
| `--dry-run` | Preview changes without applying them. | `True` |
| `--execute` | Execute the bulk operation (disables dry-run). | |
| `--force` | Skip confirmation prompts (for delete operations). | |
| `--set-release RELEASE` | Set the release/fixVersion on tickets. | |
| `--remove-release` | Remove all releases from tickets. | |
| `--transition STATUS` | Transition tickets to the specified status. | |
| `--assign USER` | Assign tickets to the specified user (email or "unassigned"). | |
| `--max-updates N` | Maximum number of tickets to update. | |
| `--max-deletes N` | Maximum number of tickets to delete. | |
| `--delete-subtasks` | When used with `--bulk-delete`, delete subtasks as well. | |
| `--show-jql` | Print the equivalent JQL statement for the operation. | |

**Examples:**
```bash
# Find orphans and set release
jira-utils --jql "project = STL AND fixVersion is EMPTY" --dump-file orphans
jira-utils --bulk-update --input-file orphans.csv --set-release "12.1.1.x" --execute

# Bulk assign and transition
jira-utils --bulk-update --input-file tickets.csv --assign "user@email.com" --transition "In Progress" --execute

# Bulk delete tickets
jira-utils --bulk-delete --input-file to_delete.csv --execute
```

### Dashboards and Gadgets

Manage Jira dashboards and their gadgets.

| Flag | Description | Default |
|------|-------------|---------|
| `--dashboards` | List accessible dashboards. | |
| `--dashboard ID` | Get dashboard details by ID. | |
| `--owner USER` | Filter dashboards by owner (use "me" for current user). | |
| `--shared` | Show only dashboards shared with current user. | |
| `--create-dashboard NAME` | Create a new dashboard with the specified name. | |
| `--update-dashboard ID` | Update dashboard by ID. | |
| `--delete-dashboard ID` | Delete dashboard by ID. | |
| `--copy-dashboard ID` | Copy/clone dashboard by ID. | |
| `--description TEXT` | Dashboard description (for create/update/copy). | |
| `--name NAME` | New name for dashboard (for update/copy). | |
| `--share-permissions JSON` | Share permissions as JSON array (e.g., `'[{"type":"global"}]'`). | |
| `--gadgets DASHBOARD_ID` | List gadgets on the specified dashboard. | |
| `--add-gadget MODULE_KEY` | Add gadget to dashboard (requires `--dashboard`). | |
| `--remove-gadget GADGET_ID` | Remove gadget from dashboard (requires `--dashboard`). | |
| `--update-gadget GADGET_ID` | Update gadget on dashboard (requires `--dashboard`). | |
| `--position ROW,COL` | Gadget position as row,column (e.g., "0,1"). | |
| `--color COLOR` | Gadget color (blue, red, yellow, green, cyan, purple, gray, white). | |
| `--gadget-properties JSON` | Gadget properties as JSON object. | |

**Examples:**
```bash
# List my dashboards
jira-utils --dashboards --owner me

# Copy a dashboard
jira-utils --copy-dashboard 10001 --name "My Team View" --description "Copied for my team"

# List gadgets on a dashboard
jira-utils --gadgets 10001

# Add a gadget
jira-utils --dashboard 10001 --add-gadget "filter-results-gadget" --color blue
```

### Filters

Manage Jira saved filters.

| Flag | Description | Default |
|------|-------------|---------|
| `--list-filters` | List accessible saved filters. | |
| `--get-filter ID` | Get details of a saved filter by ID. | |
| `--run-filter ID` | Run a saved filter by ID (executes its JQL query). | |
| `--favourite` | With `--list-filters`, show only favourite/starred filters. | |

**Examples:**
```bash
jira-utils --list-filters --favourite
jira-utils --get-filter 10500
jira-utils --run-filter 10500 --dump-file filter_results
```

## excel-utils (excel_utils.py)

The `excel-utils` CLI is used for concatenating, converting, and diffing `.xlsx` and `.csv` files locally.

### Installation

Can be run as `excel-utils` if installed via pip, or `python excel_utils.py` directly from the repository.

### Global Options

| Flag | Description | Default |
|------|-------------|---------|
| `-v, --verbose` | Enable verbose output to stdout. | |
| `-q, --quiet` | Minimal stdout. | |

### Actions (Mutually Exclusive)

| Flag | Description |
|------|-------------|
| `--concat [FILE ...]` | List of Excel (.xlsx) files to concatenate. |
| `--convert-to-csv FILE` | Convert an Excel (.xlsx) file to a comma-delimited CSV file. |
| `--convert-from-csv FILE` | Convert a comma-delimited CSV file to an Excel (.xlsx) file. |
| `--diff [FILE ...]` | Diff two or more Excel (.xlsx) files and produce a diff report. |
| `--to-plan-json FILE` | Convert a flat or indented CSV/Excel file into the feature-plan JSON format used by the Jira ticket creation pipeline. |

### Configuration Options

| Flag | Description | Default |
|------|-------------|---------|
| `--output, -o FILE` | Output filename (default depends on action). | |
| `--method METHOD` | Concatenation method: `merge-sheet` (all rows into one sheet) or `add-sheet` (each file becomes a separate sheet). | `merge-sheet` |
| `--no-formatting` | Disable all Excel formatting (header styling, conditional formatting, auto-fit columns). Produces a plain data-only workbook. | |
| `--jira-url URL` | Jira instance URL for clickable "key" column hyperlinks in `--convert-from-csv`. Pass "none" to disable links. | Default Jira URL |
| `--d-columns [COL ...]` | Column names for the Dashboard summary sheet (used with `--convert-from-csv`). Each named column gets a COUNTIF-based pivot table. | |
| `--project KEY` | Override the Jira project key (used with `--to-plan-json`). Auto-detected from rows if not provided. | |
| `--product-family NAME` | Override the product family (used with `--to-plan-json`). Auto-detected from rows if not provided. | |
| `--feature-name NAME` | Feature name for the plan (used with `--to-plan-json`). Defaults to the first epic summary. | |

**Examples:**

```bash
# Merge all rows from fileA and fileB into a single sheet
excel-utils --concat fileA.xlsx fileB.xlsx --method merge-sheet --output merged.xlsx

# Add fileA as one sheet and fileB as another sheet
excel-utils --concat fileA.xlsx fileB.xlsx --method add-sheet --output combined.xlsx

# Convert Excel to CSV
excel-utils --convert-to-csv data.xlsx --output custom_name.csv

# Convert CSV to Excel with styling and a dashboard summary sheet
excel-utils --convert-from-csv data.csv --d-columns Status Priority Component

# Diff two Excel files to see added/removed/changed rows
excel-utils --diff v1.xlsx v2.xlsx --output changes.xlsx

# Pairwise diff across three files
excel-utils --diff v1.xlsx v2.xlsx v3.xlsx
```

## drawio-utils (drawio_utilities.py)

The `drawio-utils` CLI generates draw.io XML files from Jira ticket hierarchies. This allows you to visualize Jira relationships such as dependencies and parent-child links.

### Installation

Can be run as `drawio-utils` if installed via pip, or `python drawio_utilities.py` directly from the repository.

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-v, --verbose` | Enable verbose output to stdout. | |
| `-q, --quiet` | Minimal stdout. | |
| `--create-map CSV_FILE` | Create a draw.io diagram from a Jira hierarchy CSV file. | |
| `--output, -o FILE` | Output filename for the .drawio file. | Input file with `.drawio` ext |
| `--title, -t TITLE` | Title for the diagram. | Derived from root ticket |

### Typical Workflow & Examples

1. Export hierarchy from Jira using `jira-utils`:
```bash
jira-utils --get-related STL-74071 --hierarchy --dump-file tickets
```

2. Generate the diagram from the CSV file:
```bash
drawio-utils --create-map tickets.csv --title "Feature X Dependencies"
```

3. Open the resulting `tickets.drawio` file in the draw.io desktop app, web app, or VS Code extension.

### Node Color Coding

The generated diagram automatically applies color coding based on ticket relationships:
- Root ticket: Light green background
- "is blocked by" / "blocks": Red border, light red fill
- "relates to": Blue border, light blue fill
- Other link types: Gray border, white fill
