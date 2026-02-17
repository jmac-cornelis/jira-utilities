##########################################################################################
#
# Module: agents/orchestrator.py
#
# Description: Release Planning Orchestrator Agent.
#              Coordinates the end-to-end release planning workflow.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from agents.base import BaseAgent, AgentConfig, AgentResponse
from agents.jira_analyst import JiraAnalystAgent
from agents.planning_agent import PlanningAgent
from agents.vision_analyzer import VisionAnalyzerAgent
from agents.review_agent import ReviewAgent

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# Default instruction for the Orchestrator
ORCHESTRATOR_INSTRUCTION = '''You are the Release Planning Orchestrator for Cornelis Networks.

Your role is to coordinate the end-to-end release planning workflow:

1. **Input Analysis**: Gather and analyze all input sources
   - Roadmap slides/images (via Vision Analyzer)
   - Current Jira state (via Jira Analyst)
   - Organization chart (via Draw.io tools)

2. **Planning**: Create a release structure
   - Map roadmap items to Jira tickets
   - Assign components and owners
   - Set release versions

3. **Review**: Present plan for human approval
   - Show all planned changes
   - Allow modifications
   - Get explicit approval

4. **Execution**: Create approved items in Jira
   - Create releases
   - Create tickets
   - Link tickets appropriately

Always:
- Explain what you're doing at each step
- Wait for human approval before making changes
- Report results clearly
- Handle errors gracefully

You have access to specialized sub-agents:
- Vision Analyzer: For analyzing roadmap images/slides
- Jira Analyst: For analyzing current Jira state
- Planning Agent: For creating release plans
- Review Agent: For human approval workflow
'''


@dataclass
class WorkflowState:
    '''
    State of the release planning workflow.
    '''
    # Input data
    roadmap_files: List[str] = field(default_factory=list)
    org_chart_file: Optional[str] = None
    project_key: Optional[str] = None
    
    # Extracted data
    roadmap_data: Dict[str, Any] = field(default_factory=dict)
    org_chart_data: Dict[str, Any] = field(default_factory=dict)
    jira_state: Dict[str, Any] = field(default_factory=dict)
    
    # Plan
    release_plan: Dict[str, Any] = field(default_factory=dict)
    
    # Execution
    execution_results: List[Dict[str, Any]] = field(default_factory=list)
    
    # Status
    current_step: str = 'init'
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'roadmap_files': self.roadmap_files,
            'org_chart_file': self.org_chart_file,
            'project_key': self.project_key,
            'roadmap_data': self.roadmap_data,
            'org_chart_data': self.org_chart_data,
            'jira_state': self.jira_state,
            'release_plan': self.release_plan,
            'execution_results': self.execution_results,
            'current_step': self.current_step,
            'errors': self.errors
        }


