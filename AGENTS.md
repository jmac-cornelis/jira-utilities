# AGENTS.md — Cornelis Jira PM Tools

## Repository Overview

AI-powered project management agents and standalone CLI utilities for Jira at Cornelis Networks. The codebase has three layers:

1. **Core** (`core/`) — Pure data functions, no I/O, no stdout. The foundation everything else imports.
2. **Tools** (`tools/`) — `@tool`-decorated wrappers around core, used by agents via the `BaseTool` framework.
3. **Agents** (`agents/`) — `BaseAgent` subclasses that orchestrate tools, optionally with LLM reasoning.

Entry points: `jira_utils.py` (CLI), `excel_utils.py` (CLI), `mcp_server.py` (MCP for AI), `pm_agent.py` (agent orchestrator).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Entry Points                          │
│  jira_utils.py  excel_utils.py  mcp_server.py  pm_agent │
│  ticket_monitor_cli.py    release_tracker_cli.py         │
└────────────┬──────────────────┬──────────────────────────┘
             │                  │
┌────────────▼──────┐  ┌───────▼──────────────────────────┐
│   agents/          │  │   tools/                          │
│   BaseAgent        │  │   @tool decorated functions       │
│   TicketMonitor    │  │   JiraTools (54 functions)        │
│   ReleaseTracker   │  │   ExcelTools, FileTools, etc.     │
│   JiraAnalyst      │  └───────┬──────────────────────────┘
│   PlanningAgent    │          │
│   ...              │  ┌───────▼──────────────────────────┐
└────────────┬───────┘  │   core/                           │
             │          │   queries.py  — JQL builders,     │
             └──────────┤                pagination         │
                        │   tickets.py  — issue_to_dict     │
                        │   utils.py    — output, ADF, CSV  │
                        │   reporting.py — field validation  │
                        │   monitoring.py — ticket rules     │
                        │   release_tracking.py — snapshots  │
                        └───────┬──────────────────────────┘
                                │
                        ┌───────▼──────────────────────────┐
                        │   Jira Cloud REST API             │
                        │   (via jira-python + direct REST) │
                        └──────────────────────────────────┘
```

---

## Core Modules (`core/`)

### `core/queries.py`
JQL construction and paginated search.
- `paginated_jql_search(jira, jql, max_results, fields, page_size)` → list of issues
- `build_tickets_jql(project, issue_types, statuses, date_filter, jql_extra)` → JQL string
- `build_release_tickets_jql(project, release, issue_types, statuses)` → JQL string
- `build_no_release_jql(project, issue_types, statuses)` → JQL string

### `core/tickets.py`
Unified issue conversion handling both jira-python Resource objects and REST API dicts.
- `issue_to_dict(issue)` → flat dict with all standard + custom fields

### `core/utils.py`
Shared utilities.
- `output(message, quiet_mode)` — controlled stdout
- `validate_and_repair_csv(input_file, output_file)` — fix malformed CSV
- `extract_text_from_adf(adf_content)` — Atlassian Document Format → plain text

### `core/reporting.py`
Field validation and reporting.
- `bugs_missing_field(jira, project, field='affectedVersion')` — find bugs with empty fields via JQL

### `core/monitoring.py` *(new — to be created)*
Ticket validation rules engine.
- Validation rules per issue type (Bug, Story, Epic, Sub-task)
- Field presence checking
- Dedup logic for notifications

### `core/release_tracking.py` *(new — to be created)*
Release snapshot and delta computation.
- Snapshot: ticket counts by status, priority, component
- Delta: what changed between snapshots
- Velocity: opened vs closed per day

---

## Agent Framework (`agents/`)

### Base Classes (`agents/base.py`)

```python
@dataclass
class AgentConfig:
    name: str
    description: str
    instruction: str
    model: str
    temperature: float
    max_tokens: int
    max_iterations: int
    timeout_seconds: int

@dataclass
class AgentResponse:
    content: str
    tool_calls: list
    iterations: int
    success: bool
    error: Optional[str]
    metadata: dict

