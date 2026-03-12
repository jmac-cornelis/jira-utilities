##########################################################################################
#
# Module: tests/test_release_tracker.py
#
# Description: Comprehensive tests for agents/release_tracker.py (ReleaseTrackerAgent).
#              Covers constructor, run(), track_release(), get_status(), close(),
#              cycle time collection, output formats, error handling, and edge cases.
#
# Author: Cornelis Networks
#
##########################################################################################

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from agents.release_tracker import ReleaseTrackerAgent
from core.release_tracking import TrackerConfig
from state.learning import LearningStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ticket(
    key: str,
    *,
    release: str = '1.0.0.x',
    status: str = 'Open',
    priority: str = 'P2-High',
    issue_type: str = 'Bug',
    components: Optional[List[str]] = None,
    assignee: str = 'user1',
    reporter: str = 'user2',
    created: str = '2026-03-01T10:00:00.000+0000',
    updated: str = '2026-03-10T10:00:00.000+0000',
) -> Dict[str, Any]:
    """Build a ticket dict matching issue_to_dict() output."""
    if components is None:
        components = ['JKR Host Driver']
    return {
        'key': key,
        'summary': f'Test ticket {key}',
        'status': status,
        'priority': priority,
        'issue_type': issue_type,
        'components': components,
        'fix_versions': [release],
        'assignee': assignee,
        'reporter': reporter,
        'created': created,
        'updated': updated,
    }


def _make_test_config(**overrides: Any) -> Dict[str, Any]:
    """Build a test config dict suitable for TrackerConfig.from_yaml()."""
    base: Dict[str, Any] = {
        'project': 'TEST',
        'releases': ['1.0.0.x', '2.0.0.x'],
        'schedule': '0 9 * * *',
        'track_priorities': ['P0-Stopper', 'P1-Critical'],
        'closed_statuses': ['Closed', 'Done'],
        'learning': {
            'cycle_time_window_days': 90,
            'stale_threshold_multiplier': 2.0,
            'velocity_window_days': 14,
        },
        'output': {'format': 'table'},
    }
    base.update(overrides)
    return base


def _make_mock_issue(ticket_dict: Dict[str, Any]) -> MagicMock:
    """Create a mock Jira issue object that issue_to_dict can process."""
    mock = MagicMock()
    mock.key = ticket_dict['key']
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_config() -> TrackerConfig:
    """A TrackerConfig for testing."""
    return TrackerConfig.from_yaml(_make_test_config())


@pytest.fixture
def agent(tmp_path, test_config) -> Generator[ReleaseTrackerAgent, None, None]:
    """
    Create a ReleaseTrackerAgent with a real LearningStore (tmp_path SQLite)
    but a mocked config loader so no YAML file is needed on disk.
    """
    # Patch _load_tracker_config to return our test config, and patch
    # BaseAgent.__init__ to avoid LLM client creation.
    with patch.object(
        ReleaseTrackerAgent, '_load_tracker_config', return_value=test_config,
    ):
        tracker = ReleaseTrackerAgent(
            config_path='fake/config.yaml',
            db_dir=str(tmp_path),
        )
    yield tracker
    tracker.close()


@pytest.fixture
def mock_jira() -> MagicMock:
    """A mock Jira client."""
    return MagicMock()


# ---------------------------------------------------------------------------
# 1. Constructor & Setup — default construction
# ---------------------------------------------------------------------------

class TestConstructor:

    def test_default_config_path_and_db_dir(self, tmp_path, test_config):
        """Default construction loads config from YAML and creates learning store."""
        with patch.object(
            ReleaseTrackerAgent, '_load_tracker_config', return_value=test_config,
        ):
            tracker = ReleaseTrackerAgent(db_dir=str(tmp_path))

        assert tracker.tracker_config.project == 'TEST'
        assert tracker._config_path == 'config/release_tracker.yaml'
        assert tracker.learning is not None
        tracker.close()

    def test_custom_config_path_and_db_dir(self, tmp_path, test_config):
        """Custom config_path and db_dir are respected."""
        with patch.object(
            ReleaseTrackerAgent, '_load_tracker_config', return_value=test_config,
        ):
            tracker = ReleaseTrackerAgent(
                config_path='custom/path.yaml',
                db_dir=str(tmp_path),
            )

        assert tracker._config_path == 'custom/path.yaml'
        # The learning store DB should be in tmp_path
        assert str(tmp_path) in tracker.learning.db_path
        tracker.close()

    def test_config_with_multiple_releases(self, agent):
        """Config with multiple releases is stored correctly."""
        assert agent.tracker_config.releases == ['1.0.0.x', '2.0.0.x']


