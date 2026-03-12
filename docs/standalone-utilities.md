# Standalone Utilities Reference

The project management utilities package provides three standalone CLI utilities for interacting with Jira, Excel files, and draw.io diagrams. These tools can be used independently of the AI agent workflows to automate common tasks, generate reports, and manage Jira data.

## Installation

You can run these scripts directly via python from within your virtual environment, or install them globally using pipx to make them available from anywhere.

### Running via Python

```bash
# Activate your virtual environment
source .venv/bin/activate

# Run the scripts directly
python3 jira_utils.py --help
python3 excel_utils.py --help
python3 drawio_utilities.py --help
```

### Global CLI Install (pipx)

To make `jira-utils`, `drawio-utils`, and `excel-utils` available as commands in **any** directory (without activating a venv), use [pipx](https://pipx.pypa.io/):

```bash
# Install pipx (macOS)
brew install pipx
pipx ensurepath          # adds ~/.local/bin to PATH (restart terminal)

# Editable install from the repo — changes to source are reflected immediately
pipx install /path/to/this/repo --editable

# Verify
jira-utils -h
drawio-utils -h
excel-utils -h
```

This creates an isolated virtualenv with only the CLI dependencies (`jira`, `python-dotenv`, `requests`).

---

## jira-utils (`jira_utils.py`)

The standalone Jira CLI provides project inspection, ticket queries, ticket creation, bulk operations, and dashboard management.

### Project & Metadata

```bash
# List all accessible projects
python3 jira_utils.py --list

# Project metadata
python3 jira_utils.py --project PROJ --get-workflow
python3 jira_utils.py --project PROJ --get-issue-types
python3 jira_utils.py --project PROJ --get-fields
python3 jira_utils.py --project PROJ --get-versions
python3 jira_utils.py --project PROJ --get-components
```

### Ticket Queries

```bash
# Get tickets with filters
python3 jira_utils.py --project PROJ --get-tickets
python3 jira_utils.py --project PROJ --get-tickets --issue-types Bug Story --status Open --limit 50

# Release tickets
python3 jira_utils.py --project PROJ --releases "12.*"
python3 jira_utils.py --project PROJ --release-tickets "12.3*" --issue-types Bug Story Task

# Tickets with no release
python3 jira_utils.py --project PROJ --no-release --issue-types Bug --status Open

# Ticket totals
python3 jira_utils.py --project PROJ --total --issue-types Bug --status Open "In Progress"

# Custom JQL
python3 jira_utils.py --jql "project = PROJ AND status = Open" --limit 20

# Hierarchy & relationships
python3 jira_utils.py --get-children PROJ-100
python3 jira_utils.py --get-related PROJ-100 --hierarchy
python3 jira_utils.py --get-related PROJ-100 --hierarchy 2   # depth-limited
```

### Date Filters

All ticket queries accept `--date`:

| Value | Meaning |
|-------|---------|
| `today` | Created today |
| `week` | Last 7 days |
| `month` | Last 30 days |
| `year` | Last 365 days |
| `all` | No date filter |
| `MM-DD-YYYY:MM-DD-YYYY` | Custom date range |

```bash
python3 jira_utils.py --project PROJ --get-tickets --date month
python3 jira_utils.py --project PROJ --get-tickets --date 01-01-2025:06-30-2025
```

### Dump to File

Any query can be dumped to CSV or JSON:

```bash
python3 jira_utils.py --project PROJ --get-tickets --dump-file tickets
python3 jira_utils.py --project PROJ --get-tickets --dump-file tickets --dump-format json
python3 jira_utils.py --jql "project = PROJ" --dump-file results --dump-format csv
```

### Filters

```bash
# List your favourite filters
python3 jira_utils.py --list-filters
python3 jira_utils.py --list-filters --owner user@email.com

# Run a filter by ID
python3 jira_utils.py --run-filter 12345 --limit 100
python3 jira_utils.py --run-filter 12345 --dump-file results
```

### Ticket Creation

Create Jira tickets from the CLI using `--create-ticket`. All creates are **dry-run by default**; add `--execute` to actually create the ticket.

There are two modes:

| Mode | Command | Description |
|------|---------|-------------|
| **CLI flags** | `--create-ticket` | Supply all fields via CLI arguments |
| **JSON file** | `--create-ticket path/to/file.json` | Load fields from a JSON file |

When both a JSON file and CLI flags are provided, **CLI flags override** the JSON values.

#### Required Fields

| Field | CLI Flag | JSON Key |
|-------|----------|----------|
| Project | `--project KEY` | `project` |
| Summary | `--summary TEXT` | `summary` |
| Issue type | `--issue-type TYPE` | `issue_type` |

#### Optional Fields

| Field | CLI Flag | JSON Key |
|-------|----------|----------|
| Description | `--ticket-description TEXT` | `description` |
| Assignee | `--assignee-id ACCOUNT_ID` | `assignee_id` |
| Components | `--components NAME [NAME ...]` | `components` |
| Fix versions | `--fix-versions VERSION [VERSION ...]` | `fix_versions` |
| Labels | `--labels LABEL [LABEL ...]` | `labels` |
| Parent | `--parent KEY` | `parent` |

#### Examples

```bash
# Dry-run (preview only)
python3 jira_utils.py --create-ticket \
  --project PROJ --summary "Fix login timeout" --issue-type Bug

# Execute (actually create the ticket)
python3 jira_utils.py --create-ticket \
  --project PROJ --summary "Fix login timeout" --issue-type Bug \
  --components Platform --labels triage --fix-versions 12.3.0 \
  --execute

# From JSON file
python3 jira_utils.py --create-ticket data/templates/create_story.json --execute

# JSON file + CLI override
python3 jira_utils.py --create-ticket data/templates/create_story.json \
  --summary "Override summary from CLI" --execute
```

#### JSON Input Format

See `data/templates/create_ticket_input.schema.json` for the full JSON Schema.

#### Template Files

| File | Purpose |
|------|---------|
| `data/templates/create_ticket_input.schema.json` | JSON Schema (draft 2020-12) for the `--create-ticket FILE` input format |
| `data/templates/create_ticket_input.example.json` | Generic Task example |
| `data/templates/create_story.json` | Story template with acceptance criteria |

### Bulk Update

```bash
# Step 1: Find tickets and dump to CSV
python3 jira_utils.py --jql "project = PROJ AND fixVersion is EMPTY" --dump-file orphans

# Step 2: Preview (dry-run is default)
python3 jira_utils.py --bulk-update --input-file orphans.csv --set-release "12.3.0"

# Step 3: Execute
python3 jira_utils.py --bulk-update --input-file orphans.csv --set-release "12.3.0" --execute

# Other bulk operations
python3 jira_utils.py --bulk-update --input-file tickets.csv --transition "Closed" --execute
python3 jira_utils.py --bulk-update --input-file tickets.csv --assign "user@email.com" --execute
python3 jira_utils.py --bulk-update --input-file tickets.csv --remove-release --execute
python3 jira_utils.py --bulk-update --input-file tickets.csv --set-release "v2.0" --max-updates 10 --execute
```

### Bulk Delete

```bash
# Preview deletes (dry-run)
python3 jira_utils.py --bulk-delete --input-file to_delete.csv

# Execute deletes (requires interactive confirmation)
python3 jira_utils.py --bulk-delete --input-file to_delete.csv --execute

# Delete parents and their subtasks
python3 jira_utils.py --bulk-delete --input-file parents.csv --delete-subtasks --execute

# Skip confirmation (DANGEROUS)
python3 jira_utils.py --bulk-delete --input-file to_delete.csv --execute --force
```

### Dashboard Management

```bash
# List dashboards
python3 jira_utils.py --dashboards
python3 jira_utils.py --dashboards --owner user@email.com
python3 jira_utils.py --dashboards --shared

# Get dashboard details & gadgets
python3 jira_utils.py --dashboard 12345
python3 jira_utils.py --gadgets 12345

# Create / copy / update / delete
python3 jira_utils.py --create-dashboard "My Dashboard" --description "desc"
python3 jira_utils.py --copy-dashboard 12345 --name "Copy of Dashboard"
python3 jira_utils.py --update-dashboard 12345 --name "New Name"
python3 jira_utils.py --delete-dashboard 12345 --force

# Gadget management
python3 jira_utils.py --add-gadget com.atlassian.jira.gadgets:filter-results-gadget --dashboard 12345
python3 jira_utils.py --remove-gadget 67890 --dashboard 12345
python3 jira_utils.py --update-gadget 67890 --dashboard 12345 --position 0,1 --color blue
```

### Jira CLI Flags

| Flag | Description |
|------|-------------|
| `--env FILE` | Path to dotenv file to load (default: `.env`) |
| `--list` | List all available Jira projects |
| `--project KEY` | Project key to operate on (e.g., PROJ) |
| `--get-workflow` | Display workflow statuses for the specified project |
| `--get-issue-types` | Display issue types for the specified project |
| `--get-fields [TYPE ...]` | Display create/edit/transition fields. Optionally filter by issue types |
| `--get-versions` | Display versions (releases) with detailed info |
| `--get-components` | List all components for the specified project |
| `--get-children KEY` | Display full child hierarchy for the given ticket |
| `--get-related KEY` | Display related issues for the given ticket (linked + children) |
| `--hierarchy [DEPTH]` | When used with `--get-related`, recursively traverse to build a hierarchy |
| `--table-format FORMAT` | Table layout for hierarchy CSV output (`flat` or `indented`) |
| `--releases [PATTERN]` | List releases for the specified project (optional glob pattern) |
| `--release-tickets RELEASE` | Get tickets for a release |
| `--issue-types TYPE [TYPE ...]` | Filter by issue types (e.g., Bug Story Task) |
| `--no-release` | Get tickets with no release assigned |
| `--total` | Show ticket count |
| `--get-tickets` | Get tickets |
| `--status STATUS [STATUS ...]` | Filter by status. Can specify multiple. Use `^` prefix to exclude |
| `--date FILTER` | Date filter: today, week, month, year, all, or MM-DD-YYYY:MM-DD-YYYY range |
| `--limit N` | Limit the number of tickets to retrieve |
| `--jql QUERY` | Run a custom JQL query and display results |
| `--create-ticket [FILE]` | Create a new ticket (from JSON file or CLI flags). Dry-run by default |
| `--summary TEXT` | Ticket summary |
| `--issue-type TYPE` | Issue type name |
| `--ticket-description TEXT` | Plain-text description |
| `--assignee-id ACCOUNT_ID` | Assignee accountId |
| `--components NAME [NAME ...]` | Component names to set |
| `--fix-versions VERSION [VERSION ...]` | Fix version(s) to set |
| `--labels LABEL [LABEL ...]` | Labels to set |
| `--parent KEY` | Parent ticket key |
| `--dump-file FILE` | Output filename for dumping tickets |
| `--dump-format FORMAT` | Output format: `csv`, `json`, or `excel` |
| `--bulk-update` | Perform bulk update on tickets from input file |
| `--bulk-delete` | Perform bulk delete on tickets from input file (dry-run by default) |
| `--input-file FILE` | Input CSV file containing ticket keys for bulk update/delete |
| `--set-release RELEASE` | Set the release/fixVersion on tickets |
| `--remove-release` | Remove all releases from tickets |
| `--transition STATUS` | Transition tickets to the specified status |
| `--assign USER` | Assign tickets to the specified user (email or "unassigned") |
| `--dry-run` | Preview changes without applying them (default: True) |
| `--execute` | Execute the bulk update/delete or ticket creation |
| `--max-updates N` | Maximum number of tickets to update in bulk operation |
| `--max-deletes N` | Maximum number of tickets to delete in bulk operation |
| `--delete-subtasks` | When used with `--bulk-delete`, delete subtasks as well |
| `--show-jql` | Print the equivalent JQL statement for the operation |
| `--dashboards` | List accessible dashboards |
| `--dashboard ID` | Get dashboard details by ID |
| `--owner USER` | Filter dashboards by owner (use "me" for current user) |
| `--shared` | Show only dashboards shared with current user |
| `--create-dashboard NAME` | Create a new dashboard with the specified name |
| `--update-dashboard ID` | Update dashboard by ID |
| `--delete-dashboard ID` | Delete dashboard by ID |
| `--copy-dashboard ID` | Copy/clone dashboard by ID |
| `--description TEXT` | Dashboard description |
| `--name NAME` | New name for dashboard |
| `--share-permissions JSON` | Share permissions as JSON array |
| `--force` | Skip confirmation prompts (for delete operations) |
| `--gadgets DASHBOARD_ID` | List gadgets on the specified dashboard |
| `--add-gadget MODULE_KEY` | Add gadget to dashboard |
| `--remove-gadget GADGET_ID` | Remove gadget from dashboard |
| `--update-gadget GADGET_ID` | Update gadget on dashboard |
| `--position ROW,COL` | Gadget position as row,column (e.g., "0,1") |
| `--color COLOR` | Gadget color |
| `--gadget-properties JSON` | Gadget properties as JSON object |
| `--list-filters` | List accessible saved filters |
| `--get-filter ID` | Get details of a saved filter by ID |
| `--run-filter ID` | Run a saved filter by ID |
| `--favourite` | Show only favourite/starred filters |
| `--get-comments {all,latest}` | Include comments in ticket output |
| `--no-formatting` | Disable all Excel formatting |
| `-v`, `--verbose` | Enable verbose output to stdout |
| `-q`, `--quiet` | Minimal stdout |

---

## excel-utils (`excel_utils.py`)

Concatenate, convert, and diff Excel (`.xlsx`) workbooks from the command line.

### Concatenation

```bash
# Merge all rows from multiple files into a single sheet (columns are unioned)
python3 excel_utils.py --concat fileA.xlsx fileB.xlsx --method merge-sheet --output merged.xlsx

# Add each file as a separate sheet in the output workbook
python3 excel_utils.py --concat fileA.xlsx fileB.xlsx --method add-sheet --output combined.xlsx

# Merge all .xlsx files in the current directory
python3 excel_utils.py --concat *.xlsx --method merge-sheet --output all_data.xlsx
```

### Conversion

```bash
# Excel → CSV
python3 excel_utils.py --convert-to-csv data.xlsx
python3 excel_utils.py --convert-to-csv data.xlsx --output custom_name.csv

# CSV → Excel (with header styling, conditional formatting, auto-fit columns)
python3 excel_utils.py --convert-from-csv data.csv
python3 excel_utils.py --convert-from-csv data.csv --output styled.xlsx

# CSV → Excel with clickable Jira ticket links in the "key" column
python3 excel_utils.py --convert-from-csv data.csv --jira-url https://cornelisnetworks.atlassian.net
```

### Diff

```bash
# Diff two files — produces a report with Summary and Diff sheets
python3 excel_utils.py --diff fileA.xlsx fileB.xlsx --output changes.xlsx

# Pairwise diff across three files (A→B, B→C)
python3 excel_utils.py --diff v1.xlsx v2.xlsx v3.xlsx
```

Rows are matched by a key column (`key` if present, otherwise the first column). Each row is marked **ADDED**, **REMOVED**, **CHANGED**, or **SAME**.

### Formatting Options

All output workbooks include automatic styling by default:

| Feature | Description |
|---------|-------------|
| Header styling | Bold white text on dark-blue background, centered, with borders |
| Status conditional formatting | Cell fill color based on status value (e.g., green for Closed, red for Open) |
| Priority conditional formatting | Red fill for P0-Stopper, yellow fill for P1-Critical |
| Jira ticket hyperlinks | "key" columns become clickable links to the Jira ticket (when `--jira-url` or `JIRA_URL` is set) |
| Auto-fit columns | Column widths adjusted to content |
| Frozen header row | First row stays visible when scrolling |
| Auto-filter | Drop-down filters on every column |

Use `--no-formatting` to disable all styling and produce a plain data-only workbook:

```bash
python3 excel_utils.py --convert-from-csv data.csv --no-formatting
python3 excel_utils.py --concat *.xlsx --no-formatting
```

### Excel CLI Flags

| Flag | Description |
|------|-------------|
| `--concat FILE [FILE ...]` | List of Excel (`.xlsx`) files to concatenate |
| `--convert-to-csv FILE` | Convert an Excel (`.xlsx`) file to a comma-delimited CSV file |
| `--convert-from-csv FILE` | Convert a comma-delimited CSV file to an Excel (`.xlsx`) file |
| `--diff FILE [FILE ...]` | Diff two or more Excel (`.xlsx`) files and produce a diff report |
| `--to-plan-json FILE` | Convert a CSV/Excel file into the feature-plan JSON format used by the ticket creation pipeline |
| `--project KEY` | Override the Jira project key (used with `--to-plan-json`). Auto-detected if not provided |
| `--product-family TEXT` | Override the product family (used with `--to-plan-json`). Auto-detected if not provided |
| `--feature-name TEXT` | Feature name for the plan (used with `--to-plan-json`). Defaults to the first epic summary |
| `--method METHOD` | Concatenation method: `merge-sheet` (default) or `add-sheet` |
| `--output FILE`, `-o FILE` | Output filename (default depends on action) |
| `--no-formatting` | Disable all Excel formatting (header styling, conditional formatting, auto-fit columns) |
| `--jira-url URL` | Jira instance URL for clickable "key" column hyperlinks. Pass "none" to disable |
| `--d-columns COL [COL ...]` | Column names for the Dashboard summary sheet pivot tables (used with `--convert-from-csv`) |
| `-v`, `--verbose` | Enable verbose output to stdout |
| `-q`, `--quiet` | Minimal stdout |

---

## drawio-utils (`drawio_utilities.py`)

Generate draw.io dependency diagrams from Jira hierarchy CSV exports.

### Basic Usage

```bash
# Basic usage
python3 drawio_utilities.py --create-map tickets.csv

# Custom output file and title
python3 drawio_utilities.py --create-map tickets.csv --output diagram.drawio --title "Release 12.2 Dependencies"
```

### End-to-End Workflow

```bash
# 1. Export hierarchy from Jira
python3 jira_utils.py --get-related PROJ-100 --hierarchy --dump-file tickets

# 2. Generate draw.io diagram
python3 drawio_utilities.py --create-map tickets.csv

# 3. Open the .drawio file in draw.io or VS Code
```

### Color Coding

| Link Type | Border | Fill |
|-----------|--------|------|
| Root ticket | — | Light green |
| `is blocked by` / `blocks` | Red | Light red |
| `relates to` | Blue | Light blue |
| Other | Gray | White |

### Draw.io CLI Flags

| Flag | Description |
|------|-------------|
| `--create-map CSV_FILE` | Create a draw.io diagram from a Jira hierarchy CSV file |
| `--output FILE`, `-o FILE` | Output filename for the `.drawio` file (default: input file with `.drawio` extension) |
| `--title TITLE`, `-t TITLE` | Title for the diagram (default: derived from root ticket) |
| `-v`, `--verbose` | Enable verbose output to stdout |
| `-q`, `--quiet` | Minimal stdout |
