from __future__ import annotations

import os
from typing import Any, Optional

from core.utils import extract_text_from_adf

DEFAULT_JIRA_URL = 'https://cornelisnetworks.atlassian.net'


def issue_to_dict(issue: Any) -> dict[str, Any]:
    key, issue_id, fields, raw_issue = _extract_issue_parts(issue)

    issue_type = _name_value(fields.get('issuetype')) or 'N/A'
    status = _name_value(fields.get('status')) or 'N/A'
    priority = _name_value(fields.get('priority')) or 'N/A'

    assignee_obj = fields.get('assignee')
    reporter_obj = fields.get('reporter')

    fix_versions = _list_name_values(fields.get('fixVersions'))
    affects_versions = _list_name_values(fields.get('versions'))
    components = _list_name_values(fields.get('components'))

    labels_raw = fields.get('labels') or []
    labels = [str(label) for label in labels_raw] if isinstance(labels_raw, list) else []

    created = _string_or_none(fields.get('created'))
    updated = _string_or_none(fields.get('updated'))
    resolved = _string_or_none(fields.get('resolutiondate') or fields.get('resolved'))

    summary = _string_or_empty(fields.get('summary'))
    project_key = _project_key(fields.get('project'))

    result: dict[str, Any] = {
        'key': key,
        'id': issue_id,
        'summary': summary,
        'description': extract_text_from_adf(fields.get('description')),
        'issue_type': issue_type,
        'type': issue_type,
        'status': status,
        'priority': priority,
        'status_name': status,
        'priority_name': priority,
        'assignee': _display_name(assignee_obj) or 'Unassigned',
        'assignee_display': _display_name(assignee_obj),
        'assignee_id': _account_id(assignee_obj),
        'reporter': _display_name(reporter_obj) or 'Unknown',
        'reporter_display': _display_name(reporter_obj),
        'reporter_id': _account_id(reporter_obj),
        'project': project_key,
        'project_key': project_key,
        'created': created,
        'updated': updated,
        'resolved': resolved,
        'created_ts': created,
        'updated_ts': updated,
        'resolved_ts': resolved,
        'created_date': _date_only(created),
        'updated_date': _date_only(updated),
        'resolved_date': _date_only(resolved),
        'fix_versions': fix_versions,
        'affects_versions': affects_versions,
        'components': components,
        'labels': labels,
        'fix_version': ', '.join(fix_versions) if fix_versions else '',
        'affects_version': ', '.join(affects_versions) if affects_versions else '',
        'component': ', '.join(components) if components else '',
        'labels_csv': ', '.join(labels) if labels else '',
        'url': _build_issue_url(key, issue, raw_issue),
    }

    for field_name, value in fields.items():
        if isinstance(field_name, str) and field_name.startswith('customfield_'):
            result[field_name] = _serialize_for_output(value)

    return result


def _extract_issue_parts(issue: Any) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if isinstance(issue, dict):
        raw_issue = issue
        key = str(issue.get('key', '') or '')
        issue_id = str(issue.get('id', '') or '')
        fields = issue.get('fields') or {}
        parsed_fields = fields if isinstance(fields, dict) else {}
        return key, issue_id, parsed_fields, raw_issue

    if hasattr(issue, 'fields'):
        key = str(getattr(issue, 'key', '') or '')
        issue_id = str(getattr(issue, 'id', '') or '')
        fields_obj = getattr(issue, 'fields', None)
        fields = _fields_object_to_dict(fields_obj)

        raw_issue = getattr(issue, 'raw', None)
        if isinstance(raw_issue, dict):
            key = key or str(raw_issue.get('key', '') or '')
            issue_id = issue_id or str(raw_issue.get('id', '') or '')
            raw_fields = raw_issue.get('fields') or {}
            if isinstance(raw_fields, dict):
                merged_fields = dict(raw_fields)
                merged_fields.update(fields)
                fields = merged_fields
            return key, issue_id, fields, raw_issue

        return key, issue_id, fields, {}

    key = str(getattr(issue, 'key', '') or '')
    issue_id = str(getattr(issue, 'id', '') or '')

    raw_issue = getattr(issue, 'raw', None)
    if isinstance(raw_issue, dict):
        key = key or str(raw_issue.get('key', '') or '')
        issue_id = issue_id or str(raw_issue.get('id', '') or '')
        fields = raw_issue.get('fields') or {}
        if isinstance(fields, dict):
            return key, issue_id, fields, raw_issue

    return key, issue_id, {}, {}


