##########################################################################################
#
# Module: agents/hardware_analyst.py
#
# Description: Hardware Analyst Agent for the Feature Planning pipeline.
#              Builds a deep understanding of the target Cornelis hardware product
#              by querying Jira, knowledge base, MCP, and GitHub.
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
    HardwareProfile,
    ResearchReport,
)

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# ---------------------------------------------------------------------------
# Default system instruction (loaded from config/prompts/hardware_analyst.md
# at runtime if available; this is the fallback).
# ---------------------------------------------------------------------------

HARDWARE_ANALYST_INSTRUCTION = '''You are a Hardware Analyst Agent for Cornelis Networks.

Given research findings about a new feature, build a deep understanding of the
target hardware product:
1. Map the hardware architecture (components, buses, interfaces)
2. Catalog existing firmware, drivers, and tools
3. Identify integration points for the new feature
4. Flag knowledge gaps and request missing documentation

Think like an embedded systems engineer. Be specific about interfaces and
protocols. Distinguish known facts from inferences.
'''


class HardwareAnalystAgent(BaseAgent):
    '''
    Agent that builds a deep understanding of the target Cornelis hardware.

    Queries Jira for existing HW/SW/FW tickets, reads the product knowledge
    base, and searches MCP/GitHub to construct a HardwareProfile.
    '''

    def __init__(self, **kwargs):
        '''
        Initialize the Hardware Analyst Agent.

        Registers Jira, knowledge, MCP, and web search tools.
        '''
        instruction = self._load_prompt_file() or HARDWARE_ANALYST_INSTRUCTION

        config = AgentConfig(
            name='hardware_analyst',
            description='Builds deep understanding of Cornelis hardware products',
            instruction=instruction,
            max_iterations=30,
        )

        super().__init__(config=config, **kwargs)
        self._register_hw_tools()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_hw_tools(self) -> None:
        '''Register all tools the Hardware Analyst needs.'''
        # Jira tools — for querying existing tickets, components, releases
        try:
            from tools.jira_tools import (
                get_project_info,
                get_releases,
                get_release_tickets,
                get_components,
                search_tickets,
                get_related_tickets,
            )
            self.register_tool(get_project_info)
            self.register_tool(get_releases)
            self.register_tool(get_release_tickets)
            self.register_tool(get_components)
            self.register_tool(search_tickets)
            self.register_tool(get_related_tickets)
        except ImportError:
            log.warning('jira_tools not available for HardwareAnalystAgent')

        # Knowledge tools
        try:
            from tools.knowledge_tools import (
                search_knowledge,
                read_knowledge_file,
                list_knowledge_files,
            )
            self.register_tool(search_knowledge)
            self.register_tool(read_knowledge_file)
            self.register_tool(list_knowledge_files)
        except ImportError:
            log.warning('knowledge_tools not available for HardwareAnalystAgent')

        # MCP tools
        try:
            from tools.mcp_tools import mcp_search, mcp_discover_tools
            self.register_tool(mcp_search)
            self.register_tool(mcp_discover_tools)
        except ImportError:
            log.warning('mcp_tools not available for HardwareAnalystAgent')

        # Web search — for datasheets and reference manuals
        try:
            from tools.web_search_tools import web_search
            self.register_tool(web_search)
        except ImportError:
            log.warning('web_search_tools not available for HardwareAnalystAgent')

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_prompt_file() -> Optional[str]:
        '''Load the hardware analyst prompt from config/prompts/.'''
        prompt_path = os.path.join('config', 'prompts', 'hardware_analyst.md')
        if os.path.exists(prompt_path):
            try:
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                log.warning(f'Failed to load hardware analyst prompt: {e}')
        return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the Hardware Analyst Agent.

        Input:
            input_data: Dictionary containing:
                - feature_request: str — The user's feature description
                - project_key: str — Target Jira project key
                - research_report: dict — Output from the Research Agent

        Output:
            AgentResponse with a HardwareProfile in metadata['hw_profile'].
        '''
        log.debug('HardwareAnalystAgent.run()')

        if not isinstance(input_data, dict):
            return AgentResponse.error_response(
                'Invalid input: expected dict with feature_request and project_key'
            )

        feature_request = input_data.get('feature_request', '')
        project_key = input_data.get('project_key', '')
        research_report = input_data.get('research_report', {})

        if not feature_request:
            return AgentResponse.error_response('No feature_request provided')

        # Build the user prompt
        user_prompt = self._build_hw_prompt(
            feature_request, project_key, research_report
        )

        # Run the ReAct loop
        response = self._run_with_tools(user_prompt)

        # Parse the LLM output into a structured HardwareProfile
        profile = self._parse_profile(response.content)

        # Attach structured profile to metadata
        response.metadata['hw_profile'] = profile.to_dict()

        return response

    # ------------------------------------------------------------------
    # Programmatic analysis (no LLM — deterministic tool calls)
    # ------------------------------------------------------------------

    def analyze(
        self,
        feature_request: str,
        project_key: str,
        research_report: Optional[Dict[str, Any]] = None,
    ) -> HardwareProfile:
        '''
        Analyze hardware programmatically without LLM reasoning.

        Deterministic fallback that calls tools directly.

        Input:
            feature_request:  The feature description.
            project_key:      Target Jira project key.
            research_report:  Optional research report dict.

        Output:
            HardwareProfile with hardware understanding.
        '''
        log.info(f'HardwareAnalystAgent.analyze(project={project_key})')

        profile = HardwareProfile()

        # --- Product knowledge base ---------------------------------------
        profile = self._load_product_knowledge(profile)

        # --- Jira project info --------------------------------------------
        if project_key:
            profile = self._load_jira_info(profile, project_key)

        # --- Enrich from research report ----------------------------------
        if research_report:
            profile = self._enrich_from_research(profile, research_report)

        return profile

    # ------------------------------------------------------------------
    # Internal helpers — prompt building
    # ------------------------------------------------------------------

    def _build_hw_prompt(
        self,
        feature_request: str,
        project_key: str,
        research_report: Dict[str, Any],
    ) -> str:
        '''Build the user prompt for the LLM-driven hardware analysis.'''
        lines = [
            f'## Feature Request\n\n{feature_request}\n',
        ]

        if project_key:
            lines.append(f'## Target Jira Project\n\nProject key: `{project_key}`\n')

        if research_report:
            # Include a summary of research findings for context
            overview = research_report.get('domain_overview', '')
            if overview:
                lines.append(f'## Research Context\n\n{overview}\n')

            # Include key specs found
            specs = research_report.get('standards_and_specs', [])
            if specs:
                lines.append('### Key Specifications Found:')
                for spec in specs[:10]:
                    content = spec.get('content', '')[:200]
                    confidence = spec.get('confidence', 'unknown')
                    lines.append(f'- {content} (Confidence: {confidence})')
                lines.append('')

        lines.append(
            '## Instructions\n\n'
            'Please analyze the Cornelis hardware product for this feature:\n\n'
            '1. **Read the knowledge base** — Start with `list_knowledge_files` '
            'and `read_knowledge_file` to understand our products.\n'
            '2. **Query Jira** — Use `get_project_info`, `get_components`, and '
            '`search_tickets` to find existing HW/SW/FW tickets.\n'
            '3. **Search for hardware details** — Use `mcp_search` and '
            '`web_search` for datasheets and reference manuals.\n'
            '4. **Build the hardware profile** — Map the architecture, list '
            'existing SW/FW, identify integration points.\n\n'
            'Produce your final analysis in the format specified in your '
            'system instructions.'
        )

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Internal helpers — deterministic tool calls
    # ------------------------------------------------------------------

    def _load_product_knowledge(self, profile: HardwareProfile) -> HardwareProfile:
        '''Load product information from the knowledge base.'''
        try:
            from tools.knowledge_tools import search_knowledge, read_knowledge_file
        except ImportError:
            profile.gaps.append('Knowledge tools unavailable')
            return profile

        # Read the main product knowledge file
        try:
            result = read_knowledge_file(
                file_path='data/knowledge/cornelis_products.md'
            )
            data = result.data if hasattr(result, 'data') else result
            if isinstance(data, dict) and data.get('content'):
                content = data['content']
                # Extract product name from content
                if 'OPX' in content or 'Omni-Path' in content:
                    profile.product_name = profile.product_name or 'Omni-Path Express (OPX)'
                profile.description = content[:1000]
        except Exception as e:
            log.warning(f'Failed to read product knowledge: {e}')
            profile.gaps.append('Could not read product knowledge base')

        return profile

    def _load_jira_info(
        self, profile: HardwareProfile, project_key: str
    ) -> HardwareProfile:
        '''Load hardware information from Jira.'''
        try:
            from tools.jira_tools import (
                get_project_info,
                get_components,
                search_tickets,
            )
        except ImportError:
            profile.gaps.append('Jira tools unavailable')
            return profile

        # Get project info
        try:
            result = get_project_info(project_key=project_key)
            data = result.data if hasattr(result, 'data') else result
            if isinstance(data, dict):
                profile.product_name = (
                    profile.product_name or data.get('name', project_key)
                )
        except Exception as e:
            log.warning(f'Failed to get Jira project info: {e}')

        # Get components — these map to SW/FW areas
        try:
            result = get_components(project_key=project_key)
            data = result.data if hasattr(result, 'data') else result
            if isinstance(data, dict):
                for comp in data.get('components', []):
                    name = comp.get('name', '')
                    desc = comp.get('description', '')
                    lower = name.lower()

                    if any(kw in lower for kw in ('firmware', 'fw', 'embedded')):
                        profile.existing_firmware.append({
                            'name': name,
                            'description': desc,
                            'source': 'jira_component',
                        })
                    elif any(kw in lower for kw in ('driver', 'kernel', 'hfi')):
                        profile.existing_drivers.append({
                            'name': name,
                            'description': desc,
                            'source': 'jira_component',
                        })
                    elif any(kw in lower for kw in ('tool', 'cli', 'util', 'diag')):
                        profile.existing_tools.append({
                            'name': name,
                            'description': desc,
                            'source': 'jira_component',
                        })
                    else:
                        profile.components.append({
                            'name': name,
                            'description': desc,
                            'type': 'jira_component',
                        })
        except Exception as e:
            log.warning(f'Failed to get Jira components: {e}')

        # Search for firmware-related tickets
        try:
            result = search_tickets(
                jql=f'project = {project_key} AND '
                    f'(summary ~ "firmware" OR summary ~ "driver" OR '
                    f'summary ~ "hardware") AND '
                    f'type in (Epic, Story) '
                    f'ORDER BY created DESC',
                limit=20,
            )
            data = result.data if hasattr(result, 'data') else result
            if isinstance(data, dict):
                for ticket in data.get('tickets', data.get('issues', [])):
                    summary = ticket.get('summary', '')
                    key = ticket.get('key', '')
                    status = ticket.get('status', '')
                    lower = summary.lower()

                    entry = {
                        'name': summary,
                        'jira_key': key,
                        'status': status,
                        'source': 'jira_ticket',
                    }

                    if 'firmware' in lower or 'fw' in lower:
                        profile.existing_firmware.append(entry)
                    elif 'driver' in lower:
                        profile.existing_drivers.append(entry)
                    elif 'tool' in lower or 'diagnostic' in lower:
                        profile.existing_tools.append(entry)
        except Exception as e:
            log.warning(f'Failed to search Jira tickets: {e}')

        return profile

    def _enrich_from_research(
        self,
        profile: HardwareProfile,
        research_report: Dict[str, Any],
    ) -> HardwareProfile:
        '''Enrich the hardware profile with findings from the research report.'''
        # Extract bus/interface information from research findings
        all_findings = (
            research_report.get('standards_and_specs', [])
            + research_report.get('existing_implementations', [])
            + research_report.get('internal_knowledge', [])
        )

        bus_keywords = {
            'pcie': 'PCIe',
            'pci express': 'PCIe',
            'spi': 'SPI',
            'i2c': 'I2C',
            'uart': 'UART',
            'jtag': 'JTAG',
            'usb': 'USB',
            'ethernet': 'Ethernet',
            'mdio': 'MDIO',
            'smbus': 'SMBus',
            'qspi': 'QSPI',
        }

        seen_buses = {b.get('name', '').lower() for b in profile.bus_interfaces}

        for finding in all_findings:
            content = finding.get('content', '').lower()
            for keyword, bus_name in bus_keywords.items():
                if keyword in content and bus_name.lower() not in seen_buses:
                    profile.bus_interfaces.append({
                        'name': bus_name,
                        'protocol': bus_name,
                        'description': f'Identified from research: {finding.get("content", "")[:100]}',
                        'source': 'research_inference',
                    })
                    seen_buses.add(bus_name.lower())

        # Carry over open questions as gaps
        for question in research_report.get('open_questions', []):
            if question not in profile.gaps:
                profile.gaps.append(question)

        return profile

    # ------------------------------------------------------------------
    # Internal helpers — LLM output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_profile(llm_output: str) -> HardwareProfile:
        '''
        Parse the LLM's free-text hardware analysis into a HardwareProfile.

        Best-effort parser that extracts structured data from Markdown output.
        '''
        profile = HardwareProfile()

        if not llm_output:
            return profile

        current_section = ''

        for line in llm_output.splitlines():
            stripped = line.strip()
            lower = stripped.lower()

            # Detect section headings
            if 'product overview' in lower or 'product name' in lower:
                current_section = 'overview'
            elif 'hardware architecture' in lower or 'architecture' in lower:
                current_section = 'architecture'
            elif 'existing firmware' in lower or 'firmware' in lower:
                current_section = 'firmware'
            elif 'existing driver' in lower or 'driver' in lower:
                current_section = 'drivers'
            elif 'existing tool' in lower or 'tools' in lower:
                current_section = 'tools'
            elif 'bus interface' in lower or 'interface' in lower:
                current_section = 'buses'
            elif 'integration point' in lower:
                current_section = 'integration'
            elif 'knowledge gap' in lower or 'gap' in lower or 'missing' in lower:
                current_section = 'gaps'

            # Parse bullet points
            if stripped.startswith(('-', '*', '•')):
                content = stripped.lstrip('-*• ').strip()
                if not content:
                    continue

                if current_section == 'overview':
                    if not profile.product_name and ':' in content:
                        profile.product_name = content.split(':', 1)[1].strip()
                    elif not profile.description:
                        profile.description = content

                elif current_section == 'firmware':
                    profile.existing_firmware.append({
                        'name': content[:100],
                        'description': content,
                        'source': 'llm_analysis',
                    })

                elif current_section == 'drivers':
                    profile.existing_drivers.append({
                        'name': content[:100],
                        'description': content,
                        'source': 'llm_analysis',
                    })

                elif current_section == 'tools':
                    profile.existing_tools.append({
                        'name': content[:100],
                        'description': content,
                        'source': 'llm_analysis',
                    })

                elif current_section == 'buses':
                    profile.bus_interfaces.append({
                        'name': content.split(':')[0].strip() if ':' in content else content[:50],
                        'description': content,
                        'source': 'llm_analysis',
                    })

                elif current_section == 'architecture':
                    profile.components.append({
                        'name': content.split(':')[0].strip() if ':' in content else content[:50],
                        'description': content,
                        'type': 'hardware',
                    })

                elif current_section == 'gaps':
                    profile.gaps.append(content)

        # If we got a block diagram section, try to extract it
        diagram_match = re.search(
            r'```(?:mermaid)?\s*\n(.*?)\n```',
            llm_output,
            re.DOTALL,
        )
        if diagram_match:
            profile.block_diagram = diagram_match.group(1).strip()

        return profile
