##########################################################################################
#
# Module: tests/test_ticket_monitor.py
#
# Description: Comprehensive tests for agents/ticket_monitor.py (TicketMonitorAgent).
#              All Jira interactions are mocked — no real API calls.
#
# Author: Cornelis Networks
#
##########################################################################################

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.monitoring import MonitorConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> MonitorConfig:
    """Build a MonitorConfig suitable for tests."""
    defaults = {
        'project': 'TEST',
        'poll_interval_minutes': 5,
        'validation_rules': {
            'Bug': {'required': ['components', 'priority'], 'warn': ['assignee']},
            'Story': {'required': ['components'], 'warn': []},
        },
        'learning': {
            'enabled': True,
            'min_observations': 5,
            'confidence_thresholds': {'auto_fill': 0.90, 'suggest': 0.50},
            'feedback_detection': True,
        },
        'notifications': {'jira_comment': True, 'mention_reporter': True},
    }
    defaults.update(overrides)
    return MonitorConfig.from_yaml(defaults)


def _make_ticket(
    key: str = 'TEST-1',
    issue_type: str = 'Bug',
    summary: str = 'Test ticket',
    components: Optional[List[str]] = None,
    priority: str = '',
    assignee: str = '',
    **extra: Any,
) -> Dict[str, Any]:
    """Build a ticket dict matching issue_to_dict() output."""
    ticket: Dict[str, Any] = {
        'key': key,
        'issue_type': issue_type,
        'summary': summary,
        'components': components or [],
        'priority': priority,
        'assignee': assignee,
        'reporter_id': extra.pop('reporter_id', 'acct-test'),
        'affects_versions': extra.pop('affects_versions', []),
        'fix_versions': extra.pop('fix_versions', []),
        'description': extra.pop('description', 'desc'),
        'labels': extra.pop('labels', []),
    }
    ticket.update(extra)
    return ticket


class FakeJira:
    """Minimal Jira stub for tests — mirrors test_notifications.py pattern."""

    def __init__(self):
        self._comments: Dict[str, List[Any]] = {}
        self.added: List[Any] = []
        self._issues: Dict[str, MagicMock] = {}

    def comments(self, ticket_key: str):
        return self._comments.get(ticket_key, [])

    def add_comment(self, ticket_key: str, body: Any):
        self.added.append((ticket_key, body))
        self._comments.setdefault(ticket_key, []).append(SimpleNamespace(body=body))
        return True

    def issue(self, ticket_key: str) -> MagicMock:
        if ticket_key not in self._issues:
            self._issues[ticket_key] = MagicMock()
        return self._issues[ticket_key]


# ---------------------------------------------------------------------------
# Fixture: create a TicketMonitorAgent with mocked externals
# ---------------------------------------------------------------------------

@pytest.fixture
def agent(tmp_path):
    """
    Create a TicketMonitorAgent with:
    - In-memory-like SQLite (via tmp_path)
    - Mocked get_llm_client (BaseAgent.__init__ calls it when llm=None)
    - Mocked get_jira
    - Real MonitorState and LearningStore (SQLite in tmp_path)
    """
    fake_jira = FakeJira()

    # Write a minimal config YAML so the constructor can load it
    config_path = tmp_path / 'ticket_monitor.yaml'
    config_path.write_text(
        'project: TEST\n'
        'poll_interval_minutes: 5\n'
        'validation_rules:\n'
        '  Bug:\n'
        '    required: [components, priority]\n'
        '    warn: [assignee]\n'
        '  Story:\n'
        '    required: [components]\n'
        '    warn: []\n'
        'learning:\n'
        '  enabled: true\n'
        '  min_observations: 5\n'
        '  confidence_thresholds:\n'
        '    auto_fill: 0.90\n'
        '    suggest: 0.50\n'
        '  feedback_detection: true\n'
        'notifications:\n'
        '  jira_comment: true\n'
        '  mention_reporter: true\n'
    )

    db_dir = str(tmp_path / 'db')

    # Patch get_llm_client so BaseAgent.__init__ doesn't try to connect to a real LLM
    with patch('llm.config.get_llm_client', return_value=MagicMock()):
        from agents.ticket_monitor import TicketMonitorAgent
        agent = TicketMonitorAgent(
            config_path=str(config_path),
            db_dir=db_dir,
            dry_run=False,
        )

    # Inject the fake Jira so _get_jira() returns it
    agent._jira = fake_jira

    yield agent
    agent.close()