class ReleasePlanningOrchestrator(BaseAgent):
    '''
    Orchestrator agent for release planning workflow.
    
    Coordinates Vision Analyzer, Jira Analyst, Planning Agent,
    and Review Agent to create and execute release plans.
    '''
    
    def __init__(self, **kwargs):
        '''
        Initialize the orchestrator.
        '''
        config = AgentConfig(
            name='release_planning_orchestrator',
            description='Coordinates end-to-end release planning workflow',
            instruction=ORCHESTRATOR_INSTRUCTION,
            max_iterations=50  # Higher limit for complex workflows
        )
        
        super().__init__(config=config, **kwargs)
        
        # Initialize sub-agents
        self.vision_analyzer = VisionAnalyzerAgent()
        self.jira_analyst = JiraAnalystAgent()
        self.planning_agent = PlanningAgent()
        self.review_agent = ReviewAgent()
        
        # Workflow state
        self.state = WorkflowState()
    
    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the release planning workflow.
        
        Input:
            input_data: Dictionary containing:
                - project_key: Target Jira project
                - roadmap_files: List of roadmap file paths
                - org_chart_file: Optional org chart file path
                - mode: 'full', 'analyze', 'plan', or 'execute'
        
        Output:
            AgentResponse with workflow results.
        '''
        log.debug(f'ReleasePlanningOrchestrator.run()')
        
        if not isinstance(input_data, dict):
            return AgentResponse.error_response(
                'Invalid input: expected dict with project_key and roadmap_files'
            )
        
        # Initialize state from input
        self.state = WorkflowState(
            project_key=input_data.get('project_key'),
            roadmap_files=input_data.get('roadmap_files', []),
            org_chart_file=input_data.get('org_chart_file')
        )
        
        mode = input_data.get('mode', 'full')
        
        if not self.state.project_key:
            return AgentResponse.error_response('No project_key provided')
        
        try:
            if mode == 'analyze':
                return self._run_analysis()
            elif mode == 'plan':
                return self._run_planning()
            elif mode == 'execute':
                return self._run_execution()
            else:
                return self._run_full_workflow()
                
        except Exception as e:
            log.error(f'Orchestrator error: {e}')
            return AgentResponse.error_response(str(e))
    
    def _run_analysis(self) -> AgentResponse:
        '''Run only the analysis phase.'''
        self.state.current_step = 'analysis'
        
        # Analyze roadmap files
        if self.state.roadmap_files:
            self.state.roadmap_data = self.vision_analyzer.analyze_multiple(
                self.state.roadmap_files
            )
        
        # Analyze org chart
        if self.state.org_chart_file:
            from tools.drawio_tools import get_responsibilities
            result = get_responsibilities(self.state.org_chart_file)
            if result.is_success:
                self.state.org_chart_data = result.data
            else:
                self.state.errors.append(f'Org chart: {result.error}')
        
        # Analyze Jira state
        self.state.jira_state = self.jira_analyst.analyze_project(
            self.state.project_key
        )
        
        return AgentResponse.success_response(
            content=self._format_analysis_results(),
            metadata={'state': self.state.to_dict()}
        )
    
    def _run_planning(self) -> AgentResponse:
        '''Run only the planning phase.'''
        self.state.current_step = 'planning'
        
        # Ensure we have analysis data
        if not self.state.jira_state:
            analysis_result = self._run_analysis()
            if not analysis_result.success:
                return analysis_result
        
        # Create release plan
        plan = self.planning_agent.create_plan(
            project_key=self.state.project_key,
            roadmap_data=self.state.roadmap_data,
            jira_state=self.state.jira_state,
            org_chart=self.state.org_chart_data
        )
        
        self.state.release_plan = plan.to_dict()
        
        return AgentResponse.success_response(
            content=self._format_plan(),
            metadata={'state': self.state.to_dict()}
        )
    
    def _run_execution(self) -> AgentResponse:
        '''Run only the execution phase.'''
        self.state.current_step = 'execution'
        
        if not self.state.release_plan:
            return AgentResponse.error_response('No release plan to execute')
        
        # Create review session and execute
        response = self.review_agent.run({
            'plan': self.state.release_plan,
            'mode': 'execute'
        })
        
        if response.success:
            self.state.execution_results = response.metadata.get('results', [])
        
        return response
    
    def _run_full_workflow(self) -> AgentResponse:
        '''Run the complete workflow with human review.'''
        results = []
        
        # Step 1: Analysis
        log.info('Step 1: Analyzing inputs...')
        analysis_result = self._run_analysis()
        results.append(('analysis', analysis_result))
        
        if not analysis_result.success:
            return AgentResponse.error_response(
                f'Analysis failed: {analysis_result.error}'
            )
        
        # Step 2: Planning
        log.info('Step 2: Creating release plan...')
        planning_result = self._run_planning()
        results.append(('planning', planning_result))
        
        if not planning_result.success:
            return AgentResponse.error_response(
                f'Planning failed: {planning_result.error}'
            )
        
        # Step 3: Review (present plan)
        log.info('Step 3: Presenting plan for review...')
        review_result = self.review_agent.run({
            'plan': self.state.release_plan,
            'mode': 'review'
        })
        results.append(('review', review_result))
        
        # Return the plan for human review
        # Execution will be triggered separately after approval
        return AgentResponse.success_response(
            content=self._format_full_workflow_results(results),
            metadata={
                'state': self.state.to_dict(),
                'ready_for_execution': True
            }
        )
    
    def execute_approved_plan(self) -> AgentResponse:
        '''
        Execute the approved plan.
        
        Call this after human review and approval.
        '''
        return self._run_execution()
    
    def _format_analysis_results(self) -> str:
        '''Format analysis results for display.'''
        lines = [
            '=' * 60,
            'ANALYSIS RESULTS',
            '=' * 60,
            ''
        ]
        
        # Roadmap data
        lines.append('ROADMAP DATA:')
        lines.append('-' * 40)
        rd = self.state.roadmap_data
        lines.append(f"  Files analyzed: {len(rd.get('files_analyzed', []))}")
        lines.append(f"  Releases found: {len(rd.get('releases', []))}")
        lines.append(f"  Features found: {len(rd.get('features', []))}")
        lines.append(f"  Timeline items: {len(rd.get('timeline', []))}")
        
        if rd.get('releases'):
            lines.append('\n  Releases:')
            for r in rd['releases'][:5]:
                lines.append(f"    - {r.get('version', 'Unknown')}")
        
        # Jira state
        lines.append('\nJIRA STATE:')
        lines.append('-' * 40)
        js = self.state.jira_state
        summary = js.get('summary', {})
        lines.append(f"  Existing releases: {summary.get('total_releases', 0)}")
        lines.append(f"  Unreleased: {summary.get('unreleased_count', 0)}")
        lines.append(f"  Components: {summary.get('component_count', 0)}")
        
        # Org chart
        if self.state.org_chart_data:
            lines.append('\nORG CHART:')
            lines.append('-' * 40)
            oc = self.state.org_chart_data
            lines.append(f"  Areas: {len(oc.get('by_area', {}))}")
            lines.append(f"  Team leads: {len(oc.get('team_leads', []))}")
        
        # Errors
        if self.state.errors:
            lines.append('\nERRORS:')
            lines.append('-' * 40)
            for error in self.state.errors:
                lines.append(f"  ! {error}")
        
        lines.append('')
        lines.append('=' * 60)
        
        return '\n'.join(lines)
    
    def _format_plan(self) -> str:
        '''Format the release plan for display.'''
        lines = [
            '=' * 60,
            'RELEASE PLAN',
            '=' * 60,
            ''
        ]
        
        plan = self.state.release_plan
        
        lines.append(f"Project: {plan.get('project_key')}")
        lines.append(f"Total releases: {plan.get('total_releases', 0)}")
        lines.append(f"Total tickets: {plan.get('total_tickets', 0)}")
        lines.append('')
        
        for release in plan.get('releases', []):
            lines.append(f"\nRELEASE: {release.get('name')}")
            lines.append('-' * 40)
            
            if release.get('release_date'):
                lines.append(f"  Date: {release['release_date']}")
            
            lines.append(f"  Tickets: {len(release.get('tickets', []))}")
            
            for ticket in release.get('tickets', [])[:10]:
                issue_type = ticket.get('issue_type', 'Story')
                summary = ticket.get('summary', '')[:50]
                lines.append(f"    [{issue_type}] {summary}")
            
            if len(release.get('tickets', [])) > 10:
                lines.append(f"    ... and {len(release['tickets']) - 10} more")
        
        lines.append('')
        lines.append('=' * 60)
        
        if plan.get('summary'):
            lines.append('')
            lines.append(plan['summary'])
        
        return '\n'.join(lines)
    
    def _format_full_workflow_results(
        self,
        results: List[tuple]
    ) -> str:
        '''Format full workflow results.'''
        lines = [
            '=' * 60,
            'RELEASE PLANNING WORKFLOW COMPLETE',
            '=' * 60,
            ''
        ]
        
        for step_name, result in results:
            status = '✓' if result.success else '✗'
            lines.append(f'{status} {step_name.upper()}')
        
        lines.append('')
        lines.append('-' * 60)
        lines.append('')
        lines.append('The release plan is ready for review.')
        lines.append('Please review the plan above and approve items for execution.')
        lines.append('')
        lines.append('To execute approved items, call execute_approved_plan()')
        lines.append('')
        lines.append('=' * 60)
        
        return '\n'.join(lines)
