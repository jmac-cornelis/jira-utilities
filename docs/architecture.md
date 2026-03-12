# Architecture & Development Guide

## Overview

AI-powered project management agents and standalone CLI utilities for Jira at Cornelis Networks. The codebase has three layers:

1. **Core** (`core/`) — Pure data functions, no I/O, no stdout. The foundation everything else imports.
2. **Tools** (`tools/`) — `@tool`-decorated wrappers around core, used by agents via the `BaseTool` framework.
3. **Agents** (`agents/`) — `BaseAgent` subclasses that orchestrate tools, optionally with LLM reasoning.

## Module Structure

- `agents/` — `BaseAgent` implementations for AI planning, research, and non-LLM ticket monitoring
- `config/` — `Settings` dataclass and YAML configurations for agents and tools
- `core/` — Pure logic for Jira queries, validation, release tracking, and issue conversion
- `data/` — Static data, Jira ticket JSON schemas, and ticket creation templates
- `docs/` — Architecture documentation and Mermaid diagrams
- `llm/` — Internal and external LLM client abstractions (`BaseLLM`, `CornelisLLM`)
- `notifications/` — Notification backends (Jira comments, Slack)
- `state/` — SQLite persistence for learning stores, agent sessions, and monitor checkpoints
- `tests/` — Pytest suite covering all layers of the architecture
- `tools/` — `@tool` definitions wrapping core logic for agent execution

## Core Layer (core/)

The `core/` directory contains pure functions with no side effects. Functions here return data structures rather than modifying global state or emitting stdout.

Key modules:
- `queries.py` — JQL string construction and paginated Jira search. Example: `build_tickets_jql()`.
- `tickets.py` — Unified issue conversion. Maps Jira REST API and `jira-python` objects into a standardized flat dictionary (`issue_to_dict`).
- `utils.py` — Shared text extraction and output formatting, such as `extract_text_from_adf()` and `validate_and_repair_csv()`.
- `monitoring.py` — Ticket validation rules engine. Checks field presence per issue type.
- `release_tracking.py` — Release snapshotting and delta computation. Calculates velocity (opened vs closed).
- `reporting.py` — Field validation. E.g., `bugs_missing_field()` uses JQL to quickly find empty required fields.

## Tools Layer (tools/)

The `tools/` directory exposes core logic to agents using the `@tool` decorator. A tool is a function wrapped with metadata (name, description, parameters, returns) that the LLM uses for function calling.

Tools return a `ToolResult` object containing `status`, `data`, `error`, and `metadata`. Groups of tools subclass `BaseTool`.

### Code Example: `@tool` Usage

```python
from tools.base import tool, ToolResult
from core.queries import run_my_core_search

@tool(
    name="search_jira",
    description="Search Jira tickets using a custom query string",
    returns="ToolResult containing a list of matching ticket dictionaries"
)
def search_jira(query_string: str, limit: int = 50) -> ToolResult:
    try:
        results = run_my_core_search(query_string, max_results=limit)
        return ToolResult.success(results)
    except Exception as e:
        return ToolResult.failure(f"Search failed: {str(e)}")
```

## Agent Layer (agents/)

The `agents/` directory holds the orchestrators. All agents inherit from `BaseAgent`, which handles conversation history, tool registration, and the ReAct execution loop (`_run_with_tools`).

Agents are configured via the `AgentConfig` dataclass and return an `AgentResponse` containing the final output, tool call history, and success state.

Two types of agents exist:
1. **LLM-driven** — Agents that receive a prompt and iteratively reason, use tools, and generate output (e.g., `FeaturePlanningOrchestrator`, `ResearchAgent`).
2. **Programmatic** — Agents that run on a schedule, use tools directly without an LLM, and maintain state (e.g., `TicketMonitor`, `ReleaseTracker`).

### Adding a New Agent