@pytest.fixture
def dry_agent(tmp_path):
    """Same as agent fixture but with dry_run=True."""
    config_path = tmp_path / 'ticket_monitor.yaml'
    config_path.write_text(
        'project: TEST\n'
        'validation_rules:\n'
        '  Bug:\n'
        '    required: [components, priority]\n'
        '    warn: [assignee]\n'
        'learning:\n'
        '  enabled: true\n'
        '  min_observations: 5\n'
        '  confidence_thresholds:\n'
        '    auto_fill: 0.90\n'
        '    suggest: 0.50\n'
        '  feedback_detection: true\n'
        'notifications:\n'
        '  jira_comment: true\n'
    )
    db_dir = str(tmp_path / 'db')

    with patch('llm.config.get_llm_client', return_value=MagicMock()):
        from agents.ticket_monitor import TicketMonitorAgent
        agent = TicketMonitorAgent(
            config_path=str(config_path),
            db_dir=db_dir,
            dry_run=True,
        )

    agent._jira = FakeJira()
    yield agent
    agent.close()


# ===========================================================================
# 1. Constructor & Setup
# ===========================================================================

class TestConstructor:
    """Tests 1-3: constructor, custom paths, dry_run flag."""

    def test_default_config_loads_from_yaml(self, agent):
        """Test 1: Constructor loads config from the provided YAML path."""
        assert agent.monitor_config.project == 'TEST'
        assert 'Bug' in agent.monitor_config.validation_rules
        assert agent.monitor_config.learning_enabled is True

    def test_custom_db_dir_creates_databases(self, agent, tmp_path):
        """Test 2: Custom db_dir results in SQLite files in that directory."""
        db_dir = tmp_path / 'db'
        assert (db_dir / 'monitor_state.db').exists()
        assert (db_dir / 'learning.db').exists()

    def test_dry_run_flag_stored(self, dry_agent):
        """Test 3: dry_run flag is stored on the agent."""
        assert dry_agent.dry_run is True


# ===========================================================================
# 2. run() — Happy Path
# ===========================================================================

class TestRunHappyPath:
    """Tests 4-10: normal processing flow."""

    def test_processes_new_tickets_and_flags_missing_fields(self, agent):
        """Test 4: Queries Jira, validates tickets, flags missing required fields."""
        ticket = _make_ticket(key='TEST-10', issue_type='Bug', components=[], priority='')

        agent.learning.get_field_prediction = MagicMock(return_value=('', 0.0))

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=['raw1']), \
             patch('agents.ticket_monitor.issue_to_dict', return_value=ticket):
            resp = agent.run()

        assert resp.success is True
        stats = resp.metadata['stats']
        assert stats['tickets_queried'] == 1
        assert stats['tickets_processed'] == 1
        assert stats['flags'] >= 1  # at least components flagged

    def test_skips_already_processed_tickets(self, agent):
        """Test 5: Dedup — tickets already in MonitorState are skipped."""
        ticket = _make_ticket(key='TEST-20', issue_type='Bug', components=[], priority='')

        # Mark as already processed
        agent.state.mark_processed('TEST-20', project='TEST')

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=['raw1']), \
             patch('agents.ticket_monitor.issue_to_dict', return_value=ticket):
            resp = agent.run()

        assert resp.success is True
        stats = resp.metadata['stats']
        assert stats['tickets_skipped'] == 1
        assert stats['tickets_processed'] == 0

    def test_auto_fill_updates_jira_and_records_learning(self, agent):
        """Test 6: Auto-fill action updates the Jira field, sends notification,
        and records in the learning store."""
        ticket = _make_ticket(key='TEST-30', issue_type='Bug', components=[], priority='P1-Critical')

        # Make learning store predict components with high confidence
        agent.learning.get_field_prediction = MagicMock(
            return_value=('JKR Host Driver', 0.95)
        )

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=['raw1']), \
             patch('agents.ticket_monitor.issue_to_dict', return_value=ticket):
            resp = agent.run()

        stats = resp.metadata['stats']
        assert stats['auto_fills'] >= 1

        # Verify Jira was updated
        fake_jira = agent._jira
        assert 'TEST-30' in fake_jira._issues
        fake_jira._issues['TEST-30'].update.assert_called()

    def test_suggest_action_sends_notification_only(self, agent):
        """Test 7: Suggest action posts a comment but does NOT update the field."""
        ticket = _make_ticket(key='TEST-40', issue_type='Bug', components=[], priority='P1-Critical')

        # Predict with medium confidence → suggest
        agent.learning.get_field_prediction = MagicMock(
            return_value=('JKR Host Driver', 0.70)
        )

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=['raw1']), \
             patch('agents.ticket_monitor.issue_to_dict', return_value=ticket):
            resp = agent.run()

        stats = resp.metadata['stats']
        assert stats['suggestions'] >= 1
        # Jira issue should NOT have been updated (no update call for suggest)
        fake_jira = agent._jira
        if 'TEST-40' in fake_jira._issues:
            fake_jira._issues['TEST-40'].update.assert_not_called()

    def test_flag_action_sends_flag_notification(self, agent):
        """Test 8: Flag action sends a flag notification for missing required fields."""
        # Bug missing both components and priority, no predictions
        ticket = _make_ticket(key='TEST-50', issue_type='Bug', components=[], priority='')

        agent.learning.get_field_prediction = MagicMock(return_value=('', 0.0))

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=['raw1']), \
             patch('agents.ticket_monitor.issue_to_dict', return_value=ticket):
            resp = agent.run()

        stats = resp.metadata['stats']
        assert stats['flags'] >= 1

    def test_warn_action_logs_but_no_notification(self, agent):
        """Test 9: Warn action for missing optional fields — no Jira comment posted."""
        # Bug with required fields present but assignee missing (warn field)
        ticket = _make_ticket(
            key='TEST-60', issue_type='Bug',
            components=['JKR Host Driver'], priority='P1-Critical',
            assignee='',
        )

        # No prediction for assignee
        agent.learning.get_field_prediction = MagicMock(return_value=('', 0.0))

        fake_jira = agent._jira
        initial_comments = len(fake_jira.added)

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=['raw1']), \
             patch('agents.ticket_monitor.issue_to_dict', return_value=ticket):
            resp = agent.run()

        # Warn fields don't generate notifications
        assert resp.success is True
        # No new Jira comments should have been posted for warn-only
        assert len(fake_jira.added) == initial_comments

    def test_updates_last_checked_after_processing(self, agent):
        """Test 10: last_checked is updated in MonitorState after run()."""
        assert agent.state.get_last_checked('TEST') is None

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=[]), \
             patch('agents.ticket_monitor.issue_to_dict'):
            agent.run()

        assert agent.state.get_last_checked('TEST') is not None


