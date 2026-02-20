##########################################################################################
#
# Module: tools/knowledge_tools.py
#
# Description: Local knowledge-base search and document reading tools.
#              Searches Markdown files in data/knowledge/ and reads user-provided
#              documents (PDF, DOCX, Markdown, plain text).
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

try:
    from tools.base import tool, ToolResult, BaseTool
except ImportError:
    log.warning('tools.base not available; knowledge_tools will not register @tool decorators')

    def tool(**kwargs):  # type: ignore[misc]
        def decorator(func):
            return func
        return decorator

    class ToolResult:  # type: ignore[no-redef]
        @classmethod
        def success(cls, data):
            return data

        @classmethod
        def failure(cls, msg):
            return {'error': msg}

    class BaseTool:  # type: ignore[no-redef]
        pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWLEDGE_DIR = 'data/knowledge'
SUPPORTED_TEXT_EXTENSIONS = {'.md', '.txt', '.rst', '.csv', '.json', '.yaml', '.yml'}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_knowledge_files() -> List[Path]:
    '''Return all readable files in the knowledge directory.'''
    kb_dir = Path(KNOWLEDGE_DIR)
    if not kb_dir.exists():
        log.warning(f'Knowledge directory not found: {KNOWLEDGE_DIR}')
        return []

    files = []
    for p in kb_dir.rglob('*'):
        if p.is_file() and p.suffix.lower() in SUPPORTED_TEXT_EXTENSIONS:
            files.append(p)
    return sorted(files)


def _read_text_file(path: Path) -> str:
    '''Read a text file and return its contents.'''
    try:
        return path.read_text(encoding='utf-8')
    except Exception as e:
        log.warning(f'Failed to read {path}: {e}')
        return ''


def _score_match(text: str, keywords: List[str]) -> int:
    '''
    Score how well *text* matches a list of keywords.

    Simple keyword-frequency scoring — case-insensitive.
    '''
    text_lower = text.lower()
    score = 0
    for kw in keywords:
        # Count occurrences of each keyword
        score += text_lower.count(kw.lower())
    return score


def _extract_sections(text: str) -> List[Dict[str, str]]:
    '''
    Split a Markdown file into sections based on headings.

    Output:
        List of dicts with 'heading' and 'content' keys.
    '''
    sections: List[Dict[str, str]] = []
    current_heading = ''
    current_lines: List[str] = []

    for line in text.splitlines():
        if line.startswith('#'):
            # Save previous section
            if current_heading or current_lines:
                sections.append({
                    'heading': current_heading,
                    'content': '\n'.join(current_lines).strip(),
                })
            current_heading = line.lstrip('#').strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    if current_heading or current_lines:
        sections.append({
            'heading': current_heading,
            'content': '\n'.join(current_lines).strip(),
        })

    return sections


# ---------------------------------------------------------------------------
# PDF / DOCX extraction helpers
# ---------------------------------------------------------------------------

def _extract_pdf_text(file_path: str) -> Optional[str]:
    '''
    Extract text from a PDF file.

    Tries PyMuPDF (fitz) first, then pdfplumber, then PyPDF2.
    Returns None if no PDF library is available.
    '''
    # Strategy 1: PyMuPDF (fitz)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return '\n\n'.join(pages)
    except ImportError:
        pass
    except Exception as e:
        log.warning(f'PyMuPDF failed on {file_path}: {e}')

    # Strategy 2: pdfplumber
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return '\n\n'.join(pages)
    except ImportError:
        pass
    except Exception as e:
        log.warning(f'pdfplumber failed on {file_path}: {e}')

    # Strategy 3: PyPDF2
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return '\n\n'.join(pages)
    except ImportError:
        pass
    except Exception as e:
        log.warning(f'PyPDF2 failed on {file_path}: {e}')

    return None


def _extract_docx_text(file_path: str) -> Optional[str]:
    '''
    Extract text from a DOCX file.

    Requires python-docx.
    '''
    try:
        from docx import Document
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return '\n\n'.join(paragraphs)
    except ImportError:
        log.warning('python-docx not installed; cannot read DOCX files')
        return None
    except Exception as e:
        log.warning(f'DOCX extraction failed on {file_path}: {e}')
        return None


# ---------------------------------------------------------------------------
# Public @tool functions
# ---------------------------------------------------------------------------

@tool(
    name='search_knowledge',
    description='Search the local Cornelis knowledge base for information. '
                'Searches data/knowledge/ Markdown files by keyword.',
)
def search_knowledge(query: str, max_results: int = 10) -> ToolResult:
    '''
    Search the local knowledge base for information relevant to a query.

    Splits each knowledge file into sections and scores them against the
    query keywords.  Returns the top-scoring sections.

    Input:
        query:       Search query (keywords).
        max_results: Maximum number of matching sections to return.

    Output:
        ToolResult with matching sections, each including file, heading, content,
        and relevance score.
    '''
    log.info(f'search_knowledge: "{query}"')

    files = _find_knowledge_files()
    if not files:
        return ToolResult.failure(
            f'No knowledge files found in {KNOWLEDGE_DIR}. '
            'Ensure data/knowledge/ contains .md files.'
        )

    # Tokenize query into keywords
    keywords = [w for w in re.split(r'\W+', query) if len(w) >= 2]
    if not keywords:
        return ToolResult.failure('Query too short or contains no searchable keywords')

    # Score every section in every file
    scored_sections: List[Dict[str, Any]] = []
    for fp in files:
        text = _read_text_file(fp)
        if not text:
            continue

        sections = _extract_sections(text)
        for section in sections:
            combined = f"{section['heading']} {section['content']}"
            score = _score_match(combined, keywords)
            if score > 0:
                scored_sections.append({
                    'file': str(fp),
                    'heading': section['heading'],
                    'content': section['content'][:2000],  # Truncate long sections
                    'score': score,
                })

    # Sort by score descending
    scored_sections.sort(key=lambda s: s['score'], reverse=True)
    top = scored_sections[:max_results]

    log.info(f'search_knowledge: {len(top)} results from {len(scored_sections)} candidates')

    return ToolResult.success({
        'query': query,
        'result_count': len(top),
        'total_candidates': len(scored_sections),
        'results': top,
    })


