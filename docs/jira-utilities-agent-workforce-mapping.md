# `jira-utilities` to `agent_workforce` Mapping

## Purpose

This document maps the agents and capabilities currently implemented in `jira-utilities` onto the larger organizational model defined in `~/code/other/agent_workforce`.

The goal is to answer four practical questions:

1. Which `agent_workforce` agents already have meaningful implementation overlap here?
2. Which parts of `jira-utilities` are most reusable for that larger platform?
3. Which workforce agents are only lightly represented today?
4. Where are the biggest gaps between the current repo and the target platform?

## Executive Summary

`jira-utilities` is not a broad implementation of the entire `agent_workforce` vision. It is best understood as a strong early implementation of the **Planning & Delivery** slice of that vision, plus some reusable shared infrastructure for approval, Jira interaction, Confluence interaction, file/document access, and tool-backed agent execution.

The strongest mapping is:

- `Gantt` — strong partial implementation
- `Drucker` — strong foundation, with some direct overlap already present
- `Hypatia` — strong tooling foundation, but not yet a dedicated documentation agent

The lighter partial mappings are:

- `Brooks`
- `Hedy`
- `Nightingale`
- `Herodotus`

The weakest or essentially not-yet-started mappings are:

- `Josephine`
- `Ada`
- `Curie`
- `Faraday`
- `Tesla`
- `Linus`
- `Babbage`
- `Linnaeus`

## Shared Capabilities in `jira-utilities`

Before mapping named workforce agents, it helps to separate the shared building blocks from the agent roles.

### Reusable platform elements already present

- `BaseAgent` in `agents/base.py`
  Provides the reusable agent loop, tool registration, tool execution, and structured `AgentResponse`.
- `ReviewAgent` in `agents/review_agent.py`
  Provides a general-purpose human-in-the-loop approval model that is useful well beyond release planning.
- Session state in `state/session.py`
  Provides resumable workflow state that can evolve into a broader platform session model.
- Jira tool layer in `tools/jira_tools.py`
  Provides a meaningful service substrate for Jira-backed agents.
- Confluence tool layer in `tools/confluence_tools.py`
  Provides a meaningful service substrate for documentation and knowledge publication.
- Shared utility tools in `tools/file_tools.py`, `tools/knowledge_tools.py`, `tools/web_search_tools.py`, and `tools/mcp_tools.py`
  Provide the evidence-gathering surface needed for more advanced agents.
- MCP exposure in `mcp_server.py`
  Shows one outward-facing integration model for turning internal capabilities into a standard interface.

### Why this matters

These pieces are not the full `agent_workforce` platform, but they are exactly the kind of substrate the larger system needs:

- deterministic tools first
- reusable agent runtime
- approval gating
- persistent state
- multiple external-system adapters

## Mapping by Workforce Zone

### Planning & Delivery

This is where `jira-utilities` is currently strongest.

#### Gantt — Project Planner

**Workforce intent**

`Gantt` in `agent_workforce` converts Jira state, technical evidence, and meeting decisions into milestone proposals, dependency views, and planning snapshots.

**Current mapping in `jira-utilities`**

- `agents/feature_planning_orchestrator.py`
- `agents/orchestrator.py`
- `agents/planning_agent.py`
- `agents/feature_plan_builder.py`
- `agents/jira_analyst.py`
- `agents/vision_analyzer.py`
- `agents/research_agent.py`
- `agents/hardware_analyst.py`
- `agents/scoping_agent.py`

**Maturity**

Strong partial implementation.

**Why it maps well**

This repo already does the core planning transformation that `Gantt` wants:

- ingest messy planning inputs
- analyze current Jira state
- synthesize planning artifacts
- turn those artifacts into structured work proposals
- support review before execution

The feature-planning path is especially close to `Gantt`:

- `ResearchAgent` gathers evidence
- `HardwareAnalystAgent` and `ScopingAgent` turn domain ambiguity into scoped work
- `FeaturePlanBuilderAgent` converts scope into Jira-ready structures
- `FeaturePlanningOrchestrator` coordinates the end-to-end flow

