from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Any, Mapping, Optional

import yaml


_STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'in',
    'into', 'is', 'it', 'its', 'of', 'on', 'or', 'that', 'the', 'this',
    'to', 'with', 'will', 'would', 'should', 'can', 'could', 'was', 'were',
    'ticket', 'issue', 'bug', 'story', 'task', 'epic', 'subtask',
}


_FIELD_CANDIDATES: dict[str, list[str]] = {
    'affects_versions': [
        'affectedVersion', 'affectedVersions', 'versions',
        'affects_versions', 'affects_version', 'affected_version',
    ],
    'fix_versions': [
        'fixVersions', 'fixVersion', 'fix_versions', 'fix_version',
    ],
    'components': [
        'components', 'component',
    ],
    'labels': [
        'labels', 'labels_csv',
    ],
    'assignee': [
        'assignee_display', 'assignee_id', 'assignee',
    ],
    'reporter': [
        'reporter_display', 'reporter_id', 'reporter',
    ],
    'priority': [
        'priority', 'priority_name',
    ],
    'issue_type': [
        'issue_type', 'issueType', 'issuetype', 'type',
    ],
    'parent': [
        'parent', 'parent_key',
    ],
    'description': [
        'description',
    ],
}


@dataclass
class ValidationResult:
    ticket_key: str
    issue_type: str
    missing_required: list[str] = field(default_factory=list)
    missing_warned: list[str] = field(default_factory=list)
    predictions: dict[str, dict[str, Any]] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    ticket_data: Optional[dict[str, Any]] = None


@dataclass
class MonitorConfig:
    project: str = ''
    poll_interval_minutes: int = 5
    validation_rules: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    learning_enabled: bool = True
    min_observations: int = 20
    confidence_thresholds: dict[str, float] = field(default_factory=lambda: {
        'auto_fill': 0.90,
        'suggest': 0.50,
        'flag_only': 0.0,
    })
    feedback_detection: bool = True
    keyword_extraction: bool = True
    reporter_profiling: bool = True
    notifications: dict[str, Any] = field(default_factory=dict)
    valid_affects_versions: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, yaml_input: str | Mapping[str, Any]) -> 'MonitorConfig':
        if isinstance(yaml_input, Mapping):
            payload = dict(yaml_input)
        else:
            parsed = yaml.safe_load(yaml_input) if yaml_input else {}
            if parsed is None:
                parsed = {}
            if not isinstance(parsed, dict):
                raise ValueError('ticket monitor config must deserialize to a mapping')
            payload = parsed

        raw_rules = payload.get('validation_rules') or {}
        normalized_rules: dict[str, dict[str, list[str]]] = {}
        if isinstance(raw_rules, Mapping):
            for issue_type, rule_cfg in raw_rules.items():
                if not isinstance(rule_cfg, Mapping):
                    continue
                required_raw = rule_cfg.get('required')
                warn_raw = rule_cfg.get('warn')

                required_values = required_raw if isinstance(required_raw, list) else []
                warn_values = warn_raw if isinstance(warn_raw, list) else []

                required = [str(v) for v in required_values]
                warn = [str(v) for v in warn_values]
                normalized_rules[str(issue_type)] = {
                    'required': required,
                    'warn': warn,
                }

        learning_cfg = payload.get('learning') or {}
        if not isinstance(learning_cfg, Mapping):
            learning_cfg = {}

        thresholds = {
            'auto_fill': 0.90,
            'suggest': 0.50,
            'flag_only': 0.0,
        }
        raw_thresholds = learning_cfg.get('confidence_thresholds') or {}
        if isinstance(raw_thresholds, Mapping):
            for key, default in thresholds.items():
                raw_value = raw_thresholds.get(key, default)
                try:
                    thresholds[key] = float(raw_value)
                except (TypeError, ValueError):
                    thresholds[key] = default

        notifications = payload.get('notifications') or {}
        if not isinstance(notifications, Mapping):
            notifications = {}

        raw_versions = learning_cfg.get('valid_affects_versions') or []
        valid_affects_versions = [str(v) for v in raw_versions] if isinstance(raw_versions, list) else []

        return cls(
            project=str(payload.get('project', '') or ''),
            poll_interval_minutes=int(payload.get('poll_interval_minutes', 5) or 5),
            validation_rules=normalized_rules,
            learning_enabled=bool(learning_cfg.get('enabled', True)),
            min_observations=int(learning_cfg.get('min_observations', 20) or 20),
            confidence_thresholds=thresholds,
            feedback_detection=bool(learning_cfg.get('feedback_detection', True)),
            keyword_extraction=bool(learning_cfg.get('keyword_extraction', True)),
            reporter_profiling=bool(learning_cfg.get('reporter_profiling', True)),
            notifications=dict(notifications),
            valid_affects_versions=valid_affects_versions,
        )


