import pytest

from state.learning import LearningStore


@pytest.fixture
def learning_store():
    store = LearningStore(':memory:')
    yield store
    store.close()


def test_learning_store_creates_required_tables(learning_store):
    cursor = learning_store.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row['name'] for row in cursor.fetchall()}

    assert 'observations' in names
    assert 'keyword_patterns' in names
    assert 'reporter_profiles' in names
    assert 'cycle_times' in names
    assert 'release_snapshots' in names
    assert 'auto_fill_log' in names


def test_record_ticket_and_predict_component(learning_store):
    learning_store.record_ticket(
        {
            'key': 'STL-100',
            'summary': 'Crash in host driver during init',
            'components': ['JKR Host Driver'],
            'reporter_id': 'acct-a',
            'affects_versions': ['12.1.1.x'],
            'priority': 'P1-Critical',
        }
    )

    predicted, confidence = learning_store.predict_component(
        {'summary': 'Host driver crash blocks boot'}
    )

    assert predicted == 'JKR Host Driver'
    assert confidence > 0.0

    field_value, field_conf = learning_store.get_field_prediction(
        'components',
        {'summary': 'Host driver crash blocks boot'},
    )

    assert field_value == 'JKR Host Driver'
    assert field_conf == pytest.approx(confidence)


def test_predict_affects_version_uses_reporter_history(learning_store):
    learning_store.record_ticket(
        {
            'key': 'STL-101',
            'summary': 'Link issue in verbs path',
            'component': 'BTS/verbs',
            'reporter_id': 'acct-r1',
            'affects_version': '12.1.1.x',
            'priority': 'P2-High',
        }
    )
    learning_store.record_ticket(
        {
            'key': 'STL-102',
            'summary': 'Another verbs issue',
            'component': 'BTS/verbs',
            'reporter_id': 'acct-r1',
            'affects_version': '12.1.1.x',
            'priority': 'P2-High',
        }
    )
    learning_store.record_ticket(
        {
            'key': 'STL-103',
            'summary': 'One outlier for same reporter',
            'component': 'BTS/verbs',
            'reporter_id': 'acct-r1',
            'affects_version': '12.2.0.x',
            'priority': 'P2-High',
        }
    )

    predicted, confidence = learning_store.predict_affects_version({'reporter_id': 'acct-r1'})

    assert predicted == '12.1.1.x'
    assert confidence == pytest.approx(2 / 5)

    field_value, field_conf = learning_store.get_field_prediction(
        'affects_version',
        {'reporter_id': 'acct-r1'},
    )

    assert field_value == '12.1.1.x'
    assert field_conf == pytest.approx(2 / 5)


def test_record_observation_updates_keyword_map(learning_store):
    learning_store.record_ticket(
        {
            'key': 'STL-104',
            'summary': 'Crash in fabric path',
            'component': 'CN5000 FM',
            'reporter_id': 'acct-r2',
            'affects_version': '12.1.1.x',
            'priority': 'P1-Critical',
        }
    )

    before = learning_store.get_keyword_component_map()['crash']['CN5000 FM']

    learning_store.record_observation(
        ticket_key='STL-104',
        field='component',
        predicted='CN5000 FM',
        actual='CN5000 FM',
        correct=True,
    )

    after = learning_store.get_keyword_component_map()['crash']['CN5000 FM']

    assert after > before


def test_record_auto_fill_and_update_from_correction(learning_store):
    learning_store.record_auto_fill('STL-105', 'components', 'JKR Host Driver', 0.92)
    learning_store.update_from_correction(
        ticket_key='STL-105',
        field='components',
        old_value='JKR Host Driver',
        new_value='BTS/verbs',
    )

    cursor = learning_store.conn.cursor()
    cursor.execute(
        """
        SELECT corrected_by_human, correction_value
        FROM auto_fill_log
        WHERE ticket_key = 'STL-105'
        ORDER BY id DESC
        LIMIT 1
        """
    )
    auto_row = cursor.fetchone()

    assert int(auto_row['corrected_by_human']) == 1
    assert auto_row['correction_value'] == 'BTS/verbs'

    cursor.execute(
        """
        SELECT predicted_value, actual_value, correct
        FROM observations
        WHERE ticket_key = 'STL-105'
        ORDER BY id DESC
        LIMIT 1
        """
    )
    obs_row = cursor.fetchone()

    assert obs_row['predicted_value'] == 'JKR Host Driver'
    assert obs_row['actual_value'] == 'BTS/verbs'
    assert int(obs_row['correct']) == 0