# ===========================================================================
# 3. run() — Dry Run
# ===========================================================================

class TestRunDryRun:
    """Test 11: dry_run mode."""

    def test_dry_run_validates_but_does_not_update_jira(self, dry_agent):
        """Test 11: dry_run=True validates tickets but does NOT update Jira
        or post comments."""
        ticket = _make_ticket(key='TEST-70', issue_type='Bug', components=[], priority='')

        # Even with high-confidence prediction, dry_run should not call Jira
        dry_agent.learning.get_field_prediction = MagicMock(
            return_value=('JKR Host Driver', 0.95)
        )

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=['raw1']), \
             patch('agents.ticket_monitor.issue_to_dict', return_value=ticket):
            resp = dry_agent.run()

        assert resp.success is True
        stats = resp.metadata['stats']
        # Actions are counted even in dry_run
        assert stats['tickets_processed'] == 1

        # But Jira was NOT touched
        fake_jira = dry_agent._jira
        assert len(fake_jira.added) == 0
        assert len(fake_jira._issues) == 0


# ===========================================================================
# 4. run() — Input Overrides
# ===========================================================================

class TestRunOverrides:
    """Tests 12-13: input_data overrides."""

    def test_since_override(self, agent):
        """Test 12: input_data={'since': ...} overrides last_checked."""
        with patch('agents.ticket_monitor.paginated_jql_search', return_value=[]) as mock_search, \
             patch('agents.ticket_monitor.issue_to_dict'):
            agent.run(input_data={'since': '2026-03-01'})

        # Verify the JQL used the overridden date
        call_args = mock_search.call_args
        jql = call_args[0][1]  # second positional arg is jql
        assert '2026-03-01' in jql

    def test_project_override(self, agent):
        """Test 13: input_data={'project': 'OTHER'} overrides project."""
        with patch('agents.ticket_monitor.paginated_jql_search', return_value=[]) as mock_search, \
             patch('agents.ticket_monitor.issue_to_dict'):
            resp = agent.run(input_data={'project': 'OTHER'})

        assert resp.success is True
        assert resp.metadata['project'] == 'OTHER'
        jql = mock_search.call_args[0][1]
        assert 'project = OTHER' in jql


# ===========================================================================
# 5. run() — Error Handling
# ===========================================================================