class BaseAgent(ABC):
    def register_tool(self, tool_func)
    def get_tool_schemas(self) -> list
    def execute_tool(self, name, args) -> ToolResult
    @abstractmethod
    def run(self, prompt, context) -> AgentResponse
    def _run_with_tools(self, messages) -> AgentResponse  # ReAct loop
```

### Existing Agents

| Agent | File | Purpose |
|---|---|---|
| `JiraAnalystAgent` | `jira_analyst.py` | Analyze Jira project data, generate reports |
| `PlanningAgent` | `planning_agent.py` | Create work plans from scope documents |
| `ReviewAgent` | `review_agent.py` | Review and validate plans |
| `ResearchAgent` | `research_agent.py` | Research topics for planning context |
| `ScopingAgent` | `scoping_agent.py` | Scope features from requirements |
| `HardwareAnalystAgent` | `hardware_analyst.py` | Hardware-specific Jira analysis |
| `VisionAnalyzerAgent` | `vision_analyzer.py` | Analyze images/diagrams for planning |
| `FeaturePlanBuilderAgent` | `feature_plan_builder.py` | Build feature plans with epics/stories |
| `FeaturePlanningOrchestrator` | `feature_planning_orchestrator.py` | Multi-agent feature planning workflow |
| `ReleasePlanningOrchestrator` | `orchestrator.py` | Multi-agent release planning workflow |

### New Agents

#### `TicketMonitorAgent` (`agents/ticket_monitor.py`) *(to be created)*

**Purpose**: Watch for newly created tickets, validate required fields, auto-fill when confident, flag creator when not.

**Schedule**: Every 5 minutes via cron.

**Behavior Model**: Option B — Auto-act with guardrails. When the agent's learned knowledge exceeds a confidence threshold, it auto-fills the missing field. Below threshold, it posts a Jira comment flagging the creator.

**Flow**:
1. Load state (last_checked timestamp, processed ticket keys, learning store)
2. Query: `project = STL AND created >= "{last_checked}"`
3. For each new ticket, validate per issue type rules
4. For each missing field:
   a. **Check learning store** — do we have a high-confidence prediction?
   b. **If confidence ≥ threshold** → auto-fill the field via `update_ticket()`, post comment explaining what was set and why
   c. **If confidence < threshold but > 0** → post comment with suggestion: "Based on similar tickets, this looks like component=JKR Host Driver. Please confirm or correct."
   d. **If no prediction** → post comment flagging the missing field to the creator
5. Record outcome in learning store (for future predictions)
6. Dedup: skip if already commented/acted on
7. Save state

**Validation Rules**:

| Issue Type | Required Fields | Warn Fields |
|---|---|---|
| Bug | affects_version, component, priority, description | assignee, labels |
| Story | component, fix_version | assignee |
| Epic | description, fix_version | components |
| Sub-task | parent (enforced by Jira) | — |

**Learning Capabilities**:

| Capability | Input Signal | Output Action | Confidence Source |
|---|---|---|---|
| **Component prediction** | Summary keywords, reporter history | Auto-assign component | Historical accuracy per keyword pattern |
| **Affects version prediction** | Reporter's recent tickets, active releases | Auto-assign affects_version | Reporter's typical version + recency |
| **Priority suggestion** | Keywords (crash, hang, customer, regression) | Suggest priority upgrade/downgrade | Keyword → priority correlation |
| **Reporter profiling** | Per-reporter field compliance history | Adjust notification urgency | Compliance rate over last N tickets |
| **Duplicate detection** | Summary similarity to recent open tickets | Flag potential duplicate with link | Jaccard similarity on tokenized summary |

**Confidence Thresholds** (configurable per action):
```yaml
confidence_thresholds:
  auto_fill:     0.90  # ≥90% → auto-fill field, post explanatory comment
  suggest:       0.50  # ≥50% → suggest in comment, ask creator to confirm
  flag_only:     0.00  # <50% → just flag the field as missing
