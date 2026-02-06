##########################################################################################
#
# Module: state/persistence.py
#
# Description: State persistence backends for session storage.
#              Supports JSON files and SQLite database.
#
# Author: Cornelis Networks
#
##########################################################################################

import json
import logging
import os
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from state.session import SessionState

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


class StatePersistence(ABC):
    '''
    Abstract base class for state persistence backends.
    '''
    
    @abstractmethod
    def save(self, session: SessionState) -> bool:
        '''Save a session state.'''
        pass
    
    @abstractmethod
    def load(self, session_id: str) -> Optional[SessionState]:
        '''Load a session state by ID.'''
        pass
    
    @abstractmethod
    def delete(self, session_id: str) -> bool:
        '''Delete a session state.'''
        pass
    
    @abstractmethod
    def list_sessions(self) -> List[str]:
        '''List all session IDs.'''
        pass


class JSONPersistence(StatePersistence):
    '''
    JSON file-based persistence backend.
    
    Stores each session as a separate JSON file in a directory.
    '''
    
    def __init__(self, storage_dir: str = 'data/sessions'):
        '''
        Initialize JSON persistence.
        
        Input:
            storage_dir: Directory to store session files.
        '''
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        log.debug(f'JSONPersistence initialized: {self.storage_dir}')
    
    def _get_session_path(self, session_id: str) -> Path:
        '''Get the file path for a session.'''
        return self.storage_dir / f'{session_id}.json'
    
    def save(self, session: SessionState) -> bool:
        '''
        Save a session to a JSON file.
        
        Input:
            session: The session state to save.
        
        Output:
            True if saved successfully.
        '''
        try:
            path = self._get_session_path(session.session_id)
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(session.to_dict(), f, indent=2, default=str)
            
            log.debug(f'Saved session to: {path}')
            return True
            
        except Exception as e:
            log.error(f'Failed to save session: {e}')
            return False
    
    def load(self, session_id: str) -> Optional[SessionState]:
        '''
        Load a session from a JSON file.
        
        Input:
            session_id: The session ID to load.
        
        Output:
            SessionState if found, None otherwise.
        '''
        try:
            path = self._get_session_path(session_id)
            
            if not path.exists():
                return None
            
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            log.debug(f'Loaded session from: {path}')
            return SessionState.from_dict(data)
            
        except Exception as e:
            log.error(f'Failed to load session: {e}')
            return None
    
    def delete(self, session_id: str) -> bool:
        '''
        Delete a session file.
        
        Input:
            session_id: The session ID to delete.
        
        Output:
            True if deleted successfully.
        '''
        try:
            path = self._get_session_path(session_id)
            
            if path.exists():
                path.unlink()
                log.debug(f'Deleted session: {path}')
            
            return True
            
        except Exception as e:
            log.error(f'Failed to delete session: {e}')
            return False
    
    def list_sessions(self) -> List[str]:
        '''
        List all session IDs.
        
        Output:
            List of session IDs.
        '''
        sessions = []
        
        for path in self.storage_dir.glob('*.json'):
            sessions.append(path.stem)
        
        return sessions


