##########################################################################################
#
# Module: agents/planning_agent.py
#
# Description: Planning Agent for creating release structures.
#              Maps roadmap items to Jira ticket hierarchy.
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
from tools.file_tools import FileTools

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# Default instruction for the Planning agent
PLANNING_INSTRUCTION = '''You are a Release Planning Agent specialized in creating Jira release structures.

Your role is to:
1. Take roadmap information and current Jira state as input
2. Design a release structure with appropriate ticket hierarchy
3. Map features to Epics, Stories, and Tasks
4. Assign components and owners based on org chart
5. Set appropriate release versions

When creating a release plan, follow these principles:
- Epics represent major features or initiatives
- Stories represent user-facing functionality
- Tasks represent implementation work
- Use components to categorize by area (e.g., Firmware, Driver, Tools)
- Assign owners based on the org chart responsibilities

Output your plan in a structured format with:
- Release versions to create
- Epic tickets with summaries and descriptions
- Story tickets under each Epic
- Task tickets for implementation details
- Component and owner assignments

Be specific and actionable - the plan should be ready for human review and execution.
'''


@dataclass
class PlannedTicket:
    '''
    Represents a planned Jira ticket.
    '''
    key: Optional[str] = None  # Will be assigned after creation
    summary: str = ''
    description: str = ''
    issue_type: str = 'Story'
    parent_key: Optional[str] = None
    components: List[str] = field(default_factory=list)
    fix_versions: List[str] = field(default_factory=list)
    assignee: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    priority: str = 'Medium'
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key,
            'summary': self.summary,
            'description': self.description,
            'issue_type': self.issue_type,
            'parent_key': self.parent_key,
            'components': self.components,
            'fix_versions': self.fix_versions,
            'assignee': self.assignee,
            'labels': self.labels,
            'priority': self.priority
        }


@dataclass
class PlannedRelease:
    '''
    Represents a planned release version.
    '''
    name: str
    description: str = ''
    start_date: Optional[str] = None
    release_date: Optional[str] = None
    tickets: List[PlannedTicket] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'description': self.description,
            'start_date': self.start_date,
            'release_date': self.release_date,
            'tickets': [t.to_dict() for t in self.tickets]
        }


@dataclass
class ReleasePlan:
    '''
    Complete release plan with versions and tickets.
    '''
    project_key: str
    releases: List[PlannedRelease] = field(default_factory=list)
    summary: str = ''
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'project_key': self.project_key,
            'releases': [r.to_dict() for r in self.releases],
            'summary': self.summary,
            'total_releases': len(self.releases),
            'total_tickets': sum(len(r.tickets) for r in self.releases)
        }


class PlanningAgent(BaseAgent):
    '''
    Agent for creating release plans.
    
    Takes roadmap data and current Jira state to create a structured
    release plan with tickets, assignments, and versions.
    '''
    
    def __init__(self, **kwargs):
        '''
        Initialize the Planning agent.
        '''
        config = AgentConfig(
            name='planning_agent',
            description='Creates release structures from roadmap data',
            instruction=PLANNING_INSTRUCTION
        )
        
        # Initialize with file tools for reading templates
        file_tools = FileTools()
        
        super().__init__(config=config, tools=[file_tools], **kwargs)
        
        # Load ticket templates if available
        self.templates = self._load_templates()
    
    def _load_templates(self) -> Dict[str, Dict]:
        '''Load ticket templates from data/templates directory.'''
        templates = {}
        template_dir = 'data/templates'
        
        if os.path.exists(template_dir):
            for filename in os.listdir(template_dir):
                if filename.endswith('.json'):
                    try:
                        import json
                        with open(os.path.join(template_dir, filename)) as f:
                            template_name = filename.replace('.json', '')
                            templates[template_name] = json.load(f)
                    except Exception as e:
                        log.warning(f'Failed to load template {filename}: {e}')
        
        return templates
    
    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the planning agent.
        
        Input:
            input_data: Dictionary containing:
                - roadmap_data: Extracted roadmap information
                - jira_state: Current Jira project state
                - org_chart: Organization chart data
                - project_key: Target Jira project
        
        Output:
            AgentResponse with the release plan.
        '''
        log.debug(f'PlanningAgent.run()')
        
        if not isinstance(input_data, dict):
            return AgentResponse.error_response('Invalid input: expected dict with roadmap_data, jira_state, org_chart')
        
        roadmap_data = input_data.get('roadmap_data', {})
        jira_state = input_data.get('jira_state', {})
        org_chart = input_data.get('org_chart', {})
        project_key = input_data.get('project_key', '')
        
        if not project_key:
            return AgentResponse.error_response('No project_key provided')
        
        # Build the planning request
        user_input = f'''Create a release plan for project "{project_key}".

