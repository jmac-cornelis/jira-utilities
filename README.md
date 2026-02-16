# Cornelis Agent Pipeline

An AI-powered agent pipeline for automating Jira release planning at Cornelis Networks. Built with Google ADK architecture patterns and supporting custom LLM endpoints.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Installation](#installation)
  - [Global CLI Install (pipx)](#global-cli-install-pipx)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Jira CLI (`jira_utils.py`)](#jira-cli-jira_utilspy)
  - [Draw.io CLI (`drawio_utilities.py`)](#drawio-cli-drawio_utilitiespy)
  - [Excel CLI (`excel_utils.py`)](#excel-cli-excel_utilspy)
  - [Workflows (`--workflow`)](#workflows---workflow)
  - [Agent Pipeline (`pm_agent.py`)](#agent-pipeline-pm_agentpy)
- [Ticket Creation](#ticket-creation)
- [Agent Pipeline](#agent-pipeline)
- [Tools](#tools)
- [Standalone Utilities](#standalone-utilities)
- [Development](#development)

## Overview

The Cornelis Agent Pipeline automates the process of creating Jira release structures from roadmap documents. Given roadmap slides, org charts, and the current Jira state, the agent:

1. **Analyzes** roadmap documents (PowerPoint, Excel, images)
2. **Examines** current Jira project state
3. **Creates** a release plan with tickets and assignments
4. **Reviews** the plan with human approval
5. **Executes** approved changes in Jira

### Key Features

- **Multi-agent architecture** — Specialized agents for different tasks
- **Human-in-the-loop** — Approval workflow before any Jira modifications
- **Custom LLM support** — Works with Cornelis internal LLM or external providers
- **Session persistence** — Resume interrupted workflows
- **Vision capabilities** — Extract data from images and slides
- **Ticket creation** — Create Jira tickets from CLI flags or JSON files
- **Draw.io diagrams** — Generate dependency diagrams from Jira hierarchy exports

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Release Planning Orchestrator                 │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Vision     │  │    Jira      │  │   Planning   │          │
│  │  Analyzer    │  │   Analyst    │  │    Agent     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌──────────────┐                                               │
│  │   Review     │                                               │
│  │    Agent     │                                               │
│  └──────────────┘                                               │
├─────────────────────────────────────────────────────────────────┤
│                         Tools Layer                              │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐   │
│  │ Jira Tools │ │Draw.io Tools│ │Vision Tools│ │ File Tools │   │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                      LLM Abstraction Layer                       │
│  ┌────────────────────┐  ┌────────────────────┐                 │
│  │   Cornelis LLM     │  │   LiteLLM Client   │                 │
│  │  (Internal API)    │  │ (OpenAI/Anthropic) │                 │
│  └────────────────────┘  └────────────────────┘                 │
├─────────────────────────────────────────────────────────────────┤
│                     Standalone CLI Utilities                      │
│  ┌────────────────────┐  ┌────────────────────┐                 │
│  │   jira_utils.py    │  │ drawio_utilities.py│                 │
│  └────────────────────┘  └────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

- Python 3.9 or higher
- Access to Cornelis Networks Jira instance
- Jira API token
- Access to Cornelis internal LLM (or external LLM API key)

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd cornelis-agent
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

### Global CLI Install (pipx)

To make `jira-utils` and `drawio-utils` available as commands in **any** directory (without activating a venv), use [pipx](https://pipx.pypa.io/):

```bash
# Install pipx (macOS)
brew install pipx
pipx ensurepath          # adds ~/.local/bin to PATH (restart terminal)

# Editable install from the repo — changes to source are reflected immediately
pipx install /path/to/this/repo --editable

# Verify
jira-utils -h
drawio-utils -h
```

This creates an isolated virtualenv with only the CLI dependencies (`jira`, `python-dotenv`, `requests`). The agent pipeline extras (`openai`, `litellm`, etc.) are **not** installed by default; add them with:

```bash
pipx install /path/to/this/repo --editable --pip-args='.[agents]'
```

To uninstall:

```bash
pipx uninstall cornelis-jira-tools
```

> **Note:** The `--editable` flag means the installed commands point back to your working copy. Any edits to `jira_utils.py` or `drawio_utilities.py` take effect immediately — no reinstall needed.

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Jira credentials
JIRA_EMAIL=your.email@cornelisnetworks.com
JIRA_API_TOKEN=your_api_token
JIRA_URL=https://cornelisnetworks.atlassian.net

# Cornelis internal LLM
CORNELIS_LLM_BASE_URL=http://internal-llm.cornelis.com/v1
CORNELIS_LLM_API_KEY=your_internal_key
CORNELIS_LLM_MODEL=cornelis-default

# External LLM (fallback/vision)
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key

# Provider selection
DEFAULT_LLM_PROVIDER=cornelis
VISION_LLM_PROVIDER=cornelis
FALLBACK_ENABLED=true
```

### Multiple Environment Files

You can maintain separate `.env` files for different Jira instances (e.g., sandbox vs. production) and select one at runtime with `--env`:

```bash
# Default: loads .env
python3 jira_utils.py --list

# Load a specific env file
python3 jira_utils.py --list --env .env_prod
python3 jira_utils.py --list --env .env_sandbox
```

> **Note:** The `--env` flag only affects `jira_utils.py`. The agent pipeline (`pm_agent.py`) always loads `.env`.

### LLM Provider Options

| Provider | Use Case | Configuration |
|----------|----------|---------------|
| `cornelis` | Default, internal LLM | `CORNELIS_LLM_*` variables |
| `openai` | GPT-4, GPT-4o | `OPENAI_API_KEY` |
| `anthropic` | Claude models | `ANTHROPIC_API_KEY` |

## Usage

### Jira CLI (`jira_utils.py`)

The standalone Jira CLI provides project inspection, ticket queries, ticket creation, bulk operations, and dashboard management.

#### Project & Metadata

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

#### Ticket Queries

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

#### Date Filters

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

#### Dump to File

Any query can be dumped to CSV or JSON:

```bash
python3 jira_utils.py --project PROJ --get-tickets --dump-file tickets
python3 jira_utils.py --project PROJ --get-tickets --dump-file tickets --dump-format json
python3 jira_utils.py --jql "project = PROJ" --dump-file results --dump-format csv
```

#### Bulk Update

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
```

#### Bulk Delete

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

#### Dashboard Management

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

---

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

#### Examples — CLI Flags

```bash
# Dry-run (preview only)
python3 jira_utils.py --create-ticket \
  --project PROJ --summary "Fix login timeout" --issue-type Bug

# Execute (actually create the ticket)
python3 jira_utils.py --create-ticket \
  --project PROJ --summary "Fix login timeout" --issue-type Bug \
  --components Platform --labels triage --fix-versions 12.3.0 \
  --execute
```

#### Examples — JSON File

```bash
# Dry-run from JSON
python3 jira_utils.py --create-ticket data/templates/create_story.json

# Execute from JSON
python3 jira_utils.py --create-ticket data/templates/create_story.json --execute

# JSON file + CLI override (override the summary)
python3 jira_utils.py --create-ticket data/templates/create_story.json \
  --summary "Override summary from CLI" --execute
```

#### JSON Input Format

See [`data/templates/create_ticket_input.schema.json`](data/templates/create_ticket_input.schema.json) for the full JSON Schema.

Example (`data/templates/create_ticket_input.example.json`):

```json
{
  "project": "PROJ",
  "summary": "Example ticket created via jira_utils.py",
  "issue_type": "Task",
  "description": "Plain-text description. Converted to Jira Cloud ADF on create.",
  "assignee_id": "5b10ac8d82e05b22cc7d4ef5",
  "components": ["Platform"],
  "fix_versions": ["12.3.0"],
  "labels": ["temp", "created-by-cli"],
  "parent": "PROJ-123"
}
```

A Story-specific template is also provided at [`data/templates/create_story.json`](data/templates/create_story.json).

#### Template Files

| File | Purpose |
|------|---------|
| [`data/templates/create_ticket_input.schema.json`](data/templates/create_ticket_input.schema.json) | JSON Schema (draft 2020-12) for the `--create-ticket FILE` input format |
| [`data/templates/create_ticket_input.example.json`](data/templates/create_ticket_input.example.json) | Generic Task example |
| [`data/templates/create_story.json`](data/templates/create_story.json) | Story template with acceptance criteria |

---

### Draw.io CLI (`drawio_utilities.py`)

Generate draw.io dependency diagrams from Jira hierarchy CSV exports.

```bash
# Basic usage
python3 drawio_utilities.py --create-map tickets.csv

# Custom output file and title
python3 drawio_utilities.py --create-map tickets.csv --output diagram.drawio --title "Release 12.2 Dependencies"
```

#### End-to-End Workflow

```bash
# 1. Export hierarchy from Jira
python3 jira_utils.py --get-related PROJ-100 --hierarchy --dump-file tickets

# 2. Generate draw.io diagram
python3 drawio_utilities.py --create-map tickets.csv

# 3. Open the .drawio file in draw.io or VS Code
```

#### Color Coding

| Link Type | Border | Fill |
|-----------|--------|------|
| Root ticket | — | Light green |
| `is blocked by` / `blocks` | Red | Light red |
| `relates to` | Blue | Light blue |
| Other | Gray | White |

---

### Excel CLI (`excel_utils.py`)

Concatenate, convert, and diff Excel (`.xlsx`) workbooks from the command line.

#### Concatenation

```bash
# Merge all rows from multiple files into a single sheet (columns are unioned)
python3 excel_utils.py --concat fileA.xlsx fileB.xlsx --method merge-sheet --output merged.xlsx

# Add each file as a separate sheet in the output workbook
python3 excel_utils.py --concat fileA.xlsx fileB.xlsx --method add-sheet --output combined.xlsx

# Merge all .xlsx files in the current directory
python3 excel_utils.py --concat *.xlsx --method merge-sheet --output all_data.xlsx
```

| Flag | Description |
|------|-------------|
| `--concat FILE [FILE ...]` | Two or more `.xlsx` files to concatenate |
| `--method merge-sheet\|add-sheet` | `merge-sheet` (default) merges all rows into one sheet; `add-sheet` creates a sheet per file |
| `--output FILE` | Output filename (default: `concat_output.xlsx`) |

#### Conversion

```bash
# Excel → CSV
python3 excel_utils.py --convert-to-csv data.xlsx
python3 excel_utils.py --convert-to-csv data.xlsx --output custom_name.csv

# CSV → Excel (with header styling, conditional formatting, auto-fit columns)
python3 excel_utils.py --convert-from-csv data.csv
python3 excel_utils.py --convert-from-csv data.csv --output styled.xlsx
```

| Flag | Description |
|------|-------------|
| `--convert-to-csv FILE` | Convert `.xlsx` to comma-delimited `.csv` |
| `--convert-from-csv FILE` | Convert `.csv` to styled `.xlsx` |
| `--output FILE` | Override the default output filename |

#### Diff

```bash
# Diff two files — produces a report with Summary and Diff sheets
python3 excel_utils.py --diff fileA.xlsx fileB.xlsx --output changes.xlsx

# Pairwise diff across three files (A→B, B→C)
python3 excel_utils.py --diff v1.xlsx v2.xlsx v3.xlsx
```

Rows are matched by a key column (`key` if present, otherwise the first column). Each row is marked **ADDED**, **REMOVED**, **CHANGED**, or **SAME**.

| Flag | Description |
|------|-------------|
| `--diff FILE [FILE ...]` | Two or more `.xlsx` files to diff |
| `--output FILE` | Output filename (default: `diff_output.xlsx`) |

#### Formatting Options

All output workbooks include automatic styling by default:

| Feature | Description |
|---------|-------------|
| Header styling | Bold white text on dark-blue background, centered, with borders |
| Status conditional formatting | Cell fill color based on status value (e.g., green for Closed, red for Open) |
| Priority conditional formatting | Red fill for P0-Stopper, yellow fill for P1-Critical |
| Auto-fit columns | Column widths adjusted to content |
| Frozen header row | First row stays visible when scrolling |
| Auto-filter | Drop-down filters on every column |

Use `--no-formatting` to disable all styling and produce a plain data-only workbook:

```bash
python3 excel_utils.py --convert-from-csv data.csv --no-formatting
python3 excel_utils.py --concat *.xlsx --no-formatting
```

#### Global Flags

| Flag | Description |
|------|-------------|
| `-v`, `--verbose` | Enable verbose (DEBUG-level) output |
| `-q`, `--quiet` | Minimal stdout output |
| `--no-formatting` | Disable all Excel formatting (header styling, conditional formatting, auto-fit) |

---

### Workflows (`--workflow`)

Multi-step automated pipelines that chain Jira queries, LLM analysis, and Excel formatting into a single command.

#### Bug Report Workflow

Generate a cleaned, enriched bug report from a Jira filter:

```bash
# Basic usage — looks up filter by name, pulls tickets, sends to LLM, converts to Excel
python3 pm_agent.py --workflow bug-report --filter "SW 12.1.1 P0/P1 Bugs" --timeout 800

# With debug logging
python3 pm_agent.py --workflow bug-report --filter "SW 12.1.1 P0/P1 Bugs" --timeout 800 --debug

# Custom prompt file
python3 pm_agent.py --workflow bug-report --filter "My Filter" --prompt my_prompt.md --timeout 600
```

**Steps performed:**

| Step | Action | Output |
|------|--------|--------|
| 1 | Connect to Jira | — |
| 2 | Look up filter by name from favourite filters | Filter ID |
| 3 | Run filter to get tickets with latest comments | Issues list |
| 4 | Dump tickets to JSON | `<filter_name>.json` |
| 5 | Send JSON + prompt to LLM for analysis | `llm_output.md` + extracted files |
| 6 | Convert any extracted CSV to styled Excel | `<name>.xlsx` |

#### Workflow Flags

| Flag | Description |
|------|-------------|
| `--workflow NAME` | Workflow to run (currently: `bug-report`) |
| `--filter NAME` | Jira filter name to look up (required for `bug-report`) |
| `--prompt FILE` | LLM prompt file (default: `agents/prompts/cn5000_bugs_clean.md`) |
| `--timeout SECS` | LLM request timeout in seconds |
| `--limit N` | Max tickets to retrieve |
| `--output FILE` | Override output filename |
| `--debug` | Enable debug-level logging |

---

### Agent Pipeline (`pm_agent.py`)

```bash
# Run full release planning workflow
python pm_agent.py plan --project PROJ --roadmap slides.pptx --org-chart org.drawio

# Analyze Jira project state
python pm_agent.py analyze --project PROJ --quick

# Analyze roadmap files
python pm_agent.py vision roadmap.png roadmap.xlsx

# List saved sessions
python pm_agent.py sessions --list

# Resume a saved session
python pm_agent.py resume --session abc123
```

#### Example Workflow

```bash
# 1. Start release planning
python pm_agent.py plan \
  --project ENG \
  --roadmap "Q1_Roadmap.pptx" \
  --roadmap "Features.xlsx" \
  --org-chart "Engineering_Org.drawio" \
  --save-session

# Output:
# ============================================================
# CORNELIS RELEASE PLANNING AGENT
# ============================================================
#
# Project: ENG
# Roadmap files: 2
# Org chart: Engineering_Org.drawio
#
# Step 1: Analyzing inputs...
# Step 2: Creating release plan...
# Step 3: Presenting plan for review...
#
# RELEASE PLAN
# ============
# Release: 12.1.0
#   [Epic] Implement new fabric manager interface
#   [Story] Add topology discovery - Fabric - John Smith
#   [Story] Implement health monitoring - Fabric - Jane Doe
# ...
#
# Session saved: abc123
```

### Programmatic Usage

```python
from agents.orchestrator import ReleasePlanningOrchestrator

# Create orchestrator
orchestrator = ReleasePlanningOrchestrator()

# Run workflow
result = orchestrator.run({
    'project_key': 'ENG',
    'roadmap_files': ['roadmap.pptx'],
    'org_chart_file': 'org.drawio',
    'mode': 'full'
})

if result.success:
    print(result.content)
    
    # Execute approved plan
    orchestrator.execute_approved_plan()
```

## Agent Pipeline

### Orchestrator Agent

Coordinates the end-to-end workflow:
- Manages sub-agents
- Tracks workflow state
- Handles errors and recovery

### Vision Analyzer Agent

Extracts roadmap data from visual documents:
- PowerPoint slides
- Excel spreadsheets
- Images (PNG, JPG)

### Jira Analyst Agent

Analyzes current Jira project state:
- Existing releases
- Component structure
- Team assignments
- Workflow states

### Planning Agent

Creates release structures:
- Maps features to tickets
- Assigns components and owners
- Sets release versions

### Review Agent

Manages human approval:
- Presents plans for review
- Handles modifications
- Executes approved changes

## Tools

### Jira Tools

| Tool | Description |
|------|-------------|
| `get_project_info` | Get project details |
| `get_project_workflows` | Get workflow statuses |
| `get_project_issue_types` | Get issue types |
| `get_releases` | List releases/versions |
| `get_release_tickets` | Get tickets for a release |
| `get_components` | List project components |
| `get_related_tickets` | Traverse ticket links/hierarchy |
| `search_tickets` | Run JQL query |
| `create_ticket` | Create new ticket |
| `update_ticket` | Update existing ticket |
| `create_release` | Create new release |
| `link_tickets` | Create ticket links |
| `assign_ticket` | Assign ticket to user |

### Draw.io Tools

| Tool | Description |
|------|-------------|
| `parse_org_chart` | Extract org structure from draw.io |
| `get_responsibilities` | Map people to responsibility areas |
| `create_ticket_diagram` | Generate diagram from CSV |
| `create_diagram_from_tickets` | Generate diagram from ticket data |

### Vision Tools

| Tool | Description |
|------|-------------|
| `analyze_image` | Analyze image with vision LLM |
| `extract_roadmap_from_ppt` | Extract from PowerPoint |
| `extract_roadmap_from_excel` | Extract from Excel |

## Development

### Project Structure

```
cornelis-agent/
├── agents/                  # Agent definitions
│   ├── orchestrator.py      # Main orchestrator
│   ├── jira_analyst.py      # Jira analysis
│   ├── planning_agent.py    # Release planning
│   ├── vision_analyzer.py   # Document analysis
│   └── review_agent.py      # Human review
├── llm/                     # LLM abstraction
│   ├── base.py              # Abstract interface
│   ├── cornelis_llm.py      # Internal LLM client
│   ├── litellm_client.py    # External LLM client
│   └── config.py            # LLM configuration
├── tools/                   # Agent tools
│   ├── jira_tools.py        # Jira operations
│   ├── drawio_tools.py      # Draw.io operations
│   ├── vision_tools.py      # Vision/document tools
│   └── file_tools.py        # File operations
├── state/                   # State management
│   ├── session.py           # Session state
│   └── persistence.py       # Storage backends
├── config/                  # Configuration
│   ├── settings.py          # App settings
│   └── prompts/             # Agent prompts
├── data/
│   ├── templates/           # Ticket creation templates & schema
│   │   ├── create_ticket_input.schema.json
│   │   ├── create_ticket_input.example.json
│   │   ├── create_story.json
│   │   ├── epic.json        # Agent pipeline template
│   │   ├── story.json       # Agent pipeline template
│   │   ├── task.json        # Agent pipeline template
│   │   └── release.json     # Agent pipeline template
│   └── knowledge/           # Product knowledge
│       └── cornelis_products.md
├── plans/                   # Architecture & conversation docs
├── jira_utils.py            # Standalone Jira CLI utility (→ jira-utils)
├── drawio_utilities.py      # Standalone draw.io CLI utility (→ drawio-utils)
├── pm_agent.py                  # Agent pipeline entry point
├── pyproject.toml           # Package metadata & console_scripts (pipx)
├── .env.example             # Environment template
└── requirements.txt         # Dependencies
```

### Adding New Tools

1. Create tool function with `@tool` decorator:
   ```python
   from tools.base import tool, ToolResult
   
   @tool(description='My new tool')
   def my_tool(param: str) -> ToolResult:
       # Implementation
       return ToolResult.success({'result': 'data'})
   ```

2. Add to tool collection class
3. Register with agent

### Adding New Agents

1. Create agent class extending `BaseAgent`
2. Define instruction prompt
3. Register tools
4. Implement `run()` method

### Testing

```bash
# Run tests
pytest tests/

# Run specific test
pytest tests/test_tools/test_jira_tools.py
```

## Standalone Utilities

The CLI utilities can be used standalone (without the agent pipeline). After a `pipx install` they are available globally as `jira-utils`, `drawio-utils`, and `excel-utils`:

| Command | Source | Description |
|---------|--------|-------------|
| `jira-utils` | [`jira_utils.py`](jira_utils.py) | Full-featured Jira CLI (project queries, ticket creation, bulk ops, dashboards) |
| `drawio-utils` | [`drawio_utilities.py`](drawio_utilities.py) | Draw.io diagram generator from Jira hierarchy CSV exports |
| `excel-utils` | [`excel_utils.py`](excel_utils.py) | Excel workbook concatenation, CSV conversion, and diff reporting |

Run any of them with `-h` for full help:

```bash
# Via pipx (global)
jira-utils -h
drawio-utils -h
excel-utils -h

# Or directly from the repo
python3 jira_utils.py -h
python3 drawio_utilities.py -h
python3 excel_utils.py -h
```

## License

Proprietary — Cornelis Networks

## Support

For issues or questions, contact the Engineering Tools team.
