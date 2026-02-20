##########################################################################################
#
# Module: agents/feature_planning_models.py
#
# Description: Data models for the Feature Planning Agent pipeline.
#              Defines structured types for research findings, hardware profiles,
#              scope items, and Jira plans used across all feature planning agents.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


# ---------------------------------------------------------------------------
# Research Models
# ---------------------------------------------------------------------------

@dataclass
class ResearchFinding:
    '''
    A single piece of information discovered during the research phase.

    Attributes:
        content:    The actual information found.
        source:     Where it came from (web, confluence, github, mcp, knowledge_base, user_doc).
        source_url: URL or file path to the original source.
        confidence: How confident we are in this finding (high, medium, low).
        relevance:  How relevant it is to the feature (direct, supporting, background).
        category:   Type of information (standard, spec, implementation, tutorial, internal).
    '''
    content: str
    source: str = 'unknown'
    source_url: str = ''
    confidence: str = 'medium'
    relevance: str = 'supporting'
    category: str = 'general'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'content': self.content,
            'source': self.source,
            'source_url': self.source_url,
            'confidence': self.confidence,
            'relevance': self.relevance,
            'category': self.category,
        }


@dataclass
class ResearchReport:
    '''
    Aggregated output of the Research Agent.

    Attributes:
        domain_overview:          High-level summary of the feature domain.
        standards_and_specs:      Relevant standards, protocols, specifications.
        existing_implementations: Known implementations or reference designs.
        internal_knowledge:       Findings from Cornelis internal sources.
        open_questions:           Questions that could not be answered by research.
        confidence_summary:       Count of findings by confidence level.
    '''
    domain_overview: str = ''
    standards_and_specs: List[ResearchFinding] = field(default_factory=list)
    existing_implementations: List[ResearchFinding] = field(default_factory=list)
    internal_knowledge: List[ResearchFinding] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    confidence_summary: Dict[str, int] = field(default_factory=lambda: {
        'high': 0, 'medium': 0, 'low': 0
    })

    # -- helpers ----------------------------------------------------------------

    @property
    def all_findings(self) -> List[ResearchFinding]:
        '''Return every finding across all categories.'''
        return (
            self.standards_and_specs
            + self.existing_implementations
            + self.internal_knowledge
        )

    def recompute_confidence_summary(self) -> None:
        '''Recount findings by confidence level.'''
        counts: Dict[str, int] = {'high': 0, 'medium': 0, 'low': 0}
        for f in self.all_findings:
            counts[f.confidence] = counts.get(f.confidence, 0) + 1
        self.confidence_summary = counts

    def to_dict(self) -> Dict[str, Any]:
        self.recompute_confidence_summary()
        return {
            'domain_overview': self.domain_overview,
            'standards_and_specs': [f.to_dict() for f in self.standards_and_specs],
            'existing_implementations': [f.to_dict() for f in self.existing_implementations],
            'internal_knowledge': [f.to_dict() for f in self.internal_knowledge],
            'open_questions': self.open_questions,
            'confidence_summary': self.confidence_summary,
        }


# ---------------------------------------------------------------------------
# Hardware Models
# ---------------------------------------------------------------------------

@dataclass
class HardwareProfile:
    '''
    Deep understanding of the target Cornelis hardware product.

    Attributes:
        product_name:      Name of the product (e.g. CN5000).
        description:       High-level product description.
        components:        Hardware components on the board / in the system.
        bus_interfaces:    Bus/interconnect interfaces (PCIe, SPI, I2C, etc.).
        existing_firmware: Firmware modules that already exist for this product.
        existing_drivers:  Drivers that already exist.
        existing_tools:    CLI / diagnostic tools that already exist.
        block_diagram:     Text or Mermaid description of the HW architecture.
        gaps:              Areas where information is missing.
    '''
    product_name: str = ''
    description: str = ''
    components: List[Dict[str, Any]] = field(default_factory=list)
    bus_interfaces: List[Dict[str, Any]] = field(default_factory=list)
    existing_firmware: List[Dict[str, Any]] = field(default_factory=list)
    existing_drivers: List[Dict[str, Any]] = field(default_factory=list)
    existing_tools: List[Dict[str, Any]] = field(default_factory=list)
    block_diagram: Optional[str] = None
    gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'product_name': self.product_name,
            'description': self.description,
            'components': self.components,
            'bus_interfaces': self.bus_interfaces,
            'existing_firmware': self.existing_firmware,
            'existing_drivers': self.existing_drivers,
            'existing_tools': self.existing_tools,
            'block_diagram': self.block_diagram,
            'gaps': self.gaps,
        }


# ---------------------------------------------------------------------------
# Scoping Models
# ---------------------------------------------------------------------------