```

**Learning Store** (`state/learning.py`):
```python
class LearningStore:
    """SQLite-backed learning store for ticket patterns."""

    def record_observation(self, ticket_key, field, predicted, actual, correct: bool)
    def get_keyword_component_map(self) -> dict[str, dict[str, float]]
        # {"crash": {"JKR Host Driver": 0.85, "BTS/verbs": 0.10}, ...}
    def get_reporter_profile(self, reporter_id) -> ReporterProfile
        # compliance_rate, common_components, typical_priority, typical_version
    def get_field_prediction(self, field, ticket_dict) -> tuple[str, float]
        # (predicted_value, confidence)
    def update_from_correction(self, ticket_key, field, old_value, new_value)
        # When a human corrects an auto-fill, learn from it
```

**Feedback Loop**: When a human changes a field the agent auto-filled, the agent detects this on the next poll (via `updated > last_checked` on already-processed tickets) and records the correction. This is how confidence scores improve over time.

**CLI**: `python ticket_monitor_cli.py --project STL [--dry-run] [--since "2026-03-01"] [--learn-only] [--reset-learning]`

- `--dry-run`: Validate and report, but don't update tickets or post comments
- `--learn-only`: Process tickets to build learning store, but don't take any action
- `--reset-learning`: Clear the learning store and start fresh

**Configuration** (`config/ticket_monitor.yaml`):
```yaml
project: STL
poll_interval_minutes: 5

validation_rules:
  Bug:
    required: [affectedVersion, components, priority, description]
    warn: [assignee, labels]
  Story:
    required: [components, fixVersions]
    warn: [assignee]
  Epic:
    required: [description, fixVersions]
    warn: [components]

learning:
  enabled: true
  min_observations: 20        # Need N observations before making predictions
  confidence_thresholds:
    auto_fill: 0.90
    suggest: 0.50
  feedback_detection: true    # Watch for human corrections to auto-fills
  keyword_extraction: true    # Build keyword → field value mappings
  reporter_profiling: true    # Track per-reporter patterns

notifications:
  jira_comment: true
  mention_reporter: true      # @mention the reporter in flag comments
  slack_webhook: null          # Phase 2
```

#### `ReleaseTrackerAgent` (`agents/release_tracker.py`) *(to be created)*

**Purpose**: Monitor releases throughout the day, track status changes, generate daily summaries, predict release readiness.

**Schedule**: Daily at 9 AM + on-demand via CLI.

**Flow**:
1. Load config (which releases to track)
2. For each release, snapshot all tickets by status/priority/component
3. Compare to previous snapshot → compute delta (what moved, what's new, what closed)
4. Highlight P0/P1 changes (new stoppers, status transitions)
5. Calculate velocity (opened vs closed per day)
6. Use cycle time model to predict: "At current velocity, N days to close all P0s"
7. Output summary

**Learning Capabilities**:

| Capability | Input Signal | Output | Confidence Source |
|---|---|---|---|
| **Cycle time modeling** | Historical status durations per component/priority | "P0 bugs in JKR Host Driver average 6.2 days in Verify" | Statistical mean/median over last 90 days |
| **Release readiness prediction** | Current open count + velocity trend + cycle times | "At current pace, 12.1.1.x needs ~14 more days" | Linear regression on daily close rate |
| **Blocker pattern detection** | Tickets stuck in same status > 2× average cycle time | Flag stale tickets, suggest escalation | Comparison to component/priority cycle time |
| **Component risk scoring** | Open P0/P1 count + velocity + cycle time | "JKR Host Driver is highest risk: 5 P0s, avg 8 day cycle" | Composite score |

**CLI**: `python release_tracker_cli.py --project STL --release "12.1.1.x" [--format table|json|csv|excel] [--output FILE] [--predict]`

- `--predict`: Include cycle time predictions and release readiness estimate

**Configuration** (`config/release_tracker.yaml`):
```yaml
project: STL
releases:
  - "12.1.1.x"
  - "12.2.0.x"
schedule: "0 9 * * *"  # Daily at 9 AM
track_priorities: ["P0-Stopper", "P1-Critical"]

learning:
  cycle_time_window_days: 90   # Look back N days for cycle time stats
  stale_threshold_multiplier: 2.0  # Flag if stuck > 2× average cycle time
  velocity_window_days: 14     # Use last N days for velocity calculation

output:
  format: table
  slack_webhook: null  # Phase 2
