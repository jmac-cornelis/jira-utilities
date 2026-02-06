##########################################################################################
#
# Module: agents/review_agent.py
#
# Description: Review Agent for human-in-the-loop approval workflow.
#              Presents plans for review and executes approved changes.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from agents.base import BaseAgent, AgentConfig, AgentResponse
from tools.jira_tools import JiraTools

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


class ApprovalStatus(Enum):
    '''Status of an item in the approval workflow.'''
    PENDING = 'pending'
    APPROVED = 'approved'
    MODIFIED = 'modified'
    REJECTED = 'rejected'
    EXECUTED = 'executed'
    FAILED = 'failed'


@dataclass
class ReviewItem:
    '''
    An item pending review in the approval workflow.
    '''
    id: str
    item_type: str  # 'release', 'ticket', 'link'
    action: str  # 'create', 'update', 'delete'
    data: Dict[str, Any]
    status: ApprovalStatus = ApprovalStatus.PENDING
    modified_data: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'item_type': self.item_type,
            'action': self.action,
            'data': self.data,
            'status': self.status.value,
            'modified_data': self.modified_data,
            'result': self.result,
            'error': self.error
        }
    
    def get_effective_data(self) -> Dict[str, Any]:
        '''Get the data to use (modified if available, otherwise original).'''
        return self.modified_data if self.modified_data else self.data


@dataclass
class ReviewSession:
    '''
    A review session containing items for approval.
    '''
    session_id: str
    items: List[ReviewItem] = field(default_factory=list)
    created_at: str = ''
    
    def add_item(self, item: ReviewItem) -> None:
        self.items.append(item)
    
    def get_pending(self) -> List[ReviewItem]:
        return [i for i in self.items if i.status == ApprovalStatus.PENDING]
    
    def get_approved(self) -> List[ReviewItem]:
        return [i for i in self.items if i.status == ApprovalStatus.APPROVED]
    
    def get_by_status(self, status: ApprovalStatus) -> List[ReviewItem]:
        return [i for i in self.items if i.status == status]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'session_id': self.session_id,
            'items': [i.to_dict() for i in self.items],
            'created_at': self.created_at,
            'summary': {
                'total': len(self.items),
                'pending': len(self.get_pending()),
                'approved': len(self.get_approved()),
                'rejected': len(self.get_by_status(ApprovalStatus.REJECTED)),
                'executed': len(self.get_by_status(ApprovalStatus.EXECUTED))
            }
        }


# Default instruction for the Review agent
REVIEW_INSTRUCTION = '''You are a Review Agent that facilitates human approval of release plans.

Your role is to:
1. Present planned changes clearly for human review
2. Explain what each change will do
3. Handle modifications requested by the user
4. Execute approved changes in Jira
5. Report results of executed changes

When presenting items for review:
- Show the item type (release, ticket, link)
- Show the action (create, update)
- Show all relevant details
- Highlight any potential issues or concerns

When executing changes:
- Only execute approved items
- Execute in the correct order (releases before tickets, epics before stories)
- Report success or failure for each item
- Stop and report if critical errors occur

Always be clear about what will happen and get explicit approval before making changes.
'''


class ReviewAgent(BaseAgent):
    '''
    Agent for human-in-the-loop review and approval.
    
    Manages the workflow of presenting plans for review,
    handling modifications, and executing approved changes.
    '''
    
    def __init__(
        self,
        approval_callback: Optional[Callable[[ReviewItem], ApprovalStatus]] = None,
        **kwargs
    ):
        '''
        Initialize the Review agent.
        
        Input:
            approval_callback: Optional callback function for getting approval.
                              If not provided, uses interactive console prompts.
            **kwargs: Additional arguments passed to BaseAgent.
        '''
        config = AgentConfig(
            name='review_agent',
            description='Facilitates human review and approval of release plans',
            instruction=REVIEW_INSTRUCTION
        )
        
        # Initialize with Jira tools for execution
        jira_tools = JiraTools()
        
        super().__init__(config=config, tools=[jira_tools], **kwargs)
        
        self.approval_callback = approval_callback
        self.current_session: Optional[ReviewSession] = None
    
    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the review workflow.
        
        Input:
            input_data: Dictionary containing:
                - plan: The release plan to review
                - mode: 'review', 'execute', or 'full' (default)
        
        Output:
            AgentResponse with review/execution results.
        '''
        log.debug(f'ReviewAgent.run()')
        
        if not isinstance(input_data, dict):
            return AgentResponse.error_response('Invalid input: expected dict with plan')
        
        plan = input_data.get('plan', {})
        mode = input_data.get('mode', 'full')
        
        if not plan:
            return AgentResponse.error_response('No plan provided')
        
        # Create review session from plan
        session = self.create_session_from_plan(plan)
        self.current_session = session
        
        if mode == 'review':
            # Just present for review, don't execute
            return AgentResponse.success_response(
                content=self._format_session_for_review(session),
                metadata={'session': session.to_dict()}
            )
        elif mode == 'execute':
            # Execute all approved items
            results = self.execute_approved(session)
            return AgentResponse.success_response(
                content=self._format_execution_results(results),
                metadata={'session': session.to_dict(), 'results': results}
            )
        else:
            # Full workflow: review then execute
            user_input = f'''Present the following release plan for review:

