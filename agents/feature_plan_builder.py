##########################################################################################
#
# Module: agents/feature_plan_builder.py
#
# Description: Feature Plan Builder Agent for the Feature Planning pipeline.
#              Converts a FeatureScope into a concrete Jira project plan with
#              Epics and Stories, ready for human review and execution.
#
# Author: Cornelis Networks
#
##########################################################################################

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, AgentConfig, AgentResponse
from agents.feature_planning_models import (
    FeatureScope,
    JiraPlan,
    PlannedEpic,
    PlannedStory,
    ScopeItem,
)

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# ---------------------------------------------------------------------------
# Default system instruction
# ---------------------------------------------------------------------------

PLAN_BUILDER_INSTRUCTION = '''You are a Feature Plan Builder Agent for Cornelis Networks.

Convert scoped SW/FW work items into a Jira project plan with Epics and Stories.
Group items by functional area, assign components, write clear descriptions with
acceptance criteria, and produce a dry-run plan for human review.
'''

# ---------------------------------------------------------------------------
# Category → Epic title prefix mapping
# ---------------------------------------------------------------------------

CATEGORY_EPIC_MAP = {
    'firmware': 'Firmware',
    'driver': 'Driver',
    'tool': 'Tools & Diagnostics',
    'test': 'Testing',
    'integration': 'Integration',
    'documentation': 'Documentation',
}

# Category → Jira component keyword matching
CATEGORY_COMPONENT_KEYWORDS = {
    'firmware': ['firmware', 'fw', 'embedded'],
    'driver': ['driver', 'kernel', 'hfi', 'module'],
    'tool': ['tool', 'cli', 'util', 'diag'],
    'test': ['qa', 'test', 'validation', 'quality'],
    'integration': ['integration', 'system'],
    'documentation': ['doc', 'documentation', 'docs', 'technical writing'],
}

# Category → Story summary prefix
CATEGORY_PREFIX = {
    'firmware': '[FW]',
    'driver': '[DRV]',
    'tool': '[TOOL]',
    'test': '[TEST]',
    'integration': '[INT]',
    'documentation': '[DOC]',
}


