from datetime import datetime, timezone

from agents.gantt_models import DependencyEdge, DependencyGraph, MilestoneProposal, PlanningSnapshot


def test_backlog_interpreter_and_dependency_mapper_normalize_and_attach_edges(
    fake_issue_resource_factory,
):
    from agents.gantt_components import BacklogInterpreter, DependencyMapper

    issue = fake_issue_resource_factory(
        key='STL-201',
        summary='Planner component work',
        issue_type='Story',
        status='Blocked',
        assignee=None,
        fix_versions=['12.1.0'],
        updated='2026-02-01T10:00:00.000+0000',
        issuelinks=[
            {
                'type': {
                    'name': 'Blocks',
                    'outward': 'blocks',
                    'inward': 'is blocked by',
                },
                'outwardIssue': {'key': 'STL-202'},
            }
        ],
    )
    issue.raw['fields']['parent'] = {'key': 'STL-200'}

    interpreter = BacklogInterpreter(
        jira_provider=lambda: None,
        now_provider=lambda: datetime(2026, 3, 15, tzinfo=timezone.utc),
        stale_days=30,
    )
    mapper = DependencyMapper()

    normalized = interpreter.normalize_issue(issue)
    assert normalized['parent_key'] == 'STL-200'
    assert normalized['is_stale'] is True
    assert '_issue_links' in normalized

    enriched = mapper.attach_dependency_edges([normalized])[0]
    edge_keys = {
        (edge['source_key'], edge['target_key'], edge['relationship'])
        for edge in enriched['dependency_edges']
    }

    assert '_issue_links' not in enriched
    assert ('STL-200', 'STL-201', 'parent_of') in edge_keys
    assert ('STL-201', 'STL-202', 'blocks') in edge_keys

    graph = mapper.build_graph([enriched])
    assert graph.edge_count == 2
    assert 'STL-201' in graph.blocked_keys
    assert 'STL-202' in graph.blocked_keys


def test_milestone_planner_risk_projector_and_summarizer_build_outputs():
    from agents.gantt_components import (
        DependencyMapper,
        MilestonePlanner,
        PlanningSummarizer,
        RiskProjector,
    )

    issues = [
        {
            'key': 'STL-301',
            'summary': 'Release item',
            'issue_type': 'Story',
            'status': 'In Progress',
            'assignee': '',
            'assignee_display': '',
            'fix_versions': ['12.1.0'],
            'priority': 'High',
            'is_done': False,
            'is_stale': True,
            'age_days': 40,
            'updated_date': '2026-02-01',
            'dependency_edges': [
                {
                    'source_key': 'STL-301',
                    'target_key': 'STL-302',
                    'relationship': 'blocks',
                    'inferred': False,
                    'evidence': 'jira_issue_link',
                }
            ],
        },
        {
            'key': 'STL-302',
            'summary': 'Blocked item',
            'issue_type': 'Story',
            'status': 'Open',
            'assignee': 'Jane Dev',
            'assignee_display': 'Jane Dev',
            'fix_versions': ['12.1.0'],
            'priority': 'Medium',
            'is_done': False,
            'is_stale': False,
            'age_days': 5,
            'updated_date': '2026-03-10',
            'dependency_edges': [],
        },
        {
            'key': 'STL-303',
            'summary': 'Unscheduled backlog',
            'issue_type': 'Bug',
            'status': 'Open',
            'assignee': '',
            'assignee_display': '',
            'fix_versions': [],
            'priority': 'P1-Critical',
            'is_done': False,
            'is_stale': False,
            'age_days': 3,
            'updated_date': '2026-03-12',
            'dependency_edges': [],
        },
    ]

    mapper = DependencyMapper()
    graph = mapper.build_graph(issues)

    planner = MilestonePlanner()
    milestones = planner.build_milestones(
        issues,
        releases=[{'name': '12.1.0', 'releaseDate': '2026-04-01'}],
        dependency_graph=graph,
    )

    risk_projector = RiskProjector()
    evidence_gaps = risk_projector.build_evidence_gaps(issues)
    risks = risk_projector.build_risks(issues, milestones, graph)

    summarizer = PlanningSummarizer()
    overview = summarizer.build_backlog_overview(issues, milestones, graph, risks)
    snapshot = PlanningSnapshot(
        project_key='STL',
        backlog_overview=overview,
        milestones=milestones,
        dependency_graph=graph,
        risks=risks,
        issues=issues,
        evidence_gaps=evidence_gaps,
    )
    markdown = summarizer.format_snapshot(snapshot)

    milestone_names = [milestone.name for milestone in milestones]
    risk_types = {risk.risk_type for risk in risks}

    assert milestone_names == ['12.1.0', 'Unscheduled Backlog']
    assert 'stale_work' in risk_types
    assert 'blocked_work' in risk_types
    assert 'unassigned_priority_work' in risk_types
    assert 'unscheduled_work' in risk_types
    assert overview['blocked_issues'] == 1
    assert overview['explicit_dependency_edges'] == 1
    assert overview['inferred_dependency_edges'] == 0
    assert overview['dependency_cycles'] == 0
    assert overview['risk_count'] == len(risks)
    assert '## Milestone Proposals' in markdown
    assert '- Explicit dependency edges: 1' in markdown
    assert evidence_gaps[0].startswith('Build, test, release')


