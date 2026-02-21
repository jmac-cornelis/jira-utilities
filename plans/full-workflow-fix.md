# Fix: Full Workflow Produces 0 Items

## Problem Statement

Running the full feature-plan workflow (`--workflow feature-plan` without `--scope-doc`) produces 0 scope items, 0 epics, and 0 stories. The user expects the AI to produce a detailed technical scope document (like `~/Downloads/RedfishRDE.md`) and then generate Jira tickets from it.

## Root Cause Analysis

The pipeline has **two paths** through each agent:

1. **LLM path** (`agent.run()` → `_run_with_tools()` → LLM ReAct loop → `_parse_*()` regex parser)
2. **Deterministic path** (`agent.research()` / `agent.analyze()` / `agent.scope()` → direct tool calls)

The full workflow uses the **LLM path** (via `_run_with_tools()`). The problem is a **parsing gap**: the LLM produces free-text Markdown, but the regex parsers in `_parse_report()`, `_parse_profile()`, and `_parse_scope()` are extremely rigid and fail silently when the LLM's output doesn't match the expected format exactly.

### Specific failures observed:

| Phase | Agent | Parser | Why it fails |
|-------|-------|--------|-------------|
| Research | `ResearchAgent._parse_report()` | Looks for `(Confidence: HIGH)` in bullet points | LLM doesn't always use that exact format |
| HW Analysis | `HardwareAnalystAgent._parse_profile()` | Looks for section headings like "EXISTING FIRMWARE:" | LLM uses different heading styles |
| Scoping | `ScopingAgent._parse_scope()` | Looks for `[S/M/L/XL] Title (Confidence: HIGH)` pattern | LLM doesn't produce this exact format |

When parsing fails, each agent returns an empty data structure (0 findings, 0 components, 0 scope items). The orchestrator passes these empty structures downstream, so the plan builder gets 0 scope items and produces 0 epics/stories.

### The cascade:
```
Research → 0 findings (parse fail)
  → HW Analysis gets empty research → 0 components (parse fail)
    → Scoping gets empty research + empty HW → 0 items (parse fail)
      → Plan Builder gets 0 items → 0 epics, 0 stories
```

## Solution: Hybrid Two-Pass with JSON Output

### Strategy

Instead of relying on fragile regex parsing of free-text Markdown, we:

1. **Run deterministic tool calls first** (baseline) — guaranteed to produce *something*
2. **Run the LLM with tools** (enrichment) — adds domain knowledge and reasoning
3. **Require JSON output blocks** from the LLM — reliable parsing
4. **Merge** deterministic baseline + LLM enrichment

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Output format | JSON block in LLM response | Reliable parsing, no regex guessing |
| Fallback | Deterministic baseline always runs | Guarantees non-empty output |
| Merge strategy | LLM output wins when present, baseline fills gaps | Best of both worlds |
| Diagnostic logging | Save raw LLM output per phase | Debug future parsing issues |
| Intermediate files | Save research.json, hw_profile.json, scope.json | User can inspect/edit between phases |

## Changes Required

### 1. Prompt Updates (3 files)

**`config/prompts/research_agent.md`** — Add JSON output requirement:
```markdown
## Output Format

After your research narrative, you MUST include a JSON block with your structured findings:

\`\`\`json
{
  "domain_overview": "2-3 paragraph summary...",
  "standards_and_specs": [
    {"content": "...", "source": "...", "source_url": "...", "confidence": "high|medium|low"}
  ],
  "existing_implementations": [...],
  "internal_knowledge": [...],
  "open_questions": ["question 1", "question 2"]
}
\`\`\`
```

**`config/prompts/hardware_analyst.md`** — Add JSON output requirement:
```markdown
## Output Format

After your analysis narrative, you MUST include a JSON block:

\`\`\`json
{
  "product_name": "...",
  "description": "...",
  "components": [{"name": "...", "description": "...", "type": "..."}],
  "bus_interfaces": [{"name": "...", "protocol": "...", "description": "..."}],
  "existing_firmware": [{"name": "...", "description": "..."}],
  "existing_drivers": [...],
  "existing_tools": [...],
  "gaps": ["gap 1", "gap 2"]
}
\`\`\`
```