## Roadmap Data
{self._format_roadmap(roadmap_data)}

## Current Jira State
{self._format_jira_state(jira_state)}

## Organization Chart
{self._format_org_chart(org_chart)}

Please create a detailed release plan with:
1. Release versions to create
2. Epic tickets for major features
3. Story tickets under each Epic
4. Component and owner assignments based on the org chart
5. Appropriate labels and priorities

Output the plan in a structured format that can be reviewed and executed.'''
        
        return self._run_with_tools(user_input)
    
    def create_plan(
        self,
        project_key: str,
        roadmap_data: Dict[str, Any],
        jira_state: Dict[str, Any],
        org_chart: Dict[str, Any]
    ) -> ReleasePlan:
        '''
        Create a release plan programmatically.
        
        This is a deterministic planning method that doesn't require LLM calls.
        
        Input:
            project_key: Target Jira project.
            roadmap_data: Extracted roadmap information.
            jira_state: Current Jira project state.
            org_chart: Organization chart data.
        
        Output:
            ReleasePlan object with planned releases and tickets.
        '''
        log.debug(f'create_plan(project_key={project_key})')
        
        plan = ReleasePlan(project_key=project_key)
        
        # Extract releases from roadmap
        roadmap_releases = roadmap_data.get('releases', [])
        roadmap_features = roadmap_data.get('features', [])
        roadmap_timeline = roadmap_data.get('timeline', [])
        
        # Get existing releases to avoid duplicates
        existing_releases = set()
        for release in jira_state.get('releases', []):
            existing_releases.add(release.get('name', ''))
        
        # Get components for assignment
        components = {c['name']: c for c in jira_state.get('components', [])}
        
        # Get responsibilities from org chart
        responsibilities = org_chart.get('by_area', {})
        
        # Create releases from roadmap
        for roadmap_release in roadmap_releases:
            version = roadmap_release.get('version', '')
            if not version or version in existing_releases:
                continue
            
            # Find timeline for this release
            release_date = None
            for timeline_item in roadmap_timeline:
                if version in timeline_item.get('context', ''):
                    release_date = timeline_item.get('date')
                    break
            
            planned_release = PlannedRelease(
                name=version,
                description=f'Release {version}',
                release_date=release_date
            )
            
            # Create Epic for the release
            epic = PlannedTicket(
                summary=f'Release {version} Implementation',
                description=f'Epic for tracking all work in release {version}',
                issue_type='Epic',
                fix_versions=[version],
                labels=['release-tracking']
            )
            planned_release.tickets.append(epic)
            
            # Create Stories from features
            for feature in roadmap_features:
                feature_text = feature.get('text', '')
                if not feature_text:
                    continue
                
                # Determine component based on feature text
                component = self._match_component(feature_text, list(components.keys()))
                
                # Determine assignee based on component and org chart
                assignee = self._match_assignee(component, responsibilities)
                
                story = PlannedTicket(
                    summary=feature_text[:100],  # Truncate for summary
                    description=feature_text,
                    issue_type='Story',
                    parent_key=None,  # Will link to Epic after creation
                    components=[component] if component else [],
                    fix_versions=[version],
                    assignee=assignee
                )
                planned_release.tickets.append(story)
            
            plan.releases.append(planned_release)
        
        # Generate summary
        plan.summary = self._generate_summary(plan)
        
        return plan
    
    def _format_roadmap(self, roadmap_data: Dict) -> str:
        '''Format roadmap data for the prompt.'''
        lines = []
        
        releases = roadmap_data.get('releases', [])
        if releases:
            lines.append('Releases:')
            for r in releases[:10]:
                lines.append(f"  - {r.get('version', 'Unknown')}")
        
        features = roadmap_data.get('features', [])
        if features:
            lines.append('\nFeatures:')
            for f in features[:20]:
                lines.append(f"  - {f.get('text', '')[:100]}")
        
        timeline = roadmap_data.get('timeline', [])
        if timeline:
            lines.append('\nTimeline:')
            for t in timeline[:10]:
                lines.append(f"  - {t.get('date', '')}: {t.get('context', '')[:50]}")
        
        return '\n'.join(lines) if lines else 'No roadmap data available'
    
    def _format_jira_state(self, jira_state: Dict) -> str:
        '''Format Jira state for the prompt.'''
        lines = []
        
        project_info = jira_state.get('project_info', {})
        if project_info:
            lines.append(f"Project: {project_info.get('name', 'Unknown')}")
        
        releases = jira_state.get('releases', [])
        if releases:
            lines.append(f'\nExisting Releases ({len(releases)}):')
            for r in releases[:10]:
                status = 'Released' if r.get('released') else 'Unreleased'
                lines.append(f"  - {r.get('name', 'Unknown')} ({status})")
        
        components = jira_state.get('components', [])
        if components:
            lines.append(f'\nComponents ({len(components)}):')
            for c in components[:10]:
                lines.append(f"  - {c.get('name', 'Unknown')}")
        
        return '\n'.join(lines) if lines else 'No Jira state available'
    
    def _format_org_chart(self, org_chart: Dict) -> str:
        '''Format org chart for the prompt.'''
        lines = []
        
        by_area = org_chart.get('by_area', {})
        if by_area:
            lines.append('Responsibilities by Area:')
            for area, people in list(by_area.items())[:10]:
                names = [p.get('name', '') for p in people[:3]]
                lines.append(f"  - {area}: {', '.join(names)}")
        
        team_leads = org_chart.get('team_leads', [])
        if team_leads:
            lines.append('\nTeam Leads:')
            for lead in team_leads[:10]:
                lines.append(f"  - {lead.get('name', '')}: {lead.get('title', '')}")
        
        return '\n'.join(lines) if lines else 'No org chart available'
    
    def _match_component(self, text: str, components: List[str]) -> Optional[str]:
        '''Match text to a component based on keywords.'''
        text_lower = text.lower()
        
        for component in components:
            if component.lower() in text_lower:
                return component
        
        # Try keyword matching
        keyword_map = {
            'driver': ['driver', 'kernel', 'module'],
            'firmware': ['firmware', 'fw', 'embedded'],
            'tools': ['tool', 'utility', 'cli'],
            'documentation': ['doc', 'documentation', 'guide'],
            'testing': ['test', 'qa', 'validation'],
        }
        
        for component, keywords in keyword_map.items():
            if any(kw in text_lower for kw in keywords):
                # Find matching component
                for c in components:
                    if component.lower() in c.lower():
                        return c
        
        return None
    
    def _match_assignee(
        self,
        component: Optional[str],
        responsibilities: Dict[str, List]
    ) -> Optional[str]:
        '''Match component to an assignee based on responsibilities.'''
        if not component:
            return None
        
        # Look for area matching the component
        for area, people in responsibilities.items():
            if component.lower() in area.lower() or area.lower() in component.lower():
                # Return the first lead, or first person
                for person in people:
                    if person.get('is_lead'):
                        return person.get('name')
                if people:
                    return people[0].get('name')
        
        return None
    
    def _generate_summary(self, plan: ReleasePlan) -> str:
        '''Generate a summary of the release plan.'''
        total_releases = len(plan.releases)
        total_tickets = sum(len(r.tickets) for r in plan.releases)
        
        epic_count = sum(
            1 for r in plan.releases
            for t in r.tickets
            if t.issue_type == 'Epic'
        )
        story_count = sum(
            1 for r in plan.releases
            for t in r.tickets
            if t.issue_type == 'Story'
        )
        
        return (
            f'Release Plan Summary:\n'
            f'- {total_releases} releases to create\n'
            f'- {total_tickets} total tickets\n'
            f'- {epic_count} Epics\n'
            f'- {story_count} Stories'
        )
