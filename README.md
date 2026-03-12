# Cornelis Jira PM Tools

AI-powered PM agents and CLI utilities for Jira at Cornelis Networks.

## What's In The Box

| Name | What It Does | LLM? | Run With |
|---|---|---|---|
| Ticket Monitor | Validates new tickets, auto-fills missing fields, learns from corrections | No | `python ticket_monitor_cli.py` |
| Release Tracker | Snapshots releases, tracks velocity, predicts readiness | No | `python release_tracker_cli.py` |
| Feature Planner | Multi-agent pipeline: scope doc → Initiative → Epics → Stories | Yes | `python pm_agent.py` |
| Jira CLI | Project queries, ticket creation, bulk ops, dashboards | No | `jira-utils` |
| Excel CLI | CSV/Excel conversion, merge, diff | No | `excel-utils` |
| Draw.io CLI | Dependency diagrams from Jira exports | No | `drawio-utils` |
| MCP Server | Exposes Jira tools to AI assistants (Claude Desktop) | No | `jira-mcp-server` |

## Quick Start

1. Clone & install (`pip install -e '.[agents]'` for full, `pip install -r requirements.txt` for minimal)
2. Configure `.env` (requires JIRA_EMAIL, JIRA_API_TOKEN, JIRA_URL)
3. Verify: `jira-utils --list`

## Configuration

### Environment Variables

**Required** (all tools):
| Variable | Purpose |
|---|---|
| JIRA_EMAIL | Your Jira login email |
| JIRA_API_TOKEN | API token for authentication |
| JIRA_URL | Jira instance URL |

**LLM** (Feature Planner only):
| Variable | Purpose |
|---|---|
| CORNELIS_LLM_BASE_URL | Internal LLM API endpoint |
| CORNELIS_LLM_API_KEY | Internal LLM key |
| CORNELIS_LLM_MODEL | Default internal model |
| DEFAULT_LLM_PROVIDER | Set to cornelis, openai, or anthropic |
| OPENAI_API_KEY | External fallback key |
| ANTHROPIC_API_KEY | External fallback key |

**Optional**:
| Variable | Purpose |
|---|---|
| BRAVE_SEARCH_API_KEY | Web search access |
| TAVILY_API_KEY | Alternative web search access |
| CORNELIS_MCP_URL | MCP server endpoint |
| CORNELIS_MCP_API_KEY | MCP server authentication |

### Config Files

| File Path | What It Controls |
|---|---|
| config/ticket_monitor.yaml | Validation rules, learning thresholds, notification settings |
| config/release_tracker.yaml | Tracked releases, velocity windows, cycle time config |
| config/prompts/*.md | System prompts for LLM-based agents |
| .env / .env_prod / .env_sandbox | Jira credentials per environment |

## Agents

### Ticket Monitor

Watches for newly created tickets and validates required fields based on issue type. Uses a local learning store to auto-fill missing fields when confident.

**Confidence-Based Actions:**

| Confidence | Action | Example |
|---|---|---|
| ≥90% | Auto-fill | Sets component to "JKR Host Driver" and posts comment |
| ≥50% | Suggest | Posts comment asking creator to confirm "BTS/verbs" |
| <50% | Flag | Posts comment warning about missing component |

**Validation Rules:**

| Issue Type | Required | Warn |
|---|---|---|
| Bug | affectedVersion, components, priority, description | assignee, labels |
| Story | components, fixVersions | assignee |
| Epic | description, fixVersions | components |

**Usage:**

```bash
# Validate and act on new tickets
python ticket_monitor_cli.py --project STL

# Dry-run (report only)
python ticket_monitor_cli.py --project STL --dry-run

# Process historical tickets to build learning store
python ticket_monitor_cli.py --project STL --learn-only

# Check monitor state and stats
python ticket_monitor_cli.py --status
```

**CLI Flags:**

| Flag | Description |
|---|---|
| `--project KEY` | Target Jira project |
| `--dry-run` | Report only, no updates |
| `--since DATE` | Process from specific ISO date |
| `--learn-only` | Build database without actions |
| `--reset-learning` | Clear database and restart |
| `--status` | Show current stats |

**Cron:**

```bash
*/5 * * * * cd /path/to/repo && .venv/bin/python ticket_monitor_cli.py --project STL >> logs/ticket_monitor.log 2>&1
```

**Learning:** 
The agent tracks when humans correct its auto-filled fields. This feedback loop adjusts confidence scores for future predictions.

### Release Tracker

Monitors releases throughout the day and generates daily summaries. Predicts release readiness based on cycle times and velocity.

**What It Tracks:**
1. Snapshot of tickets by status, priority, and component
2. Delta showing new, moved, and closed tickets
3. Velocity of opened versus closed items
4. Readiness predictions based on current pace
5. Stale tickets stuck beyond average cycle times

**Usage:**

```bash
# Track all releases in config
python release_tracker_cli.py --project STL

