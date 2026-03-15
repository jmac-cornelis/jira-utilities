# AGENTS.md

## Purpose

This repository is a hybrid of:

- deterministic Jira/Confluence/file utilities
- agentic planning and analysis workflows
- review-gated execution paths for Jira-backed work

The primary product is not "chat." It is a set of reusable planning and delivery workflows that turn messy inputs into structured artifacts and, when approved, into controlled system changes.

## Primary Entry Points

- `pm_agent.py`
  Main CLI for agent workflows such as `feature-plan`, release-planning flows, and `gantt-snapshot`.
- `jira_utils.py`
  Standalone Jira CLI and shared Jira integration substrate.
- `confluence_utils.py`
  Standalone Confluence CLI and shared Confluence integration substrate.
- `tools/`
  Agent-callable wrappers around the underlying utilities.
- `mcp_server.py`
  MCP surface for external tool consumers.

## Current Agent Focus

Treat this repo as strongest in the Planning & Delivery slice of the broader `agent_workforce` vision.

- `Gantt`
  Planning snapshots, milestone proposals, dependency views, and Jira-grounded planning outputs.
- `Drucker`
  Jira analysis, safe operational tooling, and review-gated write paths.
- `Hypatia`
  Confluence and documentation tooling foundation.

When extending agent behavior, prefer strengthening these areas before inventing unrelated new agent surfaces.

## Where New Work Should Go

- `agents/`
  New agent classes, deterministic planning logic, and orchestrators.
- `config/prompts/`
  Agent prompts. Keep prompts specific to the agent and aligned with the code's actual tool surface.
- `tools/`
  Agent-facing wrappers. If a utility exists underneath but agents cannot call it, expose it here.
- `tests/`
  Add targeted tests for new agent behavior, tool wrappers, and CLI workflows.
- `docs/`
  Architecture notes, workflow explanations, and `agent_workforce` mapping updates.

## Working Style

- Prefer deterministic logic first; use LLM reasoning where synthesis is genuinely needed.
- Keep human review boundaries explicit for mutating workflows.
- Make the agent/tool/MCP surfaces consistent with each other when adding capability.
- Favor small, composable helpers over large opaque agent methods.
- Preserve existing repo patterns before introducing new abstractions.

## Safety Rules

- Default to dry-run or analysis-only behavior unless the user clearly asks for execution.
- Be especially careful with Jira and Confluence writes. Validate identifiers, scope, and destination before mutating anything.
- Do not remove or overwrite user-created local scratch files unless explicitly asked.
- Never commit incidental artifacts such as logs, temporary exports, or one-off scratch inputs unless the user asks for them to be versioned.

## Scratch And Local Artifacts

These files are commonly local-only and should usually stay uncommitted:

- `confluence_test_page.md`
- `generate_release_reports.py`
- `sw_1211_p0p1_bugs.json`
- `*.log`
- ad hoc exported JSON or Markdown generated during manual testing

Always check `git status` before committing.

## Testing Expectations

- Run focused tests for the area you changed while iterating.
- Run `.venv/bin/pytest -q` before finishing when the change touches shared behavior.
- For syntax-sensitive edits, `python -m py_compile` on touched modules is a good fast check.
- If you add a CLI feature, add or update a workflow/CLI test when practical.

## Implementation Notes

- Keep CLI behavior and agent-callable tool behavior aligned.
- If functionality exists in a utility but not in `tools/` or `mcp_server.py`, that is usually a gap worth closing.
- Prefer structured outputs that can be reviewed, persisted, and reused by later workflow steps.
- For `Gantt`-oriented work, preserve explicit evidence gaps when the repo lacks real build, test, release, or meeting inputs.

## Documentation Expectations

- Update `README.md` when user-facing workflows or commands materially change.
- Update the docs in `docs/` when the architectural story changes, especially:
  - `docs/agent-usefulness-and-applications.md`
  - `docs/jira-utilities-agent-workforce-mapping.md`

## Branch And PR Hygiene

- Keep changes scoped to the branch purpose.
- Do not include unrelated scratch files in commits.
- Mention verification clearly in commit or PR summaries when tests were run.