@tool(
    name='list_knowledge_files',
    description='List all files in the local Cornelis knowledge base',
)
def list_knowledge_files() -> ToolResult:
    '''
    List all files in the data/knowledge/ directory.

    Output:
        ToolResult with a list of file paths and their sizes.
    '''
    files = _find_knowledge_files()
    file_info = []
    for fp in files:
        try:
            size = fp.stat().st_size
        except OSError:
            size = 0
        file_info.append({
            'path': str(fp),
            'name': fp.name,
            'size_bytes': size,
        })

    return ToolResult.success({
        'knowledge_dir': KNOWLEDGE_DIR,
        'file_count': len(file_info),
        'files': file_info,
    })


@tool(
    name='read_knowledge_file',
    description='Read the full contents of a specific knowledge base file',
)
def read_knowledge_file(file_path: str) -> ToolResult:
    '''
    Read a specific file from the knowledge base.

    Input:
        file_path: Path to the file (relative to workspace or absolute).

    Output:
        ToolResult with the file contents and metadata.
    '''
    fp = Path(file_path)
    if not fp.exists():
        return ToolResult.failure(f'File not found: {file_path}')

    text = _read_text_file(fp)
    if not text:
        return ToolResult.failure(f'Failed to read file: {file_path}')

    sections = _extract_sections(text)

    return ToolResult.success({
        'file_path': str(fp),
        'file_name': fp.name,
        'size_bytes': fp.stat().st_size,
        'content': text,
        'section_count': len(sections),
        'sections': [s['heading'] for s in sections],
    })


@tool(
    name='read_document',
    description='Read and extract text from a document (PDF, DOCX, Markdown, TXT)',
)
def read_document(file_path: str) -> ToolResult:
    '''
    Read a user-provided document and extract its text content.

    Supports:
      - PDF  (.pdf)  — requires PyMuPDF, pdfplumber, or PyPDF2
      - DOCX (.docx) — requires python-docx
      - Markdown (.md), Text (.txt), RST (.rst) — built-in
      - JSON (.json), YAML (.yaml/.yml) — built-in

    Input:
        file_path: Path to the document.

    Output:
        ToolResult with extracted text, file type, and metadata.
    '''
    log.info(f'read_document: {file_path}')

    fp = Path(file_path)
    if not fp.exists():
        return ToolResult.failure(f'File not found: {file_path}')

    suffix = fp.suffix.lower()
    text: Optional[str] = None
    file_type = 'unknown'

    # PDF
    if suffix == '.pdf':
        file_type = 'pdf'
        text = _extract_pdf_text(file_path)
        if text is None:
            return ToolResult.failure(
                f'Cannot read PDF: {file_path}. '
                'Install PyMuPDF (pip install pymupdf), pdfplumber, or PyPDF2.'
            )

    # DOCX
    elif suffix == '.docx':
        file_type = 'docx'
        text = _extract_docx_text(file_path)
        if text is None:
            return ToolResult.failure(
                f'Cannot read DOCX: {file_path}. '
                'Install python-docx (pip install python-docx).'
            )

    # Text-based formats
    elif suffix in SUPPORTED_TEXT_EXTENSIONS:
        file_type = suffix.lstrip('.')
        text = _read_text_file(fp)

    else:
        return ToolResult.failure(
            f'Unsupported file type: {suffix}. '
            f'Supported: .pdf, .docx, {", ".join(sorted(SUPPORTED_TEXT_EXTENSIONS))}'
        )

    if not text:
        return ToolResult.failure(f'No text content extracted from: {file_path}')

    # Compute basic stats
    line_count = text.count('\n') + 1
    word_count = len(text.split())

    return ToolResult.success({
        'file_path': str(fp),
        'file_name': fp.name,
        'file_type': file_type,
        'size_bytes': fp.stat().st_size,
        'line_count': line_count,
        'word_count': word_count,
        'content': text,
    })


# ---------------------------------------------------------------------------
# BaseTool collection (for agent registration)
# ---------------------------------------------------------------------------

class KnowledgeTools(BaseTool):
    '''Collection of knowledge base and document reading tools for agent use.'''

    @tool(description='Search the local Cornelis knowledge base')
    def search_knowledge(self, query: str, max_results: int = 10) -> ToolResult:
        return search_knowledge(query=query, max_results=max_results)

    @tool(description='List all knowledge base files')
    def list_knowledge_files(self) -> ToolResult:
        return list_knowledge_files()

    @tool(description='Read a specific knowledge base file')
    def read_knowledge_file(self, file_path: str) -> ToolResult:
        return read_knowledge_file(file_path=file_path)

    @tool(description='Read and extract text from a document')
    def read_document(self, file_path: str) -> ToolResult:
        return read_document(file_path=file_path)
