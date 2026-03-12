from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class MonitorState:
    def __init__(self, db_path: str = 'state/monitor_state.db'):
        self.db_path = db_path
        self._lock = threading.RLock()

        if db_path != ':memory:':
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)

        self.conn: Optional[sqlite3.Connection] = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _require_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError('MonitorState connection is closed')
        return self.conn

    def _init_db(self) -> None:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    project TEXT PRIMARY KEY,
                    last_checked TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_tickets (
                    ticket_key TEXT PRIMARY KEY,
                    project TEXT,
                    processed_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS validation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_key TEXT NOT NULL,
                    project TEXT,
                    result_json TEXT,
                    timestamp TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_processed_project '
                'ON processed_tickets(project)'
            )
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_history_ticket '
                'ON validation_history(ticket_key, timestamp DESC)'
            )
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_history_project '
                'ON validation_history(project, timestamp DESC)'
            )

            conn.commit()

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_last_checked(self, project: str) -> Optional[str]:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT last_checked FROM checkpoints WHERE project = ?',
                (project,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return str(row['last_checked'])

    def set_last_checked(self, project: str, timestamp: Optional[str] = None) -> str:
        value = timestamp or self._utc_now_iso()
        conn = self._require_conn()

        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO checkpoints (project, last_checked)
                VALUES (?, ?)
                ON CONFLICT(project)
                DO UPDATE SET last_checked = excluded.last_checked
                """,
                (project, value),
            )
            conn.commit()

        return value

    def is_processed(self, ticket_key: str) -> bool:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT 1 FROM processed_tickets WHERE ticket_key = ? LIMIT 1',
                (ticket_key,),
            )
            row = cursor.fetchone()

        return row is not None

    def mark_processed(
        self,
        ticket_key: str,
        project: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        ts = timestamp or self._utc_now_iso()
        conn = self._require_conn()

        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO processed_tickets (ticket_key, project, processed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(ticket_key)
                DO UPDATE SET
                    project = excluded.project,
                    processed_at = excluded.processed_at
                """,
                (ticket_key, project, ts),
            )

            cursor.execute(
                """
                INSERT INTO validation_history (ticket_key, project, result_json, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (
                    ticket_key,
                    project,
                    json.dumps(result or {}, sort_keys=True),
                    ts,
                ),
            )

            conn.commit()

    def get_validation_history(
        self,
        ticket_key: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        conn = self._require_conn()

        query = (
            'SELECT id, ticket_key, project, result_json, timestamp '
            'FROM validation_history WHERE 1=1'
        )
        params: list[Any] = []

        if ticket_key:
            query += ' AND ticket_key = ?'
            params.append(ticket_key)

        if project:
            query += ' AND project = ?'
            params.append(project)

        query += ' ORDER BY timestamp DESC, id DESC LIMIT ?'
        params.append(limit)

        with self._lock:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows:
            payload = row['result_json']
            parsed = json.loads(payload) if payload else {}
            results.append(
                {
                    'id': int(row['id']),
                    'ticket_key': str(row['ticket_key']),
                    'project': row['project'],
                    'result': parsed,
                    'timestamp': str(row['timestamp']),
                }
            )

        return results

    def get_stats(self) -> Dict[str, Any]:
        conn = self._require_conn()

        with self._lock:
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) AS count FROM checkpoints')
            checkpoint_count = int(cursor.fetchone()['count'])

            cursor.execute('SELECT COUNT(*) AS count FROM processed_tickets')
            processed_count = int(cursor.fetchone()['count'])

            cursor.execute('SELECT COUNT(*) AS count FROM validation_history')
            history_count = int(cursor.fetchone()['count'])

            cursor.execute(
                """
                SELECT project, COUNT(*) AS count
                FROM processed_tickets
                WHERE project IS NOT NULL AND project != ''
                GROUP BY project
                ORDER BY project ASC
                """
            )
            projects = {
                str(row['project']): int(row['count'])
                for row in cursor.fetchall()
            }

        return {
            'checkpoints': checkpoint_count,
            'processed_tickets': processed_count,
            'validation_history': history_count,
            'processed_by_project': projects,
        }

    def reset(self) -> None:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM checkpoints')
            cursor.execute('DELETE FROM processed_tickets')
            cursor.execute('DELETE FROM validation_history')
            conn.commit()

    def close(self) -> None:
        with self._lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
