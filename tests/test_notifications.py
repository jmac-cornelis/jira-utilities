from types import SimpleNamespace

from notifications.jira_comments import JiraCommentNotifier


class FakeJira:
    def __init__(self):
        self._comments = {}
        self.added = []

    def comments(self, ticket_key):
        return self._comments.get(ticket_key, [])

    def add_comment(self, ticket_key, body):
        self.added.append((ticket_key, body))
        self._comments.setdefault(ticket_key, []).append(SimpleNamespace(body=body))
        return True


def test_send_posts_adf_comment_for_flag_level():
    jira = FakeJira()
    notifier = JiraCommentNotifier(jira)

    sent = notifier.send(
        'STL-300',
        'Missing required field(s): component',
        level='flag',
        context={'field': 'component'},
    )

    assert sent is True
    assert len(jira.added) == 1

    ticket_key, adf = jira.added[0]
    assert ticket_key == 'STL-300'
    assert adf['type'] == 'doc'
    assert adf['version'] == 1

    panel = adf['content'][0]
    assert panel['type'] == 'panel'
    assert panel['attrs']['panelType'] == 'error'

    text = panel['content'][0]['content'][0]['text']
    assert '[PM-Agent]' in text
    assert '⚠️' in text


def test_send_levels_auto_fill_and_suggest_use_expected_panel_types():
    jira = FakeJira()
    notifier = JiraCommentNotifier(jira)

    notifier.send('STL-301', 'Auto filled component', level='auto_fill', context={'field': 'component'})
    notifier.send('STL-302', 'Suggested priority', level='suggest', context={'field': 'priority'})

    auto_panel = jira.added[0][1]['content'][0]
    suggest_panel = jira.added[1][1]['content'][0]

    assert auto_panel['attrs']['panelType'] == 'success'
    assert suggest_panel['attrs']['panelType'] == 'warning'


def test_has_existing_comment_detects_marker_and_field():
    jira = FakeJira()
    notifier = JiraCommentNotifier(jira)

    jira._comments['STL-303'] = [
        SimpleNamespace(body='regular user comment'),
        SimpleNamespace(body='[PM-Agent] ⚠️ Missing required field: component'),
    ]

    assert notifier.has_existing_comment('STL-303') is True
    assert notifier.has_existing_comment('STL-303', field='component') is True
    assert notifier.has_existing_comment('STL-303', field='priority') is False


def test_send_deduplicates_existing_comment_by_field():
    jira = FakeJira()
    notifier = JiraCommentNotifier(jira)

    jira._comments['STL-304'] = [
        SimpleNamespace(body='[PM-Agent] ⚠️ Missing required field: component')
    ]

    sent = notifier.send(
        'STL-304',
        'Missing required field(s): component',
        level='flag',
        context={'field': 'component'},
    )

    assert sent is False
    assert jira.added == []


def test_send_with_different_field_still_posts_new_comment():
    jira = FakeJira()
    notifier = JiraCommentNotifier(jira)

    jira._comments['STL-305'] = [
        SimpleNamespace(body='[PM-Agent] ⚠️ Missing required field: component')
    ]

    sent = notifier.send(
        'STL-305',
        'Missing required field(s): priority',
        level='flag',
        context={'field': 'priority'},
    )

    assert sent is True
    assert len(jira.added) == 1


def test_send_helper_methods_render_expected_messages():
    jira = FakeJira()
    notifier = JiraCommentNotifier(jira)

    auto_sent = notifier.send_auto_fill(
        ticket_key='STL-306',
        field='component',
        value='JKR Host Driver',
        confidence=0.95,
        reason='similar historical tickets',
    )
    suggest_sent = notifier.send_suggestion(
        ticket_key='STL-307',
        field='priority',
        value='P1-Critical',
        confidence=0.66,
        reason='keyword match',
    )
    flag_sent = notifier.send_flag('STL-308', ['component', 'affects_version'])

    assert auto_sent is True
    assert suggest_sent is True
    assert flag_sent is True

    auto_text = jira.added[0][1]['content'][0]['content'][0]['content'][0]['text']
    suggest_text = jira.added[1][1]['content'][0]['content'][0]['content'][0]['text']
    flag_text = jira.added[2][1]['content'][0]['content'][0]['content'][0]['text']

    assert 'Set component to JKR Host Driver' in auto_text
    assert 'Confidence: 95%' in auto_text

    assert 'priority=P1-Critical' in suggest_text
    assert 'Confidence: 66%' in suggest_text

    assert 'component, affects_version' in flag_text


def test_send_handles_jira_errors_gracefully():
    class BrokenJira(FakeJira):
        def add_comment(self, ticket_key, body):
            raise RuntimeError('jira unavailable')

    jira = BrokenJira()
    notifier = JiraCommentNotifier(jira)

    sent = notifier.send('STL-309', 'Message', level='flag', context={'field': 'component'})

    assert sent is False