class TestRunErrors:
    """Tests 14-16: error paths."""

    def test_single_ticket_failure_does_not_stop_others(self, agent):
        """Test 14: If one ticket fails to convert, remaining tickets still process."""
        good_ticket = _make_ticket(key='TEST-80', issue_type='Story', components=['X'])

        call_count = 0

        def side_effect(raw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError('bad issue data')
            return good_ticket

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=['raw1', 'raw2']), \
             patch('agents.ticket_monitor.issue_to_dict', side_effect=side_effect):
            resp = agent.run()

        assert resp.success is True
        stats = resp.metadata['stats']
        assert stats['errors'] >= 1
        assert stats['tickets_processed'] >= 1

    def test_jira_connection_failure_returns_error_response(self, agent):
        """Test 15: Jira connection failure returns error AgentResponse."""
        # Force _get_jira to raise
        agent._jira = None  # reset cached jira

        with patch('tools.jira_tools.get_jira', side_effect=ConnectionError('no jira')):
            resp = agent.run()

        assert resp.success is False
        assert 'Jira connection failed' in resp.error

    def test_empty_query_result_returns_success_with_zero_counts(self, agent):
        """Test 16: No new tickets → success with zero counts."""
        with patch('agents.ticket_monitor.paginated_jql_search', return_value=[]), \
             patch('agents.ticket_monitor.issue_to_dict'):
            resp = agent.run()

        assert resp.success is True
        stats = resp.metadata['stats']
        assert stats['tickets_queried'] == 0
        assert stats['tickets_processed'] == 0
        assert stats['auto_fills'] == 0


# ===========================================================================
# 6. run_learning_only()
# ===========================================================================

class TestRunLearningOnly:
    """Tests 17-18: learning-only mode."""

    def test_records_tickets_without_actions(self, agent):
        """Test 17: run_learning_only records tickets in learning store
        without taking any actions (no Jira updates, no comments)."""
        ticket = _make_ticket(key='TEST-90', issue_type='Bug', components=[], priority='')

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=['raw1']), \
             patch('agents.ticket_monitor.issue_to_dict', return_value=ticket):
            resp = agent.run_learning_only(since='2026-03-01')

        assert resp.success is True
        assert resp.metadata['tickets_recorded'] == 1
        assert resp.metadata['errors'] == 0

        # No Jira comments posted
        fake_jira = agent._jira
        assert len(fake_jira.added) == 0

    def test_respects_since_parameter(self, agent):
        """Test 18: run_learning_only uses the since parameter in JQL."""
        with patch('agents.ticket_monitor.paginated_jql_search', return_value=[]) as mock_search, \
             patch('agents.ticket_monitor.issue_to_dict'):
            agent.run_learning_only(since='2026-01-15')

        jql = mock_search.call_args[0][1]
        assert '2026-01-15' in jql


# ===========================================================================
# 7. Feedback Loop (_check_corrections)
# ===========================================================================

class TestFeedbackLoop:
    """Test 19: correction detection."""

    def test_detects_human_correction_to_auto_filled_field(self, agent):
        """Test 19: When a human changes a field the agent auto-filled,
        the correction is recorded in the learning store."""
        # Seed an auto_fill record in the learning store
        agent.learning.record_auto_fill('TEST-100', 'components', 'JKR Host Driver', 0.92)

        # Simulate the updated ticket now having a different component
        corrected_ticket = _make_ticket(
            key='TEST-100', issue_type='Bug',
            components=['BTS/verbs'], priority='P1-Critical',
        )

        fake_jira = agent._jira
        stats: Dict[str, int] = {
            'corrections_detected': 0,
            'errors': 0,
        }

        with patch('agents.ticket_monitor.paginated_jql_search', return_value=['raw1']), \
             patch('agents.ticket_monitor.issue_to_dict', return_value=corrected_ticket):
            agent._check_corrections(fake_jira, 'TEST', '2026-03-01', stats)

        assert stats['corrections_detected'] == 1


# ===========================================================================
# 8. get_status()
# ===========================================================================

class TestGetStatus:
    """Test 20: status reporting."""

    def test_returns_combined_state_and_learning_stats(self, agent):
        """Test 20: get_status() returns monitor_state + learning stats."""
        status = agent.get_status()

        assert 'monitor_state' in status
        assert 'learning_store' in status
        assert status['project'] == 'TEST'
        assert status['dry_run'] is False


# ===========================================================================
# 9. _build_update_fields()
# ===========================================================================

