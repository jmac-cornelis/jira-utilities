##########################################################################################
#
# Module: state/gantt_dependency_review_store.py
#
# Description: Persistence helpers for dependency inference review decisions.
#              Stores accepted/rejected judgments for inferred Gantt dependencies.
#
# Author: Cornelis Networks
#
##########################################################################################

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


class GanttDependencyReviewStore:
    '''
    JSON file-based store for Gantt dependency inference review decisions.

    Reviews are stored per project at:
        data/gantt_dependency_reviews/<PROJECT>.json
    '''

    def __init__(self, storage_dir: Optional[str] = None):
        env_dir = os.getenv('GANTT_DEPENDENCY_REVIEW_DIR')
        resolved_dir = storage_dir or env_dir or 'data/gantt_dependency_reviews'
        self.storage_dir = Path(resolved_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        log.debug(f'GanttDependencyReviewStore initialized: {self.storage_dir}')

    def record_review(
        self,
        project_key: str,
        source_key: str,
        target_key: str,
        relationship: str,
        accepted: bool,
        note: Optional[str] = None,
        reviewer: Optional[str] = None,
    ) -> Dict[str, Any]:
        '''
        Record an accept/reject judgment for an inferred dependency edge.
        '''
        normalized_project = str(project_key or '').strip().upper()
        if not normalized_project:
            raise ValueError('project_key is required')

        edge_key = self.edge_key(source_key, target_key, relationship)
        reviews = self._load_project_reviews(normalized_project)
        record = {
            'edge_key': edge_key,
            'project_key': normalized_project,
            'source_key': str(source_key or '').strip().upper(),
            'target_key': str(target_key or '').strip().upper(),
            'relationship': str(relationship or '').strip().casefold(),
            'status': 'accepted' if accepted else 'rejected',
            'note': str(note or ''),
            'reviewer': str(reviewer or ''),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        reviews[edge_key] = record
        self._save_project_reviews(normalized_project, reviews)
        return record

    def get_review(
        self,
        project_key: str,
        source_key: str,
        target_key: str,
        relationship: str,
    ) -> Optional[Dict[str, Any]]:
        '''
        Get a stored review for a dependency edge, if present.
        '''
        normalized_project = str(project_key or '').strip().upper()
        if not normalized_project:
            return None

        reviews = self._load_project_reviews(normalized_project)
        return reviews.get(self.edge_key(source_key, target_key, relationship))

    def list_reviews(
        self,
        project_key: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        '''
        List review records, optionally filtered by project or status.
        '''
        records: List[Dict[str, Any]] = []

        if project_key:
            records.extend(self._load_project_reviews(str(project_key).upper()).values())
        else:
            for path in sorted(self.storage_dir.glob('*.json')):
                project_name = path.stem.upper()
                records.extend(self._load_project_reviews(project_name).values())

        if status:
            normalized_status = str(status).strip().casefold()
            records = [
                record
                for record in records
                if str(record.get('status', '')).casefold() == normalized_status
            ]

        records.sort(
            key=lambda record: str(record.get('updated_at') or ''),
            reverse=True,
        )

        if limit is not None and limit >= 0:
            records = records[:limit]

        return records

    @staticmethod
    def edge_key(source_key: str, target_key: str, relationship: str) -> str:
        '''
        Build a normalized lookup key for a dependency edge.
        '''
        source = str(source_key or '').strip().upper()
        target = str(target_key or '').strip().upper()
        relation = str(relationship or '').strip().casefold()
        return f'{source}|{relation}|{target}'

    def _project_path(self, project_key: str) -> Path:
        return self.storage_dir / f'{project_key.upper()}.json'

    def _load_project_reviews(self, project_key: str) -> Dict[str, Dict[str, Any]]:
        path = self._project_path(project_key)
        if not path.exists():
            return {}

        try:
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except Exception as e:
            log.warning(f'Failed to load dependency reviews from {path}: {e}')
            return {}

        if not isinstance(payload, dict):
            return {}

        return {
            str(edge_key): record
            for edge_key, record in payload.items()
            if isinstance(record, dict)
        }

    def _save_project_reviews(
        self,
        project_key: str,
        reviews: Dict[str, Dict[str, Any]],
    ) -> None:
        path = self._project_path(project_key)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(reviews, f, indent=2, default=str)
