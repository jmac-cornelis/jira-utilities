##########################################################################################
#
# Module: agents/jira_analyst.py
#
# Description: Jira Analyst Agent for analyzing current Jira state.
#              Examines existing releases, tickets, components, and workflows.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, AgentConfig, AgentResponse
from tools.jira_tools import JiraTools

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# Default instruction for the Jira Analyst agent
JIRA_ANALYST_INSTRUCTION = '''You are a Jira Analyst Agent specialized in analyzing Jira project state.

Your role is to:
1. Examine the current state of a Jira project
2. Identify existing releases and their tickets
3. Understand the component structure
4. Map team assignments and ownership
5. Analyze workflow states and transitions

When analyzing a project, you should:
- List all current and upcoming releases
- Identify the ticket hierarchy (Epics -> Stories -> Tasks)
- Note which components exist and who leads them
- Understand the workflow states available
- Identify any patterns in ticket organization

Always provide structured, actionable insights that can be used for release planning.

Output your analysis in a clear, structured format with sections for:
- Release Overview
- Component Structure
- Team Assignments
- Workflow States
- Recommendations
'''


class JiraAnalystAgent(BaseAgent):
    '''
    Agent for analyzing Jira project state.
    
    This agent examines the current state of a Jira project to understand:
    - Existing releases and their tickets
    - Component structure
    - Team assignments
    - Workflow configurations
    '''
    
    def __init__(
        self,
        project_key: Optional[str] = None,
        **kwargs
    ):
        '''
        Initialize the Jira Analyst agent.
        
        Input:
            project_key: Default Jira project key to analyze.
            **kwargs: Additional arguments passed to BaseAgent.
        '''
        config = AgentConfig(
            name='jira_analyst',
            description='Analyzes Jira project state for release planning',
            instruction=JIRA_ANALYST_INSTRUCTION
        )
        
        # Initialize with Jira tools
        jira_tools = JiraTools()
        
        super().__init__(config=config, tools=[jira_tools], **kwargs)
        
        self.project_key = project_key
    
    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the Jira analysis.
        
        Input:
            input_data: Either a string (project key) or dict with analysis parameters.
        
        Output:
            AgentResponse with Jira analysis results.
        '''
        log.debug(f'JiraAnalystAgent.run(input_data={input_data})')
        
        # Parse input
        if isinstance(input_data, str):
            project_key = input_data
            analysis_scope = 'full'
        elif isinstance(input_data, dict):
            project_key = input_data.get('project_key', self.project_key)
            analysis_scope = input_data.get('scope', 'full')
        else:
            return AgentResponse.error_response('Invalid input: expected project key or dict')
        
        if not project_key:
            return AgentResponse.error_response('No project key provided')
        
        # Build the analysis request
        user_input = f'''Analyze the Jira project "{project_key}" with scope: {analysis_scope}.

Please:
1. Get project information
2. List all releases/versions
3. Get the component structure
4. Identify issue types and workflows
5. Provide a summary of the current state

Focus on information relevant for release planning.'''
        
        return self._run_with_tools(user_input)
    
    def analyze_project(self, project_key: str) -> Dict[str, Any]:
        '''
        Perform a direct analysis of a Jira project without LLM.
        
        This is a faster, deterministic analysis that doesn't require LLM calls.
        
        Input:
            project_key: The Jira project key.
        
        Output:
            Dictionary with analysis results.
        '''
        log.debug(f'analyze_project(project_key={project_key})')
        
        from tools.jira_tools import (
            get_project_info,
            get_releases,
            get_components,
            get_project_workflows,
            get_project_issue_types
        )
        
        analysis = {
            'project_key': project_key,
            'project_info': None,
            'releases': [],
            'components': [],
            'workflows': [],
            'issue_types': [],
            'errors': []
        }
        
        # Get project info
        result = get_project_info(project_key)
        if result.is_success:
            analysis['project_info'] = result.data
        else:
            analysis['errors'].append(f'Project info: {result.error}')
        
        # Get releases
        result = get_releases(project_key)
        if result.is_success:
            analysis['releases'] = result.data
        else:
            analysis['errors'].append(f'Releases: {result.error}')
        
        # Get components
        result = get_components(project_key)
        if result.is_success:
            analysis['components'] = result.data
        else:
            analysis['errors'].append(f'Components: {result.error}')
        
        # Get workflows
        result = get_project_workflows(project_key)
        if result.is_success:
            analysis['workflows'] = result.data
        else:
            analysis['errors'].append(f'Workflows: {result.error}')
        
        # Get issue types
        result = get_project_issue_types(project_key)
        if result.is_success:
            analysis['issue_types'] = result.data
        else:
            analysis['errors'].append(f'Issue types: {result.error}')
        
        # Add summary statistics
        analysis['summary'] = {
            'total_releases': len(analysis['releases']),
            'unreleased_count': len([r for r in analysis['releases'] if not r.get('released')]),
            'component_count': len(analysis['components']),
            'issue_type_count': len(analysis['issue_types']),
            'has_errors': len(analysis['errors']) > 0
        }
        
        return analysis
    
    def get_release_structure(
        self,
        project_key: str,
        release_pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        '''
        Get the structure of releases and their tickets.
        
        Input:
            project_key: The Jira project key.
            release_pattern: Optional regex pattern to filter releases.
        
        Output:
            Dictionary with release structure.
        '''
        log.debug(f'get_release_structure(project_key={project_key})')
        
        from tools.jira_tools import get_releases, get_release_tickets
        
        structure = {
            'project_key': project_key,
            'releases': []
        }
        
        # Get releases
        result = get_releases(project_key, pattern=release_pattern, include_released=False)
        if result.is_error:
            return {'error': result.error}
        
        releases = result.data
        
        # Get tickets for each release
        for release in releases:
            release_name = release['name']
            
            tickets_result = get_release_tickets(project_key, release_name, limit=200)
            
            release_data = {
                'name': release_name,
                'id': release['id'],
                'release_date': release.get('releaseDate'),
                'tickets': [],
                'ticket_count': 0,
                'by_type': {},
                'by_status': {}
            }
            
            if tickets_result.is_success:
                tickets = tickets_result.data
                release_data['tickets'] = tickets
                release_data['ticket_count'] = len(tickets)
                
                # Group by type
                for ticket in tickets:
                    ticket_type = ticket.get('type', 'Unknown')
                    if ticket_type not in release_data['by_type']:
                        release_data['by_type'][ticket_type] = []
                    release_data['by_type'][ticket_type].append(ticket['key'])
                    
                    # Group by status
                    status = ticket.get('status', 'Unknown')
                    if status not in release_data['by_status']:
                        release_data['by_status'][status] = []
                    release_data['by_status'][status].append(ticket['key'])
            
            structure['releases'].append(release_data)
        
        return structure