def test_backlog_interpreter_build_backlog_jql():
    from agents.gantt_components import BacklogInterpreter
    from agents.gantt_models import PlanningRequest

    request = PlanningRequest(project_key='STL', include_done=False)
    jql = BacklogInterpreter.build_backlog_jql(request)

    assert 'project = "STL"' in jql
    assert 'statusCategory != Done' in jql
    assert jql.endswith('ORDER BY updated DESC')


def test_dependency_mapper_infers_edges_applies_reviews_and_builds_graph(tmp_path):
    from agents.gantt_components import DependencyMapper
    from state.gantt_dependency_review_store import GanttDependencyReviewStore

    review_store = GanttDependencyReviewStore(storage_dir=str(tmp_path / 'reviews'))
    review_store.record_review(
        project_key='STL',
        source_key='STL-401',
        target_key='STL-402',
        relationship='blocks',
        accepted=True,
        note='Confirmed dependency',
    )
    review_store.record_review(
        project_key='STL',
        source_key='STL-402',
        target_key='STL-403',
        relationship='blocks',
        accepted=False,
        note='This is sequencing, not a true blocker',
    )

    mapper = DependencyMapper(review_store=review_store)
    issues = [
        {
            'key': 'STL-401',
            'summary': 'Foundation work',
            'description': '',
            'status': 'In Progress',
            'fix_versions': ['12.1.0'],
            'is_done': False,
        },
        {
            'key': 'STL-402',
            'summary': 'Integration task',
            'description': 'Blocked by STL-401. Blocks STL-403 directly.',
            'status': 'Open',
            'fix_versions': ['12.1.0'],
            'is_done': False,
        },
        {
            'key': 'STL-403',
            'summary': 'Documentation update',
            'description': '',
            'status': 'Open',
            'fix_versions': ['12.1.0'],
            'is_done': False,
        },
    ]

    enriched = mapper.attach_dependency_edges(issues, project_key='STL')
    graph = mapper.build_graph(enriched)

    assert enriched[1]['dependency_edges'][0]['review_state'] == 'accepted'
    assert enriched[1]['suppressed_dependency_edges'][0]['review_state'] == 'rejected'
    assert graph.inferred_edge_count == 1
    assert graph.suppressed_edge_count == 1
    assert graph.review_summary == {'accepted': 1, 'pending': 0, 'rejected': 1}
    assert graph.depth_by_key['STL-401'] == 0
    assert graph.depth_by_key['STL-402'] == 1
    assert graph.depth_by_key['STL-403'] == 0
    assert graph.root_blockers == ['STL-401']
    assert ['STL-401', 'STL-402'] in graph.blocker_chains


def test_dependency_mapper_detects_cycles_from_inferred_edges():
    from agents.gantt_components import DependencyMapper

    mapper = DependencyMapper()
    issues = [
        {
            'key': 'STL-501',
            'summary': 'Task A',
            'description': 'Blocked by STL-503.',
            'status': 'Open',
            'fix_versions': ['12.1.0'],
            'is_done': False,
        },
        {
            'key': 'STL-502',
            'summary': 'Task B',
            'description': 'Blocked by STL-501.',
            'status': 'Open',
            'fix_versions': ['12.1.0'],
            'is_done': False,
        },
        {
            'key': 'STL-503',
            'summary': 'Task C',
            'description': 'Blocked by STL-502.',
            'status': 'Open',
            'fix_versions': ['12.1.0'],
            'is_done': False,
        },
    ]

    graph = mapper.build_graph(mapper.attach_dependency_edges(issues, project_key='STL'))

    assert len(graph.cycle_paths) == 1
    assert set(graph.cycle_paths[0][:-1]) == {'STL-501', 'STL-502', 'STL-503'}
    assert graph.depth_by_key['STL-501'] == -1
    assert graph.depth_by_key['STL-502'] == -1
    assert graph.depth_by_key['STL-503'] == -1