**`config/prompts/scoping_agent.md`** — Add JSON output requirement:
```markdown
## Output Format

After your scoping narrative, you MUST include a JSON block:

\`\`\`json
{
  "summary": "...",
  "assumptions": ["..."],
  "firmware_items": [
    {
      "title": "...",
      "description": "...",
      "complexity": "S|M|L|XL",
      "confidence": "high|medium|low",
      "dependencies": ["..."],
      "rationale": "...",
      "acceptance_criteria": ["..."]
    }
  ],
  "driver_items": [...],
  "tool_items": [...],
  "open_questions": [
    {"question": "...", "context": "...", "blocking": true|false}
  ]
}
\`\`\`
```

### 2. Parser Updates (3 files)

Each agent's `_parse_*()` method gets a **JSON-first** strategy:

```python
def _parse_report(llm_output: str) -> ResearchReport:
    # 1. Try to extract JSON block
    json_data = _extract_json_block(llm_output)
    if json_data:
        return ResearchReport.from_dict(json_data)  # or manual construction
    
    # 2. Fall back to existing regex parser
    return _parse_report_markdown(llm_output)
```

Add a shared helper in `agents/base.py`:
```python
@staticmethod
def _extract_json_block(text: str) -> Optional[Dict]:
    """Extract the first ```json ... ``` block from LLM output."""
    match = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            log.warning('Found JSON block but failed to parse it')
    return None
```

### 3. Orchestrator Updates (`agents/feature_planning_orchestrator.py`)

**Hybrid two-pass for each phase:**

```python
def _phase_research(self) -> str:
    # Pass 1: Deterministic baseline (guaranteed non-empty)
    baseline = self.research_agent.research(
        self.state.feature_request,
        self.state.doc_paths,
    )
    
    # Pass 2: LLM enrichment (may produce richer content)
    llm_response = self.research_agent.run({
        'feature_request': self.state.feature_request,
        'doc_paths': self.state.doc_paths,
    })
    llm_report = llm_response.metadata.get('research_report', {})
    
    # Merge: LLM wins where it has content, baseline fills gaps
    merged = self._merge_research(baseline.to_dict(), llm_report)
    self.state.research_report = merged
```

**Save intermediate files:**

After each phase, save the structured output to the output directory:
```python
# After research phase
self._save_intermediate('research.json', self.state.research_report)

# After HW analysis phase  
self._save_intermediate('hw_profile.json', self.state.hw_profile)

# After scoping phase
self._save_intermediate('scope.json', self.state.feature_scope)
```

**Save raw LLM output for debugging:**
```python
self._save_debug_output(f'phase1_research_llm_raw.md', llm_response.content)
```

### 4. Output Directory Structure

The workflow should create an output directory for all artifacts:
```
plans/STLSB-redfish-rde/
├── research.json          # Phase 1 output
├── hw_profile.json        # Phase 2 output  
├── scope.json             # Phase 3 output
├── plan.json              # Phase 4 output (the Jira plan)
├── plan.md                # Markdown summary
├── plan.csv               # CSV for Jira import
├── plan.xlsx              # Excel workbook
└── debug/                 # Raw LLM outputs (for troubleshooting)
    ├── phase1_research.md
    ├── phase2_hw_analysis.md
    └── phase3_scoping.md
```

### 5. Workflow Summary Update (`pm_agent.py`)

Track all intermediate files in `all_created_files` for the summary table:
```
================================================================================
WORKFLOW COMPLETE: feature-plan
================================================================================
#   File                                    Description
1   plans/STLSB-redfish-rde/research.json   Research findings
2   plans/STLSB-redfish-rde/hw_profile.json Hardware profile
3   plans/STLSB-redfish-rde/scope.json      Feature scope
4   plans/STLSB-redfish-rde/plan.json       Feature plan JSON
5   plans/STLSB-redfish-rde/plan.md         Markdown summary
6   plans/STLSB-redfish-rde/plan.csv        Jira CSV (indented)
7   plans/STLSB-redfish-rde/plan.xlsx       Excel workbook
================================================================================
```

## Implementation Order

1. Add `_extract_json_block()` helper to `agents/base.py`
2. Update 3 prompt files with JSON output requirements
3. Update 3 agent parsers with JSON-first strategy
4. Update orchestrator with hybrid two-pass + intermediate file saving
5. Update `_workflow_feature_plan()` in `pm_agent.py` for output directory + file tracking
6. Test end-to-end
7. Commit

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| LLM still doesn't produce valid JSON | Deterministic baseline guarantees non-empty output |
| JSON block is malformed | `json.loads()` in try/except, falls back to regex parser |
| Deterministic tools fail (no web search, no MCP) | Each tool call is wrapped in try/except, returns partial results |
| Merge logic produces duplicates | Dedup by title when merging |
| Output directory already exists | Use `os.makedirs(exist_ok=True)` |
