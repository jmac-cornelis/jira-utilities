from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import statistics
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(os.path.basename(sys.argv[0]))


class LearningStore:
    _STOPWORDS = {
        'the', 'and', 'for', 'with', 'that', 'this', 'from', 'into', 'onto', 'about',
        'are', 'was', 'were', 'have', 'has', 'had', 'will', 'would', 'could', 'should',
        'can', 'not', 'but', 'you', 'your', 'our', 'their', 'they', 'them', 'its',
        'issue', 'ticket', 'bug', 'story', 'task', 'subtask', 'sub', 'epic',
        'after', 'before', 'when', 'where', 'while', 'then', 'than', 'over', 'under',
        'new', 'old', 'set', 'gets', 'got', 'too', 'very', 'via', 'out', 'all',
        'open', 'close', 'closed', 'ready', 'todo', 'done', 'fix', 'fixed',
    }

    def __init__(self, db_path: str = 'state/learning.db'):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._ticket_keywords: Dict[str, list[str]] = {}

        if db_path != ':memory:':
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)

        self.conn: Optional[sqlite3.Connection] = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_key TEXT NOT NULL,
                    field TEXT NOT NULL,
                    predicted_value TEXT,
                    actual_value TEXT,
                    correct INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS keyword_patterns (
                    keyword TEXT NOT NULL,
                    field TEXT NOT NULL,
                    value TEXT NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    miss_count INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    PRIMARY KEY (keyword, field, value)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reporter_profiles (
                    reporter_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    value TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0,
                    compliance_rate REAL NOT NULL DEFAULT 0.0,
                    PRIMARY KEY (reporter_id, field, value)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cycle_times (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_key TEXT,
                    component TEXT,
                    priority TEXT,
                    status_from TEXT,
                    status_to TEXT,
                    duration_hours REAL,
                    timestamp TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS release_snapshots (
                    release TEXT NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    status_json TEXT NOT NULL,
                    priority_json TEXT NOT NULL,
                    component_json TEXT NOT NULL,
                    PRIMARY KEY (release, snapshot_date)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS auto_fill_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_key TEXT NOT NULL,
                    field TEXT NOT NULL,
                    value_set TEXT,
                    confidence REAL,
                    corrected_by_human INTEGER NOT NULL DEFAULT 0,
                    correction_value TEXT,
                    timestamp TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_observations_ticket_field "
                "ON observations(ticket_key, field)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_keyword_patterns_field_keyword "
                "ON keyword_patterns(field, keyword)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_reporter_profiles_lookup "
                "ON reporter_profiles(reporter_id, field, count DESC)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_cycle_times_component_priority "
                "ON cycle_times(component, priority)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_auto_fill_log_ticket_field "
                "ON auto_fill_log(ticket_key, field, timestamp DESC)"
            )

            conn.commit()

    def _require_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError('LearningStore connection is closed')
        return self.conn

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_field(field: str) -> str:
        value = (field or '').strip()
        lowered = value.lower()

        if lowered in {'component', 'components'}:
            return 'component'
        if lowered in {'affectedversion', 'affects_version', 'affects_versions', 'versions'}:
            return 'affects_version'
        if lowered == 'priority':
            return 'priority'

        return lowered or value

    def _extract_keywords(self, summary: str) -> list[str]:
        if not summary:
            return []

        tokens = re.split(r'[^a-zA-Z0-9]+', summary.lower())
        keywords: list[str] = []
        seen: set[str] = set()

        for token in tokens:
            if len(token) < 3:
                continue
            if token in self._STOPWORDS:
                continue
            if token in seen:
                continue
            seen.add(token)
            keywords.append(token)

        return keywords

    @staticmethod
    def _first_value(value: Any) -> str:
        if value is None:
            return ''

        if isinstance(value, list):
            if not value:
                return ''
            first = value[0]
            return str(first).strip() if first is not None else ''

        if isinstance(value, str):
            parts = [part.strip() for part in value.split(',')]
            return parts[0] if parts and parts[0] else ''

        return str(value).strip()

    def _update_keyword_pattern(self, keyword: str, field: str, value: str, correct: bool) -> None:
        normalized_keyword = keyword.strip().lower()
        normalized_field = self._normalize_field(field)
        normalized_value = (value or '').strip()

        if not normalized_keyword or not normalized_value:
            return

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT hit_count, miss_count
                FROM keyword_patterns
                WHERE keyword = ? AND field = ? AND value = ?
                """,
                (normalized_keyword, normalized_field, normalized_value),
            )
            row = cursor.fetchone()

            hit_count = int(row['hit_count']) if row else 0
            miss_count = int(row['miss_count']) if row else 0

            if correct:
                hit_count += 1
            else:
                miss_count += 1

            confidence = hit_count / (hit_count + miss_count + 2)

            cursor.execute(
                """
                INSERT INTO keyword_patterns (keyword, field, value, hit_count, miss_count, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(keyword, field, value)
                DO UPDATE SET
                    hit_count = excluded.hit_count,
                    miss_count = excluded.miss_count,
                    confidence = excluded.confidence
                """,
                (normalized_keyword, normalized_field, normalized_value, hit_count, miss_count, confidence),
            )
            conn.commit()

    def _update_reporter_compliance(self, reporter_id: str, field: str, has_value: bool) -> None:
        normalized_reporter = (reporter_id or '').strip()
        normalized_field = self._normalize_field(field)

        if not normalized_reporter or not normalized_field:
            return

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT count, total
                FROM reporter_profiles
                WHERE reporter_id = ? AND field = ? AND value = '__present__'
                """,
                (normalized_reporter, normalized_field),
            )
            row = cursor.fetchone()

            current_count = int(row['count']) if row else 0
            current_total = int(row['total']) if row else 0

            if has_value:
                current_count += 1
            current_total += 1

            compliance_rate = current_count / current_total if current_total else 0.0

            cursor.execute(
                """
                INSERT INTO reporter_profiles (reporter_id, field, value, count, total, compliance_rate)
                VALUES (?, ?, '__present__', ?, ?, ?)
                ON CONFLICT(reporter_id, field, value)
                DO UPDATE SET
                    count = excluded.count,
                    total = excluded.total,
                    compliance_rate = excluded.compliance_rate
                """,
                (normalized_reporter, normalized_field, current_count, current_total, compliance_rate),
            )
            conn.commit()

    def _update_reporter_value(self, reporter_id: str, field: str, value: str) -> None:
        normalized_reporter = (reporter_id or '').strip()
        normalized_field = self._normalize_field(field)
        normalized_value = (value or '').strip()

        if not normalized_reporter or not normalized_field or not normalized_value:
            return

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT COALESCE(SUM(count), 0) AS total_count
                FROM reporter_profiles
                WHERE reporter_id = ? AND field = ? AND value != '__present__'
                """,
                (normalized_reporter, normalized_field),
            )
            total_before = int(cursor.fetchone()['total_count'])
            total_after = total_before + 1

            cursor.execute(
                """
                SELECT count
                FROM reporter_profiles
                WHERE reporter_id = ? AND field = ? AND value = ?
                """,
                (normalized_reporter, normalized_field, normalized_value),
            )
            row = cursor.fetchone()
            value_count = int(row['count']) if row else 0
            new_value_count = value_count + 1

            cursor.execute(
                """
                INSERT INTO reporter_profiles (reporter_id, field, value, count, total, compliance_rate)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(reporter_id, field, value)
                DO UPDATE SET
                    count = excluded.count,
                    total = excluded.total,
                    compliance_rate = excluded.compliance_rate
                """,
                (
                    normalized_reporter,
                    normalized_field,
                    normalized_value,
                    new_value_count,
                    total_after,
                    new_value_count / total_after if total_after else 0.0,
                ),
            )

            cursor.execute(
                """
                UPDATE reporter_profiles
                SET total = ?,
                    compliance_rate = CASE WHEN ? > 0 THEN CAST(count AS REAL) / ? ELSE 0.0 END
                WHERE reporter_id = ? AND field = ? AND value != '__present__'
                """,
                (total_after, total_after, total_after, normalized_reporter, normalized_field),
            )

            conn.commit()

    def _predict_from_reporter(self, field: str, ticket_dict: Dict[str, Any]) -> Tuple[str, float]:
        reporter_id = (
            str(ticket_dict.get('reporter_id') or '').strip()
            or str(ticket_dict.get('reporter') or '').strip()
        )
        if not reporter_id:
            return '', 0.0

        normalized_field = self._normalize_field(field)

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT value, count, total
                FROM reporter_profiles
                WHERE reporter_id = ?
                  AND field = ?
                  AND value != '__present__'
                ORDER BY count DESC, value ASC
                LIMIT 1
                """,
                (reporter_id, normalized_field),
            )
            row = cursor.fetchone()

        if not row:
            return '', 0.0

        count = int(row['count'])
        total = int(row['total'])
        confidence = count / (total + 2)

        return str(row['value']), confidence

    def get_field_prediction(self, field: str, ticket_dict: Dict[str, Any]) -> Tuple[str, float]:
        normalized_field = self._normalize_field(field)

        if normalized_field == 'component':
            return self.predict_component(ticket_dict)
        if normalized_field == 'affects_version':
            return self.predict_affects_version(ticket_dict)
        if normalized_field == 'priority':
            return self._predict_from_reporter('priority', ticket_dict)

        return '', 0.0

    def predict_component(self, ticket_dict: Dict[str, Any]) -> Tuple[str, float]:
        summary = str(ticket_dict.get('summary') or '')
        keywords = self._extract_keywords(summary)

        if not keywords:
            return '', 0.0

        placeholders = ','.join(['?'] * len(keywords))
        params = ['component', *keywords]

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                (
                    'SELECT keyword, value, hit_count, miss_count, confidence '
                    'FROM keyword_patterns '
                    f'WHERE field = ? AND keyword IN ({placeholders})'
                ),
                params,
            )
            rows = cursor.fetchall()

        if not rows:
            return '', 0.0

        weighted_sum: Dict[str, float] = {}
        total_weight: Dict[str, float] = {}

        for row in rows:
            value = str(row['value'])
            hit_count = int(row['hit_count'])
            miss_count = int(row['miss_count'])
            confidence = float(row['confidence'])
            weight = float(hit_count + miss_count + 1)

            weighted_sum[value] = weighted_sum.get(value, 0.0) + confidence * weight
            total_weight[value] = total_weight.get(value, 0.0) + weight

        best_value = ''
        best_confidence = 0.0
        for value, value_weight_sum in weighted_sum.items():
            score = value_weight_sum / total_weight[value] if total_weight[value] else 0.0
            if score > best_confidence:
                best_confidence = score
                best_value = value

        return best_value, best_confidence

    def predict_affects_version(self, ticket_dict: Dict[str, Any]) -> Tuple[str, float]:
        return self._predict_from_reporter('affects_version', ticket_dict)

    def record_observation(
        self,
        ticket_key: str,
        field: str,
        predicted: str,
        actual: str,
        correct: bool,
    ) -> None:
        normalized_field = self._normalize_field(field)

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO observations
                (ticket_key, field, predicted_value, actual_value, correct, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_key,
                    normalized_field,
                    predicted or '',
                    actual or '',
                    1 if correct else 0,
                    self._utc_now_iso(),
                ),
            )
            conn.commit()

        if normalized_field == 'component':
            keywords = self._ticket_keywords.get(ticket_key, [])
            for keyword in keywords:
                if predicted:
                    self._update_keyword_pattern(keyword, 'component', predicted, correct)
                if (not correct) and actual and actual != predicted:
                    self._update_keyword_pattern(keyword, 'component', actual, True)

    def record_ticket(self, ticket_dict: Dict[str, Any]) -> None:
        ticket_key = str(ticket_dict.get('key') or '').strip()
        summary = str(ticket_dict.get('summary') or '')
        keywords = self._extract_keywords(summary)

        if ticket_key:
            self._ticket_keywords[ticket_key] = keywords

        component = self._first_value(ticket_dict.get('components') or ticket_dict.get('component'))
        affects_version = self._first_value(
            ticket_dict.get('affects_versions') or ticket_dict.get('affects_version') or ticket_dict.get('versions')
        )
        priority = self._first_value(ticket_dict.get('priority'))

        reporter_id = (
            str(ticket_dict.get('reporter_id') or '').strip()
            or str(ticket_dict.get('reporter') or '').strip()
        )

        if component:
            for keyword in keywords:
                self._update_keyword_pattern(keyword, 'component', component, True)

        if reporter_id:
            self._update_reporter_compliance(reporter_id, 'component', bool(component))
            self._update_reporter_compliance(reporter_id, 'affects_version', bool(affects_version))
            self._update_reporter_compliance(reporter_id, 'priority', bool(priority))

            if component:
                self._update_reporter_value(reporter_id, 'component', component)
            if affects_version:
                self._update_reporter_value(reporter_id, 'affects_version', affects_version)
            if priority:
                self._update_reporter_value(reporter_id, 'priority', priority)

    def record_auto_fill(self, ticket_key: str, field: str, value: str, confidence: float) -> None:
        normalized_field = self._normalize_field(field)

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO auto_fill_log
                (ticket_key, field, value_set, confidence, corrected_by_human, correction_value, timestamp)
                VALUES (?, ?, ?, ?, 0, NULL, ?)
                """,
                (ticket_key, normalized_field, value, float(confidence), self._utc_now_iso()),
            )
            conn.commit()

    def update_from_correction(
        self,
        ticket_key: str,
        field: str,
        old_value: str,
        new_value: str,
    ) -> None:
        normalized_field = self._normalize_field(field)

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE auto_fill_log
                SET corrected_by_human = 1,
                    correction_value = ?
                WHERE id = (
                    SELECT id
                    FROM auto_fill_log
                    WHERE ticket_key = ? AND field = ? AND value_set = ?
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (new_value, ticket_key, normalized_field, old_value),
            )
            conn.commit()

        self.record_observation(
            ticket_key=ticket_key,
            field=normalized_field,
            predicted=old_value,
            actual=new_value,
            correct=(old_value == new_value),
        )

    def get_reporter_profile(self, reporter_id: str) -> Dict[str, Any]:
        normalized_reporter = (reporter_id or '').strip()
        profile: Dict[str, Any] = {
            'reporter_id': normalized_reporter,
            'fields': {},
            'common_components': [],
            'typical_priority': '',
            'typical_version': '',
        }

        if not normalized_reporter:
            return profile

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT field, value, count, total, compliance_rate
                FROM reporter_profiles
                WHERE reporter_id = ?
                ORDER BY field ASC, count DESC, value ASC
                """,
                (normalized_reporter,),
            )
            rows = cursor.fetchall()

        grouped: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            field = str(row['field'])
            value = str(row['value'])
            count = int(row['count'])
            total = int(row['total'])
            compliance_rate = float(row['compliance_rate'])

            if field not in grouped:
                grouped[field] = {
                    'compliance_rate': 0.0,
                    'observed_tickets': 0,
                    'common_values': [],
                    'typical_value': '',
                }

            if value == '__present__':
                grouped[field]['compliance_rate'] = compliance_rate
                grouped[field]['observed_tickets'] = total
            else:
                ratio = count / total if total else 0.0
                grouped[field]['common_values'].append(
                    {
                        'value': value,
                        'count': count,
                        'ratio': ratio,
                    }
                )
                if not grouped[field]['typical_value']:
                    grouped[field]['typical_value'] = value

        profile['fields'] = grouped

        component_values = grouped.get('component', {}).get('common_values', [])
        profile['common_components'] = [entry['value'] for entry in component_values]
        profile['typical_priority'] = grouped.get('priority', {}).get('typical_value', '')
        profile['typical_version'] = grouped.get('affects_version', {}).get('typical_value', '')

        return profile

    def get_keyword_component_map(self) -> Dict[str, Dict[str, float]]:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT keyword, value, confidence
                FROM keyword_patterns
                WHERE field = 'component'
                ORDER BY keyword ASC, confidence DESC, value ASC
                """
            )
            rows = cursor.fetchall()

        mapping: Dict[str, Dict[str, float]] = {}
        for row in rows:
            keyword = str(row['keyword'])
            value = str(row['value'])
            confidence = float(row['confidence'])
            mapping.setdefault(keyword, {})[value] = confidence

        return mapping

    def record_cycle_time(
        self,
        ticket_key: str,
        component: str,
        priority: str,
        status_from: str,
        status_to: str,
        duration_hours: float,
    ) -> None:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO cycle_times
                (ticket_key, component, priority, status_from, status_to, duration_hours, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_key,
                    component,
                    priority,
                    status_from,
                    status_to,
                    float(duration_hours),
                    self._utc_now_iso(),
                ),
            )
            conn.commit()

    def get_cycle_time_stats(self, component: str, priority: str) -> Dict[str, Any]:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT duration_hours
                FROM cycle_times
                WHERE component = ? AND priority = ?
                ORDER BY duration_hours ASC
                """,
                (component, priority),
            )
            rows = cursor.fetchall()

        durations = [float(row['duration_hours']) for row in rows if row['duration_hours'] is not None]
        if not durations:
            return {
                'count': 0,
                'average_hours': 0.0,
                'median_hours': 0.0,
            }

        return {
            'count': len(durations),
            'average_hours': float(sum(durations) / len(durations)),
            'median_hours': float(statistics.median(durations)),
        }

    def save_release_snapshot(self, release: str, snapshot: Dict[str, Any]) -> None:
        snapshot_date = str(
            snapshot.get('snapshot_date')
            or snapshot.get('date')
            or datetime.now(timezone.utc).date().isoformat()
        )
        status_data = snapshot.get('status') or snapshot.get('status_counts') or {}
        priority_data = snapshot.get('priority') or snapshot.get('priority_counts') or {}
        component_data = snapshot.get('component') or snapshot.get('component_counts') or {}

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO release_snapshots
                (release, snapshot_date, status_json, priority_json, component_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(release, snapshot_date)
                DO UPDATE SET
                    status_json = excluded.status_json,
                    priority_json = excluded.priority_json,
                    component_json = excluded.component_json
                """,
                (
                    release,
                    snapshot_date,
                    json.dumps(status_data, sort_keys=True),
                    json.dumps(priority_data, sort_keys=True),
                    json.dumps(component_data, sort_keys=True),
                ),
            )
            conn.commit()

    def get_release_snapshot(self, release: str, date: Optional[str]) -> Optional[Dict[str, Any]]:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            if date:
                cursor.execute(
                    """
                    SELECT release, snapshot_date, status_json, priority_json, component_json
                    FROM release_snapshots
                    WHERE release = ? AND snapshot_date <= ?
                    ORDER BY snapshot_date DESC
                    LIMIT 1
                    """,
                    (release, date),
                )
            else:
                cursor.execute(
                    """
                    SELECT release, snapshot_date, status_json, priority_json, component_json
                    FROM release_snapshots
                    WHERE release = ?
                    ORDER BY snapshot_date DESC
                    LIMIT 1
                    """,
                    (release,),
                )
            row = cursor.fetchone()

        if not row:
            return None

        return {
            'release': str(row['release']),
            'snapshot_date': str(row['snapshot_date']),
            'status': json.loads(row['status_json']) if row['status_json'] else {},
            'priority': json.loads(row['priority_json']) if row['priority_json'] else {},
            'component': json.loads(row['component_json']) if row['component_json'] else {},
        }

    def rebuild_confidence_scores(self) -> None:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute('SELECT keyword, field, value, hit_count, miss_count FROM keyword_patterns')
            rows = cursor.fetchall()

            for row in rows:
                hit_count = int(row['hit_count'])
                miss_count = int(row['miss_count'])
                confidence = hit_count / (hit_count + miss_count + 2)
                cursor.execute(
                    """
                    UPDATE keyword_patterns
                    SET confidence = ?
                    WHERE keyword = ? AND field = ? AND value = ?
                    """,
                    (confidence, row['keyword'], row['field'], row['value']),
                )

            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        table_names = [
            'observations',
            'keyword_patterns',
            'reporter_profiles',
            'cycle_times',
            'release_snapshots',
            'auto_fill_log',
        ]

        stats: Dict[str, Any] = {
            'tables': {},
            'observations': {
                'total': 0,
                'correct': 0,
                'accuracy': 0.0,
            },
        }

        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            for name in table_names:
                cursor.execute(f'SELECT COUNT(*) AS count FROM {name}')
                stats['tables'][name] = int(cursor.fetchone()['count'])

            cursor.execute('SELECT COUNT(*) AS count FROM observations')
            total_observations = int(cursor.fetchone()['count'])

            cursor.execute('SELECT COUNT(*) AS count FROM observations WHERE correct = 1')
            correct_observations = int(cursor.fetchone()['count'])

        stats['observations']['total'] = total_observations
        stats['observations']['correct'] = correct_observations
        stats['observations']['accuracy'] = (
            correct_observations / total_observations if total_observations else 0.0
        )

        return stats

    def reset(self) -> None:
        conn = self._require_conn()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM observations')
            cursor.execute('DELETE FROM keyword_patterns')
            cursor.execute('DELETE FROM reporter_profiles')
            cursor.execute('DELETE FROM cycle_times')
            cursor.execute('DELETE FROM release_snapshots')
            cursor.execute('DELETE FROM auto_fill_log')
            conn.commit()

        self._ticket_keywords = {}

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