# Track specific release
python release_tracker_cli.py --project STL --release "12.1.1.x"

# Include readiness predictions
python release_tracker_cli.py --project STL --predict

# Export to CSV
python release_tracker_cli.py --project STL --format csv --output report.csv

# Show tracking stats
python release_tracker_cli.py --status
```

**CLI Flags:**

| Flag | Description |
|---|---|
| `--project KEY` | Target Jira project |
| `--release VER` | Specific version to track |
| `--format FMT` | Output as table, json, csv, or excel |
| `--output FILE` | File path for export |
| `--predict` | Include readiness estimates |
| `--status` | Show tracking stats |

**Output Formats:** 
table/json/csv/excel

**Cron:**

```bash
0 9 * * * cd /path/to/repo && .venv/bin/python release_tracker_cli.py --project STL --predict >> logs/release_tracker.log 2>&1
```

### Feature Planner

Transforms engineering scope documents into fully structured Jira project plans. Orchestrates multiple agents to handle research, scoping, and review before execution.

**The Pipeline:** 
scope doc → Research → HW Analysis → Scoping → Plan Building → Review → Execute

**Three Commands:**
```bash
# Generate plan
pm_agent --workflow feature-plan --project STL --scope-doc scope.json
# Review
cat plans/STL-feature/plan.md
# Execute
pm_agent --workflow feature-plan --project STL --plan-file plan.json --execute
```

**Sub-Agents:**

| Name | Role |
|---|---|
| Research Agent | Gathers domain knowledge |
| Hardware Analyst | Maps architecture and interfaces |
| Scoping Agent | Breaks features into concrete items |
| Plan Builder | Converts items to Epics and Stories |
| Review Agent | Formats plans for human validation |

**Key Flags:**

| Flag | Description |
|---|---|
| `--scope-doc` | Input engineering document |
| `--plan-file` | Pre-generated plan to execute |
| `--initiative` | Existing Initiative to attach Epics to |
| `--execute` | Create tickets in Jira |
| `--cleanup` | Delete previously created tickets |
| `--force` | Skip confirmation prompts |

## MCP Server

Exposes Jira tools directly to AI assistants. Run it via Claude Desktop or other MCP clients. 
Configure `claude_desktop_config.json` like this:

```json
{
  "mcpServers": {
    "jira": {
      "command": "python",
      "args": ["/path/to/repo/mcp_server.py"]
    }
  }
}
```

## Standalone Utilities

These CLI utilities run locally without any LLM. Install them globally via pipx.

| CLI | Console Script | One-Line Description |
|---|---|---|
| Jira CLI | `jira-utils` | Query projects, create tickets, and manage dashboards |
| Excel CLI | `excel-utils` | Convert CSV to styled Excel, merge sheets, and run diffs |
| Draw.io CLI | `drawio-utils` | Generate dependency diagrams from Jira hierarchy exports |

See [docs/standalone-utilities.md](docs/standalone-utilities.md) for full CLI reference.

## Development

- Tests: `pytest tests/ -v` (357 tests)
- Coverage: `pytest tests/ --cov=core --cov=agents`
- See [docs/architecture.md](docs/architecture.md) for module structure and dev patterns
- See [docs/tools-reference.md](docs/tools-reference.md) for the full tools catalog

## Project Structure

```text
jira-utilities/
├── pm_agent.py
├── jira_utils.py
├── excel_utils.py
├── drawio_utilities.py
├── ticket_monitor_cli.py
├── release_tracker_cli.py
├── mcp_server.py
├── agents/
├── tools/
├── core/
├── llm/
├── notifications/
├── state/
├── config/
├── data/
├── plans/
├── tests/
├── docs/
├── pyproject.toml
└── requirements.txt
```

## License

Proprietary, Cornelis Networks