The release-planning flow is also a planning-oriented orchestration path:

- visual intake
- Jira analysis
- plan generation
- approval and execution

**Main gaps vs workforce Gantt**

- no event-driven planning snapshots
- no formal milestone proposal model
- no dependency graph as a first-class output
- no integration with execution-spine evidence like builds/tests/releases
- no delivery-risk projection from cross-agent operational data

#### Brooks — Delivery Manager

**Workforce intent**

`Brooks` monitors execution against plan, detects schedule risk and coordination failure, and produces delivery summaries.

**Current mapping in `jira-utilities`**

- `agents/jira_analyst.py`
- `agents/orchestrator.py`
- `agents/feature_planning_orchestrator.py`
- `tools/jira_tools.py`
- session state in `state/session.py`

**Maturity**

Light partial implementation.

**Why it maps at all**

The repo can already:

- inspect Jira state
- generate plan outputs
- summarize some project structure
- preserve workflow state

That means it can support planning snapshots and some manual reporting.

**Main gaps vs workforce Brooks**

- no comparison of execution reality vs approved plan over time
- no build/test/release evidence integration
- no forecast model
- no escalation model
- no risk detector grounded in objective engineering execution signals

`jira-utilities` can help Brooks, but it is not yet Brooks.

### Intelligence & Knowledge

This repo has important foundations here, but most implementations are still thin.

#### Drucker — Jira Coordinator

**Workforce intent**

`Drucker` keeps Jira operationally coherent through triage, hygiene, routing, and evidence-backed write-backs.

**Current mapping in `jira-utilities`**

- `agents/jira_analyst.py`
- `tools/jira_tools.py`
- `mcp_server.py`
- `agents/review_agent.py`
- workflow support in `pm_agent.py`

**Maturity**

Strong foundation, with partial direct implementation overlap.

**Why it maps well**

This repo already has much of the tool and control surface Drucker would need:

- project metadata lookup
- ticket search
- direct ticket retrieval
- transitions
- comments
- bulk operations
- filters and dashboards
- safe review-oriented execution patterns

The recent widening of the Jira tool surface is especially important because Drucker depends more on deterministic Jira actions than on free-form generation.

`JiraAnalystAgent` is not yet Drucker, but it is clearly Drucker-adjacent:

- it inspects the current Jira state
- it frames the project operationally
- it can act as a precursor to hygiene, coordination, and routing work

**Main gaps vs workforce Drucker**

- no continuous issue-evaluation service
- no stale-state or metadata-gap engine
- no routing coordinator
- no policy-backed write-back engine
- no durable issue-coordination record model
- no event-driven Jira issue processing

The practical conclusion is that `jira-utilities` is probably the best seed codebase for a future Drucker implementation.

#### Hypatia — Documentation Agent

**Workforce intent**

`Hypatia` turns source changes, system facts, meeting clarifications, and release context into durable documentation changes.

**Current mapping in `jira-utilities`**

- `confluence_utils.py`
- `tools/confluence_tools.py`
- `tools/file_tools.py`
- `tools/knowledge_tools.py`
- `tools/web_search_tools.py`
- `tools/mcp_tools.py`
- `agents/research_agent.py`

**Maturity**

Strong tooling foundation, weak direct agent implementation.

**Why it maps well**

This repo now has a real Confluence write surface:

- page search
- page retrieval
- create
- update
- append
- update section
- export
- child-page listing
- dry-run support

That is exactly the kind of tooling a documentation agent needs.

The repo also has supporting evidence tools:

- research and knowledge lookup
- file/document read paths
- review-style approval patterns

**Main gaps vs workforce Hypatia**

- no dedicated documentation agent class
- no documentation-impact model
- no source/build/test/release-driven documentation workflow
- no publication validation pipeline
- no as-built documentation generation model

So the right reading is:

- `jira-utilities` is not Hypatia
- `jira-utilities` does contain a useful first-generation Hypatia tool substrate

#### Herodotus — Knowledge Capture

**Workforce intent**

`Herodotus` ingests Teams meeting transcripts, extracts decisions and action items, and publishes durable meeting summaries.

**Current mapping in `jira-utilities`**

- `tools/confluence_tools.py`
- `tools/file_tools.py`
- `tools/knowledge_tools.py`
- `agents/research_agent.py`
- `agents/review_agent.py`

**Maturity**

Light conceptual overlap only.

**Why it maps at all**

The repo has pieces Herodotus would reuse:

- document read support
- page publishing support
- human review support

But those are shared utilities, not a meeting-ingest implementation.

**Main gaps vs workforce Herodotus**

- no Teams transcript ingest
- no meeting record model
- no meeting summary record
- no action extraction pipeline
- no transcript-grounded publishing workflow

Herodotus is mostly future work.

#### Nightingale — Bug Investigation

**Workforce intent**

`Nightingale` reacts to Jira bug reports, gathers context, drives reproduction, and produces durable investigation records.

**Current mapping in `jira-utilities`**

- Jira bug-report workflow in `pm_agent.py`
- `agents/jira_analyst.py`
- `tools/jira_tools.py`
- `tools/file_tools.py`
- `tools/excel_tools.py`
- `agents/research_agent.py`

**Maturity**

Light partial implementation.

**Why it maps at all**

This repo can already support bug-oriented information gathering:

- pull bug sets from Jira filters
- analyze and transform bug data
- summarize issues
- search and retrieve Jira context

That gives it some overlap with Nightingale's intake and summarization side.

**Main gaps vs workforce Nightingale**

- no bug investigation record model
- no reproduction planner
- no reproduction coordinator
- no build/test/environment context spine
- no failure-signature or clustering model
- no iterative investigation loop

The repo is more useful for bug reporting and bug summarization than bug reproduction.

#### Linnaeus — Traceability

**Workforce intent**

`Linnaeus` owns durable relationships between requirements, issues, builds, tests, releases, and versions.

**Current mapping in `jira-utilities`**

- limited related-ticket traversal in Jira tools
- planning outputs that preserve some relationship structure

**Maturity**

Minimal overlap.

**Main gaps**

- no canonical traceability record
- no cross-system relationship truth
- no durable trace store
- no build/test/release linkage model

#### Babbage — Version Manager

**Workforce intent**

`Babbage` maps internal build identities to external versions and lineage.

**Current mapping in `jira-utilities`**

- light overlap through Jira release/version inspection

**Maturity**

Minimal overlap.

**Main gaps**

- no internal/external version mapping engine
- no lineage tracking
- no conflict detection
- no version record model

### Execution Spine

This is where `jira-utilities` is currently weakest.

#### Hedy — Release Manager

**Workforce intent**

`Hedy` evaluates release readiness and governs release-state transitions using build, test, version, and traceability evidence.

**Current mapping in `jira-utilities`**

- `agents/orchestrator.py`
- `agents/planning_agent.py`
- `tools/jira_tools.py`
- `agents/review_agent.py`

**Maturity**

Light partial implementation.

**Why it maps at all**

This repo does have release-planning concepts, approval gating, and Jira version interactions.

**Why the overlap is limited**

The "release planning" here is mostly:

- planning releases
- creating Jira structures
- reviewing changes

The workforce `Hedy` is much more of a release control plane:

- evaluate readiness
- promote or block
- coordinate approvals against build/test evidence

**Main gaps vs workforce Hedy**

- no build candidate model
- no release readiness evaluation model
- no promotion pipeline
- no stage control plane
- no integration with build/test/version/traceability evidence

#### Josephine — Build & Package

**Current mapping**

None beyond indirect consumption of outputs that a build agent would eventually provide.

**Maturity**

Not started.

#### Ada — Test Planner

**Current mapping**

