from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

import ticket_monitor_cli as tm_cli
import release_tracker_cli as rt_cli

@pytest.fixture()
def mock_ticket_monitor_agent():
    """Return a MagicMock that quacks like TicketMonitorAgent."""
    agent = MagicMock()
    agent.dry_run = False
    agent.get_status.return_value = {'project': 'STL', 'dry_run': False}
    agent.run.return_value = MagicMock(content='Run complete', success=True)
    agent.run_learning_only.return_value = MagicMock(content='Learning done', success=True)
    agent.learning = MagicMock()
    agent.close.return_value = None
    return agent


@pytest.fixture()
def mock_release_tracker_agent():
    """Return a MagicMock that quacks like ReleaseTrackerAgent."""
    agent = MagicMock()
    agent.tracker_config = MagicMock()
    agent.tracker_config.project = 'STL'
    agent.tracker_config.releases = ['12.1.1.x']
    agent.tracker_config.output = {'format': 'table'}
    agent.get_status.return_value = {'project': 'STL', 'releases': ['12.1.1.x']}
    agent.run.return_value = MagicMock(content='Release summary', success=True)
    agent.close.return_value = None
    return agent


class TestTicketMonitorArgParsing:

    def test_default_args(self):
        """Default args: no project, no flags, standard config/db paths."""
        parser = tm_cli._build_parser()
        args = parser.parse_args([])

        assert args.project is None
        assert args.dry_run is False
        assert args.since is None
        assert args.learn_only is False
        assert args.reset_learning is False
        assert args.config == os.path.join('config', 'ticket_monitor.yaml')
        assert args.db_dir == 'state'
        assert args.verbose is False
        assert args.status is False

    def test_dry_run_flag(self):
        """--dry-run sets dry_run=True."""
        parser = tm_cli._build_parser()
        args = parser.parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_since_accepts_iso_date(self):
        """--since stores the provided ISO date string."""
        parser = tm_cli._build_parser()
        args = parser.parse_args(['--since', '2026-03-01'])
        assert args.since == '2026-03-01'

    def test_learn_only_flag(self):
        """--learn-only sets learn_only=True."""
        parser = tm_cli._build_parser()
        args = parser.parse_args(['--learn-only'])
        assert args.learn_only is True

    def test_reset_learning_flag(self):
        """--reset-learning sets reset_learning=True."""
        parser = tm_cli._build_parser()
        args = parser.parse_args(['--reset-learning'])
        assert args.reset_learning is True

    def test_verbose_flag(self):
        """--verbose / -v sets verbose=True."""
        parser = tm_cli._build_parser()
        for flag in ['--verbose', '-v']:
            args = parser.parse_args([flag])
            assert args.verbose is True

    def test_status_flag(self):
        """--status sets status=True."""
        parser = tm_cli._build_parser()
        args = parser.parse_args(['--status'])
        assert args.status is True

    def test_config_and_db_dir_overrides(self):
        """--config and --db-dir override their defaults."""
        parser = tm_cli._build_parser()
        args = parser.parse_args(['--config', '/tmp/my.yaml', '--db-dir', '/tmp/db'])
        assert args.config == '/tmp/my.yaml'
        assert args.db_dir == '/tmp/db'