class SQLitePersistence(StatePersistence):
    '''
    SQLite database persistence backend.
    
    Stores sessions in a SQLite database for better querying.
    '''
    
    def __init__(self, db_path: str = 'data/sessions.db'):
        '''
        Initialize SQLite persistence.
        
        Input:
            db_path: Path to the SQLite database file.
        '''
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_db()
        log.debug(f'SQLitePersistence initialized: {self.db_path}')
    
    def _init_db(self) -> None:
        '''Initialize the database schema.'''
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                project_key TEXT,
                workflow_type TEXT,
                current_step TEXT,
                created_at TEXT,
                updated_at TEXT,
                data TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_project_key ON sessions(project_key)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_updated_at ON sessions(updated_at)
        ''')
        
        conn.commit()
        conn.close()
    
    def save(self, session: SessionState) -> bool:
        '''
        Save a session to the database.
        
        Input:
            session: The session state to save.
        
        Output:
            True if saved successfully.
        '''
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            data = json.dumps(session.to_dict(), default=str)
            
            cursor.execute('''
                INSERT OR REPLACE INTO sessions 
                (session_id, project_key, workflow_type, current_step, created_at, updated_at, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                session.session_id,
                session.project_key,
                session.workflow_type,
                session.current_step,
                session.created_at,
                session.updated_at,
                data
            ))
            
            conn.commit()
            conn.close()
            
            log.debug(f'Saved session to database: {session.session_id}')
            return True
            
        except Exception as e:
            log.error(f'Failed to save session to database: {e}')
            return False
    
    def load(self, session_id: str) -> Optional[SessionState]:
        '''
        Load a session from the database.
        
        Input:
            session_id: The session ID to load.
        
        Output:
            SessionState if found, None otherwise.
        '''
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT data FROM sessions WHERE session_id = ?',
                (session_id,)
            )
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                data = json.loads(row[0])
                log.debug(f'Loaded session from database: {session_id}')
                return SessionState.from_dict(data)
            
            return None
            
        except Exception as e:
            log.error(f'Failed to load session from database: {e}')
            return None
    
    def delete(self, session_id: str) -> bool:
        '''
        Delete a session from the database.
        
        Input:
            session_id: The session ID to delete.
        
        Output:
            True if deleted successfully.
        '''
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                'DELETE FROM sessions WHERE session_id = ?',
                (session_id,)
            )
            
            conn.commit()
            conn.close()
            
            log.debug(f'Deleted session from database: {session_id}')
            return True
            
        except Exception as e:
            log.error(f'Failed to delete session from database: {e}')
            return False
    
    def list_sessions(self) -> List[str]:
        '''
        List all session IDs.
        
        Output:
            List of session IDs.
        '''
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT session_id FROM sessions ORDER BY updated_at DESC')
            
            rows = cursor.fetchall()
            conn.close()
            
            return [row[0] for row in rows]
            
        except Exception as e:
            log.error(f'Failed to list sessions: {e}')
            return []
    
    def find_sessions(
        self,
        project_key: Optional[str] = None,
        workflow_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        '''
        Find sessions matching criteria.
        
        Input:
            project_key: Filter by project key.
            workflow_type: Filter by workflow type.
            limit: Maximum number of results.
        
        Output:
            List of session summaries.
        '''
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            query = 'SELECT session_id, project_key, workflow_type, current_step, created_at, updated_at FROM sessions WHERE 1=1'
            params = []
            
            if project_key:
                query += ' AND project_key = ?'
                params.append(project_key)
            
            if workflow_type:
                query += ' AND workflow_type = ?'
                params.append(workflow_type)
            
            query += ' ORDER BY updated_at DESC LIMIT ?'
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            
            return [
                {
                    'session_id': row[0],
                    'project_key': row[1],
                    'workflow_type': row[2],
                    'current_step': row[3],
                    'created_at': row[4],
                    'updated_at': row[5]
                }
                for row in rows
            ]
            
        except Exception as e:
            log.error(f'Failed to find sessions: {e}')
            return []


def get_persistence(
    persistence_type: str = 'json',
    **kwargs
) -> StatePersistence:
    '''
    Factory function to create a persistence backend.
    
    Input:
        persistence_type: Type of persistence ('json', 'sqlite', 'both').
        **kwargs: Additional arguments for the persistence backend.
    
    Output:
        StatePersistence instance.
    '''
    if persistence_type == 'json':
        return JSONPersistence(**kwargs)
    elif persistence_type == 'sqlite':
        return SQLitePersistence(**kwargs)
    elif persistence_type == 'both':
        # Return a composite that saves to both
        return CompositePersistence(
            JSONPersistence(**kwargs),
            SQLitePersistence(**kwargs)
        )
    else:
        raise ValueError(f'Unknown persistence type: {persistence_type}')


class CompositePersistence(StatePersistence):
    '''
    Composite persistence that saves to multiple backends.
    '''
    
    def __init__(self, *backends: StatePersistence):
        self.backends = backends
    
    def save(self, session: SessionState) -> bool:
        results = [b.save(session) for b in self.backends]
        return all(results)
    
    def load(self, session_id: str) -> Optional[SessionState]:
        for backend in self.backends:
            session = backend.load(session_id)
            if session:
                return session
        return None
    
    def delete(self, session_id: str) -> bool:
        results = [b.delete(session_id) for b in self.backends]
        return all(results)
    
    def list_sessions(self) -> List[str]:
        # Return union of all sessions
        all_sessions = set()
        for backend in self.backends:
            all_sessions.update(backend.list_sessions())
        return list(all_sessions)