{self._format_session_for_review(session)}

Guide the user through reviewing each item and get their approval or modifications.
Then execute the approved items.'''
            
            return self._run_with_tools(user_input)
    
    def create_session_from_plan(self, plan: Dict[str, Any]) -> ReviewSession:
        '''
        Create a review session from a release plan.
        
        Input:
            plan: Release plan dictionary.
        
        Output:
            ReviewSession with items to review.
        '''
        import uuid
        from datetime import datetime
        
        session = ReviewSession(
            session_id=str(uuid.uuid4())[:8],
            created_at=datetime.now().isoformat()
        )
        
        item_id = 1
        
        # Add releases
        for release in plan.get('releases', []):
            session.add_item(ReviewItem(
                id=f'R{item_id}',
                item_type='release',
                action='create',
                data={
                    'name': release.get('name'),
                    'description': release.get('description', ''),
                    'release_date': release.get('release_date'),
                    'project_key': plan.get('project_key')
                }
            ))
            item_id += 1
            
            # Add tickets for this release
            for ticket in release.get('tickets', []):
                session.add_item(ReviewItem(
                    id=f'T{item_id}',
                    item_type='ticket',
                    action='create',
                    data={
                        'summary': ticket.get('summary'),
                        'description': ticket.get('description', ''),
                        'issue_type': ticket.get('issue_type', 'Story'),
                        'components': ticket.get('components', []),
                        'fix_versions': ticket.get('fix_versions', []),
                        'assignee': ticket.get('assignee'),
                        'labels': ticket.get('labels', []),
                        'project_key': plan.get('project_key')
                    }
                ))
                item_id += 1
        
        return session
    
    def review_item(self, item: ReviewItem) -> ApprovalStatus:
        '''
        Get approval for a single item.
        
        Input:
            item: The item to review.
        
        Output:
            ApprovalStatus indicating the decision.
        '''
        if self.approval_callback:
            return self.approval_callback(item)
        
        # Default: interactive console approval
        return self._interactive_approval(item)
    
    def review_all(self, session: ReviewSession) -> None:
        '''
        Review all pending items in a session.
        
        Input:
            session: The review session.
        '''
        for item in session.get_pending():
            status = self.review_item(item)
            item.status = status
    
    def approve_item(self, session: ReviewSession, item_id: str) -> bool:
        '''
        Approve a specific item.
        
        Input:
            session: The review session.
            item_id: ID of the item to approve.
        
        Output:
            True if item was found and approved.
        '''
        for item in session.items:
            if item.id == item_id:
                item.status = ApprovalStatus.APPROVED
                return True
        return False
    
    def reject_item(self, session: ReviewSession, item_id: str) -> bool:
        '''
        Reject a specific item.
        
        Input:
            session: The review session.
            item_id: ID of the item to reject.
        
        Output:
            True if item was found and rejected.
        '''
        for item in session.items:
            if item.id == item_id:
                item.status = ApprovalStatus.REJECTED
                return True
        return False
    
    def modify_item(
        self,
        session: ReviewSession,
        item_id: str,
        modifications: Dict[str, Any]
    ) -> bool:
        '''
        Modify a specific item.
        
        Input:
            session: The review session.
            item_id: ID of the item to modify.
            modifications: Dictionary of field modifications.
        
        Output:
            True if item was found and modified.
        '''
        for item in session.items:
            if item.id == item_id:
                # Merge modifications with original data
                item.modified_data = {**item.data, **modifications}
                item.status = ApprovalStatus.MODIFIED
                return True
        return False
    
    def approve_all(self, session: ReviewSession) -> int:
        '''
        Approve all pending items.
        
        Input:
            session: The review session.
        
        Output:
            Number of items approved.
        '''
        count = 0
        for item in session.get_pending():
            item.status = ApprovalStatus.APPROVED
            count += 1
        return count
    
    def execute_approved(self, session: ReviewSession) -> List[Dict[str, Any]]:
        '''
        Execute all approved items.
        
        Input:
            session: The review session.
        
        Output:
            List of execution results.
        '''
        results = []
        
        # Get approved and modified items
        to_execute = [
            i for i in session.items
            if i.status in (ApprovalStatus.APPROVED, ApprovalStatus.MODIFIED)
        ]
        
        # Sort: releases first, then epics, then other tickets
        def sort_key(item):
            if item.item_type == 'release':
                return (0, item.id)
            elif item.data.get('issue_type') == 'Epic':
                return (1, item.id)
            else:
                return (2, item.id)
        
        to_execute.sort(key=sort_key)
        
        # Track created items for linking
        created_releases = {}
        created_tickets = {}
        
        for item in to_execute:
            result = self._execute_item(item, created_releases, created_tickets)
            results.append(result)
            
            if result.get('success'):
                item.status = ApprovalStatus.EXECUTED
                item.result = result
                
                # Track created items
                if item.item_type == 'release':
                    created_releases[item.data['name']] = result.get('data', {})
                elif item.item_type == 'ticket':
                    created_tickets[item.id] = result.get('data', {})
            else:
                item.status = ApprovalStatus.FAILED
                item.error = result.get('error')
        
        return results
    
    def _execute_item(
        self,
        item: ReviewItem,
        created_releases: Dict,
        created_tickets: Dict
    ) -> Dict[str, Any]:
        '''Execute a single item.'''
        from tools.jira_tools import create_release, create_ticket
        
        data = item.get_effective_data()
        
        try:
            if item.item_type == 'release' and item.action == 'create':
                result = create_release(
                    project_key=data['project_key'],
                    name=data['name'],
                    description=data.get('description'),
                    release_date=data.get('release_date')
                )
                
                if result.is_success:
                    return {'success': True, 'data': result.data, 'item_id': item.id}
                else:
                    return {'success': False, 'error': result.error, 'item_id': item.id}
                    
            elif item.item_type == 'ticket' and item.action == 'create':
                result = create_ticket(
                    project_key=data['project_key'],
                    summary=data['summary'],
                    issue_type=data.get('issue_type', 'Story'),
                    description=data.get('description'),
                    assignee=data.get('assignee'),
                    components=data.get('components'),
                    fix_versions=data.get('fix_versions'),
                    labels=data.get('labels')
                )
                
                if result.is_success:
                    return {'success': True, 'data': result.data, 'item_id': item.id}
                else:
                    return {'success': False, 'error': result.error, 'item_id': item.id}
            
            else:
                return {
                    'success': False,
                    'error': f'Unknown item type/action: {item.item_type}/{item.action}',
                    'item_id': item.id
                }
                
        except Exception as e:
            log.error(f'Execution failed for {item.id}: {e}')
            return {'success': False, 'error': str(e), 'item_id': item.id}
    
    def _interactive_approval(self, item: ReviewItem) -> ApprovalStatus:
        '''Get approval interactively from console.'''
        print('\n' + '=' * 60)
        print(f'Review Item: {item.id}')
        print(f'Type: {item.item_type}')
        print(f'Action: {item.action}')
        print('-' * 60)
        
        for key, value in item.data.items():
            print(f'  {key}: {value}')
        
        print('-' * 60)
        print('Options: [a]pprove, [r]eject, [m]odify, [s]kip')
        
        while True:
            choice = input('Your choice: ').strip().lower()
            
            if choice in ('a', 'approve'):
                return ApprovalStatus.APPROVED
            elif choice in ('r', 'reject'):
                return ApprovalStatus.REJECTED
            elif choice in ('m', 'modify'):
                # Simple modification - just update summary for now
                new_summary = input('New summary (or Enter to keep): ').strip()
                if new_summary:
                    item.modified_data = {**item.data, 'summary': new_summary}
                return ApprovalStatus.MODIFIED
            elif choice in ('s', 'skip'):
                return ApprovalStatus.PENDING
            else:
                print('Invalid choice. Please enter a, r, m, or s.')
    
    def _format_session_for_review(self, session: ReviewSession) -> str:
        '''Format a session for display.'''
        lines = [
            f'Review Session: {session.session_id}',
            f'Created: {session.created_at}',
            f'Total Items: {len(session.items)}',
            '',
            '=' * 60,
        ]
        
        # Group by type
        releases = [i for i in session.items if i.item_type == 'release']
        tickets = [i for i in session.items if i.item_type == 'ticket']
        
        if releases:
            lines.append('\nRELEASES TO CREATE:')
            lines.append('-' * 40)
            for item in releases:
                lines.append(f"  [{item.id}] {item.data.get('name')}")
                if item.data.get('release_date'):
                    lines.append(f"       Date: {item.data['release_date']}")
        
        if tickets:
            lines.append('\nTICKETS TO CREATE:')
            lines.append('-' * 40)
            for item in tickets:
                issue_type = item.data.get('issue_type', 'Story')
                lines.append(f"  [{item.id}] [{issue_type}] {item.data.get('summary', '')[:50]}")
                if item.data.get('components'):
                    lines.append(f"       Components: {', '.join(item.data['components'])}")
                if item.data.get('assignee'):
                    lines.append(f"       Assignee: {item.data['assignee']}")
        
        lines.append('')
        lines.append('=' * 60)
        
        return '\n'.join(lines)
    
    def _format_execution_results(self, results: List[Dict]) -> str:
        '''Format execution results for display.'''
        lines = [
            'EXECUTION RESULTS',
            '=' * 60,
        ]
        
        success_count = sum(1 for r in results if r.get('success'))
        fail_count = len(results) - success_count
        
        lines.append(f'Successful: {success_count}')
        lines.append(f'Failed: {fail_count}')
        lines.append('')
        
        for result in results:
            item_id = result.get('item_id', 'Unknown')
            if result.get('success'):
                data = result.get('data', {})
                key = data.get('key') or data.get('name', 'Created')
                lines.append(f'  ✓ [{item_id}] {key}')
            else:
                error = result.get('error', 'Unknown error')
                lines.append(f'  ✗ [{item_id}] {error}')
        
        return '\n'.join(lines)
