# Cornelis Networks Jira Conventions

Standards and conventions for Jira ticket creation and management at Cornelis Networks.

## Ticket Hierarchy

### Epic → Story (2-level)
- **Epic**: Major feature or initiative (completable within 1-2 releases)
- **Story**: User-facing functionality or discrete work item (completable within a sprint)

### When to Use Each Type
- **Epic**: "Implement PQC device support", "Add 400G link speed support"
- **Story**: "Implement PQC register access layer", "Write PQC driver probe function"
- **Bug**: Defects found in existing functionality
- **Task**: Administrative or infrastructure work (not feature development)

## Naming Conventions

### Epic Summaries
Format: `[Feature Name] Category`
Examples:
- `[PQC Support] Firmware`
- `[PQC Support] Driver`
- `[PQC Support] Testing`

### Story Summaries
Format: `[Category Prefix] Descriptive title`
Prefixes:
- `[FW]` — Firmware work
- `[DRV]` — Driver/kernel work
- `[TOOL]` — CLI tools and diagnostics
- `[TEST]` — Testing work
- `[INT]` — Integration work
- `[DOC]` — Documentation work

Examples:
- `[FW] Implement PQC device initialization sequence`
- `[DRV] Add PQC device kernel driver module`
- `[TOOL] Create PQC diagnostic CLI tool`
- `[TEST] Write integration tests for PQC data path`

## Labels

### Standard Labels
- `feature-planning` — Tickets created by the feature planning workflow
- `confidence-high` / `confidence-medium` / `confidence-low` — Confidence in the scope
- `complexity-s` / `complexity-m` / `complexity-l` / `complexity-xl` — Relative size

### Product Labels
- `opx` — Omni-Path Express related
- `fabric-manager` — Fabric Manager related
- `host-stack` — Host Software Stack related

## Components

### Common Component Names
- Firmware, FW
- Driver, Kernel Driver, HFI Driver
- Tools, CLI Tools, Diagnostics
- QA, Testing, Validation
- Documentation, Docs
- Fabric Manager, FM
- PSM2
- Build, Infrastructure

## Description Template

### Story Description
```markdown
## Overview
[What this story delivers and why it matters]

## Technical Details
[Specific implementation details, APIs, interfaces]

## Dependencies
- BLOCKED_BY: [ticket key or description]
- RELATED_TO: [ticket key or description]

## Acceptance Criteria
- [ ] [Specific, testable criterion]
- [ ] [Specific, testable criterion]
- [ ] [Specific, testable criterion]

## Confidence: [HIGH/MEDIUM/LOW]
## Complexity: [S/M/L/XL]
```

### Epic Description
```markdown
## [Epic Title] for [Feature Name]

This Epic tracks all [category] work for the "[feature]" feature.

### Stories (N):
- [Complexity] Story title (Confidence: level)
- [Complexity] Story title (Confidence: level)
```

## Priority Guidelines

- **Blocker**: Prevents other work from proceeding; must be resolved immediately
- **Critical**: Core functionality; must be in the release
- **Major**: Important functionality; should be in the release
- **Minor**: Nice-to-have; can be deferred if needed
- **Trivial**: Cosmetic or very low impact

## Release Versioning

Format: `Major.Minor.Patch`
- Major: Architectural changes, breaking API changes
- Minor: New features, non-breaking changes
- Patch: Bug fixes, minor improvements

## Workflow States

### Standard Flow
`Open` → `In Progress` → `In Review` → `Done`

### With QA
`Open` → `In Progress` → `In Review` → `QA` → `Done`

### Blocked
Any state → `Blocked` → (return to previous state)
