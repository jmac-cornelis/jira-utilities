# User Resolver Design — Automatic Assignee Resolution

## Problem

Jira Cloud requires an `accountId` (e.g., `"712020:daf767ac-..."`) for the assignee
field, but plan inputs (LLM-generated JSON, CSV/Excel files, org charts) contain
human-readable values: display names ("John Doe"), usernames ("jdoe"), or emails
("jdoe@cornelisnetworks.com").

Currently, any non-accountId assignee is silently dropped and the ticket is created
unassigned.

## Design: Transparent UserResolver

A `UserResolver` class in `jira_utils.py` that automatically resolves human-readable
assignee strings to Jira `accountId` values. It runs transparently — no CLI flags,
no user intervention — at every point where an assignee is set on a ticket.

### Key Principles

1. **Always-on**: Resolution happens automatically whenever `create_ticket()` is called.
2. **Cached**: A single Jira API call per unique assignee string per session. The cache
   is an in-memory dict that persists for the lifetime of the process.
3. **Graceful degradation**: If resolution fails (no match, API error, no connection),
   the ticket is created unassigned with a warning — never a hard failure.
4. **Project-scoped**: Uses `search_assignable_users_for_issues(project=...)` to only
   match users who can actually be assigned to tickets in the target project.

### Detection Logic

An assignee value is classified as:

| Pattern | Classification | Action |
|---------|---------------|--------|
| Contains `:` (e.g., `712020:daf767ac-...`) | Already an accountId | Use as-is |
| Contains `@` without `:` | Email address | Resolve via API |
| Matches `^[a-z][a-z0-9._-]+$` (lowercase, no spaces) | Username | Resolve via API |
| Contains spaces or mixed case | Display name | Resolve via API |
| Empty / None | No assignee | Skip |

### Matching Strategy

When the Jira API returns multiple candidates for a search query:

1. **Exact match** on `displayName` (case-insensitive) → use it
2. **Exact match** on `emailAddress` (case-insensitive) → use it
3. **Starts-with match** on `displayName` → use it
4. **Fuzzy match** — score candidates by:
   - Levenshtein-like similarity on display name
   - Whether the query appears as a substring of the display name
   - Whether the query appears in the email prefix
5. **Ambiguous** — if top two scores are too close, log a warning with the candidates
   and return `None` (ticket created unassigned)

### Integration Points

```
┌─────────────────────────────────────────────────────────┐
│                    UserResolver                          │
│  resolve(assignee_str, project_key) → Optional[str]     │
│  resolve_plan(plan_dict, project_key) → plan_dict       │
│  get_resolution_report() → List[dict]                   │
└──────────────┬──────────────────────────────────────────┘
               │
    ┌──────────┼──────────────────────────────┐
    │          │                              │
    ▼          ▼                              ▼
jira_utils   orchestrator                 tools/
create_ticket  _preflight_validate         jira_tools
               _phase_execution            create_ticket
```

#### 1. `jira_utils.create_ticket()` (primary integration)
- Replace the current "email check → skip" logic with `UserResolver.resolve()`
- This is the single choke-point: every ticket creation goes through here

#### 2. `_preflight_validate()` in orchestrator
- Before execution, resolve all assignees in the plan and report the mapping
- Show: `✅ "John Doe" → 712020:daf767ac-... (John Doe)`
- Show: `⚠️ "unknown_person" → not found (will be unassigned)`

#### 3. `_phase_execution()` in orchestrator
- The plan dict is pre-processed: all assignee fields are replaced with resolved
  accountIds before any `create_ticket()` calls
- This means `create_ticket()` always receives either a valid accountId or None

#### 4. `tools/jira_tools.create_ticket()` (agent tool)
- Same resolution logic via the shared `UserResolver` instance

### Class API

```python
class UserResolver:
    """Resolve human-readable assignee strings to Jira accountIds."""

    def __init__(self, jira=None):
        """Initialize with an optional Jira connection.
        
        If jira is None, resolution is deferred until first use
        (lazy connection via get_connection()).
        """

    def resolve(self, assignee: str, project_key: str = '') -> Optional[str]:
        """Resolve a single assignee string to an accountId.
        
        Returns the accountId string, or None if unresolvable.
        """

    def resolve_plan(self, plan: Dict, project_key: str = '') -> Dict:
        """Resolve all assignee fields in a feature-plan dict in-place.
        
        Walks epics and stories, replacing assignee values with accountIds.
        Returns the modified plan dict.
        """

    def get_resolution_report(self) -> List[Dict[str, str]]:
        """Return a report of all resolution attempts.
        
        Each entry: {input, resolved_to, display_name, status}
        status: 'resolved', 'not_found', 'ambiguous', 'already_id', 'error'
        """

    def is_account_id(self, value: str) -> bool:
        """Check if a string looks like a Jira accountId."""

    @property
    def cache(self) -> Dict[str, Optional[str]]:
        """The current resolution cache (input → accountId)."""
```

