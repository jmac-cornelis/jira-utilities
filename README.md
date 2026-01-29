# Jira Utilities

A command-line tool for interacting with Cornelis Networks' Jira instance. This utility provides various functions for querying projects, tickets, releases, and performing bulk updates.

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Authentication](#authentication)
- [Usage](#usage)
- [Command Reference](#command-reference)
- [Examples](#examples)
- [Output Formats](#output-formats)
- [Date Filters](#date-filters)

## Requirements

- Python 3.9 or higher
- Access to Cornelis Networks Jira instance
- Jira API token

### Python Dependencies

- `jira` - Jira API client library
- `requests` - HTTP library for API calls

## Installation

1. Clone or download this repository

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install jira requests
   ```

## Authentication

This script uses Jira API tokens for authentication. You must set up environment variables before running:

1. Generate an API token at: https://id.atlassian.com/manage-profile/security/api-tokens

2. Set environment variables:
   ```bash
   export JIRA_EMAIL="your.email@cornelisnetworks.com"
   export JIRA_API_TOKEN="your_api_token_here"
   ```

   Alternatively, create a `.env` file with these exports and source it:
   ```bash
   source .env
   ```

> **IMPORTANT:** Never commit credentials to version control.

## Usage

Basic syntax:
```bash
python jira_utils.py [OPTIONS]
```

With virtual environment:
```bash
source venv/bin/activate && source .env && python jira_utils.py [OPTIONS]
```

## Command Reference

### Global Options

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help message and exit |
| `-v, --verbose` | Enable verbose/debug output to stdout |
| `-q, --quiet` | Minimal stdout output |
| `--show-jql` | Print the equivalent JQL statement and save to `jql.txt` |

### Project Information

| Option | Description |
|--------|-------------|
| `--list` | List all available Jira projects |
| `--project KEY` | Specify project key to operate on (required for most commands) |
| `--workflow` | Display workflow statuses for the specified project |
| `--issue-types` | Display issue types for the specified project |
| `--fields [TYPE ...]` | Display create/edit/transition fields. Optionally filter by issue types |
| `--versions` | Display versions (releases) with detailed info |
| `--components` | List all components for the project |

### Release Management

| Option | Description |
|--------|-------------|
| `--releases [PATTERN]` | List releases for the project. Optional glob pattern (e.g., `"12.*"`) |
| `--release-tickets RELEASE` | Get tickets associated with a specific release (case-insensitive) |
| `--no-release [TYPE ...]` | Get tickets with no release assigned. Optionally filter by issue types |

### Ticket Queries

| Option | Description |
|--------|-------------|
| `--total [TYPE ...]` | Show ticket count. Optionally filter by issue types |
| `--get-tickets [TYPE ...]` | Get tickets. Optionally filter by issue types |
| `--jql QUERY` | Run a custom JQL query |

### Query Filters

| Option | Description |
|--------|-------------|
| `--status STATUS [STATUS ...]` | Filter by status (case-insensitive). Multiple statuses allowed |
| `--date FILTER` | Date filter (see [Date Filters](#date-filters)) |
| `--limit N` | Limit the number of tickets retrieved |

### Output Options

| Option | Description |
|--------|-------------|
| `--dump-file FILE` | Output filename for dumping tickets (extension added automatically) |
| `--dump-format FORMAT` | Output format: `csv` (default) or `json` |

### Bulk Update Operations

| Option | Description |
|--------|-------------|
| `--bulk-update` | Perform bulk update on tickets from input file |
| `--input-file FILE` | Input CSV file containing ticket keys for bulk update |
| `--set-release RELEASE` | Set the release/fixVersion on tickets |
| `--remove-release` | Remove all releases from tickets |
| `--transition STATUS` | Transition tickets to the specified status |
| `--assign USER` | Assign tickets to user (email or "unassigned") |
| `--dry-run` | Preview changes without applying them (default: True) |
| `--execute` | Execute the bulk update (disables dry-run) |
| `--max-updates N` | Maximum number of tickets to update |

## Examples

### List Projects
```bash
python jira_utils.py --list
```

### Project Information
```bash
# Show workflow statuses
python jira_utils.py --project PROJ --workflow

# Show issue types
python jira_utils.py --project PROJ --issue-types

# Show all fields for all issue types
python jira_utils.py --project PROJ --fields

# Show fields for specific issue types
python jira_utils.py --project PROJ --fields Bug Task

# Show versions/releases
python jira_utils.py --project PROJ --versions

# Show components
python jira_utils.py --project PROJ --components

# Show only components with tickets created in the last 2 weeks
python jira_utils.py --project PROJ --components --date week

# Show components with activity this month
python jira_utils.py --project PROJ --components --date month

# Dump components to file
python jira_utils.py --project PROJ --components --dump-file components

# Dump active components with ticket counts
python jira_utils.py --project PROJ --components --date week --dump-file active_components

# Show all project info at once
python jira_utils.py --project PROJ --workflow --issue-types --fields --versions --components
```

### Release Queries
```bash
# List all releases
python jira_utils.py --project PROJ --releases

# List releases matching a pattern
python jira_utils.py --project PROJ --releases "12.*"

# Dump releases to file
python jira_utils.py --project PROJ --releases --dump-file all_releases
python jira_utils.py --project PROJ --releases "12.*" --dump-file 12x_releases

# List releases with exclusions (12.* but not containing "Samples")
python jira_utils.py --project PROJ --releases "12.*,^*Samples*"

# Multiple exclusions
python jira_utils.py --project PROJ --releases "12.*,^*Samples*,^*Test*"

# Multiple includes with exclusions
python jira_utils.py --project PROJ --releases "12.*,13.*,^*Samples*"

# Get tickets for a specific release
python jira_utils.py --project PROJ --release-tickets "v1.0"

# Get tickets for all releases matching a pattern
python jira_utils.py --project PROJ --releases "12.*" --get-tickets

# Get tickets for releases with exclusions
python jira_utils.py --project PROJ --releases "12.*,^*Samples*" --get-tickets

# Get Open tickets for 12.x releases and dump to file
python jira_utils.py --project PROJ --releases "12.*" --get-tickets --status Open --dump-file 12x_tickets

# Get tickets with no release assigned
python jira_utils.py --project PROJ --no-release

# Get Open Bugs with no release
python jira_utils.py --project PROJ --no-release Bug --status Open
```

### Ticket Counts
```bash
# Total ticket count
python jira_utils.py --project PROJ --total

# Count for specific issue types
python jira_utils.py --project PROJ --total Bug Task

# Count for Open tickets
python jira_utils.py --project PROJ --total --status Open

# Count for Open/In Progress Bugs
python jira_utils.py --project PROJ --total Bug --status Open "In Progress"

# Count for tickets created this week
python jira_utils.py --project PROJ --total --date week
```

### Get Tickets
```bash
# Get all tickets
python jira_utils.py --project PROJ --get-tickets

# Get up to 50 Open Bugs
python jira_utils.py --project PROJ --get-tickets Bug --status Open --limit 50

# Get Closed tickets from this month
python jira_utils.py --project PROJ --get-tickets --status Closed --date month

# Get tickets created in date range
python jira_utils.py --project PROJ --get-tickets --date 01-01-2024:12-31-2024

# Dump all tickets to CSV
python jira_utils.py --project PROJ --get-tickets --dump-file tickets

# Dump Open Bugs to JSON
python jira_utils.py --project PROJ --get-tickets Bug --status Open --dump-file bugs --dump-format json
```

### Custom JQL Queries
```bash
# Run a custom JQL query
python jira_utils.py --jql "project = PROJ AND status = Open"

# JQL with limit
python jira_utils.py --jql "assignee = currentUser() AND status != Done" --limit 20

# Dump JQL results to CSV
python jira_utils.py --jql "project = PROJ" --dump-file results --dump-format csv
```

### Show Equivalent JQL
```bash
# Show the JQL that would be generated
python jira_utils.py --project PROJ --get-tickets Bug --status Open --show-jql

# The JQL is displayed at the end and saved to jql.txt
```

### Bulk Updates
```bash
# Step 1: Find tickets and dump to CSV
python jira_utils.py --jql "project = PROJ AND fixVersion is EMPTY" --dump-file orphans

# Step 2: Preview bulk update (dry-run is default)
python jira_utils.py --bulk-update --input-file orphans.csv --set-release "12.1.1.x"

# Step 3: Execute bulk update
python jira_utils.py --bulk-update --input-file orphans.csv --set-release "12.1.1.x" --execute

# Transition tickets to Closed
python jira_utils.py --bulk-update --input-file tickets.csv --transition "Closed" --execute

# Assign tickets to a user
python jira_utils.py --bulk-update --input-file tickets.csv --assign "user@email.com" --execute

# Remove releases from tickets
python jira_utils.py --bulk-update --input-file tickets.csv --remove-release --execute

# Limit number of updates
python jira_utils.py --bulk-update --input-file tickets.csv --set-release "v2.0" --max-updates 10 --execute
```

## Output Formats

### CSV Format
The default output format. Includes columns:
- Key
- Project
- Type
- Status
- Priority
- Summary
- Assignee
- Reporter
- Created
- Updated
- Resolved
- Fix Version
- Affects Version (for bugs)

### Console Output
The console table displays:
- Key
- Type
- Status
- Priority
- Created
- Updated
- Fix Version
- Assignee
- Summary

### JSON Format
Use `--dump-format json` for JSON output. Each ticket is a JSON object with full field data.

## Release Pattern Syntax

The `--releases` option supports glob patterns with exclusions:

| Pattern | Description |
|---------|-------------|
| `*` | Match all releases |
| `12.*` | Match releases starting with "12." |
| `*beta*` | Match releases containing "beta" |
| `12.*,^*Samples*` | Match 12.* but exclude those containing "Samples" |
| `12.*,^*Samples*,^*Test*` | Multiple exclusions |
| `12.*,13.*` | Match either 12.* or 13.* |
| `12.*,13.*,^*Samples*` | Multiple includes with exclusion |

### Pattern Rules

- Use `*` as a wildcard (matches any characters)
- Use `?` to match a single character
- Separate multiple patterns with commas
- Prefix exclusion patterns with `^`
- Exclusions apply to all include patterns

### Examples

```bash
# All 12.x releases except samples
python jira_utils.py --project PROJ --releases "12.*,^*Samples*"

# All 12.x and 13.x releases except test releases
python jira_utils.py --project PROJ --releases "12.*,13.*,^*Test*,^*test*"

# Get tickets for filtered releases
python jira_utils.py --project PROJ --releases "12.*,^*Samples*" --get-tickets --dump-file filtered_tickets
```

## Date Filters

The `--date` option supports the following filters:

| Filter | Description |
|--------|-------------|
| `today` | Tickets created today |
| `week` | Tickets created in the last 7 days |
| `month` | Tickets created in the last 30 days |
| `year` | Tickets created in the last 365 days |
| `all` | All tickets (no date filter) |
| `MM-DD-YYYY:MM-DD-YYYY` | Tickets created within date range |

### Date Range Examples
```bash
# Tickets created in January 2024
python jira_utils.py --project PROJ --get-tickets --date 01-01-2024:01-31-2024

# Tickets created in Q1 2024
python jira_utils.py --project PROJ --get-tickets --date 01-01-2024:03-31-2024
```

## Logging

The script maintains two types of output:

1. **stdout** - Clean, formatted tables and user-facing messages
2. **Log file** (`jira_utils.log`) - Detailed logging with timestamps, function names, and line numbers

Use `-v` (verbose) for debug-level output to stdout, or `-q` (quiet) for minimal output.

## Files Generated

| File | Description |
|------|-------------|
| `jira_utils.log` | Detailed execution log (overwritten each run) |
| `jql.txt` | Last JQL query when using `--show-jql` |
| `*.csv` / `*.json` | Ticket dumps when using `--dump-file` |

## Error Handling

The script handles common errors gracefully:

- **Missing credentials** - Prompts to set environment variables
- **Invalid project** - Lists available projects
- **Invalid issue type/status** - Shows valid options
- **Rate limiting** - Automatic retry with backoff
- **Network errors** - Clear error messages

## Author

John Macdonald

## License

Internal use - Cornelis Networks