```

---

## Notifications (`notifications/`) *(to be created)*

```python
class NotificationBackend(ABC):
    @abstractmethod
    def send(self, ticket_key, message, context) -> bool

class JiraCommentNotifier(NotificationBackend):
    """Post ADF-formatted comments on Jira tickets.
    
    Comment types:
    - AUTO_FILL: "I've set {field} to {value} based on {reason}. Confidence: {pct}%. Please correct if wrong."
    - SUGGEST: "This looks like it might be {field}={value} based on {reason}. Can you confirm?"
    - FLAG: "Missing required field: {field}. Please update this ticket."
    """

class SlackNotifier(NotificationBackend):  # Phase 2
    """Send messages via Slack webhook."""
```

**Comment Format** (ADF):
- Auto-fill: ✅ icon, green panel, explains what was set and why
- Suggestion: 💡 icon, yellow panel, asks creator to confirm
- Flag: ⚠️ icon, red panel, lists missing fields

Dedup: Before posting a Jira comment, check existing comments on the ticket to avoid nagging. Use a marker string (e.g., `[PM-Agent]`) to identify agent comments.

---

## State Management (`state/`)

### Existing
- `state/persistence.py` — SQLite-backed state storage
- `state/session.py` — Session management

### New: `state/monitor_state.py` *(to be created)*
- Checkpoint: last_checked timestamp per project
- Processed: set of ticket keys already validated
- History: validation results for audit trail
- Snapshots: release state at each check (for delta computation)

### New: `state/learning.py` *(to be created)*
Learning store for both agents. SQLite-backed.

**Tables**:
```
observations        — (ticket_key, field, predicted_value, actual_value, correct, timestamp)
keyword_patterns    — (keyword, field, value, hit_count, miss_count, confidence)
reporter_profiles   — (reporter_id, field, value, count, total, compliance_rate)
cycle_times         — (ticket_key, component, priority, status_from, status_to, duration_hours, timestamp)
release_snapshots   — (release, snapshot_date, status_json, priority_json, component_json)
auto_fill_log       — (ticket_key, field, value_set, confidence, corrected_by_human, correction_value, timestamp)
```

**Feedback Loop**:
1. Agent auto-fills field on ticket → logged in `auto_fill_log`
2. Next poll detects `updated > last_checked` on processed tickets
3. If field value changed from what agent set → record correction in `observations`
4. Keyword/reporter confidence scores recalculated
5. Over time, predictions improve or the agent learns to stop predicting for ambiguous cases

---

## Configuration (`config/`)

### `config/settings.py`
`Settings` dataclass with `from_env()`, `validate()`, `to_dict()`. Singleton via `get_settings()`.

### Environment Files
- `.env_prod` — Production Jira (STL project)
- `.env_sandbox` — Sandbox Jira (STLSB project)

Required variables: `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_URL`

### Agent Prompts
System prompts in `config/prompts/<agent_name>.md` — loaded by BaseAgent.

---

## Tools (`tools/`)

### `tools/jira_tools.py` — 54 @tool functions

**Project**: get_project_info, get_project_workflows, get_project_issue_types, get_components
**Releases**: get_releases, get_release_tickets, create_release
**Tickets**: create_ticket, update_ticket, assign_ticket, link_tickets
**Search**: search_tickets, run_jql_query, run_filter, list_filters
**Hierarchy**: get_children_hierarchy, get_related_tickets
**Reporting**: get_ticket_totals, get_tickets_by_date, bugs_missing_field, get_status_transitions, run_daily_report
**Dashboards**: list_dashboards, get_dashboard, create_dashboard
**Bulk**: bulk_update_tickets

### `tools/excel_tools.py`
build_excel_map, convert_csv_to_excel, create_dashboard_sheet, diff_excel_files, merge_excel_files

### `tools/base.py`
`@tool` decorator, `ToolResult` dataclass, `ToolDefinition`, `BaseTool` ABC.

---

## Jira Field Reference (STL Project)

### Standard Fields
| Field | API Name | Notes |
|---|---|---|
| Key | `key` | e.g., STL-76865 |
| Summary | `summary` | |
| Description | `description` | May be ADF format |
| Status | `status` | Open, In Progress, Verify, Closed, To Do, Ready |
| Priority | `priority` | P0-Stopper, P1-Critical, P2-High, P3-Medium, P4-Low |
| Issue Type | `issuetype` | Bug, Story, Epic, Sub-task, Initiative |
| Assignee | `assignee` | Must use accountId for Cloud |
| Reporter | `reporter` | |
| Components | `components` | Array of component objects |
| Fix Version/s | `fixVersions` | Target release |
| Affects Version/s | `versions` | Version where bug was found |
| Labels | `labels` | Array of strings |
| Parent | `parent` | Epic link or parent issue |
| Created | `created` | Read-only |
| Updated | `updated` | Read-only |
| Resolved | `resolutiondate` | Read-only |

### Custom Fields
| Field | Prod ID | Sandbox ID | Type |
|---|---|---|---|
| Product Family | `customfield_28382` | `customfield_28434` | Array of {value: string} |
| Customer/s ID | `customfield_17504` | `customfield_17504` | Array of strings |

### Key Components (STL)
JKR Host Driver, JKR FW - ASIC Mgmt, JKR FW - Platform, OFI OPX, BTS/verbs, CN5000 FM, CN5000 Fabric Perf, GPU networking, Chassis Mgmt, Customer Support, MYR FW, In Band Management

### Key Releases
Format: `X.Y.Z.x` (e.g., 12.1.1.x, 12.2.0.x)

---

## Testing

- **195 tests**, **82% coverage**
- Test files in `tests/`
- Run: `source .venv/bin/activate && pytest tests/ -v`
- Coverage: `pytest tests/ --cov=core --cov=jira_utils --cov=excel_utils --cov=mcp_server`
- CI: GitHub Actions workflow publishes HTML reports to GitHub Pages

---

## Development Patterns

### Adding a New Agent
1. Create `agents/my_agent.py` subclassing `BaseAgent`
2. Register tools via `self.register_tool()`
3. Implement `run()` method
4. Add system prompt in `config/prompts/my_agent.md`
5. Add CLI entry point if needed
6. Add tests in `tests/test_my_agent.py`

### Adding Core Logic
1. Pure functions in `core/` — no I/O, no globals, return data
2. Type hints on all parameters and returns
3. Tests before implementation

### Field Validation Pattern
```python
# Use JQL for field-empty checks (efficient, server-side)
bugs_missing_field(jira, project='STL', field='affectedVersion')