@dataclass
class ScopeItem:
    '''
    A single unit of SW/FW work identified during scoping.

    Attributes:
        title:               Short title for the work item.
        description:         Detailed description of what needs to be done.
        category:            firmware | driver | tool | test | integration | documentation.
        complexity:          Relative size: S, M, L, XL.
        confidence:          How confident we are this is needed: high, medium, low.
        dependencies:        Titles of other ScopeItems this depends on.
        rationale:           Why this work is needed.
        acceptance_criteria: Conditions that must be true when this work is done.
    '''
    title: str = ''
    description: str = ''
    category: str = 'firmware'
    complexity: str = 'M'
    confidence: str = 'medium'
    dependencies: List[str] = field(default_factory=list)
    rationale: str = ''
    acceptance_criteria: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'description': self.description,
            'category': self.category,
            'complexity': self.complexity,
            'confidence': self.confidence,
            'dependencies': self.dependencies,
            'rationale': self.rationale,
            'acceptance_criteria': self.acceptance_criteria,
        }


@dataclass
class Question:
    '''
    A question the agent needs answered by the user.

    Attributes:
        question: The question text.
        context:  Why we need to know this.
        options:  Suggested answers (if applicable).
        blocking: Whether this blocks further progress.
    '''
    question: str = ''
    context: str = ''
    options: List[str] = field(default_factory=list)
    blocking: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'question': self.question,
            'context': self.context,
            'options': self.options,
            'blocking': self.blocking,
        }


@dataclass
class FeatureScope:
    '''
    Complete scoping output for a feature.

    Attributes:
        feature_name:         Short name for the feature.
        summary:              Executive summary of the scoped work.
        firmware_items:       FW modules, init sequences, register access, etc.
        driver_items:         Kernel drivers, user-space libraries.
        tool_items:           CLI tools, diagnostics.
        test_items:           Test plans, automation.
        integration_items:    Integration with existing SW/FW stack.
        documentation_items:  API docs, user guides, release notes.
        open_questions:       Questions that need human answers.
        assumptions:          Assumptions made during scoping.
        confidence_report:    Aggregate confidence metrics.
    '''
    feature_name: str = ''
    summary: str = ''
    firmware_items: List[ScopeItem] = field(default_factory=list)
    driver_items: List[ScopeItem] = field(default_factory=list)
    tool_items: List[ScopeItem] = field(default_factory=list)
    test_items: List[ScopeItem] = field(default_factory=list)
    integration_items: List[ScopeItem] = field(default_factory=list)
    documentation_items: List[ScopeItem] = field(default_factory=list)
    open_questions: List[Question] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    confidence_report: Dict[str, Any] = field(default_factory=dict)

    # -- helpers ----------------------------------------------------------------

    @property
    def all_items(self) -> List[ScopeItem]:
        '''Return every scope item across all categories.'''
        return (
            self.firmware_items
            + self.driver_items
            + self.tool_items
            + self.test_items
            + self.integration_items
            + self.documentation_items
        )

    def recompute_confidence_report(self) -> None:
        '''Build aggregate confidence metrics from all scope items.'''
        items = self.all_items
        total = len(items)
        if total == 0:
            self.confidence_report = {'total_items': 0}
            return

        by_confidence: Dict[str, int] = {}
        by_complexity: Dict[str, int] = {}
        by_category: Dict[str, int] = {}

        for item in items:
            by_confidence[item.confidence] = by_confidence.get(item.confidence, 0) + 1
            by_complexity[item.complexity] = by_complexity.get(item.complexity, 0) + 1
            by_category[item.category] = by_category.get(item.category, 0) + 1

        self.confidence_report = {
            'total_items': total,
            'by_confidence': by_confidence,
            'by_complexity': by_complexity,
            'by_category': by_category,
            'blocking_questions': sum(1 for q in self.open_questions if q.blocking),
            'total_questions': len(self.open_questions),
        }

    def to_dict(self) -> Dict[str, Any]:
        self.recompute_confidence_report()
        return {
            'feature_name': self.feature_name,
            'summary': self.summary,
            'firmware_items': [i.to_dict() for i in self.firmware_items],
            'driver_items': [i.to_dict() for i in self.driver_items],
            'tool_items': [i.to_dict() for i in self.tool_items],
            'test_items': [i.to_dict() for i in self.test_items],
            'integration_items': [i.to_dict() for i in self.integration_items],
            'documentation_items': [i.to_dict() for i in self.documentation_items],
            'open_questions': [q.to_dict() for q in self.open_questions],
            'assumptions': self.assumptions,
            'confidence_report': self.confidence_report,
        }


# ---------------------------------------------------------------------------
# Jira Plan Models
# ---------------------------------------------------------------------------

@dataclass
class PlannedEpic:
    '''
    An Epic to be created in Jira.

    Attributes:
        summary:      Epic title.
        description:  Epic description.
        components:   Jira component names.
        labels:       Jira labels.
        stories:      Stories under this Epic.
    '''
    summary: str = ''
    description: str = ''
    components: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    stories: List['PlannedStory'] = field(default_factory=list)

    # Populated after Jira creation
    key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key,
            'summary': self.summary,
            'description': self.description,
            'components': self.components,
            'labels': self.labels,
            'stories': [s.to_dict() for s in self.stories],
        }