def test_get_reporter_profile_returns_compliance_and_typicals(learning_store):
    learning_store.record_ticket(
        {
            'key': 'STL-106',
            'summary': 'Driver issue one',
            'component': 'JKR Host Driver',
            'reporter_id': 'acct-r3',
            'affects_version': '12.1.1.x',
            'priority': 'P1-Critical',
        }
    )
    learning_store.record_ticket(
        {
            'key': 'STL-107',
            'summary': 'Driver issue two',
            'component': 'JKR Host Driver',
            'reporter_id': 'acct-r3',
            'affects_version': '12.1.1.x',
            'priority': 'P1-Critical',
        }
    )
    learning_store.record_ticket(
        {
            'key': 'STL-108',
            'summary': 'Missing component from reporter',
            'component': '',
            'reporter_id': 'acct-r3',
            'affects_version': '12.1.1.x',
            'priority': 'P1-Critical',
        }
    )

    profile = learning_store.get_reporter_profile('acct-r3')

    assert profile['typical_version'] == '12.1.1.x'
    assert profile['typical_priority'] == 'P1-Critical'
    assert 'JKR Host Driver' in profile['common_components']
    assert profile['fields']['component']['observed_tickets'] == 3
    assert profile['fields']['component']['compliance_rate'] == pytest.approx(2 / 3)


def test_cycle_time_stats_and_empty_result(learning_store):
    learning_store.record_cycle_time(
        ticket_key='STL-109',
        component='JKR Host Driver',
        priority='P1-Critical',
        status_from='Open',
        status_to='In Progress',
        duration_hours=10,
    )
    learning_store.record_cycle_time(
        ticket_key='STL-110',
        component='JKR Host Driver',
        priority='P1-Critical',
        status_from='In Progress',
        status_to='Verify',
        duration_hours=20,
    )
    learning_store.record_cycle_time(
        ticket_key='STL-111',
        component='JKR Host Driver',
        priority='P1-Critical',
        status_from='Verify',
        status_to='Closed',
        duration_hours=30,
    )

    stats = learning_store.get_cycle_time_stats('JKR Host Driver', 'P1-Critical')

    assert stats['count'] == 3
    assert stats['average_hours'] == pytest.approx(20.0)
    assert stats['median_hours'] == pytest.approx(20.0)

    empty = learning_store.get_cycle_time_stats('Unknown', 'P0-Stopper')

    assert empty == {
        'count': 0,
        'average_hours': 0.0,
        'median_hours': 0.0,
    }


def test_save_and_get_release_snapshot_with_date_fallback(learning_store):
    learning_store.save_release_snapshot(
        '12.1.1.x',
        {
            'snapshot_date': '2026-03-01',
            'status': {'Open': 10, 'Verify': 2},
            'priority': {'P0-Stopper': 1, 'P1-Critical': 3},
            'component': {'JKR Host Driver': 4},
        },
    )
    learning_store.save_release_snapshot(
        '12.1.1.x',
        {
            'snapshot_date': '2026-03-10',
            'status': {'Open': 7, 'Verify': 1},
            'priority': {'P0-Stopper': 0, 'P1-Critical': 2},
            'component': {'JKR Host Driver': 3},
        },
    )

    fallback = learning_store.get_release_snapshot('12.1.1.x', '2026-03-05')
    latest = learning_store.get_release_snapshot('12.1.1.x', None)

    assert fallback['snapshot_date'] == '2026-03-01'
    assert fallback['status']['Open'] == 10

    assert latest['snapshot_date'] == '2026-03-10'
    assert latest['status']['Open'] == 7


def test_rebuild_confidence_scores_recomputes_values(learning_store):
    cursor = learning_store.conn.cursor()
    cursor.execute(
        """
        INSERT INTO keyword_patterns
        (keyword, field, value, hit_count, miss_count, confidence)
        VALUES ('crash', 'component', 'JKR Host Driver', 3, 1, 0.0)
        """
    )
    learning_store.conn.commit()

    learning_store.rebuild_confidence_scores()

    cursor.execute(
        """
        SELECT confidence
        FROM keyword_patterns
        WHERE keyword = 'crash' AND field = 'component' AND value = 'JKR Host Driver'
        """
    )
    row = cursor.fetchone()

    assert float(row['confidence']) == pytest.approx(3 / 6)


def test_get_stats_and_reset(learning_store):
    learning_store.record_observation('STL-112', 'component', 'A', 'A', True)
    learning_store.record_observation('STL-113', 'component', 'A', 'B', False)
    learning_store.record_auto_fill('STL-114', 'component', 'A', 0.9)

    stats = learning_store.get_stats()

    assert stats['tables']['observations'] == 2
    assert stats['tables']['auto_fill_log'] == 1
    assert stats['observations']['total'] == 2
    assert stats['observations']['correct'] == 1
    assert stats['observations']['accuracy'] == pytest.approx(0.5)

    learning_store.reset()
    reset_stats = learning_store.get_stats()

    assert reset_stats['tables']['observations'] == 0
    assert reset_stats['tables']['keyword_patterns'] == 0
    assert reset_stats['tables']['reporter_profiles'] == 0
    assert reset_stats['tables']['cycle_times'] == 0
    assert reset_stats['tables']['release_snapshots'] == 0
    assert reset_stats['tables']['auto_fill_log'] == 0


def test_get_field_prediction_unknown_field_returns_empty(learning_store):
    predicted, confidence = learning_store.get_field_prediction('fix_version', {'summary': 'anything'})

    assert predicted == ''
    assert confidence == 0.0
