import json
from types import SimpleNamespace

import pytest

from agents.base import AgentConfig, BaseAgent
from llm.base import BaseLLM, LLMResponse
from tools.base import ToolResult, tool


class _DummyLLM(BaseLLM):
    def __init__(self, responses):
        super().__init__(model='dummy-model')
        self._responses = list(responses)
        self.calls = []

    def chat(self, messages, temperature=0.7, max_tokens=None, **kwargs):
        self.calls.append({
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'kwargs': kwargs,
        })
        return self._responses.pop(0)

    def chat_with_vision(self, messages, images, temperature=0.7, max_tokens=None, **kwargs):
        raise NotImplementedError

    def supports_vision(self) -> bool:
        return False


def _tool_call_response(tool_name: str, arguments: dict, content: str = '') -> LLMResponse:
    tool_call = SimpleNamespace(
        function=SimpleNamespace(
            name=tool_name,
            arguments=json.dumps(arguments),
        )
    )
    raw_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(tool_calls=[tool_call]),
                finish_reason=None,
            )
        ]
    )
    return LLMResponse(content=content, model='dummy-model', raw_response=raw_response)


def _final_response(content: str) -> LLMResponse:
    raw_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(tool_calls=[]),
                finish_reason='stop',
            )
        ]
    )
    return LLMResponse(content=content, model='dummy-model', raw_response=raw_response)


class _TestAgent(BaseAgent):
    def __init__(self, llm, tools=None):
        super().__init__(
            config=AgentConfig(
                name='test_agent',
                description='Test agent',
                instruction='Use tools when helpful.',
            ),
            llm=llm,
            tools=tools,
        )

    def run(self, input_data):
        return self._run_with_tools(str(input_data))


@tool(description='Add two integers')
def _add_numbers(a: int, b: int) -> ToolResult:
    return ToolResult.success({'sum': a + b})


def test_base_agent_tool_loop_executes_registered_tool_and_returns_final_response():
    llm = _DummyLLM([
        _tool_call_response('_add_numbers', {'a': 2, 'b': 3}),
        _final_response('Completed with tool output.'),
    ])
    agent = _TestAgent(llm=llm, tools=[_add_numbers])

    response = agent.run('Please add 2 and 3')

    assert response.success is True
    assert response.content == 'Completed with tool output.'
    assert response.iterations == 2
    assert response.tool_calls[0]['tool'] == '_add_numbers'
    assert response.tool_calls[0]['result']['data']['sum'] == 5
    assert any(
        schema['function']['name'] == '_add_numbers'
        for schema in agent.get_tool_schemas()
    )


def test_jira_analyst_agent_registers_new_jira_tools(monkeypatch: pytest.MonkeyPatch):
    from agents.jira_analyst import JiraAnalystAgent

    monkeypatch.setattr(
        JiraAnalystAgent,
        '_load_prompt_file',
        staticmethod(lambda: 'jira analyst prompt'),
    )
    agent = JiraAnalystAgent(llm=_DummyLLM([]))

    assert 'get_ticket' in agent.tools
    assert 'get_project_fields' in agent.tools
    assert 'list_transitions' in agent.tools
    assert 'transition_ticket' in agent.tools
    assert 'add_ticket_comment' in agent.tools


def test_jira_analyst_analyze_project_collects_summary_and_errors(monkeypatch: pytest.MonkeyPatch):
    from agents.jira_analyst import JiraAnalystAgent
    from tools import jira_tools as jira_tools_module

    monkeypatch.setattr(
        JiraAnalystAgent,
        '_load_prompt_file',
        staticmethod(lambda: 'jira analyst prompt'),
    )
    monkeypatch.setattr(
        jira_tools_module,
        'get_project_info',
        lambda project_key: ToolResult.success({'key': project_key, 'name': 'Storage Team'}),
    )
    monkeypatch.setattr(
        jira_tools_module,
        'get_releases',
        lambda _project_key: ToolResult.failure('release lookup failed'),
    )
    monkeypatch.setattr(
        jira_tools_module,
        'get_components',
        lambda _project_key: ToolResult.success([{'name': 'Fabric'}]),
    )
    monkeypatch.setattr(
        jira_tools_module,
        'get_project_workflows',
        lambda _project_key: ToolResult.success([{'name': 'Open'}]),
    )
    monkeypatch.setattr(
        jira_tools_module,
        'get_project_issue_types',
        lambda _project_key: ToolResult.success([{'name': 'Bug'}, {'name': 'Story'}]),
    )

    agent = JiraAnalystAgent(llm=_DummyLLM([]))
    analysis = agent.analyze_project('STL')

    assert analysis['project_info']['key'] == 'STL'
    assert analysis['errors'] == ['Releases: release lookup failed']
    assert analysis['summary']['component_count'] == 1
    assert analysis['summary']['issue_type_count'] == 2
    assert analysis['summary']['has_errors'] is True