1. Create `agents/my_agent.py` subclassing `BaseAgent`.
2. Register tools via `self.register_tool()`.
3. Implement the `run(self, prompt, context)` method.
4. Add the system instruction prompt in `config/prompts/my_agent.md`.
5. Add a CLI entry point script if needed.
6. Write tests in `tests/test_my_agent.py`.

## State Management (state/)

The `state/` directory provides SQLite-backed persistence for agents and tools.

- `learning.py` — `LearningStore` tracks historical actions, agent predictions vs human corrections, and field value frequency for keyword profiling.
- `monitor_state.py` — Checkpoint tracking for the Ticket Monitor (last checked timestamps, processed issue keys).
- `session.py` — Maintains LLM agent conversation history and context across workflow phases.
- `persistence.py` — Low-level SQLite wrapper supporting JSON serialization and migration.

## Notifications (notifications/)

The `notifications/` directory handles outbound messaging from programmatic agents.

All notifiers implement the `NotificationBackend` abstract base class.
- `JiraCommentNotifier` — Posts Atlassian Document Format (ADF) comments on tickets. Supports different comment types (AUTO_FILL, SUGGEST, FLAG) with visual indicators.

### Dedup Pattern
Before posting, the notifier fetches existing ticket comments and checks for a specific marker string (e.g., `[PM-Agent]`) to prevent duplicate warnings.

## Configuration

Settings are managed via the `config/` directory and environment variables.

- `Settings` dataclass: Centralized, typed configuration with validation, loaded from `.env` files via `from_env()`.
- `ticket_monitor.yaml` & `release_tracker.yaml`: Agent-specific execution parameters (validation rules, confidence thresholds, scheduling).
- `prompts/`: Directory containing Markdown system instructions for LLM agents.

## Development Patterns

### Field Validation (Server vs Client)
- **Server-side:** Use JQL for broad sweeps. E.g., `project = STL AND affectedVersion is EMPTY`. Fast and efficient.
- **Client-side:** Use `issue_to_dict()` for deep validation of individual tickets against complex rules arrays.

### Notification Dedup
Always check existing state before alerting.
```python
comments = jira.comments(ticket_key)
already_notified = any('[PM-Agent]' in str(c.body) for c in comments)
if not already_notified:
    jira.add_comment(ticket_key, adf_comment)
```

### Learning Feedback Loop (Predict → Act → Learn)
Programmatic agents learn from human interaction.
1. Agent predicts a field value.
2. If confidence is high, the agent auto-fills the field.
3. On the next pass, the agent checks if the ticket was updated.
4. If a human changed the auto-filled value, the agent records the correction in `LearningStore` to improve future predictions.

### Adding Core Logic
1. Create pure functions in `core/` — no side effects, no print statements.
2. Use type hints for all parameters and return values.
3. Write unit tests before wiring into a tool or agent.

## Testing

The project has comprehensive coverage (195 tests, ~82% coverage).

- Test patterns: Mock Jira REST API responses using `responses` or `unittest.mock`.
- Run tests: `source .venv/bin/activate && pytest tests/ -v`
- Run with coverage: `pytest tests/ --cov=core --cov=tools --cov=agents`

## CI/CD

The project uses GitHub Actions for continuous integration.
- Configured in `.github/workflows/tests.yml`.
- Runs pytest and enforces coverage thresholds on pull requests.
- Publishes HTML coverage reports to GitHub Pages on merges to main.

## Jira Field Reference

### Standard Fields (STL Project)
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

### Custom Fields
| Field | Prod ID | Sandbox ID | Type |
|---|---|---|---|
| Product Family | `customfield_28382` | `customfield_28434` | Array of {value: string} |
| Customer/s ID | `customfield_17504` | `customfield_17504` | Array of strings |

### Key Components (STL)
JKR Host Driver, JKR FW - ASIC Mgmt, JKR FW - Platform, OFI OPX, BTS/verbs, CN5000 FM, CN5000 Fabric Perf, GPU networking, Chassis Mgmt, Customer Support, MYR FW, In Band Management

### Key Releases
Format: `X.Y.Z.x` (e.g., 12.1.1.x, 12.2.0.x)