### Caching

- **Key**: normalized lowercase assignee string
- **Value**: `accountId` string or `None` (negative cache for "not found")
- **Scope**: per-process (in-memory dict on the UserResolver instance)
- **Shared**: a module-level singleton `_user_resolver` in `jira_utils.py`,
  accessed via `get_user_resolver()`, similar to the existing `get_connection()` pattern

### Preflight Output Example

```
Pre-flight Validation:
  ✅ Project STLSB exists and is accessible
  ✅ Issue type "Epic" is valid
  ✅ Issue type "Story" is valid
  ✅ Components validated: firmware, driver, tools

  Assignee Resolution:
    ✅ "John Doe"     → 712020:daf767ac-... (John Doe)
    ✅ "jdoe"         → 712020:daf767ac-... (John Doe)
    ✅ "asmith"       → 557058:b2c4e1f0-... (Alice Smith)
    ⚠️ "unknown_dev"  → not found (tickets will be unassigned)
    ℹ️ 3 of 4 assignees resolved
```

### Files to Modify

| File | Change |
|------|--------|
| `jira_utils.py` | Add `UserResolver` class, `get_user_resolver()`, update `create_ticket()` |
| `agents/feature_planning_orchestrator.py` | Add assignee resolution in `_preflight_validate()` and `_phase_execution()` |
| `tools/jira_tools.py` | Update `create_ticket()` tool to use resolver |
| `mcp_server.py` | Update `assign_ticket()` to use resolver |

### Error Handling

- **No Jira connection**: Log warning, return None (ticket unassigned)
- **API rate limit**: Catch 429, wait and retry once, then return None
- **API error**: Log warning, return None
- **Ambiguous match**: Log warning with candidates, return None
- **Empty query**: Return None immediately (no API call)

---

## Implementation Notes (2026-03-04)

### What Was Implemented

All integration points from the design are complete and tested:

| File | Lines | Change |
|------|-------|--------|
| `jira_utils.py` | 515–891 | `UserResolver` class (~350 lines), `get_user_resolver()`, `reset_user_resolver()` singleton |
| `jira_utils.py` | 3884–3895 | `create_ticket()` — replaced email-check with `resolver.resolve()` |
| `tools/jira_tools.py` | 418–429 | `create_ticket()` tool — same resolver pattern |
| `agents/feature_planning_orchestrator.py` | 1562–1580 | `_preflight_validate()` — `resolve_plan()` + `format_resolution_report()` |
| `mcp_server.py` | 696–722 | `assign_ticket()` — resolver with project key extraction from ticket key |

### Scoring Algorithm (as implemented)

| Score | Condition |
|-------|-----------|
| 100 | Exact match on `displayName` (case-insensitive) |
| 95 | Exact match on `emailAddress` (case-insensitive) |
| 90 | Exact match on email prefix (before `@`) |
| 70 | `displayName` starts with query |
| 65 | All query words are a subset of display name words (handles reversed order) |
| 60 | Query is a substring of `displayName` |
| 55 | Query is a substring of `emailAddress` |
| 40×overlap | Partial word overlap between query and display name |
| < 30 | Treated as "not found" |

**Ambiguity detection**: If the top two candidates score within 10% of each other
and the best score is below 90, the match is flagged as `ambiguous` and the ticket
is created unassigned.

### Cache Key Format

`"{assignee_lower}|{PROJECT_KEY}"` — project-scoped so the same name can resolve
differently across projects (e.g., if a user is only assignable in certain projects).

### Test Results

40/40 unit tests passing, covering:
- `is_account_id()` — 5 cases (valid accountIds, emails, names, empty)
- `_pick_best_match()` — 15 cases (exact, email, prefix, starts-with, substring,
  word overlap, no match, ambiguous, email tiebreaker)
- `resolve()` — 5 cases (pass-through, API, cache, no-API-on-cache, not-found)
- `resolve_plan()` — 4 cases (epic, story, empty, None)
- `format_resolution_report()` — 5 cases (header, entries, count)
- Singleton — 2 cases (same instance, reset)
- Edge cases — 4 cases (empty, whitespace, single candidate)