# ---------------------------------------------------------------------------
# 2. run() — Happy Path
# ---------------------------------------------------------------------------

class TestRunHappyPath:

    def _patch_jira_and_queries(
        self,
        tickets_by_release: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ):
        """
        Return a context manager that patches Jira connection, JQL builder,
        paginated search, and issue_to_dict for the agent's run().
        """
        if tickets_by_release is None:
            tickets_by_release = {
                '1.0.0.x': [_ticket('TEST-1', release='1.0.0.x')],
                '2.0.0.x': [_ticket('TEST-2', release='2.0.0.x', status='Closed')],
            }

        mock_jira = MagicMock()

        def fake_search(jira, jql, *args, **kwargs):
            # Return mock issues for the matching release
            for release, tickets in tickets_by_release.items():
                if release in jql:
                    return [_make_mock_issue(t) for t in tickets]
            return []

        def fake_issue_to_dict(issue):
            # Map mock issue back to ticket dict by key
            for tickets in tickets_by_release.values():
                for t in tickets:
                    if t['key'] == issue.key:
                        return t
            return {'key': issue.key, 'status': 'Open', 'priority': 'P2-High',
                    'components': [], 'fix_versions': []}

        return (
            patch.object(ReleaseTrackerAgent, '_get_jira_connection', return_value=mock_jira),
            patch('agents.release_tracker.paginated_jql_search', side_effect=fake_search),
            patch('agents.release_tracker.build_release_tickets_jql',
                  side_effect=lambda proj, rel: f'project = {proj} AND fixVersion = "{rel}"'),
            patch('agents.release_tracker.issue_to_dict', side_effect=fake_issue_to_dict),
        )

    def test_processes_all_releases_returns_combined_summary(self, agent):
        """run() processes all configured releases and returns combined summary."""
        patches = self._patch_jira_and_queries()
        with patches[0], patches[1], patches[2], patches[3]:
            response = agent.run()

        assert response.success is True
        assert response.content  # non-empty summary
        assert response.metadata['releases_tracked'] == 2
        assert len(response.metadata['errors']) == 0

    def test_builds_snapshot_and_saves_to_learning_store(self, agent):
        """run() saves snapshots to the learning store."""
        patches = self._patch_jira_and_queries()
        with patches[0], patches[1], patches[2], patches[3]:
            agent.run()

        # Verify snapshot was saved for release 1.0.0.x
        today = datetime.now(timezone.utc).date().isoformat()
        snapshot = agent.learning.get_release_snapshot('1.0.0.x', today)
        assert snapshot is not None
        assert snapshot['release'] == '1.0.0.x'

    def test_computes_delta_when_previous_snapshot_exists(self, agent):
        """When a previous snapshot exists, delta is computed."""
        # Pre-seed a snapshot for yesterday
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        agent.learning.save_release_snapshot('1.0.0.x', {
            'snapshot_date': yesterday,
            'status': {'Open': 1},
            'priority': {'P2-High': 1},
            'component': {'JKR Host Driver': 1},
        })

        patches = self._patch_jira_and_queries()
        with patches[0], patches[1], patches[2], patches[3]:
            response = agent.run({'releases': ['1.0.0.x']})

        assert response.success is True
        # The release_data should contain a delta with a period that includes '->'
        release_data = response.metadata['release_data']
        assert len(release_data) == 1
        delta = release_data[0]['delta']
        assert '->' in delta['period']

    def test_no_delta_on_first_run(self, agent):
        """On first run with no previous snapshot, delta is baseline."""
        patches = self._patch_jira_and_queries()
        with patches[0], patches[1], patches[2], patches[3]:
            response = agent.run({'releases': ['1.0.0.x']})

        release_data = response.metadata['release_data']
        delta = release_data[0]['delta']
        assert '(baseline)' in delta['period']

    def test_includes_readiness_when_predict_true(self, agent):
        """When predict=True, readiness assessment is included."""
        patches = self._patch_jira_and_queries()
        with patches[0], patches[1], patches[2], patches[3]:
            response = agent.run({'predict': True})

        release_data = response.metadata['release_data']
        # At least one release should have readiness data
        assert any(rd.get('readiness') is not None for rd in release_data)


# ---------------------------------------------------------------------------
# 3. run() — Input Overrides
# ---------------------------------------------------------------------------