Only faint conceptual overlap through planning decomposition patterns.

**Maturity**

Not started.

#### Curie — Test Generator

**Current mapping**

None.

**Maturity**

Not started.

#### Faraday — Test Executor

**Current mapping**

None.

**Maturity**

Not started.

#### Tesla — Environment Manager

**Current mapping**

None.

**Maturity**

Not started.

#### Linus — Code Review

**Current mapping**

None of substance in the current repo.

**Maturity**

Not started.

## Direct Mapping from Current `jira-utilities` Agents

This is the inverse view: starting from the agents that already exist here and showing where they land in `agent_workforce`.

| `jira-utilities` component | Best workforce mapping | Notes |
|---|---|---|
| `ReleasePlanningOrchestrator` | `Gantt` with light `Drucker` flavor | Primarily planning and proposal coordination |
| `FeaturePlanningOrchestrator` | `Gantt` | Strongest direct fit in the repo |
| `PlanningAgent` | `Gantt` | Core plan synthesis behavior |
| `FeaturePlanBuilderAgent` | `Gantt` -> `Drucker` handoff | Turns scoped work into Jira-ready structures |
| `JiraAnalystAgent` | `Drucker` precursor | Strong current-state Jira understanding, but not yet hygiene/routing orchestration |
| `ReviewAgent` | Shared cross-cutting capability | Reusable across `Drucker`, `Hedy`, `Hypatia`, `Brooks`, and `Gantt` |
| `VisionAnalyzerAgent` | `Gantt` intake adapter | Helps turn roadmap artifacts into planning inputs |
| `ResearchAgent` | Upstream support for `Gantt`, `Hypatia`, and `Nightingale` | Better understood as shared intelligence than a workforce one-to-one mapping |
| `HardwareAnalystAgent` | Upstream support for `Gantt` | Particularly valuable for feature-intake planning |
| `ScopingAgent` | Upstream support for `Gantt` | Transforms ambiguity into schedulable work |

## Practical Interpretation

If the organization wants to use `jira-utilities` as a seed implementation for `agent_workforce`, the healthiest interpretation is:

- use this repo as the starting codebase for `Gantt`
- grow `Drucker` out of the existing Jira tool and analysis layer
- use the Confluence and document tooling here as the starting substrate for `Hypatia`
- reuse `ReviewAgent` as a shared approval capability across the future platform

That is more realistic than trying to force this repo to represent the entire workforce.

## Recommended Positioning

### What `jira-utilities` should claim today

This repo can credibly claim:

- a strong planning-agent implementation slice
- a strong Jira-coordination tooling substrate
- a useful Confluence/documentation substrate
- a reusable approval and workflow orchestration pattern

### What it should not claim yet

This repo should not yet claim:

- a full event-driven agent platform
- execution-spine implementation
- durable traceability ownership
- release readiness control-plane automation
- bug reproduction automation
- Teams transcript knowledge capture

## Suggested Next Steps

If the goal is to converge this repo toward the workforce model, the most sensible path is:

1. Formalize `Gantt` as the umbrella role for the existing planning agents.
2. Grow `JiraAnalystAgent` plus `jira_tools` into a real `Drucker` slice:
   metadata gaps, stale-state detection, recommendation records, and safe write-backs.
3. Add a dedicated documentation agent on top of the new Confluence layer as the first `Hypatia` slice.
4. Standardize service interfaces around these agents:
   request model, response model, audit metadata, and approval hooks.
5. Leave execution-spine agents for a separate phase, since they depend on systems this repo does not currently model.

## Bottom Line

`jira-utilities` already maps meaningfully onto the `agent_workforce` vision, but not evenly.

Its center of gravity is:

- `Gantt` first
- `Drucker` second
- `Hypatia` tooling third

Everything else is either an adjacency or a future integration point.

That makes this repo a strong candidate for the **planning, Jira coordination, and documentation-facing edge** of the larger agent platform, not the execution spine or the full enterprise agent runtime.
