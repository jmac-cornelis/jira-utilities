import pytest

from state.monitor_state import MonitorState


@pytest.fixture
def monitor_state():
    store = MonitorState(':memory:')
    yield store
    store.close()


def test_checkpoint_round_trip(monitor_state):
    assert monitor_state.get_last_checked('STL') is None

    set_value = monitor_state.set_last_checked('STL', '2026-03-10T01:02:03+00:00')

    assert set_value == '2026-03-10T01:02:03+00:00'
    assert monitor_state.get_last_checked('STL') == '2026-03-10T01:02:03+00:00'


def test_set_last_checked_defaults_to_generated_timestamp(monitor_state):
    value = monitor_state.set_last_checked('STLSB')

    assert isinstance(value, str)
    assert monitor_state.get_last_checked('STLSB') == value


def test_processed_ticket_dedup(monitor_state):
    assert monitor_state.is_processed('STL-200') is False

    monitor_state.mark_processed('STL-200', project='STL', result={'missing': ['component']})

    assert monitor_state.is_processed('STL-200') is True

    history = monitor_state.get_validation_history(ticket_key='STL-200')
    assert len(history) == 1
    assert history[0]['ticket_key'] == 'STL-200'
    assert history[0]['result'] == {'missing': ['component']}


def test_mark_processed_updates_existing_row_and_appends_history(monitor_state):
    monitor_state.mark_processed(
        'STL-201',
        project='STL',
        result={'missing': ['description']},
        timestamp='2026-03-11T00:00:00+00:00',
    )
    monitor_state.mark_processed(
        'STL-201',
        project='STL',
        result={'missing': []},
        timestamp='2026-03-11T01:00:00+00:00',
    )

    cursor = monitor_state.conn.cursor()
    cursor.execute(
        """
        SELECT processed_at
        FROM processed_tickets
        WHERE ticket_key = 'STL-201'
        """
    )
    row = cursor.fetchone()

    assert row['processed_at'] == '2026-03-11T01:00:00+00:00'

    history = monitor_state.get_validation_history(ticket_key='STL-201', limit=10)
    assert len(history) == 2
    assert history[0]['result'] == {'missing': []}
    assert history[1]['result'] == {'missing': ['description']}


def test_get_validation_history_filters_by_project(monitor_state):
    monitor_state.mark_processed('STL-202', project='STL', result={'missing': ['component']})
    monitor_state.mark_processed('STLSB-1', project='STLSB', result={'missing': ['priority']})

    stl_history = monitor_state.get_validation_history(project='STL')

    assert len(stl_history) == 1
    assert stl_history[0]['ticket_key'] == 'STL-202'


def test_get_stats_and_reset(monitor_state):
    monitor_state.set_last_checked('STL', '2026-03-10T01:02:03+00:00')
    monitor_state.mark_processed('STL-203', project='STL', result={'missing': ['component']})
    monitor_state.mark_processed('STL-204', project='STL', result={'missing': []})
    monitor_state.mark_processed('STLSB-2', project='STLSB', result={'missing': ['priority']})

    stats = monitor_state.get_stats()

    assert stats['checkpoints'] == 1
    assert stats['processed_tickets'] == 3
    assert stats['validation_history'] == 3
    assert stats['processed_by_project'] == {'STL': 2, 'STLSB': 1}

    monitor_state.reset()
    reset_stats = monitor_state.get_stats()

    assert reset_stats['checkpoints'] == 0
    assert reset_stats['processed_tickets'] == 0
    assert reset_stats['validation_history'] == 0
    assert reset_stats['processed_by_project'] == {}