def _fields_object_to_dict(fields_obj: Any) -> dict[str, Any]:
    if fields_obj is None:
        return {}

    if isinstance(fields_obj, dict):
        return fields_obj

    fields: dict[str, Any] = {}

    standard_attrs = [
        'summary',
        'description',
        'issuetype',
        'status',
        'priority',
        'assignee',
        'reporter',
        'created',
        'updated',
        'resolutiondate',
        'project',
        'fixVersions',
        'versions',
        'components',
        'labels',
    ]

    for attr in standard_attrs:
        if hasattr(fields_obj, attr):
            fields[attr] = getattr(fields_obj, attr)

    for attr in dir(fields_obj):
        if not attr.startswith('customfield_'):
            continue
        try:
            fields[attr] = getattr(fields_obj, attr)
        except Exception:
            continue

    return fields


def _name_value(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, dict):
        found = value.get('name') or value.get('value')
        return str(found) if found is not None else None

    if isinstance(value, str):
        return value

    found = getattr(value, 'name', None) or getattr(value, 'value', None)
    return str(found) if found is not None else None


def _display_name(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, dict):
        found = value.get('displayName') or value.get('name')
        return str(found) if found is not None else None

    if isinstance(value, str):
        return value

    found = getattr(value, 'displayName', None) or getattr(value, 'name', None)
    return str(found) if found is not None else None


def _account_id(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, dict):
        found = value.get('accountId') or value.get('name')
        return str(found) if found is not None else None

    found = getattr(value, 'accountId', None) or getattr(value, 'name', None)
    return str(found) if found is not None else None


def _project_key(value: Any) -> str:
    if value is None:
        return ''

    if isinstance(value, dict):
        return str(value.get('key', '') or '')

    return str(getattr(value, 'key', '') or '')


def _list_name_values(values: Any) -> list[str]:
    if not values:
        return []

    if not isinstance(values, list):
        values = [values]

    names: list[str] = []
    for item in values:
        if isinstance(item, str):
            names.append(item)
            continue

        if isinstance(item, dict):
            name = item.get('name') or item.get('value')
            if name:
                names.append(str(name))
            continue

        name = getattr(item, 'name', None) or getattr(item, 'value', None)
        if name:
            names.append(str(name))

    return names


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ''
    return str(value)


def _date_only(value: Optional[str]) -> str:
    if not value:
        return ''
    return str(value)[:10]


def _build_issue_url(key: str, issue: Any, raw_issue: dict[str, Any]) -> str:
    if not key:
        return ''

    self_url = None
    if isinstance(issue, dict):
        self_url = issue.get('self')
    else:
        self_url = getattr(issue, 'self', None)

    if not self_url and isinstance(raw_issue, dict):
        self_url = raw_issue.get('self')

    if isinstance(self_url, str) and '/rest/api/' in self_url:
        base_url = self_url.split('/rest/api/', 1)[0]
    else:
        base_url = os.getenv('JIRA_URL', DEFAULT_JIRA_URL)

    return f'{base_url}/browse/{key}'


def _serialize_for_output(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {k: _serialize_for_output(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_serialize_for_output(v) for v in value]

    if isinstance(value, tuple):
        return [_serialize_for_output(v) for v in value]

    raw = getattr(value, 'raw', None)
    if isinstance(raw, dict):
        return _serialize_for_output(raw)

    compact = {}
    for attr in ('id', 'key', 'name', 'value', 'displayName', 'accountId'):
        attr_value = getattr(value, attr, None)
        if attr_value is not None:
            compact[attr] = _serialize_for_output(attr_value)

    if compact:
        return compact

    return str(value)
