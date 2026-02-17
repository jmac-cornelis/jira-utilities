##########################################################################################
#
# Module: state/session.py
#
# Description: Session state management for agent workflows.
#              Tracks workflow progress and enables resumption.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


@dataclass
class SessionState:
    '''
    State of an agent workflow session.
    
    Tracks all data and progress through a release planning workflow,
    enabling persistence and resumption.
    '''
    # Session identification
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Workflow configuration
    project_key: Optional[str] = None
    workflow_type: str = 'release_planning'
    
    # Input data
    roadmap_files: List[str] = field(default_factory=list)
    org_chart_file: Optional[str] = None
    additional_inputs: Dict[str, Any] = field(default_factory=dict)
    
    # Extracted/analyzed data
    roadmap_data: Dict[str, Any] = field(default_factory=dict)
    org_chart_data: Dict[str, Any] = field(default_factory=dict)
    jira_state: Dict[str, Any] = field(default_factory=dict)
    
    # Planning data
    release_plan: Dict[str, Any] = field(default_factory=dict)
    
    # Review/approval state
    review_session_id: Optional[str] = None
    approved_items: List[str] = field(default_factory=list)
    rejected_items: List[str] = field(default_factory=list)
    modified_items: Dict[str, Dict] = field(default_factory=dict)
    
    # Execution state
    executed_items: List[str] = field(default_factory=list)
    created_releases: List[Dict] = field(default_factory=list)
    created_tickets: List[Dict] = field(default_factory=list)
    execution_errors: List[Dict] = field(default_factory=list)
    
    # Workflow progress
    current_step: str = 'init'
    completed_steps: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    # Conversation history (for LLM context)
    conversation_history: List[Dict] = field(default_factory=list)
    
    def update_timestamp(self) -> None:
        '''Update the updated_at timestamp.'''
        self.updated_at = datetime.now().isoformat()
    
    def mark_step_complete(self, step: str) -> None:
        '''Mark a workflow step as complete.'''
        if step not in self.completed_steps:
            self.completed_steps.append(step)
        self.update_timestamp()
    
    def set_current_step(self, step: str) -> None:
        '''Set the current workflow step.'''
        self.current_step = step
        self.update_timestamp()
    
    def add_error(self, error: str) -> None:
        '''Add an error to the session.'''
        self.errors.append(error)
        self.update_timestamp()
    
    def add_conversation(self, role: str, content: str) -> None:
        '''Add a message to conversation history.'''
        self.conversation_history.append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        })
        self.update_timestamp()
    
    def to_dict(self) -> Dict[str, Any]:
        '''Convert session state to dictionary.'''
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionState':
        '''Create session state from dictionary.'''
        return cls(**data)
    
    def get_summary(self) -> Dict[str, Any]:
        '''Get a summary of the session state.'''
        return {
            'session_id': self.session_id,
            'project_key': self.project_key,
            'current_step': self.current_step,
            'completed_steps': self.completed_steps,
            'releases_planned': len(self.release_plan.get('releases', [])),
            'tickets_planned': self.release_plan.get('total_tickets', 0),
            'items_approved': len(self.approved_items),
            'items_executed': len(self.executed_items),
            'has_errors': len(self.errors) > 0,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }


class SessionManager:
    '''
    Manages workflow sessions with persistence.
    '''
    
    def __init__(self, persistence=None):
        '''
        Initialize the session manager.
        
        Input:
            persistence: Optional StatePersistence instance for saving/loading sessions.
        '''
        self.persistence = persistence
        self.current_session: Optional[SessionState] = None
        self._sessions: Dict[str, SessionState] = {}
    
    def create_session(
        self,
        project_key: str,
        workflow_type: str = 'release_planning',
        **kwargs
    ) -> SessionState:
        '''
        Create a new session.
        
        Input:
            project_key: The Jira project key.
            workflow_type: Type of workflow.
            **kwargs: Additional session parameters.
        
        Output:
            New SessionState instance.
        '''
        session = SessionState(
            project_key=project_key,
            workflow_type=workflow_type,
            **kwargs
        )
        
        self._sessions[session.session_id] = session
        self.current_session = session
        
        log.info(f'Created session: {session.session_id}')
        
        # Persist if persistence is configured
        if self.persistence:
            self.persistence.save(session)
        
        return session
    
    def get_session(self, session_id: str) -> Optional[SessionState]:
        '''
        Get a session by ID.
        
        Input:
            session_id: The session ID.
        
        Output:
            SessionState if found, None otherwise.
        '''
        # Check in-memory cache first
        if session_id in self._sessions:
            return self._sessions[session_id]
        
        # Try to load from persistence
        if self.persistence:
            session = self.persistence.load(session_id)
            if session:
                self._sessions[session_id] = session
                return session
        
        return None
    
    def save_session(self, session: Optional[SessionState] = None) -> bool:
        '''
        Save a session to persistence.
        
        Input:
            session: Session to save (defaults to current session).
        
        Output:
            True if saved successfully.
        '''
        session = session or self.current_session
        if not session:
            log.warning('No session to save')
            return False
        
        session.update_timestamp()
        self._sessions[session.session_id] = session
        
        if self.persistence:
            return self.persistence.save(session)
        
        return True
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        '''
        List all available sessions.
        
        Output:
            List of session summaries.
        '''
        sessions = []
        
        # Get from persistence
        if self.persistence:
            session_ids = self.persistence.list_sessions()
            for sid in session_ids:
                session = self.get_session(sid)
                if session:
                    sessions.append(session.get_summary())
        else:
            # Just return in-memory sessions
            for session in self._sessions.values():
                sessions.append(session.get_summary())
        
        return sessions
    
    def delete_session(self, session_id: str) -> bool:
        '''
        Delete a session.
        
        Input:
            session_id: The session ID to delete.
        
        Output:
            True if deleted successfully.
        '''
        # Remove from memory
        if session_id in self._sessions:
            del self._sessions[session_id]
        
        # Remove from persistence
        if self.persistence:
            return self.persistence.delete(session_id)
        
        return True
    
    def resume_session(self, session_id: str) -> Optional[SessionState]:
        '''
        Resume a previous session.
        
        Input:
            session_id: The session ID to resume.
        
        Output:
            SessionState if found and resumed.
        '''
        session = self.get_session(session_id)
        if session:
            self.current_session = session
            log.info(f'Resumed session: {session_id} at step: {session.current_step}')
            return session
        
        log.warning(f'Session not found: {session_id}')
        return None