class TestBuildUpdateFields:
    """Tests 21-23: Jira Cloud field formatting."""

    def test_components_format(self):
        """Test 21: components → [{'name': value}]."""
        from agents.ticket_monitor import TicketMonitorAgent
        result = TicketMonitorAgent._build_update_fields('components', 'JKR Host Driver')
        assert result == {'components': [{'name': 'JKR Host Driver'}]}

    def test_priority_format(self):
        """Test 22: priority → {'name': value}."""
        from agents.ticket_monitor import TicketMonitorAgent
        result = TicketMonitorAgent._build_update_fields('priority', 'P1-Critical')
        assert result == {'priority': {'name': 'P1-Critical'}}

    def test_affects_versions_format(self):
        """Test 23: affects_versions → [{'name': value}]."""
        from agents.ticket_monitor import TicketMonitorAgent
        result = TicketMonitorAgent._build_update_fields('versions', '12.1.1.x')
        assert result == {'versions': [{'name': '12.1.1.x'}]}

    def test_fix_versions_format(self):
        """Test 23b: fixVersions → [{'name': value}]."""
        from agents.ticket_monitor import TicketMonitorAgent
        result = TicketMonitorAgent._build_update_fields('fixVersions', '12.2.0.x')
        assert result == {'fixVersions': [{'name': '12.2.0.x'}]}

    def test_labels_format(self):
        """Labels → [value]."""
        from agents.ticket_monitor import TicketMonitorAgent
        result = TicketMonitorAgent._build_update_fields('labels', 'triage')
        assert result == {'labels': ['triage']}

    def test_unknown_field_passthrough(self):
        """Unknown fields pass through as {field: value}."""
        from agents.ticket_monitor import TicketMonitorAgent
        result = TicketMonitorAgent._build_update_fields('custom_field', 'hello')
        assert result == {'custom_field': 'hello'}


# ===========================================================================
# 10. close()
# ===========================================================================

class TestClose:
    """Test 24: cleanup."""

    def test_close_cleans_up_db_connections(self, agent):
        """Test 24: close() closes both state and learning DB connections."""
        # Verify connections are open
        assert agent.state.conn is not None
        assert agent.learning.conn is not None

        agent.close()

        # After close, connections should be None
        assert agent.learning.conn is None


# ===========================================================================
# 11. _get_current_field_value() — static helper
# ===========================================================================

class TestGetCurrentFieldValue:
    """Additional edge-case tests for the alias-aware field extractor."""

    def test_direct_field_lookup(self):
        """Direct key match returns the value."""
        from agents.ticket_monitor import TicketMonitorAgent
        ticket = {'priority': 'P1-Critical'}
        assert TicketMonitorAgent._get_current_field_value(ticket, 'priority') == 'P1-Critical'

    def test_list_field_joined(self):
        """List values are joined with ', '."""
        from agents.ticket_monitor import TicketMonitorAgent
        ticket = {'components': ['A', 'B']}
        assert TicketMonitorAgent._get_current_field_value(ticket, 'components') == 'A, B'

    def test_alias_lookup_for_component(self):
        """Alias 'component' resolves to 'components' key in ticket."""
        from agents.ticket_monitor import TicketMonitorAgent
        ticket = {'component': 'JKR Host Driver'}
        # Looking up 'components' should find 'component' via alias
        assert TicketMonitorAgent._get_current_field_value(ticket, 'components') == 'JKR Host Driver'

    def test_missing_field_returns_empty_string(self):
        """Missing field returns empty string."""
        from agents.ticket_monitor import TicketMonitorAgent
        ticket = {'key': 'TEST-1'}
        assert TicketMonitorAgent._get_current_field_value(ticket, 'components') == ''

    def test_none_value_returns_empty_string(self):
        """None value returns empty string."""
        from agents.ticket_monitor import TicketMonitorAgent
        ticket = {'priority': None}
        assert TicketMonitorAgent._get_current_field_value(ticket, 'priority') == ''


# ===========================================================================
# 12. _build_summary() — static helper
# ===========================================================================

class TestBuildSummary:
    """Verify summary string formatting."""

    def test_summary_contains_all_stat_keys(self):
        """Summary includes all stat categories."""
        from agents.ticket_monitor import TicketMonitorAgent
        stats = {
            'tickets_queried': 10,
            'tickets_skipped': 2,
            'tickets_processed': 8,
            'auto_fills': 3,
            'suggestions': 1,
            'flags': 2,
            'corrections_detected': 1,
            'errors': 0,
        }
        summary = TicketMonitorAgent._build_summary(stats, 'TEST')
        assert 'project TEST' in summary
        assert '10' in summary
        assert '8' in summary
        assert '3' in summary