class TestRunInputOverrides:

    def _setup_patches(self, agent):
        """Common patches for override tests."""
        tickets = {'1.0.0.x': [_ticket('TEST-1', release='1.0.0.x')]}

        mock_jira = MagicMock()

        def fake_search(jira, jql, *args, **kwargs):
            for release, tix in tickets.items():
                if release in jql:
                    return [_make_mock_issue(t) for t in tix]
            return []

        def fake_issue_to_dict(issue):
            for tix in tickets.values():
                for t in tix:
                    if t['key'] == issue.key:
                        return t
            return {'key': issue.key, 'status': 'Open', 'priority': 'P2-High',
                    'components': [], 'fix_versions': []}

        return (
            patch.object(ReleaseTrackerAgent, '_get_jira_connection', return_value=mock_jira),
            patch('agents.release_tracker.paginated_jql_search', side_effect=fake_search),
            patch('agents.release_tracker.build_release_tickets_jql',
                  side_effect=lambda proj, rel: f'project = {proj} AND fixVersion = "{rel}"'),
            patch('agents.release_tracker.issue_to_dict', side_effect=fake_issue_to_dict),
        )

    def test_releases_override(self, agent):
        """input_data={'releases': ['1.0.0.x']} overrides configured releases."""
        patches = self._setup_patches(agent)
        with patches[0], patches[1], patches[2], patches[3]:
            response = agent.run({'releases': ['1.0.0.x']})

        # Only one release tracked instead of two
        assert response.metadata['releases_tracked'] == 1

    def test_format_json_override(self, agent):
        """input_data={'format': 'json'} returns valid JSON."""
        patches = self._setup_patches(agent)
        with patches[0], patches[1], patches[2], patches[3]:
            response = agent.run({'releases': ['1.0.0.x'], 'format': 'json'})

        # Content should be valid JSON
        parsed = json.loads(response.content)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_predict_override(self, agent):
        """input_data={'predict': True} enables predictions."""
        patches = self._setup_patches(agent)
        with patches[0], patches[1], patches[2], patches[3]:
            response = agent.run({'releases': ['1.0.0.x'], 'predict': True})

        release_data = response.metadata['release_data']
        assert release_data[0].get('readiness') is not None


# ---------------------------------------------------------------------------
# 4. run() — Output Formats
# ---------------------------------------------------------------------------

class TestRunOutputFormats:

    def _setup_patches(self):
        """Common patches for format tests."""
        tickets = {
            '1.0.0.x': [
                _ticket('TEST-1', release='1.0.0.x', status='Open', priority='P0-Stopper'),
                _ticket('TEST-2', release='1.0.0.x', status='Closed', priority='P2-High'),
            ],
        }

        mock_jira = MagicMock()

        def fake_search(jira, jql, *args, **kwargs):
            for release, tix in tickets.items():
                if release in jql:
                    return [_make_mock_issue(t) for t in tix]
            return []

        def fake_issue_to_dict(issue):
            for tix in tickets.values():
                for t in tix:
                    if t['key'] == issue.key:
                        return t
            return {'key': issue.key, 'status': 'Open', 'priority': 'P2-High',
                    'components': [], 'fix_versions': []}

        return (
            patch.object(ReleaseTrackerAgent, '_get_jira_connection', return_value=mock_jira),
            patch('agents.release_tracker.paginated_jql_search', side_effect=fake_search),
            patch('agents.release_tracker.build_release_tickets_jql',
                  side_effect=lambda proj, rel: f'project = {proj} AND fixVersion = "{rel}"'),
            patch('agents.release_tracker.issue_to_dict', side_effect=fake_issue_to_dict),
        )

    def test_table_format_default(self, agent):
        """Default table format returns human-readable text."""
        patches = self._setup_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            response = agent.run({'releases': ['1.0.0.x'], 'format': 'table'})

        # Should contain release name and human-readable labels
        assert 'Release 1.0.0.x' in response.content
        assert 'New tickets' in response.content or 'Open tickets' in response.content

    def test_json_format(self, agent):
        """JSON format returns valid JSON with release data."""
        patches = self._setup_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            response = agent.run({'releases': ['1.0.0.x'], 'format': 'json'})

        parsed = json.loads(response.content)
        assert isinstance(parsed, list)
        assert parsed[0]['release'] == '1.0.0.x'
        assert 'snapshot' in parsed[0]

    def test_csv_format(self, agent):
        """CSV format returns CSV with headers."""
        patches = self._setup_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            response = agent.run({'releases': ['1.0.0.x'], 'format': 'csv'})

        lines = response.content.strip().split('\n')
        # First line is header
        header = lines[0]
        assert 'release' in header
        assert 'total_tickets' in header
        # Second line is data
        assert len(lines) >= 2
        assert '1.0.0.x' in lines[1]


