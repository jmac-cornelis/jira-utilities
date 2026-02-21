##########################################################################################
#
# Module: agents/feature_planning_orchestrator.py
#
# Description: Feature Planning Orchestrator Agent.
#              Coordinates the end-to-end feature-to-Jira workflow:
#              Research → Hardware Analysis → Scoping → Plan Building → Review → Execute.
#
# Author: Cornelis Networks
#
##########################################################################################

import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, AgentConfig, AgentResponse
from agents.feature_planning_models import FeaturePlanningState

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# ---------------------------------------------------------------------------
# Default system instruction
# ---------------------------------------------------------------------------

ORCHESTRATOR_INSTRUCTION = '''You are the Feature Planning Orchestrator for Cornelis Networks.

You coordinate a multi-phase workflow that takes a high-level feature request
and produces a complete Jira project plan with Epics and Stories.

Phases: Research → Hardware Analysis → Scoping → Plan Building → Review → Execute.

Always explain what you're doing. Never create Jira tickets without approval.
Be transparent about confidence levels and unknowns.
'''


class FeaturePlanningOrchestrator(BaseAgent):
    '''
    Orchestrator agent for the feature-to-Jira planning workflow.

    Coordinates Research Agent, Hardware Analyst, Scoping Agent,
    Feature Plan Builder, and Review Agent to produce a complete
    Jira project plan from a high-level feature request.
    '''

    def __init__(self, output_dir: str = '', **kwargs):
        '''
        Initialize the Feature Planning Orchestrator.

        Input:
            output_dir: Optional directory for intermediate/debug files.
                        If empty, intermediate files are not saved.
        '''
        instruction = self._load_prompt_file() or ORCHESTRATOR_INSTRUCTION

        config = AgentConfig(
            name='feature_planning_orchestrator',
            description='Coordinates end-to-end feature-to-Jira planning workflow',
            instruction=instruction,
            max_iterations=50,
        )

        super().__init__(config=config, **kwargs)

        # Sub-agents are lazily initialized to avoid import overhead
        self._research_agent = None
        self._hw_analyst = None
        self._scoping_agent = None
        self._plan_builder = None
        self._review_agent = None

        # Workflow state
        self.state = FeaturePlanningState()

        # Output directory for intermediate files (research.json, etc.)
        # and debug output (raw LLM responses).
        self._output_dir = output_dir
        self._created_files: List[str] = []

    # ------------------------------------------------------------------
    # Lazy sub-agent initialization
    # ------------------------------------------------------------------

    @property
    def research_agent(self):
        if self._research_agent is None:
            from agents.research_agent import ResearchAgent
            self._research_agent = ResearchAgent()
        return self._research_agent

    @property
    def hw_analyst(self):
        if self._hw_analyst is None:
            from agents.hardware_analyst import HardwareAnalystAgent
            self._hw_analyst = HardwareAnalystAgent()
        return self._hw_analyst

    @property
    def scoping_agent(self):
        if self._scoping_agent is None:
            from agents.scoping_agent import ScopingAgent
            self._scoping_agent = ScopingAgent()
        return self._scoping_agent

    @property
    def plan_builder(self):
        if self._plan_builder is None:
            from agents.feature_plan_builder import FeaturePlanBuilderAgent
            self._plan_builder = FeaturePlanBuilderAgent()
        return self._plan_builder

    @property
    def review_agent(self):
        if self._review_agent is None:
            from agents.review_agent import ReviewAgent
            self._review_agent = ReviewAgent()
        return self._review_agent

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_prompt_file() -> Optional[str]:
        '''Load the orchestrator prompt from config/prompts/.'''
        prompt_path = os.path.join(
            'config', 'prompts', 'feature_planning_orchestrator.md'
        )
        if os.path.exists(prompt_path):
            try:
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                log.warning(f'Failed to load orchestrator prompt: {e}')
        return None

    # ------------------------------------------------------------------
    # Intermediate / debug file helpers
    # ------------------------------------------------------------------

    def _save_intermediate(self, filename: str, data: Any) -> Optional[str]:
        '''
        Save an intermediate data structure (dict/list) to the output directory.

        Returns the file path if saved, or None if no output_dir is configured.
        '''
        if not self._output_dir:
            return None

        os.makedirs(self._output_dir, exist_ok=True)
        filepath = os.path.join(self._output_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            log.info(f'Saved intermediate file: {filepath}')
            self._created_files.append(filepath)
            return filepath
        except Exception as e:
            log.warning(f'Failed to save intermediate file {filepath}: {e}')
            return None

    def _save_debug_output(self, filename: str, text: str) -> Optional[str]:
        '''
        Save raw LLM output to the debug/ subdirectory for troubleshooting.

        Returns the file path if saved, or None.
        '''
        if not self._output_dir:
            return None

        debug_dir = os.path.join(self._output_dir, 'debug')
        os.makedirs(debug_dir, exist_ok=True)
        filepath = os.path.join(debug_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(text or '')
            log.info(f'Saved debug output: {filepath}')
            self._created_files.append(filepath)
            return filepath
        except Exception as e:
            log.warning(f'Failed to save debug output {filepath}: {e}')
            return None

    # ------------------------------------------------------------------
    # Merge helpers — combine deterministic baseline + LLM enrichment
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_research(baseline: Dict[str, Any], llm_report: Dict[str, Any]) -> Dict[str, Any]:
        '''
        Merge a deterministic research baseline with LLM-enriched findings.

        LLM output wins where it has content; baseline fills gaps.
        Deduplicates findings by content substring matching.
        '''
        if not llm_report:
            return baseline
        if not baseline:
            return llm_report

        merged = dict(baseline)

        # Domain overview: prefer LLM if it's longer/richer
        llm_overview = llm_report.get('domain_overview', '')
        if len(llm_overview) > len(merged.get('domain_overview', '')):
            merged['domain_overview'] = llm_overview

        # Merge finding lists — add LLM findings that aren't duplicates
        for key in ('standards_and_specs', 'existing_implementations', 'internal_knowledge'):
            baseline_items = merged.get(key, [])
            llm_items = llm_report.get(key, [])

            # Build a set of baseline content snippets for dedup
            seen = set()
            for item in baseline_items:
                content = (item.get('content', '') or '')[:80].lower()
                if content:
                    seen.add(content)

            for item in llm_items:
                content = (item.get('content', '') or '')[:80].lower()
                if content and content not in seen:
                    baseline_items.append(item)
                    seen.add(content)

            merged[key] = baseline_items

        # Merge open questions
        baseline_qs = set(q.lower() for q in merged.get('open_questions', []))
        for q in llm_report.get('open_questions', []):
            if q.lower() not in baseline_qs:
                merged.setdefault('open_questions', []).append(q)

        return merged

    @staticmethod
    def _merge_hw_profile(baseline: Dict[str, Any], llm_profile: Dict[str, Any]) -> Dict[str, Any]:
        '''
        Merge a deterministic HW profile baseline with LLM-enriched profile.
        '''
        if not llm_profile:
            return baseline
        if not baseline:
            return llm_profile

        merged = dict(baseline)

        # Scalar fields: prefer LLM if non-empty
        for key in ('product_name', 'description'):
            llm_val = llm_profile.get(key, '')
            if llm_val and len(llm_val) > len(merged.get(key, '')):
                merged[key] = llm_val

        # List fields: merge with dedup by name
        for key in ('components', 'bus_interfaces', 'existing_firmware',
                     'existing_drivers', 'existing_tools'):
            baseline_items = merged.get(key, [])
            seen_names = set(
                (item.get('name', '') or '').lower() for item in baseline_items
            )
            for item in llm_profile.get(key, []):
                name = (item.get('name', '') or '').lower()
                if name and name not in seen_names:
                    baseline_items.append(item)
                    seen_names.add(name)
            merged[key] = baseline_items

        # Gaps: merge with dedup
        baseline_gaps = set(g.lower() for g in merged.get('gaps', []))
        for gap in llm_profile.get('gaps', []):
            if gap.lower() not in baseline_gaps:
                merged.setdefault('gaps', []).append(gap)

        return merged

    @staticmethod
    def _merge_scope(baseline: Dict[str, Any], llm_scope: Dict[str, Any]) -> Dict[str, Any]:
        '''
        Merge a deterministic scope baseline with LLM-enriched scope.

        LLM scope items are preferred because they have richer descriptions,
        rationale, and acceptance criteria.  Baseline items fill gaps.
        '''
        if not llm_scope:
            return baseline
        if not baseline:
            return llm_scope

        merged = dict(llm_scope)  # LLM wins as the primary source

        # Summary: prefer LLM
        if not merged.get('summary') and baseline.get('summary'):
            merged['summary'] = baseline['summary']

        # Assumptions: merge
        baseline_assumptions = set(
            a.lower() for a in baseline.get('assumptions', [])
        )
        for a in merged.get('assumptions', []):
            baseline_assumptions.discard(a.lower())
        # Add remaining baseline assumptions
        for a in baseline.get('assumptions', []):
            if a.lower() in baseline_assumptions:
                merged.setdefault('assumptions', []).append(a)
                baseline_assumptions.discard(a.lower())

        # Item lists: add baseline items whose titles don't appear in LLM scope
        for key in ('firmware_items', 'driver_items', 'tool_items',
                     'test_items', 'integration_items', 'documentation_items'):
            llm_items = merged.get(key, [])
            llm_titles = set(
                (item.get('title', '') or '').lower() for item in llm_items
            )
            for item in baseline.get(key, []):
                title = (item.get('title', '') or '').lower()
                if title and title not in llm_titles:
                    llm_items.append(item)
                    llm_titles.add(title)
            merged[key] = llm_items

        # Open questions: merge
        llm_qs = set()
        for q in merged.get('open_questions', []):
            if isinstance(q, dict):
                llm_qs.add((q.get('question', '') or '').lower())
            elif isinstance(q, str):
                llm_qs.add(q.lower())
        for q in baseline.get('open_questions', []):
            q_text = q.get('question', '').lower() if isinstance(q, dict) else str(q).lower()
            if q_text and q_text not in llm_qs:
                merged.setdefault('open_questions', []).append(q)

        return merged

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the feature planning workflow.

        Input:
            input_data: Dictionary containing:
                - feature_request: str — The user's feature description (required)
                - project_key: str — Target Jira project key (required)
                - doc_paths: List[str] — Optional paths to spec documents
                - mode: str — 'full', 'research', 'plan', 'scope-to-plan', or 'execute'
                - scope_doc: str — Path to a pre-existing scope document (used with mode='scope-to-plan')
                - execute: bool — Whether to create tickets in Jira

        Output:
            AgentResponse with workflow results and state.
        '''
        log.debug('FeaturePlanningOrchestrator.run()')

        if not isinstance(input_data, dict):
            return AgentResponse.error_response(
                'Invalid input: expected dict with feature_request and project_key'
            )

        # Initialize state from input
        feature_request = input_data.get('feature_request', '')
        project_key = input_data.get('project_key', '')
        doc_paths = input_data.get('doc_paths', [])
        mode = input_data.get('mode', 'full')
        execute = input_data.get('execute', False)
        scope_doc = input_data.get('scope_doc', '')

        # Allow callers to set the output directory at run-time
        output_dir = input_data.get('output_dir', '')
        if output_dir:
            self._output_dir = output_dir

        if not feature_request:
            return AgentResponse.error_response('No feature_request provided')
        if not project_key:
            return AgentResponse.error_response('No project_key provided')

        self.state = FeaturePlanningState(
            feature_request=feature_request,
            project_key=project_key,
            doc_paths=doc_paths,
        )

        try:
            if mode == 'research':
                return self._run_research_only()
            elif mode == 'plan':
                return self._run_plan_only()
            elif mode == 'scope-to-plan':
                return self._run_scope_to_plan(
                    scope_doc=scope_doc, execute=execute
                )
            elif mode == 'execute':
                return self._run_execute_only()
            else:
                return self._run_full_workflow(execute=execute)

        except Exception as e:
            log.error(f'Feature planning orchestrator error: {e}')
            self.state.errors.append(str(e))
            return AgentResponse.error_response(
                str(e),
                metadata={'state': self.state.to_dict()},
            )

    # ------------------------------------------------------------------
    # Workflow modes
    # ------------------------------------------------------------------

    def _run_research_only(self) -> AgentResponse:
        '''Run only the research phase.'''
        result = self._phase_research()
        return AgentResponse.success_response(
            content=result,
            metadata={'state': self.state.to_dict()},
        )

    def _run_plan_only(self) -> AgentResponse:
        '''Run research through plan generation (no execution).'''
        results = []

        # Phase 1: Research
        results.append(self._phase_research())

        # Phase 2: Hardware Analysis
        results.append(self._phase_hw_analysis())

        # Phase 3: Scoping
        results.append(self._phase_scoping())

        # Phase 4: Plan Generation
        results.append(self._phase_plan_generation())

        return AgentResponse.success_response(
            content='\n\n'.join(results),
            metadata={
                'state': self.state.to_dict(),
                'ready_for_review': True,
            },
        )

    def _run_execute_only(self) -> AgentResponse:
        '''Execute a previously generated plan.'''
        if not self.state.jira_plan:
            return AgentResponse.error_response(
                'No Jira plan to execute. Run the full workflow first.'
            )
        return self._phase_execution()

    def _run_scope_to_plan(
        self, scope_doc: str = '', execute: bool = False
    ) -> AgentResponse:
        '''
        Skip research/HW-analysis/scoping — parse a pre-existing scope
        document and jump straight to plan generation + review + execute.

        The scope document can be:
          • A JSON file whose structure matches FeatureScope.to_dict()
          • A Markdown / plain-text file that the LLM will parse into scope items
          • A PDF or DOCX that will be extracted to text first

        Input:
            scope_doc: Path to the scope document.
            execute:   Whether to create Jira tickets after plan generation.

        Output:
            AgentResponse with the generated plan (and execution results if execute=True).
        '''
        results: List[str] = []

        if not scope_doc:
            return AgentResponse.error_response(
                'mode=scope-to-plan requires a --scope-doc path'
            )

        # ---- Phase 0: Parse the scope document into a FeatureScope dict ----
        log.info('=' * 60)
        log.info('PHASE 0: Parsing scope document → FeatureScope')
        log.info('=' * 60)

        scope_result = self._parse_scope_document(scope_doc)
        if scope_result is None:
            return AgentResponse.error_response(
                f'Failed to parse scope document: {scope_doc}'
            )

        self.state.feature_scope = scope_result
        self.state.mark_phase_complete('research')
        self.state.mark_phase_complete('hw_analysis')
        self.state.mark_phase_complete('scoping')

        results.append(
            f'PHASE 0: Scope Document Parsed\n'
            f'  Source: {scope_doc}\n'
            f'  Feature: {scope_result.get("feature_name", "?")}\n'
            f'  Items: {sum(len(scope_result.get(k, [])) for k in ("firmware_items", "driver_items", "tool_items", "test_items", "integration_items", "documentation_items"))}'
        )

        # ---- Phase 4: Plan Generation ----
        log.info('=' * 60)
        log.info('PHASE 4: Jira Plan Generation')
        log.info('=' * 60)
        results.append(self._phase_plan_generation())

        # ---- Phase 5: Review ----
        log.info('=' * 60)
        log.info('PHASE 5: Plan Review')
        log.info('=' * 60)
        results.append(self._format_plan_for_review())

        # ---- Phase 6: Execute (only if --execute) ----
        if execute:
            log.info('=' * 60)
            log.info('PHASE 6: Jira Execution')
            log.info('=' * 60)
            exec_result = self._phase_execution()
            if exec_result.success:
                results.append(exec_result.content)
            else:
                results.append(f'Execution failed: {exec_result.error}')

        return AgentResponse.success_response(
            content='\n\n'.join(results),
            metadata={
                'state': self.state.to_dict(),
                'ready_for_execution': not execute,
                'scope_doc': scope_doc,
            },
        )

    # ------------------------------------------------------------------
    # Scope document parser
    # ------------------------------------------------------------------

    def _parse_scope_document(self, doc_path: str) -> Optional[Dict[str, Any]]:
        '''
        Parse a scope document into a FeatureScope-compatible dict.

        Supports three formats:
          1. JSON  — must match FeatureScope.to_dict() schema (direct load)
          2. Markdown / plain text — parsed by the LLM into structured scope
          3. PDF / DOCX — extracted to text first, then parsed by the LLM

        Input:
            doc_path: Path to the scope document.

        Output:
            A dict matching FeatureScope.to_dict() structure, or None on failure.
        '''
        if not os.path.exists(doc_path):
            log.error(f'Scope document not found: {doc_path}')
            return None

        ext = os.path.splitext(doc_path)[1].lower()

        # ---- JSON: direct load ----
        if ext == '.json':
            return self._parse_scope_json(doc_path)

        # ---- PDF / DOCX: extract text first ----
        if ext in ('.pdf', '.docx'):
            text = self._extract_document_text(doc_path)
            if not text:
                log.error(f'Failed to extract text from {doc_path}')
                return None
            return self._parse_scope_text(text, source=doc_path)

        # ---- Markdown / plain text ----
        try:
            with open(doc_path, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception as e:
            log.error(f'Failed to read scope document {doc_path}: {e}')
            return None

        if not text.strip():
            log.error(f'Scope document is empty: {doc_path}')
            return None

        return self._parse_scope_text(text, source=doc_path)

    def _parse_scope_json(self, json_path: str) -> Optional[Dict[str, Any]]:
        '''
        Load a JSON scope document.  Validates that it has at least one
        category list (firmware_items, driver_items, etc.).

        Input:
            json_path: Path to the JSON file.

        Output:
            FeatureScope-compatible dict, or None on failure.
        '''
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            log.error(f'Failed to parse JSON scope document {json_path}: {e}')
            return None

        if not isinstance(data, dict):
            log.error(f'JSON scope document must be a dict, got {type(data).__name__}')
            return None

        # Minimal validation: at least one item list should be present
        item_keys = [
            'firmware_items', 'driver_items', 'tool_items',
            'test_items', 'integration_items', 'documentation_items',
        ]
        has_items = any(data.get(k) for k in item_keys)

        if not has_items:
            # Maybe the user provided a flat list of items — try to adapt
            if 'items' in data and isinstance(data['items'], list):
                log.info('Adapting flat "items" list into categorized scope')
                data = self._categorize_flat_items(data)
            else:
                log.warning(
                    'JSON scope document has no item lists; '
                    'will attempt to use it as-is'
                )

        # Ensure required top-level keys have defaults
        data.setdefault('feature_name', '')
        data.setdefault('summary', '')
        for k in item_keys:
            data.setdefault(k, [])
        data.setdefault('open_questions', [])
        data.setdefault('assumptions', [])
        data.setdefault('confidence_report', {})

        log.info(
            f'Loaded JSON scope: {data.get("feature_name", "?")} — '
            f'{sum(len(data.get(k, [])) for k in item_keys)} items'
        )
        return data

    @staticmethod
    def _categorize_flat_items(data: Dict[str, Any]) -> Dict[str, Any]:
        '''
        Convert a flat {"items": [...]} structure into the categorized
        FeatureScope format by inspecting each item's "category" field.

        Input:
            data: Dict with an "items" key containing a list of scope item dicts.

        Output:
            Dict with items distributed into *_items lists.
        '''
        category_map = {
            'firmware': 'firmware_items',
            'driver': 'driver_items',
            'tool': 'tool_items',
            'test': 'test_items',
            'integration': 'integration_items',
            'documentation': 'documentation_items',
        }

        result = {
            'feature_name': data.get('feature_name', ''),
            'summary': data.get('summary', ''),
            'firmware_items': [],
            'driver_items': [],
            'tool_items': [],
            'test_items': [],
            'integration_items': [],
            'documentation_items': [],
            'open_questions': data.get('open_questions', []),
            'assumptions': data.get('assumptions', []),
            'confidence_report': {},
        }

        for item in data.get('items', []):
            cat = item.get('category', 'firmware').lower()
            target_key = category_map.get(cat, 'firmware_items')
            result[target_key].append(item)

        return result

    def _parse_scope_text(
        self, text: str, source: str = ''
    ) -> Optional[Dict[str, Any]]:
        '''
        Use the LLM to parse free-form text (Markdown, plain text, extracted
        PDF/DOCX) into a structured FeatureScope dict.

        The LLM is given the text and asked to produce JSON matching the
        FeatureScope schema.

        Input:
            text:   The raw text content of the scope document.
            source: Original file path (for logging).

        Output:
            FeatureScope-compatible dict, or None on failure.
        '''
        import re

        log.info(f'Parsing scope text via LLM ({len(text)} chars from {source})')

        # Build the LLM prompt
        parse_prompt = (
            'You are given a technical scoping document for a Cornelis Networks '
            'feature.  Parse it into a structured JSON object with this schema:\n\n'
            '```json\n'
            '{\n'
            '  "feature_name": "short name",\n'
            '  "summary": "executive summary",\n'
            '  "firmware_items": [ { "title": "...", "description": "...", '
            '"category": "firmware", "complexity": "S|M|L|XL", '
            '"confidence": "high|medium|low", "dependencies": [], '
            '"rationale": "...", "acceptance_criteria": ["..."] } ],\n'
            '  "driver_items": [ ... ],\n'
            '  "tool_items": [ ... ],\n'
            '  "test_items": [ ... ],\n'
            '  "integration_items": [ ... ],\n'
            '  "documentation_items": [ ... ],\n'
            '  "open_questions": [ { "question": "...", "context": "...", '
            '"options": [], "blocking": false } ],\n'
            '  "assumptions": [ "..." ]\n'
            '}\n'
            '```\n\n'
            'Rules:\n'
            '- Assign each work item to the most appropriate category.\n'
            '- If the document mentions complexity/size, map it to S/M/L/XL.\n'
            '- If the document mentions confidence, map it to high/medium/low.\n'
            '- If not stated, default complexity to M and confidence to medium.\n'
            '- Extract acceptance criteria from the text where possible.\n'
            '- Identify dependencies between items by title.\n'
            '- List any open questions or unknowns.\n'
            '- List any assumptions made.\n\n'
            'Return ONLY the JSON object, no other text.\n\n'
            '--- SCOPE DOCUMENT ---\n\n'
            f'{text}\n'
        )

        try:
            from llm.config import get_llm_client
            llm = get_llm_client()
            from llm.base import Message
            messages = [Message.user(parse_prompt)]
            response = llm.chat(messages=messages)

            if not response or not response.content:
                log.error('LLM returned empty response for scope parsing')
                return None

            # Extract JSON from the response (may be wrapped in ```json ... ```)
            content = response.content.strip()
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1).strip()

            data = json.loads(content)

            if not isinstance(data, dict):
                log.error(f'LLM scope parse returned {type(data).__name__}, expected dict')
                return None

            # Ensure all required keys
            item_keys = [
                'firmware_items', 'driver_items', 'tool_items',
                'test_items', 'integration_items', 'documentation_items',
            ]
            data.setdefault('feature_name', '')
            data.setdefault('summary', '')
            for k in item_keys:
                data.setdefault(k, [])
            data.setdefault('open_questions', [])
            data.setdefault('assumptions', [])
            data.setdefault('confidence_report', {})

            total = sum(len(data.get(k, [])) for k in item_keys)
            log.info(f'LLM parsed scope: {data.get("feature_name", "?")} — {total} items')
            return data

        except json.JSONDecodeError as e:
            log.error(f'Failed to parse LLM scope output as JSON: {e}')
            return None
        except Exception as e:
            log.error(f'LLM scope parsing failed: {e}')
            return None

    @staticmethod
    def _extract_document_text(doc_path: str) -> Optional[str]:
        '''
        Extract plain text from a PDF or DOCX file.

        Uses the same library fallback chain as knowledge_tools:
        PDF:  PyMuPDF → pdfplumber → PyPDF2
        DOCX: python-docx

        Input:
            doc_path: Path to the document.

        Output:
            Extracted text, or None on failure.
        '''
        ext = os.path.splitext(doc_path)[1].lower()

        if ext == '.pdf':
            # Try PyMuPDF first
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(doc_path)
                text = '\n'.join(page.get_text() for page in doc)
                doc.close()
                if text.strip():
                    return text
            except ImportError:
                pass
            except Exception as e:
                log.warning(f'PyMuPDF failed on {doc_path}: {e}')

            # Try pdfplumber
            try:
                import pdfplumber
                with pdfplumber.open(doc_path) as pdf:
                    text = '\n'.join(
                        page.extract_text() or '' for page in pdf.pages
                    )
                if text.strip():
                    return text
            except ImportError:
                pass
            except Exception as e:
                log.warning(f'pdfplumber failed on {doc_path}: {e}')

            # Try PyPDF2
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(doc_path)
                text = '\n'.join(
                    page.extract_text() or '' for page in reader.pages
                )
                if text.strip():
                    return text
            except ImportError:
                pass
            except Exception as e:
                log.warning(f'PyPDF2 failed on {doc_path}: {e}')

            log.error(f'No PDF library available to extract {doc_path}')
            return None

        elif ext == '.docx':
            try:
                from docx import Document
                doc = Document(doc_path)
                text = '\n'.join(p.text for p in doc.paragraphs)
                if text.strip():
                    return text
            except ImportError:
                log.error('python-docx not installed; cannot extract DOCX')
            except Exception as e:
                log.error(f'DOCX extraction failed for {doc_path}: {e}')
            return None

        else:
            log.error(f'Unsupported document type for extraction: {ext}')
            return None

    def _run_full_workflow(self, execute: bool = False) -> AgentResponse:
        '''Run the complete workflow.'''
        results = []

        # Phase 1: Research
        log.info('=' * 60)
        log.info('PHASE 1: Research')
        log.info('=' * 60)
        results.append(self._phase_research())

        # Check for blocking questions
        blocking = self._get_blocking_questions()
        if blocking:
            results.append(self._format_blocking_questions(blocking))
            return AgentResponse.success_response(
                content='\n\n'.join(results),
                metadata={
                    'state': self.state.to_dict(),
                    'blocked': True,
                    'blocking_questions': [q.get('question', '') for q in blocking],
                },
            )

        # Phase 2: Hardware Analysis
        log.info('=' * 60)
        log.info('PHASE 2: Hardware Analysis')
        log.info('=' * 60)
        results.append(self._phase_hw_analysis())

        # Phase 3: Scoping
        log.info('=' * 60)
        log.info('PHASE 3: SW/FW Scoping')
        log.info('=' * 60)
        results.append(self._phase_scoping())

        # Check for blocking questions from scoping
        blocking = self._get_blocking_questions()
        if blocking:
            results.append(self._format_blocking_questions(blocking))
            return AgentResponse.success_response(
                content='\n\n'.join(results),
                metadata={
                    'state': self.state.to_dict(),
                    'blocked': True,
                    'blocking_questions': [q.get('question', '') for q in blocking],
                },
            )

        # Phase 4: Plan Generation
        log.info('=' * 60)
        log.info('PHASE 4: Jira Plan Generation')
        log.info('=' * 60)
        results.append(self._phase_plan_generation())

        # Phase 5: Present for review
        log.info('=' * 60)
        log.info('PHASE 5: Plan Review')
        log.info('=' * 60)
        results.append(self._format_plan_for_review())

        # Phase 6: Execute (only if --execute flag is set)
        if execute:
            log.info('=' * 60)
            log.info('PHASE 6: Jira Execution')
            log.info('=' * 60)
            exec_result = self._phase_execution()
            if exec_result.success:
                results.append(exec_result.content)
            else:
                results.append(f'Execution failed: {exec_result.error}')

        return AgentResponse.success_response(
            content='\n\n'.join(results),
            metadata={
                'state': self.state.to_dict(),
                'ready_for_execution': not execute,
            },
        )

    # ------------------------------------------------------------------
    # Individual phases
    # ------------------------------------------------------------------

    def _phase_research(self) -> str:
        '''
        Phase 1: Research the feature domain.

        Hybrid two-pass approach:
          Pass 1 — deterministic tool calls (guaranteed baseline)
          Pass 2 — LLM with tools (enrichment via JSON output)
          Merge  — LLM wins where it has content, baseline fills gaps
        '''
        self.state.current_phase = 'research'
        start = time.time()

        try:
            # Pass 1: Deterministic baseline (guaranteed non-empty)
            log.info('Phase 1 — Pass 1: deterministic research')
            baseline_report = self.research_agent.research(
                self.state.feature_request,
                self.state.doc_paths or None,
            )
            baseline_dict = baseline_report.to_dict()
            baseline_count = len(baseline_report.all_findings)
            log.info(f'Phase 1 — Pass 1 complete: {baseline_count} findings')

            # Pass 2: LLM enrichment (may produce richer content)
            log.info('Phase 1 — Pass 2: LLM enrichment')
            llm_response = self.research_agent.run({
                'feature_request': self.state.feature_request,
                'doc_paths': self.state.doc_paths,
            })

            llm_report = {}
            if llm_response.success:
                llm_report = llm_response.metadata.get('research_report', {})
                # Save raw LLM output for debugging
                self._save_debug_output(
                    'phase1_research_llm.md', llm_response.content
                )

            llm_count = (
                len(llm_report.get('standards_and_specs', []))
                + len(llm_report.get('existing_implementations', []))
                + len(llm_report.get('internal_knowledge', []))
            )
            log.info(f'Phase 1 — Pass 2 complete: {llm_count} LLM findings')

            # Merge: LLM wins where it has content, baseline fills gaps
            merged = self._merge_research(baseline_dict, llm_report)
            self.state.research_report = merged
            self.state.mark_phase_complete('research')

            # Save intermediate file
            self._save_intermediate('research.json', merged)

            duration = time.time() - start
            report = merged
            conf = report.get('confidence_summary', {})

            specs = len(report.get('standards_and_specs', []))
            impls = len(report.get('existing_implementations', []))
            internal = len(report.get('internal_knowledge', []))

            return (
                f'PHASE 1: Research — COMPLETE ({duration:.1f}s)\n'
                f'  Domain overview: {len(report.get("domain_overview", ""))} chars\n'
                f'  Standards/specs: {specs}\n'
                f'  Implementations: {impls}\n'
                f'  Internal knowledge: {internal}\n'
                f'  Total findings: {specs + impls + internal} '
                f'(baseline={baseline_count}, LLM={llm_count})\n'
                f'  Confidence: {conf.get("high", 0)} high, '
                f'{conf.get("medium", 0)} medium, '
                f'{conf.get("low", 0)} low\n'
                f'  Open questions: {len(report.get("open_questions", []))}'
            )

        except Exception as e:
            self.state.errors.append(f'Research exception: {e}')
            log.error(f'Phase 1 research error: {e}', exc_info=True)
            return f'PHASE 1: Research — ERROR\n  {e}'

    def _phase_hw_analysis(self) -> str:
        '''
        Phase 2: Analyze the hardware product.

        Hybrid two-pass approach:
          Pass 1 — deterministic tool calls (guaranteed baseline)
          Pass 2 — LLM with tools (enrichment via JSON output)
          Merge  — LLM wins where it has content, baseline fills gaps
        '''
        self.state.current_phase = 'hw_analysis'
        start = time.time()

        try:
            # Pass 1: Deterministic baseline
            log.info('Phase 2 — Pass 1: deterministic HW analysis')
            baseline_profile = self.hw_analyst.analyze(
                self.state.feature_request,
                self.state.project_key,
                self.state.research_report or None,
            )
            baseline_dict = baseline_profile.to_dict()
            baseline_count = (
                len(baseline_profile.components)
                + len(baseline_profile.existing_firmware)
            )
            log.info(f'Phase 2 — Pass 1 complete: {baseline_count} items')

            # Pass 2: LLM enrichment
            log.info('Phase 2 — Pass 2: LLM enrichment')
            llm_response = self.hw_analyst.run({
                'feature_request': self.state.feature_request,
                'project_key': self.state.project_key,
                'research_report': self.state.research_report or {},
            })

            llm_profile = {}
            if llm_response.success:
                llm_profile = llm_response.metadata.get('hw_profile', {})
                self._save_debug_output(
                    'phase2_hw_analysis_llm.md', llm_response.content
                )

            llm_count = (
                len(llm_profile.get('components', []))
                + len(llm_profile.get('existing_firmware', []))
            )
            log.info(f'Phase 2 — Pass 2 complete: {llm_count} LLM items')

            # Merge
            merged = self._merge_hw_profile(baseline_dict, llm_profile)
            self.state.hw_profile = merged
            self.state.mark_phase_complete('hw_analysis')

            # Save intermediate file
            self._save_intermediate('hw_profile.json', merged)

            duration = time.time() - start
            profile = merged

            return (
                f'PHASE 2: Hardware Analysis — COMPLETE ({duration:.1f}s)\n'
                f'  Product: {profile.get("product_name", "Unknown")}\n'
                f'  Components: {len(profile.get("components", []))}\n'
                f'  Bus interfaces: {len(profile.get("bus_interfaces", []))}\n'
                f'  Existing firmware: {len(profile.get("existing_firmware", []))}\n'
                f'  Existing drivers: {len(profile.get("existing_drivers", []))}\n'
                f'  Existing tools: {len(profile.get("existing_tools", []))}\n'
                f'  Knowledge gaps: {len(profile.get("gaps", []))}\n'
                f'  Sources: baseline={baseline_count}, LLM={llm_count}'
            )

        except Exception as e:
            self.state.errors.append(f'HW analysis exception: {e}')
            log.error(f'Phase 2 HW analysis error: {e}', exc_info=True)
            return f'PHASE 2: Hardware Analysis — ERROR\n  {e}'

    def _phase_scoping(self) -> str:
        '''
        Phase 3: Scope the SW/FW work.

        Hybrid two-pass approach:
          Pass 1 — deterministic scoping (guaranteed baseline)
          Pass 2 — LLM with tools (enrichment via JSON output)
          Merge  — LLM scope items preferred (richer), baseline fills gaps
        '''
        self.state.current_phase = 'scoping'
        start = time.time()

        try:
            # Pass 1: Deterministic baseline
            log.info('Phase 3 — Pass 1: deterministic scoping')
            baseline_scope = self.scoping_agent.scope(
                self.state.feature_request,
                self.state.research_report or None,
                self.state.hw_profile or None,
            )
            baseline_dict = baseline_scope.to_dict()
            baseline_count = len(baseline_scope.all_items)
            log.info(f'Phase 3 — Pass 1 complete: {baseline_count} items')

            # Pass 2: LLM enrichment
            log.info('Phase 3 — Pass 2: LLM enrichment')
            llm_response = self.scoping_agent.run({
                'feature_request': self.state.feature_request,
                'research_report': self.state.research_report or {},
                'hw_profile': self.state.hw_profile or {},
            })

            llm_scope = {}
            if llm_response.success:
                llm_scope = llm_response.metadata.get('feature_scope', {})
                self._save_debug_output(
                    'phase3_scoping_llm.md', llm_response.content
                )

            llm_count = sum(
                len(llm_scope.get(k, []))
                for k in ('firmware_items', 'driver_items', 'tool_items',
                          'test_items', 'integration_items', 'documentation_items')
            )
            log.info(f'Phase 3 — Pass 2 complete: {llm_count} LLM items')

            # Merge: LLM scope items preferred (richer), baseline fills gaps
            merged = self._merge_scope(baseline_dict, llm_scope)
            self.state.feature_scope = merged
            self.state.mark_phase_complete('scoping')

            # Accumulate questions
            scope = merged
            for q in scope.get('open_questions', []):
                self.state.questions_for_user.append(q)

            # Save intermediate file
            self._save_intermediate('scope.json', merged)

            duration = time.time() - start
            conf = scope.get('confidence_report', {})

            return (
                f'PHASE 3: SW/FW Scoping — COMPLETE ({duration:.1f}s)\n'
                f'  Total items: {conf.get("total_items", 0)}\n'
                f'  By category: {conf.get("by_category", {})}\n'
                f'  By confidence: {conf.get("by_confidence", {})}\n'
                f'  By complexity: {conf.get("by_complexity", {})}\n'
                f'  Open questions: {conf.get("total_questions", 0)} '
                f'({conf.get("blocking_questions", 0)} blocking)\n'
                f'  Sources: baseline={baseline_count}, LLM={llm_count}'
            )

        except Exception as e:
            self.state.errors.append(f'Scoping exception: {e}')
            log.error(f'Phase 3 scoping error: {e}', exc_info=True)
            return f'PHASE 3: SW/FW Scoping — ERROR\n  {e}'

    def _phase_plan_generation(self) -> str:
        '''Phase 4: Generate the Jira plan.'''
        self.state.current_phase = 'plan_generation'
        start = time.time()

        try:
            response = self.plan_builder.run({
                'feature_request': self.state.feature_request,
                'project_key': self.state.project_key,
                'feature_scope': self.state.feature_scope or {},
            })

            if response.success:
                self.state.jira_plan = response.metadata.get('jira_plan', {})
                self.state.mark_phase_complete('plan_generation')

                duration = time.time() - start
                plan = self.state.jira_plan or {}

                return (
                    f'PHASE 4: Jira Plan Generation — COMPLETE ({duration:.1f}s)\n'
                    f'  Project: {plan.get("project_key", "?")}\n'
                    f'  Epics: {plan.get("total_epics", 0)}\n'
                    f'  Stories: {plan.get("total_stories", 0)}\n'
                    f'  Total tickets: {plan.get("total_tickets", 0)}'
                )
            else:
                error = response.error or 'Unknown error'
                self.state.errors.append(f'Plan generation failed: {error}')
                return f'PHASE 4: Jira Plan Generation — FAILED\n  Error: {error}'

        except Exception as e:
            self.state.errors.append(f'Plan generation exception: {e}')
            return f'PHASE 4: Jira Plan Generation — ERROR\n  {e}'

    def _phase_execution(self) -> AgentResponse:
        '''Phase 6: Create tickets in Jira.'''
        self.state.current_phase = 'execution'

        plan = self.state.jira_plan
        if not plan:
            return AgentResponse.error_response('No Jira plan to execute')

        try:
            from tools.jira_tools import create_ticket
        except ImportError:
            return AgentResponse.error_response('jira_tools not available')

        project_key = plan.get('project_key', '')
        created_tickets: List[Dict[str, Any]] = []
        errors: List[str] = []

        for epic_data in plan.get('epics', []):
            # Create the Epic
            try:
                epic_result = create_ticket(
                    project_key=project_key,
                    summary=epic_data.get('summary', ''),
                    issue_type='Epic',
                    description=epic_data.get('description', ''),
                    components=epic_data.get('components'),
                    labels=epic_data.get('labels'),
                )

                epic_key = None
                if hasattr(epic_result, 'is_success') and epic_result.is_success:
                    epic_key = epic_result.data.get('key')
                    created_tickets.append({
                        'type': 'Epic',
                        'key': epic_key,
                        'summary': epic_data.get('summary', ''),
                    })
                    log.info(f'Created Epic: {epic_key}')
                else:
                    error = getattr(epic_result, 'error', str(epic_result))
                    errors.append(f"Epic '{epic_data.get('summary', '')}': {error}")
                    continue

            except Exception as e:
                errors.append(f"Epic '{epic_data.get('summary', '')}': {e}")
                continue

            # Create Stories under this Epic
            for story_data in epic_data.get('stories', []):
                try:
                    story_result = create_ticket(
                        project_key=project_key,
                        summary=story_data.get('summary', ''),
                        issue_type='Story',
                        description=story_data.get('description', ''),
                        components=story_data.get('components'),
                        labels=story_data.get('labels'),
                        parent_key=epic_key,
                        assignee=story_data.get('assignee'),
                    )

                    if hasattr(story_result, 'is_success') and story_result.is_success:
                        story_key = story_result.data.get('key')
                        created_tickets.append({
                            'type': 'Story',
                            'key': story_key,
                            'summary': story_data.get('summary', ''),
                            'parent': epic_key,
                        })
                        log.info(f'Created Story: {story_key} under {epic_key}')
                    else:
                        error = getattr(story_result, 'error', str(story_result))
                        errors.append(
                            f"Story '{story_data.get('summary', '')}': {error}"
                        )

                except Exception as e:
                    errors.append(f"Story '{story_data.get('summary', '')}': {e}")

        self.state.mark_phase_complete('execution')

        # Format results
        lines = [
            'PHASE 6: Jira Execution — COMPLETE',
            f'  Created: {len(created_tickets)} tickets',
            f'  Errors: {len(errors)}',
            '',
        ]

        if created_tickets:
            lines.append('Created Tickets:')
            for t in created_tickets:
                parent = f" (under {t['parent']})" if t.get('parent') else ''
                lines.append(f"  [{t['type']}] {t['key']}: {t['summary']}{parent}")

        if errors:
            lines.extend(['', 'Errors:'])
            for e in errors:
                lines.append(f'  ! {e}')

        content = '\n'.join(lines)

        return AgentResponse.success_response(
            content=content,
            metadata={
                'state': self.state.to_dict(),
                'created_tickets': created_tickets,
                'execution_errors': errors,
            },
        )

    # ------------------------------------------------------------------
    # Helpers — question handling
    # ------------------------------------------------------------------

    def _get_blocking_questions(self) -> List[Dict[str, Any]]:
        '''Get all blocking questions accumulated so far.'''
        return [
            q for q in self.state.questions_for_user
            if isinstance(q, dict) and q.get('blocking', False)
        ]

    @staticmethod
    def _format_blocking_questions(questions: List[Dict[str, Any]]) -> str:
        '''Format blocking questions for display.'''
        lines = [
            '⚠️  BLOCKING QUESTIONS — Human input required before proceeding:',
            '',
        ]
        for i, q in enumerate(questions, 1):
            lines.append(f'  {i}. {q.get("question", "?")}')
            context = q.get('context', '')
            if context:
                lines.append(f'     Context: {context}')
            options = q.get('options', [])
            if options:
                lines.append(f'     Options: {", ".join(options)}')
            lines.append('')

        lines.append(
            'Please answer these questions and re-run the workflow to continue.'
        )
        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Helpers — plan review formatting
    # ------------------------------------------------------------------

    def _format_plan_for_review(self) -> str:
        '''Format the Jira plan for human review.'''
        plan = self.state.jira_plan
        if not plan:
            return 'PHASE 5: Plan Review — NO PLAN AVAILABLE'

        lines = [
            '=' * 60,
            'PHASE 5: Plan Review — READY FOR APPROVAL',
            '=' * 60,
            '',
        ]

        # Include the Markdown summary if available
        markdown = plan.get('summary_markdown', '')
        if markdown:
            lines.append(markdown)
        else:
            # Fallback: basic summary
            lines.extend([
                f'Project: {plan.get("project_key", "?")}',
                f'Feature: {plan.get("feature_name", "?")}',
                f'Epics: {plan.get("total_epics", 0)}',
                f'Stories: {plan.get("total_stories", 0)}',
                f'Total tickets: {plan.get("total_tickets", 0)}',
            ])

        lines.extend([
            '',
            '=' * 60,
            '',
            'To execute this plan and create tickets in Jira, re-run with --execute.',
            'To modify the plan, adjust the feature request or provide additional docs.',
            '',
            '=' * 60,
        ])

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def get_state(self) -> Dict[str, Any]:
        '''Return the current workflow state as a dict.'''
        return self.state.to_dict()

    def load_state(self, state_dict: Dict[str, Any]) -> None:
        '''Load workflow state from a dict (for resumption).'''
        self.state = FeaturePlanningState(
            feature_request=state_dict.get('feature_request', ''),
            project_key=state_dict.get('project_key', ''),
            doc_paths=state_dict.get('doc_paths', []),
            research_report=state_dict.get('research_report'),
            hw_profile=state_dict.get('hw_profile'),
            feature_scope=state_dict.get('feature_scope'),
            jira_plan=state_dict.get('jira_plan'),
            questions_for_user=state_dict.get('questions_for_user', []),
            current_phase=state_dict.get('current_phase', 'init'),
            completed_phases=state_dict.get('completed_phases', []),
            errors=state_dict.get('errors', []),
        )

    def save_plan_to_file(self, output_path: str) -> str:
        '''
        Save the Jira plan to a JSON file.

        Input:
            output_path: Path to write the JSON file.

        Output:
            The path written to.
        '''
        plan = self.state.jira_plan
        if not plan:
            raise ValueError('No Jira plan to save')

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2)

        log.info(f'Saved Jira plan to: {output_path}')
        return output_path

    def save_markdown_to_file(self, output_path: str) -> str:
        '''
        Save the plan's Markdown summary to a file.

        Input:
            output_path: Path to write the Markdown file.

        Output:
            The path written to.
        '''
        plan = self.state.jira_plan
        if not plan:
            raise ValueError('No Jira plan to save')

        markdown = plan.get('summary_markdown', '')
        if not markdown:
            raise ValueError('No Markdown summary in the plan')

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown)

        log.info(f'Saved plan Markdown to: {output_path}')
        return output_path