def test_research_agent_registers_search_related_tools(monkeypatch: pytest.MonkeyPatch):
    from agents.research_agent import ResearchAgent

    monkeypatch.setattr(
        ResearchAgent,
        '_load_prompt_file',
        staticmethod(lambda: 'research prompt'),
    )
    agent = ResearchAgent(llm=_DummyLLM([]))

    assert 'web_search' in agent.tools
    assert 'web_search_multi' in agent.tools
    assert 'mcp_discover_tools' in agent.tools
    assert 'mcp_call_tool' in agent.tools
    assert 'mcp_search' in agent.tools
    assert 'search_knowledge' in agent.tools
    assert 'read_document' in agent.tools


def test_research_agent_research_aggregates_findings(monkeypatch: pytest.MonkeyPatch):
    from agents.research_agent import ResearchAgent
    from tools import knowledge_tools, mcp_tools, web_search_tools

    monkeypatch.setattr(
        ResearchAgent,
        '_load_prompt_file',
        staticmethod(lambda: 'research prompt'),
    )
    monkeypatch.setattr(
        web_search_tools,
        'web_search',
        lambda query, max_results=5: ToolResult.success({
            'results': [
                {
                    'title': f'Result for {query}',
                    'snippet': 'Reference implementation details',
                    'url': 'https://example.test/spec',
                }
            ]
        }),
    )
    monkeypatch.setattr(
        mcp_tools,
        'mcp_search',
        lambda query: ToolResult.success({'tool': 'internal-search', 'query': query}),
    )
    monkeypatch.setattr(
        knowledge_tools,
        'search_knowledge',
        lambda query, max_results=5: ToolResult.success({
            'results': [
                {
                    'heading': 'Internal Notes',
                    'content': 'Existing CN5000 support notes',
                    'file': 'data/knowledge/cn5000.md',
                }
            ]
        }),
    )
    monkeypatch.setattr(
        knowledge_tools,
        'read_document',
        lambda file_path: ToolResult.success({
            'content': 'User spec document content',
            'file_path': file_path,
        }),
    )

    agent = ResearchAgent(llm=_DummyLLM([]))
    report = agent.research(
        feature_request='Add PCIe loopback diagnostics for CN5000',
        doc_paths=['specs/loopback.md'],
    )

    assert len(report.existing_implementations) == 4
    assert len(report.internal_knowledge) == 2
    assert len(report.standards_and_specs) == 1
    assert report.confidence_summary['high'] == 2
    assert report.confidence_summary['medium'] == 5
    assert 'Found 7 relevant findings' in report.domain_overview


def test_review_agent_create_session_and_execute_approved_items(monkeypatch: pytest.MonkeyPatch):
    from agents.review_agent import ApprovalStatus, ReviewAgent
    from tools import jira_tools as jira_tools_module

    monkeypatch.setattr(
        ReviewAgent,
        '_load_prompt_file',
        staticmethod(lambda: 'review prompt'),
    )

    create_release_calls = []
    create_ticket_calls = []

    monkeypatch.setattr(
        jira_tools_module,
        'create_release',
        lambda **kwargs: (
            create_release_calls.append(kwargs) or
            ToolResult.success({'id': 'rel-1', 'name': kwargs['name']})
        ),
    )
    monkeypatch.setattr(
        jira_tools_module,
        'create_ticket',
        lambda **kwargs: (
            create_ticket_calls.append(kwargs) or
            ToolResult.success({'key': 'STL-900', 'summary': kwargs['summary']})
        ),
    )

    agent = ReviewAgent(llm=_DummyLLM([]))
    session = agent.create_session_from_plan({
        'project_key': 'STL',
        'releases': [
            {
                'name': '12.2.0',
                'description': 'Q2 release',
                'release_date': '2026-06-01',
                'tickets': [
                    {
                        'summary': 'Initial summary',
                        'description': 'Implement feature',
                        'issue_type': 'Story',
                        'components': ['Fabric'],
                        'fix_versions': ['12.2.0'],
                        'labels': ['agentic'],
                    }
                ],
            }
        ],
    })

    assert len(session.items) == 2
    assert session.items[0].id == 'R1'
    assert session.items[1].id == 'T2'

    assert agent.approve_item(session, 'R1') is True
    assert agent.modify_item(session, 'T2', {'summary': 'Revised summary'}) is True
    assert session.items[0].status == ApprovalStatus.APPROVED
    assert session.items[1].status == ApprovalStatus.MODIFIED

    results = agent.execute_approved(session)

    assert [result['item_id'] for result in results] == ['R1', 'T2']
    assert create_release_calls[0]['name'] == '12.2.0'
    assert create_ticket_calls[0]['summary'] == 'Revised summary'
    assert session.items[0].status == ApprovalStatus.EXECUTED
    assert session.items[1].status == ApprovalStatus.EXECUTED