# Use issue_to_dict() for client-side validation
ticket = issue_to_dict(issue)
missing = [f for f in required_fields if not ticket.get(f)]
```

### Notification Pattern
```python
# Check for existing comments before posting (dedup)
comments = jira.comments(ticket_key)
already_notified = any('[PM-Agent]' in str(c.body) for c in comments)
if not already_notified:
    jira.add_comment(ticket_key, adf_comment)
```

### Learning Pattern
```python
# Predict a field value
from state.learning import LearningStore
store = LearningStore('state/learning.db')
ticket = issue_to_dict(issue)

predicted_value, confidence = store.get_field_prediction('components', ticket)

if confidence >= config.thresholds.auto_fill:
    # Auto-fill: update ticket + post explanatory comment
    update_ticket(ticket['key'], components=[predicted_value])
    post_comment(ticket['key'], f"[PM-Agent] ✅ Set component to {predicted_value} (confidence: {confidence:.0%})")
    store.record_observation(ticket['key'], 'components', predicted_value, predicted_value, correct=True)
elif confidence >= config.thresholds.suggest:
    # Suggest: post comment asking for confirmation
    post_comment(ticket['key'], f"[PM-Agent] 💡 This looks like component={predicted_value}. Can you confirm?")
else:
    # Flag: just note the missing field
    post_comment(ticket['key'], f"[PM-Agent] ⚠️ Missing required field: components")

# Later: detect human corrections
if ticket_was_updated_since_our_action(ticket['key']):
    current_value = get_current_field(ticket['key'], 'components')
    if current_value != predicted_value:
        store.update_from_correction(ticket['key'], 'components', predicted_value, current_value)
```
