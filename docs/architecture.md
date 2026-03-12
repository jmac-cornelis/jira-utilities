# Architecture

## Overview

The Cornelis Networks Jira PM Tools repository uses a clean, three-layer architecture designed for modularity, testability, and AI agent integration. Data flows up from pure functions to tools, which are orchestrated by agents.

1. **Core** (`core/`): Pure data functions. No I/O, no stdout, no side effects. The foundation everything else imports.
2. **Tools** (`tools/`): `@tool`-decorated wrappers around core logic. Agents use these via the `BaseTool` framework.
3. **Agents** (`agents/`): `BaseAgent` subclasses that orchestrate tools, usually with LLM reasoning.

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

## Module Structure

- **`agents/`**: AI agent implementations and orchestrators.
- **`config/`**: System configuration, environment management, and LLM prompts.
- **`core/`**: Pure Python functions for domain logic.
- **`docs/`**: Documentation and contributor guides.
- **`llm/`**: LLM provider integrations (Cornelis, OpenAI, Anthropic).
- **`notifications/`**: Notification backends (Jira comments, Slack).
- **`state/`**: SQLite-backed persistence and session management.
- **`tests/`**: Pytest suite for all modules.
- **`tools/`**: Function wrappers exposing core logic to agents.

## Core Layer (`core/`)

The core layer holds pure functions. It handles data transformation, query building, and validation. It must not handle I/O or state directly.

### Responsibilities
- **`queries.py`**: JQL string construction and paginated Jira searches. Returns lists of issues.
- **`tickets.py`**: Issue conversion. Formats both jira-python resources and raw REST dicts into flat, standardized dictionaries.
- **`utils.py`**: Shared helpers. Handles CSV validation and repairing, Atlassian Document Format (ADF) parsing, and controlled standard output.
- **`reporting.py`**: Field validation logic. Checks for missing required fields on tickets.
- **`monitoring.py`**: Rules engine defining which fields are required or generate warnings based on issue type.
- **`release_tracking.py`**: Snapshot logic. Computes deltas between release states and calculates velocity.

### Development Pattern
Return data structures. Let callers (CLI entry points or tools) handle formatting and output. Use type hints extensively.

## Tools Layer (`tools/`)

The tools layer exposes core functions to agents using a consistent interface.

### Pattern: `@tool` Decorator
We use a custom `@tool` decorator in `tools/base.py`. This decorator:
1. Extracts parameter information from type hints and docstrings.
2. Wraps the core function to return a standardized `ToolResult`.
3. Attaches a `ToolDefinition` metadata object, allowing the agent framework to automatically generate OpenAI-compatible function schemas.

```python
@tool(description='Search for Jira tickets')
def search_tickets(jql: str, limit: int = 50) -> ToolResult:
    # Search tickets using JQL query.
    pass
```

Tools are grouped into classes inheriting from `BaseTool` (e.g., `JiraTools`, `ExcelTools`).

## Agent Layer (`agents/`)

Agents orchestrate tool calls to achieve complex goals. They run a ReAct-style loop: think, use tool, observe result, repeat.

### Pattern: `BaseAgent`
All agents inherit from `BaseAgent`.

- `AgentConfig`: Dataclass holding the name, description, system instruction, model parameters, and timeouts.
- `AgentResponse`: Dataclass holding the final content, tool call history, iterations taken, and success state.
- `_run_with_tools()`: The core execution loop managing the conversation history and tool dispatching.

### Adding a New Agent
1. Create `agents/my_agent.py` subclassing `BaseAgent`.
2. Implement the `run()` method.
3. Register needed tools using `self.register_tool()`.
4. Create a system prompt markdown file in `config/prompts/my_agent.md`.
5. Add tests in `tests/test_my_agent.py`.

## State Management (`state/`)

We persist agent memory and system state using SQLite.

- **`persistence.py`**: Generic SQLite-backed storage.
- **`session.py`**: Agent conversation session tracking.
- **`monitor_state.py`**: Checkpoints for the Ticket Monitor (last checked timestamps, processed tickets).
- **`learning.py`**: The learning store. Tracks observations, keyword patterns, and reporter profiles to build confidence scores for auto-filling ticket fields.

## Notifications (`notifications/`)

Agents communicate findings back to the team through notifications.

- **`NotificationBackend` ABC**: Abstract interface for all notifiers.
- **`JiraCommentNotifier`**: Posts Atlassian Document Format (ADF) comments on tickets. Supports different comment types (Auto-fill, Suggestion, Flag).

### Pattern: Deduplication
Before posting, check for existing notifications to avoid nagging.

```python
comments = jira.comments(ticket_key)
already_notified = any('[PM-Agent]' in str(c.body) for c in comments)
if not already_notified:
    jira.add_comment(ticket_key, adf_comment)
```

## Configuration

Configuration is managed centrally via a `Settings` dataclass in `config/settings.py`.

- Uses `from_env()` to load from `.env` files.
- Validates required credentials via `validate()`.
- Supports dynamic fallback between LLM providers.

## Development Patterns

### Field Validation
Use server-side JQL for bulk empty-field checks. Use `issue_to_dict()` and standard Python dictionaries for client-side validation of single tickets.

### Learning Loop
The system improves by predicting, acting, and observing human corrections.
1. Predict a field value using `LearningStore`.
2. If confidence is high, auto-fill and log.
3. If confidence is medium, suggest via comment.
4. On the next poll, check if a human changed the auto-filled value. Record the correction to adjust future confidence.

## Testing

The project maintains high test coverage (~82%, 357+ tests).

- **Framework**: Pytest.
- **Patterns**: Heavy use of fixtures, mocking for API calls, and `tmp_path` for file operations.
- **Running Tests**: `source .venv/bin/activate && pytest tests/ -v`

## CI/CD

We use GitHub Actions (`.github/workflows/tests.yml`) to enforce code quality.
- Runs the pytest suite on every push.
- Generates HTML coverage reports published to GitHub Pages.