class TestTicketMonitorMain:

    @patch('ticket_monitor_cli.TicketMonitorAgent', create=True)
    def _run_main(self, argv, MockAgent, agent_instance):
        MockAgent.return_value = agent_instance
        with patch.object(sys, 'argv', ['ticket_monitor_cli.py'] + argv):
            with patch.dict('sys.modules', {
                'agents.ticket_monitor': MagicMock(TicketMonitorAgent=MockAgent),
            }):
                return tm_cli.main()

    def test_normal_run_returns_zero(self, mock_ticket_monitor_agent):
        """Normal run: creates agent, calls run(), returns 0 on success."""
        rc = self._run_main([], agent_instance=mock_ticket_monitor_agent)
        assert rc == 0
        mock_ticket_monitor_agent.run.assert_called_once()
        mock_ticket_monitor_agent.close.assert_called_once()

    def test_learn_only_calls_run_learning_only(self, mock_ticket_monitor_agent):
        """--learn-only calls run_learning_only() instead of run()."""
        rc = self._run_main(['--learn-only'], agent_instance=mock_ticket_monitor_agent)
        assert rc == 0
        mock_ticket_monitor_agent.run_learning_only.assert_called_once()
        mock_ticket_monitor_agent.run.assert_not_called()

    def test_status_calls_get_status(self, mock_ticket_monitor_agent):
        """--status calls get_status(), returns 0."""
        rc = self._run_main(['--status'], agent_instance=mock_ticket_monitor_agent)
        assert rc == 0
        mock_ticket_monitor_agent.get_status.assert_called_once()
        mock_ticket_monitor_agent.run.assert_not_called()

    def test_reset_learning_calls_reset(self, mock_ticket_monitor_agent):
        """--reset-learning calls agent.learning.reset(), returns 0."""
        rc = self._run_main(['--reset-learning'], agent_instance=mock_ticket_monitor_agent)
        assert rc == 0
        mock_ticket_monitor_agent.learning.reset.assert_called_once()

    def test_agent_run_failure_returns_one(self, mock_ticket_monitor_agent):
        """When agent.run() returns success=False, main() returns 1."""
        mock_ticket_monitor_agent.run.return_value = MagicMock(
            content='Error occurred', success=False,
        )
        rc = self._run_main([], agent_instance=mock_ticket_monitor_agent)
        assert rc == 1

    def test_keyboard_interrupt_returns_one(self, mock_ticket_monitor_agent):
        """KeyboardInterrupt during run() is caught and returns 1."""
        mock_ticket_monitor_agent.run.side_effect = KeyboardInterrupt
        rc = self._run_main([], agent_instance=mock_ticket_monitor_agent)
        assert rc == 1
        mock_ticket_monitor_agent.close.assert_called_once()

    def test_project_and_since_passed_as_overrides(self, mock_ticket_monitor_agent):
        """--project and --since are forwarded as input_data overrides."""
        self._run_main(
            ['--project', 'STLSB', '--since', '2026-01-15'],
            agent_instance=mock_ticket_monitor_agent,
        )
        call_args = mock_ticket_monitor_agent.run.call_args
        input_data = call_args[1].get('input_data') or call_args[0][0] if call_args[0] else call_args[1].get('input_data')
        assert input_data is not None
        assert input_data['project'] == 'STLSB'
        assert input_data['since'] == '2026-01-15'


class TestReleaseTrackerArgParsing:

    def test_default_args(self):
        """Default args: no project, no releases, standard config/db paths."""
        parser = rt_cli.build_parser()
        args = parser.parse_args([])

        assert args.project is None
        assert args.releases is None
        assert args.format is None
        assert args.output is None
        assert args.predict is False
        assert args.config == 'config/release_tracker.yaml'
        assert args.db_dir == 'state'
        assert args.verbose is False
        assert args.status is False

    def test_release_can_be_specified_multiple_times(self):
        """--release is append-able for tracking multiple releases."""
        parser = rt_cli.build_parser()
        args = parser.parse_args(['--release', '12.1.1.x', '--release', '12.2.0.x'])
        assert args.releases == ['12.1.1.x', '12.2.0.x']

    def test_format_accepts_valid_choices(self):
        """--format accepts table, json, csv, excel."""
        parser = rt_cli.build_parser()
        for fmt in ('table', 'json', 'csv', 'excel'):
            args = parser.parse_args(['--format', fmt])
            assert args.format == fmt

    def test_format_rejects_invalid_choice(self):
        """--format rejects values not in the choices list."""
        parser = rt_cli.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(['--format', 'xml'])

    def test_output_sets_file_path(self):
        """--output / -o stores the output file path."""
        parser = rt_cli.build_parser()
        args = parser.parse_args(['-o', '/tmp/report.json'])
        assert args.output == '/tmp/report.json'

    def test_predict_flag(self):
        """--predict sets predict=True."""
        parser = rt_cli.build_parser()
        args = parser.parse_args(['--predict'])
        assert args.predict is True


