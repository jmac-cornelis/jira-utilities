##########################################################################################
#
# Module: state/gantt_snapshot_store.py
#
# Description: Persistence helpers for Gantt planning snapshots.
#              Stores durable JSON + Markdown snapshot artifacts and supports
#              retrieval/listing for later review.
#
# Author: Cornelis Networks
#
##########################################################################################

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.gantt_models import PlanningSnapshot

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


class GanttSnapshotStore:
    '''
    JSON + Markdown persistence for Gantt planning snapshots.

    Snapshots are stored at:
        data/gantt_snapshots/<PROJECT>/<SNAPSHOT_ID>/snapshot.json
        data/gantt_snapshots/<PROJECT>/<SNAPSHOT_ID>/summary.md
    '''

    def __init__(self, storage_dir: Optional[str] = None):
        env_dir = os.getenv('GANTT_SNAPSHOT_DIR')
        resolved_dir = storage_dir or env_dir or 'data/gantt_snapshots'
        self.storage_dir = Path(resolved_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        log.debug(f'GanttSnapshotStore initialized: {self.storage_dir}')

    def save_snapshot(
        self,
        snapshot: PlanningSnapshot | Dict[str, Any],
        summary_markdown: Optional[str] = None,
    ) -> Dict[str, Any]:
        '''
        Persist a snapshot and return a summary record for indexing/reporting.
        '''
        if isinstance(snapshot, PlanningSnapshot):
            snapshot_data = snapshot.to_dict()
            if summary_markdown is None:
                summary_markdown = snapshot.summary_markdown
        else:
            snapshot_data = dict(snapshot)

        snapshot_id = str(snapshot_data.get('snapshot_id') or '').strip()
        if not snapshot_id:
            raise ValueError('Snapshot is missing snapshot_id')

        project_key = str(snapshot_data.get('project_key') or '').strip().upper()
        if not project_key:
            raise ValueError('Snapshot is missing project_key')

        snapshot_dir = self.storage_dir / project_key / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        json_path = snapshot_dir / 'snapshot.json'
        markdown_path = snapshot_dir / 'summary.md'

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot_data, f, indent=2, default=str)

        markdown_text = summary_markdown
        if markdown_text is None:
            markdown_text = str(snapshot_data.get('summary_markdown') or '')

        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.write(markdown_text)

        summary = self._build_summary(snapshot_data, json_path, markdown_path)
        log.info(f'Saved Gantt snapshot {snapshot_id} to {snapshot_dir}')
        return summary

    def get_snapshot(
        self,
        snapshot_id: str,
        project_key: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        '''
        Load a stored snapshot by ID.
        '''
        json_path = self._find_snapshot_json(snapshot_id, project_key=project_key)
        if json_path is None:
            return None

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                snapshot_data = json.load(f)
        except Exception as e:
            log.error(f'Failed to load Gantt snapshot {snapshot_id}: {e}')
            return None

        markdown_path = json_path.parent / 'summary.md'
        summary_markdown = ''
        if markdown_path.exists():
            try:
                summary_markdown = markdown_path.read_text(encoding='utf-8')
            except Exception as e:
                log.warning(f'Failed to read Gantt summary markdown {markdown_path}: {e}')

        return {
            'snapshot': snapshot_data,
            'summary_markdown': summary_markdown,
            'summary': self._build_summary(snapshot_data, json_path, markdown_path),
        }

    def list_snapshots(
        self,
        project_key: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        '''
        List stored snapshots, optionally filtered by project.
        '''
        summaries: List[Dict[str, Any]] = []
        json_paths = self._iter_snapshot_json_paths(project_key=project_key)

        for json_path in json_paths:
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    snapshot_data = json.load(f)
            except Exception as e:
                log.warning(f'Skipping unreadable snapshot file {json_path}: {e}')
                continue

            summaries.append(
                self._build_summary(
                    snapshot_data,
                    json_path,
                    json_path.parent / 'summary.md',
                )
            )

        summaries.sort(
            key=lambda item: (
                self._sort_timestamp(item.get('created_at')),
                str(item.get('snapshot_id') or ''),
            ),
            reverse=True,
        )

        if limit is not None and limit >= 0:
            summaries = summaries[:limit]

        return summaries

    def _iter_snapshot_json_paths(self, project_key: Optional[str] = None) -> List[Path]:
        if project_key:
            project_dir = self.storage_dir / str(project_key).upper()
            if not project_dir.exists():
                return []
            return sorted(project_dir.glob('*/snapshot.json'))

        return sorted(self.storage_dir.glob('*/*/snapshot.json'))

    def _find_snapshot_json(
        self,
        snapshot_id: str,
        project_key: Optional[str] = None,
    ) -> Optional[Path]:
        snapshot_id = str(snapshot_id).strip()
        if not snapshot_id:
            return None

        if project_key:
            candidate = (
                self.storage_dir / str(project_key).upper() / snapshot_id / 'snapshot.json'
            )
            return candidate if candidate.exists() else None

        matches = list(self.storage_dir.glob(f'*/{snapshot_id}/snapshot.json'))
        if not matches:
            return None

        if len(matches) > 1:
            log.warning(
                f'Multiple stored Gantt snapshots matched ID {snapshot_id}; using {matches[0]}'
            )

        return matches[0]

    @staticmethod
    def _build_summary(
        snapshot_data: Dict[str, Any],
        json_path: Path,
        markdown_path: Path,
    ) -> Dict[str, Any]:
        overview = snapshot_data.get('backlog_overview') or {}
        milestones = snapshot_data.get('milestones') or []
        risks = snapshot_data.get('risks') or []
        dependency_graph = snapshot_data.get('dependency_graph') or {}

        return {
            'snapshot_id': str(snapshot_data.get('snapshot_id') or ''),
            'project_key': str(snapshot_data.get('project_key') or '').upper(),
            'created_at': str(snapshot_data.get('created_at') or ''),
            'planning_horizon_days': int(snapshot_data.get('planning_horizon_days') or 0),
            'total_issues': int(overview.get('total_issues') or 0),
            'blocked_issues': int(overview.get('blocked_issues') or 0),
            'stale_issues': int(overview.get('stale_issues') or 0),
            'milestone_count': len(milestones),
            'risk_count': len(risks),
            'edge_count': int(dependency_graph.get('edge_count') or 0),
            'storage_dir': str(json_path.parent),
            'json_path': str(json_path),
            'markdown_path': str(markdown_path),
        }

    @staticmethod
    def _sort_timestamp(value: Any) -> datetime:
        raw = str(value or '').strip()
        if not raw:
            return datetime.min

        try:
            if raw.endswith('Z'):
                raw = raw[:-1] + '+00:00'
            return datetime.fromisoformat(raw)
        except ValueError:
            return datetime.min
