##########################################################################################
#
# Module: agents/scoping_agent.py
#
# Description: Scoping Agent for the Feature Planning pipeline.
#              Acts as an embedded SW/FW engineering expert to define and scope
#              all software/firmware work required for a new hardware feature.
#
# Author: Cornelis Networks
#
##########################################################################################

import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, AgentConfig, AgentResponse
from agents.feature_planning_models import (
    FeatureScope,
    HardwareProfile,
    Question,
    ResearchReport,
    ScopeItem,
)

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# ---------------------------------------------------------------------------
# Default system instruction
# ---------------------------------------------------------------------------

SCOPING_INSTRUCTION = '''You are a Scoping Agent for Cornelis Networks — an expert
embedded software/firmware engineer. Given research findings and a hardware profile,
define and scope all SW/FW work needed. Assign confidence levels and complexity
estimates. Identify dependencies and open questions. Never fabricate information.
'''


class ScopingAgent(BaseAgent):
    '''
    Agent that defines and scopes SW/FW development work for a new feature.

    Takes research findings and hardware understanding as input, then produces
    a FeatureScope with categorized work items, dependencies, confidence
    levels, and open questions.
    '''

    def __init__(self, **kwargs):
        '''
        Initialize the Scoping Agent.

        Registers knowledge tools for reference lookups during scoping.
        '''
        instruction = self._load_prompt_file() or SCOPING_INSTRUCTION

        config = AgentConfig(
            name='scoping_agent',
            description='Defines and scopes SW/FW work for new hardware features',
            instruction=instruction,
            max_iterations=25,
        )

        super().__init__(config=config, **kwargs)
        self._register_scoping_tools()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_scoping_tools(self) -> None:
        '''Register tools the Scoping Agent may need for reference lookups.'''
        # Knowledge tools — for checking existing patterns and conventions
        try:
            from tools.knowledge_tools import search_knowledge, read_knowledge_file
            self.register_tool(search_knowledge)
            self.register_tool(read_knowledge_file)
        except ImportError:
            log.warning('knowledge_tools not available for ScopingAgent')

        # Web search — for looking up implementation patterns
        try:
            from tools.web_search_tools import web_search
            self.register_tool(web_search)
        except ImportError:
            log.warning('web_search_tools not available for ScopingAgent')

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_prompt_file() -> Optional[str]:
        '''Load the scoping agent prompt from config/prompts/.'''
        prompt_path = os.path.join('config', 'prompts', 'scoping_agent.md')
        if os.path.exists(prompt_path):
            try:
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                log.warning(f'Failed to load scoping agent prompt: {e}')
        return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the Scoping Agent.

        Input:
            input_data: Dictionary containing:
                - feature_request: str — The user's feature description
                - research_report: dict — Output from the Research Agent
                - hw_profile: dict — Output from the Hardware Analyst Agent

        Output:
            AgentResponse with a FeatureScope in metadata['feature_scope'].
        '''
        log.debug('ScopingAgent.run()')

        if not isinstance(input_data, dict):
            return AgentResponse.error_response(
                'Invalid input: expected dict with feature_request, '
                'research_report, and hw_profile'
            )

        feature_request = input_data.get('feature_request', '')
        research_report = input_data.get('research_report', {})
        hw_profile = input_data.get('hw_profile', {})

        if not feature_request:
            return AgentResponse.error_response('No feature_request provided')

        # Build the user prompt
        user_prompt = self._build_scoping_prompt(
            feature_request, research_report, hw_profile
        )

        # Run the ReAct loop
        response = self._run_with_tools(user_prompt)

        # Parse the LLM output into a structured FeatureScope
        scope = self._parse_scope(response.content, feature_request)

        # Attach structured scope to metadata
        response.metadata['feature_scope'] = scope.to_dict()

        return response

    # ------------------------------------------------------------------
    # Programmatic scoping (no LLM — deterministic)
    # ------------------------------------------------------------------

    def scope(
        self,
        feature_request: str,
        research_report: Optional[Dict[str, Any]] = None,
        hw_profile: Optional[Dict[str, Any]] = None,
    ) -> FeatureScope:
        '''
        Perform scoping programmatically without LLM reasoning.

        Deterministic fallback that generates a basic scope structure
        based on the hardware profile and research findings.

        Input:
            feature_request:  The feature description.
            research_report:  Optional research report dict.
            hw_profile:       Optional hardware profile dict.

        Output:
            FeatureScope with categorized work items.
        '''
        log.info(f'ScopingAgent.scope(): "{feature_request[:80]}..."')

        scope = FeatureScope(feature_name=feature_request[:100])

        # Generate items based on what we know about the hardware
        if hw_profile:
            scope = self._scope_from_hw_profile(scope, hw_profile)

        # Add standard items that almost every feature needs
        scope = self._add_standard_items(scope, feature_request)

        # Build summary
        scope.summary = self._build_summary(scope)
        scope.recompute_confidence_report()

        return scope

    # ------------------------------------------------------------------
    # Internal helpers — prompt building
    # ------------------------------------------------------------------

    def _build_scoping_prompt(
        self,
        feature_request: str,
        research_report: Dict[str, Any],
        hw_profile: Dict[str, Any],
    ) -> str:
        '''Build the user prompt for the LLM-driven scoping session.'''
        lines = [
            f'## Feature Request\n\n{feature_request}\n',
        ]

        # Include research context
        if research_report:
            overview = research_report.get('domain_overview', '')
            if overview:
                lines.append(f'## Research Findings\n\n{overview}\n')

            # Key specs
            specs = research_report.get('standards_and_specs', [])
            if specs:
                lines.append('### Relevant Standards/Specs:')
                for spec in specs[:10]:
                    content = spec.get('content', '')[:300]
                    confidence = spec.get('confidence', 'unknown')
                    lines.append(f'- {content} (Confidence: {confidence})')
                lines.append('')

            # Open questions from research
            questions = research_report.get('open_questions', [])
            if questions:
                lines.append('### Open Questions from Research:')
                for q in questions[:10]:
                    lines.append(f'- {q}')
                lines.append('')

        # Include hardware profile
        if hw_profile:
            lines.append('## Hardware Profile\n')

            product = hw_profile.get('product_name', 'Unknown')
            lines.append(f'**Product**: {product}\n')

            desc = hw_profile.get('description', '')
            if desc:
                lines.append(f'{desc[:500]}\n')

            buses = hw_profile.get('bus_interfaces', [])
            if buses:
                lines.append('### Bus Interfaces:')
                for bus in buses:
                    lines.append(f"- {bus.get('name', '?')}: {bus.get('description', '')[:100]}")
                lines.append('')

            fw = hw_profile.get('existing_firmware', [])
            if fw:
                lines.append('### Existing Firmware:')
                for item in fw[:10]:
                    lines.append(f"- {item.get('name', '?')}")
                lines.append('')

            drivers = hw_profile.get('existing_drivers', [])
            if drivers:
                lines.append('### Existing Drivers:')
                for item in drivers[:10]:
                    lines.append(f"- {item.get('name', '?')}")
                lines.append('')

            gaps = hw_profile.get('gaps', [])
            if gaps:
                lines.append('### Knowledge Gaps:')
                for gap in gaps[:10]:
                    lines.append(f'- {gap}')
                lines.append('')

        lines.append(
            '## Instructions\n\n'
            'Please scope all SW/FW work needed for this feature:\n\n'
            '1. **Firmware items** — Init, config, data path, error handling, '
            'diagnostics\n'
            '2. **Driver items** — Kernel module, user-space lib, sysfs/debugfs\n'
            '3. **Tool items** — CLI tools, diagnostics, monitoring\n'
            '4. **Test items** — Unit, integration, system, performance tests\n'
            '5. **Integration items** — Changes to existing SW/FW stack\n'
            '6. **Documentation items** — API docs, user guides, release notes\n\n'
            'For each item, provide:\n'
            '- Complexity (S/M/L/XL)\n'
            '- Confidence (HIGH/MEDIUM/LOW)\n'
            '- Dependencies\n'
            '- Acceptance criteria\n\n'
            'Also list any BLOCKING questions that need human answers before '
            'work can proceed.\n\n'
            'Produce your output in the format specified in your system instructions.'
        )

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Internal helpers — deterministic scoping
    # ------------------------------------------------------------------

    def _scope_from_hw_profile(
        self,
        scope: FeatureScope,
        hw_profile: Dict[str, Any],
    ) -> FeatureScope:
        '''Generate scope items based on the hardware profile.'''
        buses = hw_profile.get('bus_interfaces', [])
        product = hw_profile.get('product_name', 'the product')

        # For each bus interface, we likely need FW + driver support
        for bus in buses:
            bus_name = bus.get('name', 'Unknown')

            # Firmware: register access layer
            scope.firmware_items.append(ScopeItem(
                title=f'{bus_name} Register Access Layer',
                description=(
                    f'Implement register read/write functions for the new device '
                    f'connected via {bus_name} on {product}.'
                ),
                category='firmware',
                complexity='M',
                confidence='medium',
                rationale=f'Required to communicate with the device over {bus_name}.',
                acceptance_criteria=[
                    f'Can read/write all device registers over {bus_name}',
                    'Register access functions are tested with known values',
                    'Error handling for bus errors is implemented',
                ],
            ))

            # Firmware: initialization
            scope.firmware_items.append(ScopeItem(
                title=f'{bus_name} Device Initialization',
                description=(
                    f'Implement power-on initialization sequence for the device '
                    f'connected via {bus_name}.'
                ),
                category='firmware',
                complexity='M',
                confidence='medium',
                dependencies=[f'{bus_name} Register Access Layer'],
                rationale='Device must be properly initialized before use.',
                acceptance_criteria=[
                    'Device is detected and initialized on power-on',
                    'Initialization status is reported via health check',
                    'Graceful handling of device-not-present scenario',
                ],
            ))

        # Driver: kernel module
        scope.driver_items.append(ScopeItem(
            title='Kernel Driver Module',
            description=(
                f'Implement or extend the Linux kernel driver for the new '
                f'device on {product}.'
            ),
            category='driver',
            complexity='L',
            confidence='medium',
            dependencies=[
                item.title for item in scope.firmware_items
            ],
            rationale='Kernel driver is required for OS-level device access.',
            acceptance_criteria=[
                'Driver loads and binds to the device',
                'Device is accessible from user space',
                'Driver handles device errors gracefully',
                'Driver supports module parameters for configuration',
            ],
        ))

        return scope

    def _add_standard_items(
        self,
        scope: FeatureScope,
        feature_request: str,
    ) -> FeatureScope:
        '''Add standard items that almost every feature needs.'''
        feature_short = feature_request[:60]

        # Tool: CLI diagnostic
        scope.tool_items.append(ScopeItem(
            title='CLI Diagnostic Tool',
            description=(
                f'Implement CLI tool for configuring, querying status, and '
                f'diagnosing the new feature: {feature_short}.'
            ),
            category='tool',
            complexity='M',
            confidence='high',
            dependencies=['Kernel Driver Module'],
            rationale='Users and support need CLI access for configuration and debug.',
            acceptance_criteria=[
                'Can query device status from command line',
                'Can configure device parameters',
                'Provides useful error messages',
                'Includes --help and man page',
            ],
        ))

        # Test: integration test
        scope.test_items.append(ScopeItem(
            title='Integration Test Suite',
            description=(
                f'Develop integration tests that verify end-to-end functionality '
                f'of the new feature: {feature_short}.'
            ),
            category='test',
            complexity='L',
            confidence='high',
            dependencies=['Kernel Driver Module', 'CLI Diagnostic Tool'],
            rationale='Integration tests ensure all components work together.',
            acceptance_criteria=[
                'Tests cover happy path and error paths',
                'Tests run in CI/CD pipeline',
                'Tests produce clear pass/fail results',
                'Test coverage documented',
            ],
        ))

        # Test: unit tests
        scope.test_items.append(ScopeItem(
            title='Unit Tests for Firmware Modules',
            description='Write unit tests for each new firmware module.',
            category='test',
            complexity='M',
            confidence='high',
            dependencies=[item.title for item in scope.firmware_items],
            rationale='Unit tests catch bugs early and enable safe refactoring.',
            acceptance_criteria=[
                'Each firmware module has corresponding unit tests',
                'Tests mock hardware access for host-side execution',
                'Code coverage > 80%',
            ],
        ))

        # Documentation: API docs
        scope.documentation_items.append(ScopeItem(
            title='API Documentation',
            description=(
                f'Document all new APIs (firmware, driver, user-space) for '
                f'the feature: {feature_short}.'
            ),
            category='documentation',
            complexity='M',
            confidence='high',
            dependencies=['Kernel Driver Module'],
            rationale='API documentation is required for internal and external users.',
            acceptance_criteria=[
                'All public APIs are documented with usage examples',
                'Error codes and return values are documented',
                'Documentation is reviewed by a peer',
            ],
        ))

        # Documentation: user guide
        scope.documentation_items.append(ScopeItem(
            title='User Guide Update',
            description=(
                f'Update the user guide with installation, configuration, and '
                f'troubleshooting for: {feature_short}.'
            ),
            category='documentation',
            complexity='S',
            confidence='high',
            dependencies=['CLI Diagnostic Tool', 'API Documentation'],
            rationale='Users need documentation to install and use the feature.',
            acceptance_criteria=[
                'Installation steps are documented',
                'Configuration options are documented',
                'Troubleshooting section covers common issues',
            ],
        ))

        # Add a standard assumption
        scope.assumptions.append(
            'The existing build system and toolchain can be used without modification.'
        )
        scope.assumptions.append(
            'The target Linux kernel version supports the required driver interfaces.'
        )

        return scope

    @staticmethod
    def _build_summary(scope: FeatureScope) -> str:
        '''Build an executive summary of the scope.'''
        items = scope.all_items
        total = len(items)
        by_cat = {}
        for item in items:
            by_cat[item.category] = by_cat.get(item.category, 0) + 1

        cat_summary = ', '.join(
            f'{count} {cat}' for cat, count in sorted(by_cat.items())
        )

        blocking = sum(1 for q in scope.open_questions if q.blocking)

        return (
            f'Scoped {total} work items ({cat_summary}) for: '
            f'{scope.feature_name}. '
            f'{len(scope.open_questions)} open questions '
            f'({blocking} blocking).'
        )

    # ------------------------------------------------------------------
    # Internal helpers — LLM output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_scope(llm_output: str, feature_request: str) -> FeatureScope:
        '''
        Parse the LLM's scoping output into a FeatureScope.

        Strategy: try JSON extraction first (reliable), then fall back to
        the legacy Markdown regex parser (best-effort).
        '''
        scope = FeatureScope(feature_name=feature_request[:100])

        if not llm_output:
            return scope

        # ------------------------------------------------------------------
        # Strategy 1: Extract a ```json block (preferred — prompt requires it)
        # ------------------------------------------------------------------
        from agents.base import BaseAgent
        json_data = BaseAgent._extract_json_block(llm_output)

        if json_data and isinstance(json_data, dict):
            log.info('ScopingAgent: parsed scope from JSON block')

            scope.summary = (json_data.get('summary', '') or '')[:500]

            for assumption in json_data.get('assumptions', []):
                if isinstance(assumption, str) and assumption.strip():
                    scope.assumptions.append(assumption.strip())

            # Map JSON keys to FeatureScope list attributes + category names
            item_key_map = {
                'firmware_items': ('firmware_items', 'firmware'),
                'driver_items': ('driver_items', 'driver'),
                'tool_items': ('tool_items', 'tool'),
                'test_items': ('test_items', 'test'),
                'integration_items': ('integration_items', 'integration'),
                'documentation_items': ('documentation_items', 'documentation'),
            }

            for json_key, (attr_name, category) in item_key_map.items():
                for item_dict in json_data.get(json_key, []):
                    if not isinstance(item_dict, dict):
                        continue
                    item = ScopeItem(
                        title=item_dict.get('title', ''),
                        description=item_dict.get('description', ''),
                        category=category,
                        complexity=item_dict.get('complexity', 'M').upper(),
                        confidence=(item_dict.get('confidence', 'medium') or 'medium').lower(),
                        dependencies=item_dict.get('dependencies', []),
                        rationale=item_dict.get('rationale', ''),
                        acceptance_criteria=item_dict.get('acceptance_criteria', []),
                    )
                    target_list = getattr(scope, attr_name, None)
                    if target_list is not None:
                        target_list.append(item)

            for q_dict in json_data.get('open_questions', []):
                if isinstance(q_dict, dict):
                    scope.open_questions.append(Question(
                        question=q_dict.get('question', ''),
                        context=q_dict.get('context', ''),
                        blocking=bool(q_dict.get('blocking', False)),
                    ))
                elif isinstance(q_dict, str) and q_dict.strip():
                    scope.open_questions.append(Question(
                        question=q_dict.strip(),
                        context='',
                        blocking=False,
                    ))

            scope.recompute_confidence_report()
            return scope

        # ------------------------------------------------------------------
        # Strategy 2: Legacy Markdown regex parser (fallback)
        # ------------------------------------------------------------------
        log.info('ScopingAgent: no JSON block found — falling back to Markdown parser')

        # --- Extract summary -----------------------------------------------
        summary_match = re.search(
            r'SUMMARY:\s*\n(.*?)(?=\n[A-Z]|\n#{1,3}\s|\Z)',
            llm_output,
            re.DOTALL | re.IGNORECASE,
        )
        if summary_match:
            scope.summary = summary_match.group(1).strip()[:500]

        # --- Extract assumptions -------------------------------------------
        assumptions_match = re.search(
            r'ASSUMPTIONS?:\s*\n(.*?)(?=\n[A-Z][A-Z\s]+:|\n#{1,3}\s|\Z)',
            llm_output,
            re.DOTALL | re.IGNORECASE,
        )
        if assumptions_match:
            for line in assumptions_match.group(1).splitlines():
                line = line.strip().lstrip('-*• ').strip()
                if line:
                    scope.assumptions.append(line)

        # --- Extract scope items by section --------------------------------
        # Map section keywords to the target list on FeatureScope
        section_map = {
            'firmware': 'firmware_items',
            'driver': 'driver_items',
            'tool': 'tool_items',
            'test': 'test_items',
            'integration': 'integration_items',
            'documentation': 'documentation_items',
            'doc': 'documentation_items',
        }

        current_section = ''
        current_item: Optional[Dict[str, Any]] = None
        current_field = ''

        for line in llm_output.splitlines():
            stripped = line.strip()
            lower = stripped.lower()

            # Detect section headings (e.g., "FIRMWARE ITEMS:")
            for keyword, attr_name in section_map.items():
                if keyword in lower and (
                    stripped.endswith(':') or stripped.startswith('#')
                ):
                    # Save any in-progress item
                    if current_item and current_section:
                        _save_item(scope, current_section, current_item)
                    current_section = attr_name
                    current_item = None
                    current_field = ''
                    break

            # Detect open questions section
            if 'open question' in lower or 'question' in lower and stripped.endswith(':'):
                if current_item and current_section:
                    _save_item(scope, current_section, current_item)
                current_section = 'questions'
                current_item = None
                continue

            # Parse items within a section
            if current_section == 'questions':
                if stripped.startswith(('-', '*', '•')):
                    text = stripped.lstrip('-*• ').strip()
                    blocking = 'blocking' in lower
                    # Remove [BLOCKING] / [NON-BLOCKING] prefix
                    text = re.sub(
                        r'^\[(?:NON-?)?BLOCKING\]\s*', '', text, flags=re.IGNORECASE
                    )
                    # Split on " — " to get question and context
                    parts = text.split(' — ', 1)
                    question_text = parts[0].strip()
                    context = parts[1].strip() if len(parts) > 1 else ''
                    # Remove "Context:" prefix
                    context = re.sub(r'^Context:\s*', '', context, flags=re.IGNORECASE)

                    scope.open_questions.append(Question(
                        question=question_text,
                        context=context,
                        blocking=blocking,
                    ))
                continue

            if not current_section:
                continue

            # Detect a new scope item line:
            #   [S/M/L/XL] Title (Confidence: HIGH/MEDIUM/LOW)
            item_match = re.match(
                r'^\s*\[?(S|M|L|XL)\]?\s+(.+?)\s*'
                r'\(.*?[Cc]onfidence:\s*(HIGH|MEDIUM|LOW).*?\)\s*$',
                stripped,
                re.IGNORECASE,
            )
            if item_match:
                # Save previous item
                if current_item:
                    _save_item(scope, current_section, current_item)

                current_item = {
                    'complexity': item_match.group(1).upper(),
                    'title': item_match.group(2).strip(),
                    'confidence': item_match.group(3).lower(),
                    'description': '',
                    'rationale': '',
                    'dependencies': [],
                    'acceptance_criteria': [],
                }
                current_field = ''
                continue

            # Parse sub-fields of the current item
            if current_item:
                if lower.startswith('description:'):
                    current_field = 'description'
                    current_item['description'] = stripped.split(':', 1)[1].strip()
                elif lower.startswith('rationale:'):
                    current_field = 'rationale'
                    current_item['rationale'] = stripped.split(':', 1)[1].strip()
                elif lower.startswith('dependencies:') or lower.startswith('dependency:'):
                    current_field = 'dependencies'
                    dep_text = stripped.split(':', 1)[1].strip()
                    if dep_text:
                        # Parse "BLOCKED_BY: X" or "RELATED_TO: X"
                        dep_text = re.sub(
                            r'^(BLOCKED_BY|RELATED_TO):\s*',
                            '', dep_text, flags=re.IGNORECASE,
                        )
                        current_item['dependencies'].append(dep_text)
                elif lower.startswith('acceptance criteria:') or lower.startswith('acceptance:'):
                    current_field = 'acceptance_criteria'
                elif stripped.startswith(('-', '*', '•')) and current_field:
                    text = stripped.lstrip('-*• ').strip()
                    if current_field == 'acceptance_criteria':
                        current_item['acceptance_criteria'].append(text)
                    elif current_field == 'dependencies':
                        dep_text = re.sub(
                            r'^(BLOCKED_BY|RELATED_TO):\s*',
                            '', text, flags=re.IGNORECASE,
                        )
                        current_item['dependencies'].append(dep_text)
                elif current_field in ('description', 'rationale') and stripped:
                    current_item[current_field] += ' ' + stripped

        # Save last item
        if current_item and current_section:
            _save_item(scope, current_section, current_item)

        scope.recompute_confidence_report()
        return scope


# ---------------------------------------------------------------------------
# Module-level helper (used by the parser)
# ---------------------------------------------------------------------------

def _save_item(scope: FeatureScope, section_attr: str, item_dict: Dict[str, Any]) -> None:
    '''Convert an item dict to a ScopeItem and append to the correct list.'''
    # Determine category from section attribute name
    category_map = {
        'firmware_items': 'firmware',
        'driver_items': 'driver',
        'tool_items': 'tool',
        'test_items': 'test',
        'integration_items': 'integration',
        'documentation_items': 'documentation',
    }

    item = ScopeItem(
        title=item_dict.get('title', ''),
        description=item_dict.get('description', '').strip(),
        category=category_map.get(section_attr, 'firmware'),
        complexity=item_dict.get('complexity', 'M'),
        confidence=item_dict.get('confidence', 'medium'),
        dependencies=item_dict.get('dependencies', []),
        rationale=item_dict.get('rationale', '').strip(),
        acceptance_criteria=item_dict.get('acceptance_criteria', []),
    )

    target_list = getattr(scope, section_attr, None)
    if target_list is not None:
        target_list.append(item)
    else:
        log.warning(f'Unknown scope section: {section_attr}')