class TestReleaseTrackerMain:

    def _run_main(self, argv, agent_instance, agent_init_side_effect=None):
        MockAgent = MagicMock(return_value=agent_instance)
        if agent_init_side_effect:
            MockAgent.side_effect = agent_init_side_effect

        with patch.object(sys, 'argv', ['release_tracker_cli.py'] + argv):
            with patch.dict('sys.modules', {
                'agents.release_tracker': MagicMock(ReleaseTrackerAgent=MockAgent),
            }):
                return rt_cli.main()

    def test_normal_run_returns_zero(self, mock_release_tracker_agent, capsys):
        """Normal run: creates agent, calls run(), prints output, returns 0."""
        rc = self._run_main([], agent_instance=mock_release_tracker_agent)
        assert rc == 0
        mock_release_tracker_agent.run.assert_called_once()
        mock_release_tracker_agent.close.assert_called_once()
        captured = capsys.readouterr()
        assert 'Release summary' in captured.out

    def test_status_calls_get_status(self, mock_release_tracker_agent, capsys):
        """--status calls get_status(), prints JSON, returns 0."""
        rc = self._run_main(['--status'], agent_instance=mock_release_tracker_agent)
        assert rc == 0
        mock_release_tracker_agent.get_status.assert_called_once()
        mock_release_tracker_agent.run.assert_not_called()
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed['project'] == 'STL'

    def test_output_writes_to_file(self, mock_release_tracker_agent, tmp_path):
        """--output writes content to the specified file."""
        out_file = str(tmp_path / 'report.txt')
        rc = self._run_main(
            ['--output', out_file],
            agent_instance=mock_release_tracker_agent,
        )
        assert rc == 0
        assert os.path.exists(out_file)
        with open(out_file, 'r', encoding='utf-8') as fh:
            assert 'Release summary' in fh.read()

    def test_agent_init_failure_returns_one(self, mock_release_tracker_agent):
        """When ReleaseTrackerAgent() raises, main() returns 1."""
        rc = self._run_main(
            [],
            agent_instance=mock_release_tracker_agent,
            agent_init_side_effect=RuntimeError('Config missing'),
        )
        assert rc == 1

    def test_agent_run_failure_returns_one(self, mock_release_tracker_agent):
        """When agent.run() returns success=False, main() returns 1."""
        mock_release_tracker_agent.run.return_value = MagicMock(
            content='Failed', success=False,
        )
        rc = self._run_main([], agent_instance=mock_release_tracker_agent)
        assert rc == 1

    def test_predict_flag_forwarded(self, mock_release_tracker_agent):
        """--predict is forwarded in the input_data dict."""
        self._run_main(
            ['--predict'],
            agent_instance=mock_release_tracker_agent,
        )
        call_args = mock_release_tracker_agent.run.call_args
        input_data = call_args[0][0] if call_args[0] else call_args[1].get('input_data')
        assert input_data['predict'] is True

    def test_releases_forwarded(self, mock_release_tracker_agent):
        """--release values are forwarded in the input_data dict."""
        self._run_main(
            ['--release', '12.1.1.x', '--release', '12.2.0.x'],
            agent_instance=mock_release_tracker_agent,
        )
        call_args = mock_release_tracker_agent.run.call_args
        input_data = call_args[0][0] if call_args[0] else call_args[1].get('input_data')
        assert input_data['releases'] == ['12.1.1.x', '12.2.0.x']

    def test_excel_format_uses_csv_internally(self, mock_release_tracker_agent):
        """--format excel passes 'csv' as effective_format to agent.run()."""
        self._run_main(
            ['--format', 'excel'],
            agent_instance=mock_release_tracker_agent,
        )
        call_args = mock_release_tracker_agent.run.call_args
        input_data = call_args[0][0] if call_args[0] else call_args[1].get('input_data')
        assert input_data['format'] == 'csv'