def test_risk_projector_and_summarizer_surface_dependency_analysis_details():
    from agents.gantt_components import PlanningSummarizer, RiskProjector

    issues = [
        {
            'key': 'STL-601',
            'summary': 'Root blocker',
            'status': 'In Progress',
            'assignee': 'Owner',
            'assignee_display': 'Owner',
            'fix_versions': ['12.1.0'],
            'priority': 'High',
            'is_done': False,
            'is_stale': False,
        },
        {
            'key': 'STL-602',
            'summary': 'Sequenced work',
            'status': 'Blocked',
            'assignee': 'Owner',
            'assignee_display': 'Owner',
            'fix_versions': ['12.1.0'],
            'priority': 'Medium',
            'is_done': False,
            'is_stale': False,
        },
        {
            'key': 'STL-603',
            'summary': 'Downstream item',
            'status': 'Open',
            'assignee': 'Owner',
            'assignee_display': 'Owner',
            'fix_versions': ['12.1.0'],
            'priority': 'Medium',
            'is_done': False,
            'is_stale': False,
        },
    ]
    graph = DependencyGraph(
        nodes=[{'key': issue['key']} for issue in issues],
        edges=[
            DependencyEdge(
                source_key='STL-601',
                target_key='STL-602',
                relationship='blocks',
                inferred=True,
                review_state='accepted',
                evidence='issue_text',
            ),
            DependencyEdge(
                source_key='STL-602',
                target_key='STL-603',
                relationship='blocks',
                inferred=True,
                review_state='pending',
                evidence='issue_text',
            ),
        ],
        blocked_keys=['STL-602', 'STL-603'],
        cycle_paths=[['STL-601', 'STL-602', 'STL-601']],
        depth_by_key={'STL-601': 0, 'STL-602': 1, 'STL-603': 2},
        blocker_chains=[['STL-601', 'STL-602', 'STL-603']],
        root_blockers=['STL-601'],
        review_summary={'accepted': 1, 'pending': 2, 'rejected': 1},
        suppressed_edges=[
            DependencyEdge(
                source_key='STL-603',
                target_key='STL-604',
                relationship='blocks',
                inferred=True,
                review_state='rejected',
                evidence='issue_text',
            )
        ],
    )
    milestones = [
        MilestoneProposal(
            name='12.1.0',
            target_date='2026-04-01',
            issue_keys=['STL-601', 'STL-602', 'STL-603'],
            total_issues=3,
            open_issues=3,
            blocked_issues=2,
            unassigned_issues=0,
            summary='3 open, 2 blocked, 0 unassigned',
        )
    ]

    risk_projector = RiskProjector()
    risks = risk_projector.build_risks(issues, milestones, graph)
    summarizer = PlanningSummarizer()
    overview = summarizer.build_backlog_overview(issues, milestones, graph, risks)
    snapshot = PlanningSnapshot(
        project_key='STL',
        backlog_overview=overview,
        milestones=milestones,
        dependency_graph=graph,
        risks=risks,
        issues=issues,
        evidence_gaps=['Build evidence is still external to this snapshot.'],
    )
    markdown = summarizer.format_snapshot(snapshot)

    risk_types = {risk.risk_type for risk in risks}

    assert 'dependency_cycle' in risk_types
    assert 'blocker_chain' in risk_types
    assert overview['dependency_cycles'] == 1
    assert overview['max_dependency_depth'] == 2
    assert overview['suppressed_dependency_edges'] == 1
    assert overview['dependency_review_summary']['pending'] == 2
    assert 'Cycle paths: 1' in markdown
    assert 'accepted=1, pending=2, rejected=1' in markdown
    assert 'STL-601 -> STL-602 -> STL-603' in markdown