def _snake_case(value: str) -> str:
    value = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', value)
    return value.replace('-', '_').strip().lower()


def _canonical_field_name(field_name: str) -> str:
    key = _snake_case(field_name)

    if key in {'affected_version', 'affected_versions', 'affects_version', 'affects_versions', 'versions'}:
        return 'affects_versions'
    if key in {'fix_version', 'fix_versions'}:
        return 'fix_versions'
    if key in {'component', 'components'}:
        return 'components'
    if key in {'issue_type', 'issue_types', 'issuetype', 'type'}:
        return 'issue_type'

    return key


def _candidate_keys(field_name: str) -> list[str]:
    canonical = _canonical_field_name(field_name)

    candidates = [field_name, _snake_case(field_name), canonical]
    candidates.extend(_FIELD_CANDIDATES.get(canonical, []))

    seen: set[str] = set()
    unique: list[str] = []
    for key in candidates:
        if key in seen:
            continue
        seen.add(key)
        unique.append(key)
    return unique


def _value_present(field_name: str, value: Any) -> bool:
    if value is None:
        return False

    if isinstance(value, bool):
        return True

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return False

        lower_value = normalized.lower()
        if lower_value in {'none', 'null', 'n/a'}:
            return False

        if field_name == 'assignee' and lower_value == 'unassigned':
            return False
        if field_name == 'reporter' and lower_value == 'unknown':
            return False

        return True

    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0

    return True


def check_field_present(ticket_dict: Mapping[str, Any], field_name: str) -> bool:
    canonical = _canonical_field_name(field_name)

    for key in _candidate_keys(field_name):
        if key not in ticket_dict:
            continue
        if _value_present(canonical, ticket_dict.get(key)):
            return True

    return False


def _rules_for_issue_type(issue_type: str, config: MonitorConfig) -> dict[str, list[str]]:
    direct = config.validation_rules.get(issue_type)
    if direct is not None:
        return direct

    folded = issue_type.casefold()
    for known_type, rules in config.validation_rules.items():
        if known_type.casefold() == folded:
            return rules

    return {'required': [], 'warn': []}


def validate_ticket(ticket_dict: Mapping[str, Any], config: MonitorConfig) -> ValidationResult:
    ticket_key = str(ticket_dict.get('key', '') or '')
    issue_type = str(
        ticket_dict.get('issue_type')
        or ticket_dict.get('type')
        or ticket_dict.get('issuetype')
        or 'Unknown'
    )

    rules = _rules_for_issue_type(issue_type, config)
    required_fields = [str(field) for field in (rules.get('required') or [])]
    warn_fields = [str(field) for field in (rules.get('warn') or [])]

    missing_required = [
        field_name for field_name in required_fields
        if not check_field_present(ticket_dict, field_name)
    ]
    missing_warned = [
        field_name for field_name in warn_fields
        if not check_field_present(ticket_dict, field_name)
    ]

    return ValidationResult(
        ticket_key=ticket_key,
        issue_type=issue_type,
        missing_required=missing_required,
        missing_warned=missing_warned,
        ticket_data=dict(ticket_dict),
    )