class FeaturePlanBuilderAgent(BaseAgent):
    '''
    Agent that converts a FeatureScope into a Jira project plan.

    Produces a JiraPlan with Epics and Stories, including component
    assignment, descriptions with acceptance criteria, and confidence tags.
    '''

    def __init__(self, **kwargs):
        '''
        Initialize the Feature Plan Builder Agent.

        Registers Jira and file tools for component lookup and output.
        '''
        instruction = self._load_prompt_file() or PLAN_BUILDER_INSTRUCTION

        config = AgentConfig(
            name='feature_plan_builder',
            description='Converts scoped work into Jira Epics and Stories',
            instruction=instruction,
            max_iterations=20,
        )

        # The plan builder sends large prompts (full scope + Jira metadata)
        # so we need a longer LLM timeout than the default 120s.
        if 'llm' not in kwargs:
            from llm.config import get_llm_client
            kwargs['llm'] = get_llm_client(timeout=600.0)

        super().__init__(config=config, **kwargs)
        self._register_builder_tools()

        # Cache for Jira components (populated on first use)
        self._jira_components: Optional[List[Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_builder_tools(self) -> None:
        '''Register tools the Plan Builder needs.'''
        # Jira tools — for component lookup
        try:
            from tools.jira_tools import get_project_info, get_components
            self.register_tool(get_project_info)
            self.register_tool(get_components)
        except ImportError:
            log.warning('jira_tools not available for FeaturePlanBuilderAgent')

        # File tools — for writing output
        try:
            from tools.file_tools import write_file, write_json
            self.register_tool(write_file)
            self.register_tool(write_json)
        except ImportError:
            log.warning('file_tools not available for FeaturePlanBuilderAgent')

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_prompt_file() -> Optional[str]:
        '''Load the plan builder prompt from config/prompts/.'''
        prompt_path = os.path.join('config', 'prompts', 'feature_plan_builder.md')
        if os.path.exists(prompt_path):
            try:
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                log.warning(f'Failed to load feature plan builder prompt: {e}')
        return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the Feature Plan Builder Agent.

        Input:
            input_data: Dictionary containing:
                - feature_request: str — The user's feature description
                - project_key: str — Target Jira project key
                - feature_scope: dict — Output from the Scoping Agent

        Output:
            AgentResponse with a JiraPlan in metadata['jira_plan'].
        '''
        log.debug('FeaturePlanBuilderAgent.run()')

        if not isinstance(input_data, dict):
            return AgentResponse.error_response(
                'Invalid input: expected dict with feature_scope and project_key'
            )

        feature_request = input_data.get('feature_request', '')
        project_key = input_data.get('project_key', '')
        feature_scope = input_data.get('feature_scope', {})

        if not project_key:
            return AgentResponse.error_response('No project_key provided')
        if not feature_scope:
            return AgentResponse.error_response('No feature_scope provided')

        # Build the user prompt
        user_prompt = self._build_plan_prompt(
            feature_request, project_key, feature_scope
        )

        # Run the ReAct loop — this lets the LLM call tools (e.g.
        # get_project_info, get_components) to gather Jira metadata.
        # The loop may time out on large prompts; that's OK because the
        # deterministic build_plan() below is the authoritative output.
        react_response = self._run_with_tools(user_prompt)

        if not react_response.success:
            log.warning(
                f'ReAct loop did not succeed '
                f'(error={react_response.error}); '
                f'falling back to deterministic build_plan()'
            )

        # Build the plan programmatically — this is the authoritative,
        # deterministic path that does not depend on the ReAct loop.
        plan = self.build_plan(
            feature_name=feature_scope.get('feature_name', feature_request[:100]),
            project_key=project_key,
            feature_scope=feature_scope,
        )

        # Return a success response with the structured plan regardless
        # of whether the ReAct loop succeeded.  The ReAct content is
        # included as supplementary context when available.
        return AgentResponse.success_response(
            content=react_response.content or plan.summary_markdown or '',
            tool_calls=react_response.tool_calls,
            iterations=react_response.iterations,
            metadata={'jira_plan': plan.to_dict()},
        )

    # ------------------------------------------------------------------
    # Programmatic plan building (deterministic)
    # ------------------------------------------------------------------

    def build_plan(
        self,
        feature_name: str,
        project_key: str,
        feature_scope: Dict[str, Any],
    ) -> JiraPlan:
        '''
        Build a Jira plan programmatically from a FeatureScope dict.

        This is the deterministic path that does not require LLM calls.

        Input:
            feature_name:   Short name for the feature.
            project_key:    Target Jira project key.
            feature_scope:  FeatureScope as a dict (from .to_dict()).

        Output:
            JiraPlan with Epics and Stories.
        '''
        log.info(f'FeaturePlanBuilderAgent.build_plan(project={project_key})')

        plan = JiraPlan(
            project_key=project_key,
            feature_name=feature_name,
        )

        # Load Jira components for assignment
        components = self._get_jira_components(project_key)

        # Group scope items by category and create Epics
        category_items = {
            'firmware': feature_scope.get('firmware_items', []),
            'driver': feature_scope.get('driver_items', []),
            'tool': feature_scope.get('tool_items', []),
            'test': feature_scope.get('test_items', []),
            'integration': feature_scope.get('integration_items', []),
            'documentation': feature_scope.get('documentation_items', []),
        }

        for category, items in category_items.items():
            if not items:
                continue

            epic_title = CATEGORY_EPIC_MAP.get(category, category.title())
            epic_component = self._match_component(category, components)

            epic = PlannedEpic(
                summary=f'[{feature_name[:50]}] {epic_title}',
                description=self._build_epic_description(
                    feature_name, epic_title, items
                ),
                components=[epic_component] if epic_component else [],
                labels=['feature-planning'],
            )

            # Create Stories from scope items
            prefix = CATEGORY_PREFIX.get(category, '')
            for item in items:
                story = self._scope_item_to_story(
                    item, prefix, epic.summary, components, category
                )
                epic.stories.append(story)

            plan.epics.append(epic)

        # Build the Markdown summary
        plan.summary_markdown = self._build_markdown_summary(plan, feature_scope)

        # Build confidence report
        plan.confidence_report = self._build_confidence_report(plan)

        return plan

    # ------------------------------------------------------------------
    # Internal helpers — Jira component lookup
    # ------------------------------------------------------------------

    def _get_jira_components(self, project_key: str) -> List[Dict[str, Any]]:
        '''Fetch Jira components for the project (cached).'''
        if self._jira_components is not None:
            return self._jira_components

        try:
            from tools.jira_tools import get_components
            result = get_components(project_key=project_key)
            data = result.data if hasattr(result, 'data') else result
            if isinstance(data, dict):
                self._jira_components = data.get('components', [])
                return self._jira_components
        except Exception as e:
            log.warning(f'Failed to fetch Jira components: {e}')

        self._jira_components = []
        return self._jira_components

    def _match_component(
        self,
        category: str,
        components: List[Dict[str, Any]],
    ) -> Optional[str]:
        '''Match a scope category to a Jira component name.'''
        keywords = CATEGORY_COMPONENT_KEYWORDS.get(category, [])
        if not keywords:
            return None

        for comp in components:
            comp_name = comp.get('name', '')
            comp_lower = comp_name.lower()
            if any(kw in comp_lower for kw in keywords):
                return comp_name

        return None

    # ------------------------------------------------------------------
    # Internal helpers — Story creation
    # ------------------------------------------------------------------

    def _scope_item_to_story(
        self,
        item: Dict[str, Any],
        prefix: str,
        parent_epic_summary: str,
        components: List[Dict[str, Any]],
        category: str,
    ) -> PlannedStory:
        '''Convert a scope item dict into a PlannedStory.'''
        title = item.get('title', 'Untitled')
        description = item.get('description', '')
        rationale = item.get('rationale', '')
        confidence = item.get('confidence', 'medium')
        complexity = item.get('complexity', 'M')
        dependencies = item.get('dependencies', [])
        acceptance_criteria = item.get('acceptance_criteria', [])

        # Build the full Story description in Markdown
        desc_lines = ['## Overview', '']
        if description:
            desc_lines.append(description)
        if rationale:
            desc_lines.extend(['', '## Rationale', '', rationale])

        if dependencies:
            desc_lines.extend(['', '## Dependencies'])
            for dep in dependencies:
                desc_lines.append(f'- BLOCKED_BY: {dep}')

        if acceptance_criteria:
            desc_lines.extend(['', '## Acceptance Criteria'])
            for ac in acceptance_criteria:
                desc_lines.append(f'- [ ] {ac}')

        desc_lines.extend([
            '',
            f'## Confidence: {confidence.upper()}',
            f'## Complexity: {complexity.upper()}',
        ])

        full_description = '\n'.join(desc_lines)

        # Match component
        component = self._match_component(category, components)

        # Build labels
        labels = [
            'feature-planning',
            f'confidence-{confidence.lower()}',
            f'complexity-{complexity.lower()}',
        ]

        return PlannedStory(
            summary=f'{prefix} {title}'.strip(),
            description=full_description,
            components=[component] if component else [],
            labels=labels,
            complexity=complexity,
            confidence=confidence,
            acceptance_criteria=acceptance_criteria,
            dependencies=dependencies,
            parent_epic_summary=parent_epic_summary,
        )

    # ------------------------------------------------------------------
    # Internal helpers — description builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_epic_description(
        feature_name: str,
        epic_title: str,
        items: List[Dict[str, Any]],
    ) -> str:
        '''Build the Epic description.'''
        lines = [
            f'## {epic_title} for {feature_name}',
            '',
            f'This Epic tracks all {epic_title.lower()} work for the '
            f'"{feature_name}" feature.',
            '',
            f'### Stories ({len(items)}):',
        ]
        for item in items:
            complexity = item.get('complexity', '?')
            confidence = item.get('confidence', '?')
            lines.append(
                f"- [{complexity}] {item.get('title', '?')} "
                f"(Confidence: {confidence})"
            )

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Internal helpers — Markdown summary
    # ------------------------------------------------------------------

    def _build_markdown_summary(
        self,
        plan: JiraPlan,
        feature_scope: Dict[str, Any],
    ) -> str:
        '''Build a human-readable Markdown summary of the plan.'''
        lines = [
            f'# JIRA PROJECT PLAN: {plan.feature_name}',
            '',
            f'**Project**: {plan.project_key}',
            f'**Total Epics**: {plan.total_epics}',
            f'**Total Stories**: {plan.total_stories}',
            f'**Total Tickets**: {plan.total_tickets}',
            '',
            '---',
            '',
        ]

        for epic in plan.epics:
            components_str = ', '.join(epic.components) if epic.components else 'unassigned'
            lines.extend([
                f'## EPIC: {epic.summary}',
                f'  Components: {components_str}',
                f'  Labels: {", ".join(epic.labels)}',
                f'  Stories: {len(epic.stories)}',
                '',
            ])

            for story in epic.stories:
                s_components = ', '.join(story.components) if story.components else 'unassigned'
                assignee = story.assignee or 'unassigned'
                lines.extend([
                    f'  ### STORY: {story.summary}',
                    f'    Components: {s_components}',
                    f'    Assignee: {assignee}',
                    f'    Labels: {", ".join(story.labels)}',
                    f'    Confidence: {story.confidence.upper()}',
                    f'    Complexity: {story.complexity.upper()}',
                    f'    Acceptance Criteria: {len(story.acceptance_criteria)} items',
                ])
                if story.dependencies:
                    lines.append(f'    Dependencies: {", ".join(story.dependencies)}')
                lines.append('')

        # Confidence report
        report = plan.confidence_report
        lines.extend([
            '---',
            '',
            '## CONFIDENCE REPORT',
            '',
        ])
        by_conf = report.get('by_confidence', {})
        for level in ('high', 'medium', 'low'):
            count = by_conf.get(level, 0)
            lines.append(f'- {level.upper()} confidence stories: {count}')

        # Open questions from scoping
        questions = feature_scope.get('open_questions', [])
        if questions:
            lines.extend([
                '',
                '## OPEN QUESTIONS',
                '',
            ])
            for q in questions:
                if isinstance(q, dict):
                    blocking = '[BLOCKING]' if q.get('blocking') else '[NON-BLOCKING]'
                    lines.append(f"- {blocking} {q.get('question', '?')}")
                    if q.get('context'):
                        lines.append(f"  Context: {q['context']}")
                else:
                    lines.append(f'- {q}')

        # Assumptions
        assumptions = feature_scope.get('assumptions', [])
        if assumptions:
            lines.extend([
                '',
                '## ASSUMPTIONS',
                '',
            ])
            for a in assumptions:
                lines.append(f'- {a}')

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Internal helpers — confidence report
    # ------------------------------------------------------------------

    @staticmethod
    def _build_confidence_report(plan: JiraPlan) -> Dict[str, Any]:
        '''Build aggregate confidence metrics for the plan.'''
        by_confidence: Dict[str, int] = {}
        by_complexity: Dict[str, int] = {}
        total_stories = 0
        stories_with_deps = 0

        for epic in plan.epics:
            for story in epic.stories:
                total_stories += 1
                conf = story.confidence.lower()
                by_confidence[conf] = by_confidence.get(conf, 0) + 1
                comp = story.complexity.upper()
                by_complexity[comp] = by_complexity.get(comp, 0) + 1
                if story.dependencies:
                    stories_with_deps += 1

        return {
            'total_epics': plan.total_epics,
            'total_stories': total_stories,
            'by_confidence': by_confidence,
            'by_complexity': by_complexity,
            'stories_with_dependencies': stories_with_deps,
        }

    # ------------------------------------------------------------------
    # Internal helpers — prompt building
    # ------------------------------------------------------------------

    def _build_plan_prompt(
        self,
        feature_request: str,
        project_key: str,
        feature_scope: Dict[str, Any],
    ) -> str:
        '''Build the user prompt for the LLM-driven plan building.'''
        lines = [
            f'## Feature Request\n\n{feature_request}\n',
            f'## Target Jira Project\n\nProject key: `{project_key}`\n',
            '## Scoped Work Items\n',
        ]

        # Summarize scope items by category
        for category in ('firmware', 'driver', 'tool', 'test',
                         'integration', 'documentation'):
            items = feature_scope.get(f'{category}_items', [])
            if items:
                label = CATEGORY_EPIC_MAP.get(category, category.title())
                lines.append(f'### {label} ({len(items)} items):')
                for item in items:
                    complexity = item.get('complexity', '?')
                    confidence = item.get('confidence', '?')
                    title = item.get('title', '?')
                    lines.append(
                        f'- [{complexity}] {title} (Confidence: {confidence})'
                    )
                lines.append('')

        # Open questions
        questions = feature_scope.get('open_questions', [])
        if questions:
            lines.append('### Open Questions:')
            for q in questions:
                if isinstance(q, dict):
                    lines.append(f"- {q.get('question', '?')}")
                else:
                    lines.append(f'- {q}')
            lines.append('')

        lines.append(
            '## Instructions\n\n'
            'Please build a Jira project plan from these scoped items:\n\n'
            '1. **Look up components** — Use `get_components` to find the '
            f'project\'s component list for `{project_key}`.\n'
            '2. **Create Epics** — One per functional area (Firmware, Driver, '
            'Tools, Testing, Documentation).\n'
            '3. **Create Stories** — One per scope item, with full descriptions '
            'and acceptance criteria.\n'
            '4. **Assign components** — Match scope categories to Jira components.\n'
            '5. **Generate the plan** — Produce the dry-run output in the format '
            'specified in your system instructions.\n\n'
            'This is a DRY RUN — do NOT create any tickets. Just produce the plan.'
        )

        return '\n'.join(lines)
