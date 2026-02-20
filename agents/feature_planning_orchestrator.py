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

    def __init__(self, **kwargs):
        '''
        Initialize the Feature Planning Orchestrator.
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
                - mode: str — 'full', 'research', 'plan', or 'execute'
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
        '''Phase 1: Research the feature domain.'''
        self.state.current_phase = 'research'
        start = time.time()

        try:
            response = self.research_agent.run({
                'feature_request': self.state.feature_request,
                'doc_paths': self.state.doc_paths,
            })

            if response.success:
                self.state.research_report = response.metadata.get(
                    'research_report', {}
                )
                self.state.mark_phase_complete('research')

                duration = time.time() - start
                report = self.state.research_report or {}
                conf = report.get('confidence_summary', {})

                return (
                    f'PHASE 1: Research — COMPLETE ({duration:.1f}s)\n'
                    f'  Domain overview: {len(report.get("domain_overview", ""))} chars\n'
                    f'  Standards/specs: {len(report.get("standards_and_specs", []))}\n'
                    f'  Implementations: {len(report.get("existing_implementations", []))}\n'
                    f'  Internal knowledge: {len(report.get("internal_knowledge", []))}\n'
                    f'  Confidence: {conf.get("high", 0)} high, '
                    f'{conf.get("medium", 0)} medium, '
                    f'{conf.get("low", 0)} low\n'
                    f'  Open questions: {len(report.get("open_questions", []))}'
                )
            else:
                error = response.error or 'Unknown error'
                self.state.errors.append(f'Research failed: {error}')
                return f'PHASE 1: Research — FAILED\n  Error: {error}'

        except Exception as e:
            self.state.errors.append(f'Research exception: {e}')
            return f'PHASE 1: Research — ERROR\n  {e}'

    def _phase_hw_analysis(self) -> str:
        '''Phase 2: Analyze the hardware product.'''
        self.state.current_phase = 'hw_analysis'
        start = time.time()

        try:
            response = self.hw_analyst.run({
                'feature_request': self.state.feature_request,
                'project_key': self.state.project_key,
                'research_report': self.state.research_report or {},
            })

            if response.success:
                self.state.hw_profile = response.metadata.get('hw_profile', {})
                self.state.mark_phase_complete('hw_analysis')

                duration = time.time() - start
                profile = self.state.hw_profile or {}

                return (
                    f'PHASE 2: Hardware Analysis — COMPLETE ({duration:.1f}s)\n'
                    f'  Product: {profile.get("product_name", "Unknown")}\n'
                    f'  Components: {len(profile.get("components", []))}\n'
                    f'  Bus interfaces: {len(profile.get("bus_interfaces", []))}\n'
                    f'  Existing firmware: {len(profile.get("existing_firmware", []))}\n'
                    f'  Existing drivers: {len(profile.get("existing_drivers", []))}\n'
                    f'  Existing tools: {len(profile.get("existing_tools", []))}\n'
                    f'  Knowledge gaps: {len(profile.get("gaps", []))}'
                )
            else:
                error = response.error or 'Unknown error'
                self.state.errors.append(f'HW analysis failed: {error}')
                return f'PHASE 2: Hardware Analysis — FAILED\n  Error: {error}'

        except Exception as e:
            self.state.errors.append(f'HW analysis exception: {e}')
            return f'PHASE 2: Hardware Analysis — ERROR\n  {e}'

    def _phase_scoping(self) -> str:
        '''Phase 3: Scope the SW/FW work.'''
        self.state.current_phase = 'scoping'
        start = time.time()

        try:
            response = self.scoping_agent.run({
                'feature_request': self.state.feature_request,
                'research_report': self.state.research_report or {},
                'hw_profile': self.state.hw_profile or {},
            })

            if response.success:
                self.state.feature_scope = response.metadata.get(
                    'feature_scope', {}
                )
                self.state.mark_phase_complete('scoping')

                # Accumulate questions
                scope = self.state.feature_scope or {}
                for q in scope.get('open_questions', []):
                    self.state.questions_for_user.append(q)

                duration = time.time() - start
                conf = scope.get('confidence_report', {})

                return (
                    f'PHASE 3: SW/FW Scoping — COMPLETE ({duration:.1f}s)\n'
                    f'  Total items: {conf.get("total_items", 0)}\n'
                    f'  By category: {conf.get("by_category", {})}\n'
                    f'  By confidence: {conf.get("by_confidence", {})}\n'
                    f'  By complexity: {conf.get("by_complexity", {})}\n'
                    f'  Open questions: {conf.get("total_questions", 0)} '
                    f'({conf.get("blocking_questions", 0)} blocking)'
                )
            else:
                error = response.error or 'Unknown error'
                self.state.errors.append(f'Scoping failed: {error}')
                return f'PHASE 3: SW/FW Scoping — FAILED\n  Error: {error}'

        except Exception as e:
            self.state.errors.append(f'Scoping exception: {e}')
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