def _coerce_prediction(raw_prediction: Any) -> tuple[Optional[Any], float]:
    if raw_prediction is None:
        return None, 0.0

    if isinstance(raw_prediction, tuple) and len(raw_prediction) >= 2:
        value = raw_prediction[0]
        try:
            confidence = float(raw_prediction[1])
        except (TypeError, ValueError):
            confidence = 0.0
        return value, max(0.0, min(1.0, confidence))

    if isinstance(raw_prediction, Mapping):
        value = raw_prediction.get('value')
        if value is None:
            value = raw_prediction.get('prediction')
        if value is None:
            value = raw_prediction.get('predicted')
        try:
            confidence = float(raw_prediction.get('confidence', 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        return value, max(0.0, min(1.0, confidence))

    return raw_prediction, 1.0


def _predict_for_field(
    learning_store: Any,
    field_name: str,
    validation: ValidationResult,
) -> tuple[Optional[Any], float]:
    if learning_store is None:
        return None, 0.0

    if isinstance(learning_store, Mapping):
        for key in (field_name, _canonical_field_name(field_name)):
            if key in learning_store:
                return _coerce_prediction(learning_store.get(key))
        return None, 0.0

    ticket_data = validation.ticket_data or {
        'key': validation.ticket_key,
        'issue_type': validation.issue_type,
    }

    getter = getattr(learning_store, 'get_field_prediction', None)
    if callable(getter):
        for args in (
            (field_name, ticket_data),
            (field_name, {'ticket_key': validation.ticket_key, 'issue_type': validation.issue_type}),
            (field_name,),
        ):
            try:
                return _coerce_prediction(getter(*args))
            except (TypeError, AttributeError):
                continue

    fallback_getter = getattr(learning_store, 'get_prediction', None)
    if callable(fallback_getter):
        for args in ((field_name, ticket_data), (field_name,)):
            try:
                return _coerce_prediction(fallback_getter(*args))
            except (TypeError, AttributeError):
                continue

    return None, 0.0


def determine_actions(
    validation: ValidationResult,
    learning_store: Any,
    config: MonitorConfig,
) -> ValidationResult:
    auto_threshold = float(config.confidence_thresholds.get('auto_fill', 0.90))
    suggest_threshold = float(config.confidence_thresholds.get('suggest', 0.50))

    predictions: dict[str, dict[str, Any]] = dict(validation.predictions)
    actions: list[dict[str, Any]] = list(validation.actions)

    valid_av = set(config.valid_affects_versions) if config.valid_affects_versions else set()

    def decide_action(field_name: str, severity: str) -> None:
        predicted_value: Optional[Any] = None
        confidence = 0.0

        if config.learning_enabled:
            predicted_value, confidence = _predict_for_field(learning_store, field_name, validation)

        canonical = _canonical_field_name(field_name)
        if predicted_value is not None and canonical in ('affects_versions', 'affected_version'):
            if valid_av and str(predicted_value) not in valid_av:
                predicted_value = None
                confidence = 0.0

        action = 'flag' if severity == 'required' else 'warn'
        if predicted_value is not None and confidence >= auto_threshold:
            action = 'auto_fill'
        elif predicted_value is not None and confidence >= suggest_threshold:
            action = 'suggest'

        if predicted_value is not None:
            predictions[field_name] = {
                'value': predicted_value,
                'confidence': confidence,
            }

        actions.append({
            'field': field_name,
            'severity': severity,
            'action': action,
            'confidence': confidence,
            'value': predicted_value,
        })

    for field_name in validation.missing_required:
        decide_action(field_name, 'required')

    for field_name in validation.missing_warned:
        decide_action(field_name, 'warn')

    return replace(validation, predictions=predictions, actions=actions)


def extract_keywords(text: Optional[str]) -> list[str]:
    if not text:
        return []

    tokens = re.findall(r'[a-z0-9]+', text.lower())

    keywords: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in _STOPWORDS:
            continue
        if len(token) <= 1:
            continue
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)

    return keywords


def load_monitor_config(path: str) -> MonitorConfig:
    with open(path, 'r', encoding='utf-8') as handle:
        content = handle.read()
    return MonitorConfig.from_yaml(content)
