##########################################################################################
#
# Module: agents/research_agent.py
#
# Description: Research Agent for the Feature Planning pipeline.
#              Gathers comprehensive technical information about a new feature
#              from web search, Cornelis MCP, local knowledge base, and
#              user-provided documents.
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
    ResearchFinding,
    ResearchReport,
)

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# ---------------------------------------------------------------------------
# Default system instruction (loaded from config/prompts/research_agent.md
# at runtime if available; this is the fallback).
# ---------------------------------------------------------------------------

RESEARCH_INSTRUCTION = '''You are a Research Agent for Cornelis Networks.

Given a feature request, you must:
1. Research the technology domain using web search and internal knowledge
2. Find existing implementations and reference designs
3. Gather internal Cornelis knowledge
4. Identify gaps and open questions

Tag every finding with a confidence level (HIGH, MEDIUM, LOW) and source.
Never fabricate information. If you don't know, say so.
'''


class ResearchAgent(BaseAgent):
    '''
    Agent that gathers comprehensive technical information about a feature.

    Uses web search, Cornelis MCP, local knowledge base, and user-provided
    documents to build a ResearchReport with confidence-tagged findings.
    '''

    def __init__(self, **kwargs):
        '''
        Initialize the Research Agent.

        Registers web search, MCP, and knowledge tools.
        '''
        # Load the full prompt from disk if available; fall back to inline
        instruction = self._load_prompt_file() or RESEARCH_INSTRUCTION

        config = AgentConfig(
            name='research_agent',
            description='Researches new feature domains for SW/FW planning',
            instruction=instruction,
            max_iterations=30,  # Research may require many tool calls
        )

        super().__init__(config=config, **kwargs)

        # Register tool collections
        self._register_research_tools()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_research_tools(self) -> None:
        '''Register all tools the Research Agent needs.'''
        # Web search tools
        try:
            from tools.web_search_tools import web_search, web_search_multi
            self.register_tool(web_search)
            self.register_tool(web_search_multi)
        except ImportError:
            log.warning('web_search_tools not available')

        # MCP tools
        try:
            from tools.mcp_tools import mcp_discover_tools, mcp_call_tool, mcp_search
            self.register_tool(mcp_discover_tools)
            self.register_tool(mcp_call_tool)
            self.register_tool(mcp_search)
        except ImportError:
            log.warning('mcp_tools not available')

        # Knowledge tools
        try:
            from tools.knowledge_tools import (
                search_knowledge,
                list_knowledge_files,
                read_knowledge_file,
                read_document,
            )
            self.register_tool(search_knowledge)
            self.register_tool(list_knowledge_files)
            self.register_tool(read_knowledge_file)
            self.register_tool(read_document)
        except ImportError:
            log.warning('knowledge_tools not available')

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_prompt_file() -> Optional[str]:
        '''Load the research agent prompt from config/prompts/.'''
        prompt_path = os.path.join('config', 'prompts', 'research_agent.md')
        if os.path.exists(prompt_path):
            try:
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                log.warning(f'Failed to load research agent prompt: {e}')
        return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the Research Agent.

        Input:
            input_data: Dictionary containing:
                - feature_request: str — The user's feature description
                - doc_paths: List[str] — Optional paths to user-provided documents
                - search_queries: List[str] — Optional pre-built search queries

        Output:
            AgentResponse with a ResearchReport in metadata['research_report'].
        '''
        log.debug('ResearchAgent.run()')

        if isinstance(input_data, str):
            # Simple string input — treat as the feature request
            input_data = {'feature_request': input_data}

        if not isinstance(input_data, dict):
            return AgentResponse.error_response(
                'Invalid input: expected dict with feature_request'
            )

        feature_request = input_data.get('feature_request', '')
        if not feature_request:
            return AgentResponse.error_response('No feature_request provided')

        doc_paths = input_data.get('doc_paths', [])

        # Build the user prompt that drives the LLM + tool loop
        user_prompt = self._build_research_prompt(feature_request, doc_paths)

        # Run the ReAct loop (LLM calls tools, observes results, repeats)
        response = self._run_with_tools(user_prompt)

        # Parse the LLM's final output into a structured ResearchReport
        report = self._parse_report(response.content)

        # Attach the structured report to metadata
        response.metadata['research_report'] = report.to_dict()

        return response

    # ------------------------------------------------------------------
    # Programmatic research (no LLM — deterministic tool calls)
    # ------------------------------------------------------------------

    def research(
        self,
        feature_request: str,
        doc_paths: Optional[List[str]] = None,
    ) -> ResearchReport:
        '''
        Perform research programmatically without LLM reasoning.

        This is a deterministic fallback that calls tools directly.
        Useful for testing or when the LLM is unavailable.

        Input:
            feature_request: The feature description.
            doc_paths:       Optional list of document paths to read.

        Output:
            ResearchReport with findings from all available sources.
        '''
        log.info(f'ResearchAgent.research(): "{feature_request[:80]}..."')

        report = ResearchReport()
        keywords = self._extract_keywords(feature_request)

        # --- Web search ---------------------------------------------------
        report = self._do_web_search(report, feature_request, keywords)

        # --- MCP search ---------------------------------------------------
        report = self._do_mcp_search(report, feature_request, keywords)

        # --- Knowledge base search ----------------------------------------
        report = self._do_knowledge_search(report, keywords)

        # --- Read user documents ------------------------------------------
        if doc_paths:
            report = self._do_document_read(report, doc_paths)

        # --- Build domain overview ----------------------------------------
        report.domain_overview = self._build_domain_overview(
            feature_request, report
        )

        # Recompute confidence summary
        report.recompute_confidence_summary()

        return report

    # ------------------------------------------------------------------
    # Internal helpers — prompt building
    # ------------------------------------------------------------------

    def _build_research_prompt(
        self,
        feature_request: str,
        doc_paths: List[str],
    ) -> str:
        '''Build the user prompt for the LLM-driven research loop.'''
        lines = [
            f'## Feature Request\n\n{feature_request}\n',
        ]

        if doc_paths:
            lines.append('## User-Provided Documents\n')
            lines.append('Please read these documents for additional context:\n')
            for path in doc_paths:
                lines.append(f'- `{path}`')
            lines.append('')

        lines.append(
            '## Instructions\n\n'
            'Please research this feature thoroughly:\n\n'
            '1. **Web Search**: Search for relevant standards, specifications, '
            'datasheets, and reference implementations.\n'
            '2. **Internal Knowledge**: Search the Cornelis knowledge base and '
            'MCP server for internal information.\n'
            '3. **Documents**: Read any user-provided documents listed above.\n'
            '4. **Synthesize**: Organize your findings into a structured report '
            'with confidence levels.\n\n'
            'Use the available tools to gather information. Tag every finding '
            'with its source and confidence level (HIGH, MEDIUM, LOW).\n\n'
            'When you have gathered sufficient information, produce your final '
            'research report in the format specified in your system instructions.'
        )

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Internal helpers — keyword extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        '''
        Extract meaningful keywords from a feature request.

        Filters out common stop words and short tokens.
        '''
        stop_words = {
            'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'could', 'should', 'may', 'might', 'can', 'shall',
            'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
            'as', 'into', 'through', 'during', 'before', 'after', 'above',
            'below', 'between', 'out', 'off', 'over', 'under', 'again',
            'further', 'then', 'once', 'and', 'but', 'or', 'nor', 'not',
            'so', 'yet', 'both', 'each', 'few', 'more', 'most', 'other',
            'some', 'such', 'no', 'only', 'own', 'same', 'than', 'too',
            'very', 'just', 'because', 'if', 'when', 'where', 'how',
            'what', 'which', 'who', 'whom', 'this', 'that', 'these',
            'those', 'it', 'its', 'we', 'our', 'us', 'i', 'me', 'my',
            'you', 'your', 'he', 'she', 'they', 'them', 'their',
        }

        # Tokenize on non-alphanumeric boundaries
        tokens = re.split(r'[^a-zA-Z0-9]+', text.lower())
        keywords = [t for t in tokens if len(t) >= 2 and t not in stop_words]

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)

        return unique

    # ------------------------------------------------------------------
    # Internal helpers — tool-based research steps
    # ------------------------------------------------------------------

    def _do_web_search(
        self,
        report: ResearchReport,
        feature_request: str,
        keywords: List[str],
    ) -> ResearchReport:
        '''Run web searches and add findings to the report.'''
        try:
            from tools.web_search_tools import web_search
        except ImportError:
            report.open_questions.append(
                'Web search unavailable — could not research public information'
            )
            return report

        # Build search queries from different angles
        queries = [
            feature_request,  # The raw request
            ' '.join(keywords[:5]) + ' specification',
            ' '.join(keywords[:5]) + ' datasheet',
            ' '.join(keywords[:5]) + ' firmware driver implementation',
        ]

        for query in queries:
            try:
                result = web_search(query=query, max_results=5)
                data = result.data if hasattr(result, 'data') else result
                if isinstance(data, dict):
                    for item in data.get('results', []):
                        finding = ResearchFinding(
                            content=f"{item.get('title', '')}: {item.get('snippet', '')}",
                            source='web',
                            source_url=item.get('url', ''),
                            confidence='medium',
                            relevance='supporting',
                            category='spec' if 'spec' in query else 'general',
                        )
                        report.existing_implementations.append(finding)
            except Exception as e:
                log.warning(f'Web search failed for "{query}": {e}')

        return report

    def _do_mcp_search(
        self,
        report: ResearchReport,
        feature_request: str,
        keywords: List[str],
    ) -> ResearchReport:
        '''Query the Cornelis MCP server and add findings to the report.'''
        try:
            from tools.mcp_tools import mcp_search
        except ImportError:
            return report

        query = ' '.join(keywords[:8])
        try:
            result = mcp_search(query=query)
            data = result.data if hasattr(result, 'data') else result
            if isinstance(data, dict) and 'error' not in str(data):
                finding = ResearchFinding(
                    content=json.dumps(data, indent=2)[:2000],
                    source='mcp',
                    source_url='cornelis-mcp',
                    confidence='medium',
                    relevance='direct',
                    category='internal',
                )
                report.internal_knowledge.append(finding)
        except Exception as e:
            log.debug(f'MCP search failed: {e}')

        return report

    def _do_knowledge_search(
        self,
        report: ResearchReport,
        keywords: List[str],
    ) -> ResearchReport:
        '''Search the local knowledge base and add findings to the report.'''
        try:
            from tools.knowledge_tools import search_knowledge
        except ImportError:
            return report

        query = ' '.join(keywords[:8])
        try:
            result = search_knowledge(query=query, max_results=5)
            data = result.data if hasattr(result, 'data') else result
            if isinstance(data, dict):
                for item in data.get('results', []):
                    finding = ResearchFinding(
                        content=f"{item.get('heading', '')}: "
                                f"{item.get('content', '')[:500]}",
                        source='knowledge_base',
                        source_url=item.get('file', ''),
                        confidence='high',  # Internal docs are authoritative
                        relevance='direct',
                        category='internal',
                    )
                    report.internal_knowledge.append(finding)
        except Exception as e:
            log.warning(f'Knowledge search failed: {e}')

        return report

    def _do_document_read(
        self,
        report: ResearchReport,
        doc_paths: List[str],
    ) -> ResearchReport:
        '''Read user-provided documents and add findings to the report.'''
        try:
            from tools.knowledge_tools import read_document
        except ImportError:
            report.open_questions.append(
                'Document reader unavailable — could not read user-provided docs'
            )
            return report

        for path in doc_paths:
            try:
                result = read_document(file_path=path)
                data = result.data if hasattr(result, 'data') else result
                if isinstance(data, dict) and data.get('content'):
                    # Treat user-provided docs as high-confidence
                    finding = ResearchFinding(
                        content=data['content'][:3000],
                        source='user_doc',
                        source_url=path,
                        confidence='high',
                        relevance='direct',
                        category='spec',
                    )
                    report.standards_and_specs.append(finding)
            except Exception as e:
                log.warning(f'Failed to read document {path}: {e}')
                report.open_questions.append(
                    f'Could not read document: {path} ({e})'
                )

        return report

    # ------------------------------------------------------------------
    # Internal helpers — synthesis
    # ------------------------------------------------------------------

    @staticmethod
    def _build_domain_overview(
        feature_request: str,
        report: ResearchReport,
    ) -> str:
        '''Build a domain overview from the collected findings.'''
        total = len(report.all_findings)
        high = sum(1 for f in report.all_findings if f.confidence == 'high')
        specs = len(report.standards_and_specs)
        impls = len(report.existing_implementations)
        internal = len(report.internal_knowledge)

        return (
            f'Research for: {feature_request}\n\n'
            f'Found {total} relevant findings across all sources:\n'
            f'- {specs} standards/specifications\n'
            f'- {impls} existing implementations/references\n'
            f'- {internal} internal knowledge items\n'
            f'- {high} high-confidence findings\n'
            f'- {len(report.open_questions)} open questions\n'
        )

    # ------------------------------------------------------------------
    # Internal helpers — LLM output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_report(llm_output: str) -> ResearchReport:
        '''
        Parse the LLM's free-text research report into a ResearchReport.

        This is a best-effort parser that extracts structured data from
        the LLM's Markdown-formatted output.
        '''
        report = ResearchReport()

        if not llm_output:
            return report

        # Extract domain overview (text before the first section heading)
        sections = re.split(r'\n(?=#{1,3}\s|[A-Z][A-Z\s&]+:)', llm_output)
        if sections:
            report.domain_overview = sections[0].strip()[:3000]

        # Extract findings by looking for bullet points with confidence tags
        confidence_pattern = re.compile(
            r'[-*]\s+(.+?)\s*\(.*?[Cc]onfidence:\s*(HIGH|MEDIUM|LOW).*?\)',
            re.IGNORECASE,
        )
        source_pattern = re.compile(
            r'\(.*?[Ss]ource:\s*([^,)]+)',
            re.IGNORECASE,
        )

        current_section = ''
        for line in llm_output.splitlines():
            line_stripped = line.strip()

            # Detect section headings
            lower = line_stripped.lower()
            if 'standard' in lower or 'specification' in lower:
                current_section = 'standards'
            elif 'implementation' in lower or 'existing' in lower:
                current_section = 'implementations'
            elif 'internal' in lower or 'knowledge' in lower:
                current_section = 'internal'
            elif 'open question' in lower or 'gap' in lower:
                current_section = 'questions'

            # Parse findings with confidence tags
            match = confidence_pattern.search(line_stripped)
            if match:
                content = match.group(1).strip()
                confidence = match.group(2).lower()

                # Try to extract source
                source_match = source_pattern.search(line_stripped)
                source_url = source_match.group(1).strip() if source_match else ''

                finding = ResearchFinding(
                    content=content,
                    source='web' if 'http' in source_url else 'unknown',
                    source_url=source_url,
                    confidence=confidence,
                    relevance='direct' if current_section in ('standards', 'internal') else 'supporting',
                    category='spec' if current_section == 'standards' else 'general',
                )

                if current_section == 'standards':
                    report.standards_and_specs.append(finding)
                elif current_section == 'internal':
                    report.internal_knowledge.append(finding)
                else:
                    report.existing_implementations.append(finding)

            # Parse open questions
            elif current_section == 'questions' and line_stripped.startswith(('-', '*')):
                question_text = line_stripped.lstrip('-* ').strip()
                if question_text:
                    report.open_questions.append(question_text)

        report.recompute_confidence_summary()
        return report
