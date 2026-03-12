from core.monitoring import (
    MonitorConfig,
    ValidationResult,
    check_field_present,
    determine_actions,
    extract_keywords,
    load_monitor_config,
    validate_ticket,
)


class _LearningStore:
    def __init__(self, mapping):
        self.mapping = mapping

    def get_field_prediction(self, field_name, *_args):
        return self.mapping.get(field_name)


def _build_config() -> MonitorConfig:
    return MonitorConfig(
        project='STL',
        validation_rules={
            'Bug': {
                'required': ['affectedVersion', 'components', 'priority', 'description'],
                'warn': ['assignee', 'labels'],
            },
            'Story': {
                'required': ['components', 'fixVersions'],
                'warn': ['assignee'],
            },
        },
        confidence_thresholds={
            'auto_fill': 0.90,
            'suggest': 0.50,
            'flag_only': 0.0,
        },
    )


def test_check_field_present_supports_camel_and_snake_aliases():
    ticket = {
        'affects_versions': ['12.1.1.x'],
        'fixVersions': [{'name': '12.2.0.x'}],
        'component': 'JKR Host Driver',
        'description': 'Crash seen during stress run',
        'assignee': 'Unassigned',
        'labels_csv': 'regression, host',
    }

    assert check_field_present(ticket, 'affectedVersion') is True
    assert check_field_present(ticket, 'fixVersions') is True
    assert check_field_present(ticket, 'components') is True
    assert check_field_present(ticket, 'labels') is True
    assert check_field_present(ticket, 'assignee') is False
    assert check_field_present(ticket, 'priority') is False


def test_validate_ticket_flags_required_and_warn_fields():
    config = _build_config()
    ticket = {
        'key': 'STL-700',
        'issue_type': 'Bug',
        'summary': 'GPU hang under load',
        'components': [],
        'description': '',
        'priority': 'P1-Critical',
        'affects_versions': [],
        'assignee': 'Unassigned',
        'labels': [],
    }

    result = validate_ticket(ticket, config)

    assert isinstance(result, ValidationResult)
    assert result.ticket_key == 'STL-700'
    assert result.issue_type == 'Bug'
    assert result.missing_required == ['affectedVersion', 'components', 'description']
    assert result.missing_warned == ['assignee', 'labels']


def test_validate_ticket_is_case_insensitive_on_issue_type():
    config = _build_config()
    ticket = {
        'key': 'STL-701',
        'issue_type': 'story',
        'components': ['BTS/verbs'],
        'fix_versions': [],
        'assignee': 'Unassigned',
    }

    result = validate_ticket(ticket, config)

    assert result.missing_required == ['fixVersions']
    assert result.missing_warned == ['assignee']


def test_determine_actions_applies_auto_fill_suggest_and_flag_paths():
    config = _build_config()
    validation = ValidationResult(
        ticket_key='STL-702',
        issue_type='Bug',
        missing_required=['affectedVersion', 'components'],
        missing_warned=['labels'],
    )

    learning_store = _LearningStore(
        {
            'affectedVersion': ('12.1.1.x', 0.95),
            'components': ('JKR Host Driver', 0.60),
            'labels': ('regression', 0.40),
        }
    )

    enriched = determine_actions(validation, learning_store, config)

    action_map = {row['field']: row for row in enriched.actions}
    assert action_map['affectedVersion']['action'] == 'auto_fill'
    assert action_map['components']['action'] == 'suggest'
    assert action_map['labels']['action'] == 'warn'

    assert enriched.predictions['affectedVersion']['value'] == '12.1.1.x'
    assert enriched.predictions['components']['value'] == 'JKR Host Driver'
    assert enriched.predictions['labels']['confidence'] == 0.40


def test_determine_actions_with_learning_disabled_keeps_flag_behavior():
    base = _build_config()
    config = MonitorConfig(
        project=base.project,
        validation_rules=base.validation_rules,
        learning_enabled=False,
        confidence_thresholds=base.confidence_thresholds,
    )

    validation = ValidationResult(
        ticket_key='STL-703',
        issue_type='Bug',
        missing_required=['components'],
        missing_warned=['labels'],
    )

    enriched = determine_actions(validation, {'components': ('FW', 0.99)}, config)

    action_map = {row['field']: row['action'] for row in enriched.actions}
    assert action_map['components'] == 'flag'
    assert action_map['labels'] == 'warn'
    assert enriched.predictions == {}


def test_extract_keywords_filters_stopwords_and_duplicates():
    text = 'Crash crash in the JKR driver and customer regression on GPU fabric'

    keywords = extract_keywords(text)

    assert keywords == ['crash', 'jkr', 'driver', 'customer', 'regression', 'gpu', 'fabric']


def test_load_monitor_config_reads_yaml(tmp_path):
    config_path = tmp_path / 'ticket_monitor.yaml'
    config_path.write_text(
        '\n'.join(
            [
                'project: STL',
                'poll_interval_minutes: 5',
                'validation_rules:',
                '  Bug:',
                '    required: [affectedVersion, components, priority, description]',
                '    warn: [assignee, labels]',
                'learning:',
                '  enabled: true',
                '  min_observations: 10',
                '  confidence_thresholds:',
                '    auto_fill: 0.91',
                '    suggest: 0.51',
                'notifications:',
                '  jira_comment: true',
            ]
        ),
        encoding='utf-8',
    )

    config = load_monitor_config(str(config_path))

    assert config.project == 'STL'
    assert config.poll_interval_minutes == 5
    assert config.validation_rules['Bug']['required'][0] == 'affectedVersion'
    assert config.min_observations == 10
    assert config.confidence_thresholds['auto_fill'] == 0.91
    assert config.notifications['jira_comment'] is True