@dataclass
class PlannedStory:
    '''
    A Story to be created in Jira under an Epic.

    Attributes:
        summary:             Story title.
        description:         Story description (includes acceptance criteria).
        components:          Jira component names.
        labels:              Jira labels.
        assignee:            Assignee account ID or display name.
        complexity:          Relative size: S, M, L, XL.
        confidence:          How confident we are this is needed.
        acceptance_criteria: List of acceptance criteria.
        dependencies:        Keys or titles of stories this depends on.
    '''
    summary: str = ''
    description: str = ''
    components: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    assignee: Optional[str] = None
    complexity: str = 'M'
    confidence: str = 'medium'
    acceptance_criteria: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)

    # Populated after Jira creation
    key: Optional[str] = None
    # Set by the plan builder to reference the parent Epic
    parent_epic_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key,
            'summary': self.summary,
            'description': self.description,
            'components': self.components,
            'labels': self.labels,
            'assignee': self.assignee,
            'complexity': self.complexity,
            'confidence': self.confidence,
            'acceptance_criteria': self.acceptance_criteria,
            'dependencies': self.dependencies,
            'parent_epic_summary': self.parent_epic_summary,
        }


@dataclass
class JiraPlan:
    '''
    Complete Jira project plan ready for review and execution.

    Attributes:
        project_key:       Target Jira project key.
        feature_name:      Name of the feature being planned.
        epics:             List of Epics (each containing Stories).
        summary_markdown:  Human-readable Markdown summary of the plan.
        confidence_report: Aggregate confidence metrics.
    '''
    project_key: str = ''
    feature_name: str = ''
    epics: List[PlannedEpic] = field(default_factory=list)
    summary_markdown: str = ''
    confidence_report: Dict[str, Any] = field(default_factory=dict)

    # -- helpers ----------------------------------------------------------------

    @property
    def total_epics(self) -> int:
        return len(self.epics)

    @property
    def total_stories(self) -> int:
        return sum(len(e.stories) for e in self.epics)

    @property
    def total_tickets(self) -> int:
        return self.total_epics + self.total_stories

    def to_dict(self) -> Dict[str, Any]:
        return {
            'project_key': self.project_key,
            'feature_name': self.feature_name,
            'total_epics': self.total_epics,
            'total_stories': self.total_stories,
            'total_tickets': self.total_tickets,
            'epics': [e.to_dict() for e in self.epics],
            'summary_markdown': self.summary_markdown,
            'confidence_report': self.confidence_report,
        }


# ---------------------------------------------------------------------------
# Orchestrator State
# ---------------------------------------------------------------------------

@dataclass
class FeaturePlanningState:
    '''
    Full state of a feature planning workflow run.

    Persisted via SessionManager so the workflow can be resumed.

    Attributes:
        feature_request:    The user's original feature description.
        project_key:        Target Jira project key.
        doc_paths:          Paths to user-provided documents.
        research_report:    Output of the Research Agent.
        hw_profile:         Output of the Hardware Analyst Agent.
        feature_scope:      Output of the Scoping Agent.
        jira_plan:          Output of the Feature Plan Builder Agent.
        questions_for_user: Accumulated questions across all phases.
        current_phase:      Current workflow phase name.
        completed_phases:   List of completed phase names.
        errors:             Errors encountered during the workflow.
    '''
    feature_request: str = ''
    project_key: str = ''
    doc_paths: List[str] = field(default_factory=list)

    # Phase outputs (stored as dicts for JSON serialization)
    research_report: Optional[Dict[str, Any]] = None
    hw_profile: Optional[Dict[str, Any]] = None
    feature_scope: Optional[Dict[str, Any]] = None
    jira_plan: Optional[Dict[str, Any]] = None

    # Cross-cutting
    questions_for_user: List[Dict[str, Any]] = field(default_factory=list)

    # Workflow tracking
    current_phase: str = 'init'
    completed_phases: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def mark_phase_complete(self, phase: str) -> None:
        '''Mark a phase as completed and clear it as current.'''
        if phase not in self.completed_phases:
            self.completed_phases.append(phase)
        if self.current_phase == phase:
            self.current_phase = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'feature_request': self.feature_request,
            'project_key': self.project_key,
            'doc_paths': self.doc_paths,
            'research_report': self.research_report,
            'hw_profile': self.hw_profile,
            'feature_scope': self.feature_scope,
            'jira_plan': self.jira_plan,
            'questions_for_user': self.questions_for_user,
            'current_phase': self.current_phase,
            'completed_phases': self.completed_phases,
            'errors': self.errors,
        }