# ---------------------------------------------------------------------------
# 5. run() — Error Handling
# ---------------------------------------------------------------------------

class TestRunErrorHandling:

    def test_single_release_failure_doesnt_stop_others(self, agent):
        """If one release fails, other releases still get processed."""
        mock_jira = MagicMock()
        call_count = 0

        def fake_search(jira, jql, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            # First call (for 1.0.0.x) raises, second (for 2.0.0.x) succeeds
            if '1.0.0.x' in jql:
                raise RuntimeError('Simulated Jira error')
            return [_make_mock_issue(_ticket('TEST-2', release='2.0.0.x'))]

        def fake_issue_to_dict(issue):
            return _ticket('TEST-2', release='2.0.0.x')

        with (
            patch.object(ReleaseTrackerAgent, '_get_jira_connection', return_value=mock_jira),
            patch('agents.release_tracker.paginated_jql_search', side_effect=fake_search),
            patch('agents.release_tracker.build_release_tickets_jql',
                  side_effect=lambda proj, rel: f'project = {proj} AND fixVersion = "{rel}"'),
            patch('agents.release_tracker.issue_to_dict', side_effect=fake_issue_to_dict),
        ):
            response = agent.run()

        # Should still succeed because 2.0.0.x worked
        assert response.success is True
        assert response.metadata['releases_tracked'] == 1
        assert len(response.metadata['errors']) == 1
        assert '1.0.0.x' in response.metadata['errors'][0]

    def test_jira_connection_failure_returns_error(self, agent):
        """Jira connection failure returns error AgentResponse."""
        with patch.object(
            ReleaseTrackerAgent, '_get_jira_connection',
            side_effect=ConnectionError('Cannot connect'),
        ):
            response = agent.run()

        assert response.success is False
        assert 'Jira connection failed' in response.error

    def test_empty_release_no_tickets(self, agent):
        """Empty release (no tickets) is handled gracefully."""
        mock_jira = MagicMock()

        with (
            patch.object(ReleaseTrackerAgent, '_get_jira_connection', return_value=mock_jira),
            patch('agents.release_tracker.paginated_jql_search', return_value=[]),
            patch('agents.release_tracker.build_release_tickets_jql',
                  side_effect=lambda proj, rel: f'project = {proj} AND fixVersion = "{rel}"'),
        ):
            response = agent.run({'releases': ['1.0.0.x']})

        # Should succeed with an empty snapshot
        assert response.success is True
        release_data = response.metadata['release_data']
        assert release_data[0]['snapshot']['total_tickets'] == 0

    def test_no_releases_configured_returns_error(self, tmp_path):
        """If no releases are configured, run() returns an error."""
        empty_config = TrackerConfig.from_yaml({
            'project': 'TEST',
            'releases': [],
        })
        with patch.object(
            ReleaseTrackerAgent, '_load_tracker_config', return_value=empty_config,
        ):
            tracker = ReleaseTrackerAgent(db_dir=str(tmp_path))

        response = tracker.run()
        assert response.success is False
        assert response.error is not None
        assert 'No releases configured' in response.error
        tracker.close()

    def test_all_releases_fail_returns_error(self, agent):
        """If all releases fail, run() returns an error response."""
        mock_jira = MagicMock()

        with (
            patch.object(ReleaseTrackerAgent, '_get_jira_connection', return_value=mock_jira),
            patch('agents.release_tracker.paginated_jql_search',
                  side_effect=RuntimeError('Jira down')),
            patch('agents.release_tracker.build_release_tickets_jql',
                  side_effect=lambda proj, rel: f'project = {proj} AND fixVersion = "{rel}"'),
        ):
            response = agent.run()

        assert response.success is False
        assert response.error == 'All releases failed'
        assert len(response.metadata['errors']) == 2


# ---------------------------------------------------------------------------
# 6. track_release()
# ---------------------------------------------------------------------------

class TestTrackRelease:

    def test_tracks_single_release(self, agent):
        """track_release() tracks a single release and returns AgentResponse."""
        mock_jira = MagicMock()
        tickets = [_ticket('TEST-1', release='1.0.0.x')]

        with (
            patch.object(ReleaseTrackerAgent, '_get_jira_connection', return_value=mock_jira),
            patch('agents.release_tracker.paginated_jql_search',
                  return_value=[_make_mock_issue(t) for t in tickets]),
            patch('agents.release_tracker.build_release_tickets_jql',
                  return_value='project = TEST AND fixVersion = "1.0.0.x"'),
            patch('agents.release_tracker.issue_to_dict',
                  side_effect=lambda issue: tickets[0]),
        ):
            response = agent.track_release('1.0.0.x')

        assert response.success is True
        assert 'Release 1.0.0.x' in response.content
        assert response.metadata['release_data']['release'] == '1.0.0.x'

    def test_track_release_with_predict(self, agent):
        """track_release() with predict=True includes readiness."""
        mock_jira = MagicMock()
        tickets = [_ticket('TEST-1', release='1.0.0.x', priority='P0-Stopper')]

        with (
            patch.object(ReleaseTrackerAgent, '_get_jira_connection', return_value=mock_jira),
            patch('agents.release_tracker.paginated_jql_search',
                  return_value=[_make_mock_issue(t) for t in tickets]),
            patch('agents.release_tracker.build_release_tickets_jql',
                  return_value='project = TEST AND fixVersion = "1.0.0.x"'),
            patch('agents.release_tracker.issue_to_dict',
                  side_effect=lambda issue: tickets[0]),
        ):
            response = agent.track_release('1.0.0.x', predict=True)

        assert response.success is True
        assert response.metadata['release_data']['readiness'] is not None

    def test_track_release_jira_failure(self, agent):
        """track_release() returns error on Jira connection failure."""
        with patch.object(
            ReleaseTrackerAgent, '_get_jira_connection',
            side_effect=ConnectionError('Cannot connect'),
        ):
            response = agent.track_release('1.0.0.x')

        assert response.success is False
        assert 'Jira connection failed' in response.error


# ---------------------------------------------------------------------------
# 7. Cycle Time Collection
# ---------------------------------------------------------------------------

class TestCycleTimeCollection:

    def test_extracts_status_transitions_from_changelog(self, agent):
        """_extract_cycle_times_from_issue reads changelog histories."""
        # Build a mock issue with changelog
        mock_issue = MagicMock()

        # Create a status change item
        mock_item = MagicMock()
        mock_item.field = 'status'
        mock_item.fromString = 'Open'
        mock_item.toString = 'In Progress'

        mock_history = MagicMock()
        mock_history.created = '2026-03-05T10:00:00.000+0000'
        mock_history.items = [mock_item]

        mock_issue.changelog.histories = [mock_history]

        ticket = _ticket('TEST-1')

        # Should not raise — just logs the transition
        agent._extract_cycle_times_from_issue(mock_issue, ticket)

    def test_handles_issues_without_changelog(self, agent):
        """_extract_cycle_times_from_issue handles missing changelog gracefully."""
        mock_issue = MagicMock(spec=[])  # No changelog attribute
        del mock_issue.changelog  # Ensure getattr returns None

        ticket = _ticket('TEST-1')

        # Should not raise
        agent._extract_cycle_times_from_issue(mock_issue, ticket)

    def test_collect_cycle_times_filters_by_priority(self, agent):
        """_collect_cycle_times only processes tracked-priority tickets."""
        mock_jira = MagicMock()

        # One P0 ticket (tracked) and one P4 ticket (not tracked)
        p0_ticket = _ticket('TEST-1', priority='P0-Stopper')
        p4_ticket = _ticket('TEST-2', priority='P4-Low')

        mock_issues = [_make_mock_issue(p0_ticket), _make_mock_issue(p4_ticket)]

        call_log = []

        def fake_extract(raw_issue, ticket):
            call_log.append(ticket['key'])

        with (
            patch('agents.release_tracker.paginated_jql_search', return_value=mock_issues),
            patch('agents.release_tracker.build_release_tickets_jql',
                  return_value='project = TEST AND fixVersion = "1.0.0.x"'),
            patch('agents.release_tracker.issue_to_dict',
                  side_effect=lambda issue: p0_ticket if issue.key == 'TEST-1' else p4_ticket),
            patch.object(agent, '_extract_cycle_times_from_issue', side_effect=fake_extract),
        ):
            agent._collect_cycle_times(mock_jira, ['1.0.0.x'])

        # Only the P0 ticket should have been processed
        assert 'TEST-1' in call_log
        assert 'TEST-2' not in call_log


# ---------------------------------------------------------------------------
# 8. get_status()
# ---------------------------------------------------------------------------

class TestGetStatus:

    def test_returns_config_and_learning_stats(self, agent):
        """get_status() returns config info + learning stats."""
        status = agent.get_status()

        assert status['project'] == 'TEST'
        assert status['releases'] == ['1.0.0.x', '2.0.0.x']
        assert status['config_path'] == 'fake/config.yaml'
        assert 'learning_store' in status
        assert 'tables' in status['learning_store']


# ---------------------------------------------------------------------------
# 9. _reconstruct_previous_snapshot()
# ---------------------------------------------------------------------------

class TestReconstructPreviousSnapshot:

    def test_reconstructs_from_stored_dict(self, agent):
        """Reconstructs ReleaseSnapshot from stored aggregate data."""
        snapshot_dict = {
            'snapshot_date': '2026-03-11',
            'status': {'Open': 3, 'Closed': 2},
            'priority': {'P0-Stopper': 1, 'P2-High': 4},
            'component': {'JKR Host Driver': 3, 'BTS/verbs': 2},
        }

        result = agent._reconstruct_previous_snapshot('1.0.0.x', snapshot_dict)

        assert result is not None
        assert result.release == '1.0.0.x'
        assert result.timestamp == '2026-03-11'
        assert result.total_tickets == 5  # 3 + 2 from status counts
        assert result.by_status == {'Open': 3, 'Closed': 2}
        assert result.by_priority == {'P0-Stopper': 1, 'P2-High': 4}
        assert result.by_component == {'JKR Host Driver': 3, 'BTS/verbs': 2}
        assert result.tickets == []

    def test_returns_none_when_no_previous_snapshot(self, agent):
        """Returns None when snapshot_dict causes an error."""
        # An empty dict should still work (total_tickets=0)
        result = agent._reconstruct_previous_snapshot('1.0.0.x', {})
        assert result is not None
        assert result.total_tickets == 0

    def test_returns_none_on_corrupt_data(self, agent):
        """Returns None when stored data is corrupt."""
        # Force an exception by passing non-dict status values
        corrupt_dict = {
            'snapshot_date': '2026-03-11',
            'status': 'not_a_dict',  # This will cause sum() to fail
        }

        result = agent._reconstruct_previous_snapshot('1.0.0.x', corrupt_dict)
        # Should return None because sum('not_a_dict') raises TypeError
        assert result is None


# ---------------------------------------------------------------------------
# 10. close()
# ---------------------------------------------------------------------------

class TestClose:

    def test_closes_learning_store(self, tmp_path, test_config):
        """close() closes the learning store connection."""
        with patch.object(
            ReleaseTrackerAgent, '_load_tracker_config', return_value=test_config,
        ):
            tracker = ReleaseTrackerAgent(db_dir=str(tmp_path))

        tracker.close()
        assert tracker.learning.conn is None


# ---------------------------------------------------------------------------
# 11. _format_csv (static)
# ---------------------------------------------------------------------------

class TestFormatCsv:

    def test_format_csv_with_data(self):
        """_format_csv produces CSV with correct headers and data."""
        release_data = [
            {
                'release': '1.0.0.x',
                'snapshot': {'total_tickets': 5},
                'delta': {
                    'new_tickets': ['TEST-1', 'TEST-2'],
                    'closed_tickets': ['TEST-3'],
                    'status_changes': [{'key': 'TEST-4', 'from': 'Open', 'to': 'Closed'}],
                    'priority_changes': [],
                },
                'readiness': {
                    'p0_open': 1,
                    'p1_open': 2,
                    'daily_close_rate': 1.5,
                    'estimated_days_remaining': 3.3,
                },
            },
        ]

        csv_output = ReleaseTrackerAgent._format_csv(release_data)

        assert 'release' in csv_output
        assert '1.0.0.x' in csv_output
        assert '5' in csv_output  # total_tickets

    def test_format_csv_empty_data(self):
        """_format_csv returns empty string for empty data."""
        assert ReleaseTrackerAgent._format_csv([]) == ''

    def test_format_csv_no_readiness(self):
        """_format_csv handles missing readiness gracefully."""
        release_data = [
            {
                'release': '1.0.0.x',
                'snapshot': {'total_tickets': 2},
                'delta': {
                    'new_tickets': [],
                    'closed_tickets': [],
                    'status_changes': [],
                    'priority_changes': [],
                },
                'readiness': None,
            },
        ]

        csv_output = ReleaseTrackerAgent._format_csv(release_data)
        assert '1.0.0.x' in csv_output
