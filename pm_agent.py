#!/usr/bin/env python3
##########################################################################################
#
# Script name: pm_agent.py
#
# Description: CLI entry point for Cornelis Agent Pipeline.
#              Provides commands for release planning workflow.
#
# Author: Cornelis Networks
#
# Usage:
#   python pm_agent.py --help
#   python pm_agent.py --plan --project PROJ --roadmap slides.pptx
#   python pm_agent.py --analyze --project PROJ
#   python pm_agent.py --resume --session abc123
#
##########################################################################################

import argparse
import logging
import re
import sys
import os
from datetime import date
from typing import Any, cast

from dotenv import load_dotenv

from core.utils import output, validate_and_repair_csv

import jira_utils
import excel_utils

jira_api = cast(Any, jira_utils)

# Load environment variables
load_dotenv()

# ****************************************************************************************
# Global data and configuration
# ****************************************************************************************

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))
log.setLevel(logging.DEBUG)

# File handler for logging
fh = logging.FileHandler('cornelis_agent.log', mode='w')
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)-15s [%(funcName)25s:%(lineno)-5s] %(levelname)-8s %(message)s')
fh.setFormatter(formatter)
log.addHandler(fh)

# Output control
_quiet_mode = False


# ****************************************************************************************
# Command handlers
# ****************************************************************************************

def cmd_plan(args):
    '''
    Run the release planning workflow.
    '''
    log.debug(f'cmd_plan(project={args.project}, plan_mode={args.plan_mode})')
    
    from agents.orchestrator import ReleasePlanningOrchestrator
    from state.session import SessionManager
    from state.persistence import get_persistence
    
    output('')
    output('=' * 60)
    output('CORNELIS RELEASE PLANNING AGENT')
    output('=' * 60)
    output('')
    
    # Set up persistence
    persistence = None
    if args.save_session:
        persistence = get_persistence(args.persistence_format)
    
    session_manager = SessionManager(persistence=persistence)
    
    # Collect input files
    roadmap_files = []
    if args.roadmap:
        roadmap_files.extend(args.roadmap)
    
    # Create orchestrator and run
    orchestrator = ReleasePlanningOrchestrator()
    
    output(f'Project: {args.project}')
    output(f'Roadmap files: {len(roadmap_files)}')
    if args.org_chart:
        output(f'Org chart: {args.org_chart}')
    output('')
    
    # Run the workflow
    result = orchestrator.run({
        'project_key': args.project,
        'roadmap_files': roadmap_files,
        'org_chart_file': args.org_chart,
        'mode': args.plan_mode
    })
    
    if result.success:
        output(result.content)
        
        # Save session if requested
        if args.save_session and orchestrator.state:
            from state.session import SessionState
            session = SessionState(
                project_key=args.project,
                roadmap_files=roadmap_files,
                org_chart_file=args.org_chart,
                roadmap_data=orchestrator.state.roadmap_data,
                jira_state=orchestrator.state.jira_state,
                release_plan=orchestrator.state.release_plan,
                current_step=orchestrator.state.current_step
            )
            session_manager.current_session = session
            session_manager.save_session()
            output(f'\nSession saved: {session.session_id}')
    else:
        output(f'ERROR: {result.error}')
        return 1
    
    return 0


def cmd_analyze(args):
    '''
    Analyze Jira project state.
    '''
    log.debug(f'cmd_analyze(project={args.project}, quick={args.quick})')
    
    from agents.jira_analyst import JiraAnalystAgent
    
    output('')
    output('=' * 60)
    output('JIRA PROJECT ANALYSIS')
    output('=' * 60)
    output('')
    
    analyst = JiraAnalystAgent(project_key=args.project)
    
    if args.quick:
        # Quick analysis without LLM
        analysis = analyst.analyze_project(args.project)
        
        output(f"Project: {analysis.get('project_key')}")
        output('')
        
        summary = analysis.get('summary', {})
        output(f"Releases: {summary.get('total_releases', 0)} ({summary.get('unreleased_count', 0)} unreleased)")
        output(f"Components: {summary.get('component_count', 0)}")
        output(f"Issue Types: {summary.get('issue_type_count', 0)}")
        
        if analysis.get('errors'):
            output('\nErrors:')
            for error in analysis['errors']:
                output(f'  ! {error}')
    else:
        # Full LLM-powered analysis
        result = analyst.run(args.project)
        
        if result.success:
            output(result.content)
        else:
            output(f'ERROR: {result.error}')
            return 1
    
    return 0


def cmd_vision(args):
    '''
    Analyze roadmap files.
    '''
    log.debug(f'cmd_vision(files={args.vision})')
    
    from agents.vision_analyzer import VisionAnalyzerAgent
    
    output('')
    output('=' * 60)
    output('ROADMAP ANALYSIS')
    output('=' * 60)
    output('')
    
    analyzer = VisionAnalyzerAgent()
    
    if len(args.vision) == 1:
        result = analyzer.analyze_file(args.vision[0])
    else:
        result = analyzer.analyze_multiple(args.vision)
    
    if 'error' in result:
        output(f'ERROR: {result["error"]}')
        return 1
    
    output(f"Files analyzed: {len(result.get('files_analyzed', [args.vision[0]]))}")
    output(f"Releases found: {len(result.get('releases', []))}")
    output(f"Features found: {len(result.get('features', []))}")
    output(f"Timeline items: {len(result.get('timeline', []))}")
    
    if result.get('releases'):
        output('\nReleases:')
        for r in result['releases'][:10]:
            output(f"  - {r.get('version', 'Unknown')}")
    
    if result.get('features'):
        output('\nFeatures:')
        for f in result['features'][:10]:
            output(f"  - {f.get('text', '')[:60]}")
    
    return 0


def cmd_sessions(args):
    '''
    List or manage sessions.
    '''
    log.debug(f'cmd_sessions(list={args.list_sessions}, delete={args.delete_session})')
    
    from state.session import SessionManager
    from state.persistence import get_persistence
    
    persistence = get_persistence(args.persistence_format)
    session_manager = SessionManager(persistence=persistence)
    
    if args.delete_session:
        if session_manager.delete_session(args.delete_session):
            output(f'Deleted session: {args.delete_session}')
        else:
            output(f'Failed to delete session: {args.delete_session}')
        return 0
    
    # List sessions
    sessions = session_manager.list_sessions()
    
    output('')
    output('=' * 60)
    output('SAVED SESSIONS')
    output('=' * 60)
    output('')
    
    if not sessions:
        output('No saved sessions found.')
        return 0
    
    output(f'{"ID":<10} {"Project":<12} {"Step":<15} {"Updated":<20}')
    output('-' * 60)
    
    for session in sessions:
        output(f"{session['session_id']:<10} {session.get('project_key', 'N/A'):<12} {session.get('current_step', 'N/A'):<15} {session.get('updated_at', 'N/A')[:19]:<20}")
    
    output('')
    output(f'Total: {len(sessions)} sessions')
    
    return 0


def cmd_build_excel_map(args):
    ticket_keys = [k.upper() for k in args.ticket_keys]
    hierarchy_depth = args.hierarchy
    limit = getattr(args, 'limit', None)

    if getattr(args, 'output', None):
        output_file = args.output
    elif len(ticket_keys) == 1:
        output_file = f'{ticket_keys[0]}.xlsx'
    else:
        output_file = f'{"_".join(ticket_keys)}.xlsx'

    keep_intermediates = getattr(args, 'keep_intermediates', False)

    if not output_file.endswith('.xlsx'):
        output_file = f'{output_file}.xlsx'

    log.debug(f'cmd_build_excel_map(ticket_keys={ticket_keys}, hierarchy={args.hierarchy}, limit={limit}, output={output_file})')

    output('')
    output('=' * 60)
    output('BUILD EXCEL MAP')
    output('=' * 60)
    output(f'Root ticket(s):  {", ".join(ticket_keys)}')
    output(f'Hierarchy depth: {hierarchy_depth}')
    output(f'Output file:     {output_file}')
    if limit:
        output(f'Limit:           {limit}')
    output('')

    try:
        result = excel_utils.build_excel_map(
            ticket_keys=ticket_keys,
            hierarchy_depth=hierarchy_depth,
            limit=limit,
            output_file=output_file,
            project_key=getattr(args, 'project', None),
            keep_intermediates=keep_intermediates,
            output_callback=output,
        )

        if keep_intermediates:
            temp_dir = result.get('temp_dir')
            temp_files = result.get('temp_files', [])
            if temp_dir:
                output(f'Intermediate files kept in: {temp_dir}')
                for temp_file in temp_files:
                    output(f'  {temp_file}')

        return 0

    except Exception as e:
        log.error(f'Failed to build Excel map: {e}', exc_info=True)
        output(f'ERROR: {e}')
        return 1


def _extract_and_save_files(response_text):
    '''
    Parse fenced code blocks from an LLM response and save any that specify
    a filename.

    Recognised patterns (the filename line immediately precedes the opening
    fence or is embedded in the fence info-string):

        **`path/to/file.ext`**          (bold-backtick markdown)
        `path/to/file.ext`              (backtick markdown)
        path/to/file.ext                (bare path on its own line)
        ```lang:path/to/file.ext        (colon-separated in info-string)
        ```path/to/file.ext             (info-string IS the path)

    Returns a list of (filepath, content) tuples that were written.
    '''
    saved = []

    # ---- Strategy 1: filename on the line before the opening fence ----------
    # Matches patterns like:
    #   **`somefile.py`**
    #   `somefile.py`
    #   somefile.py
    # followed by ```<optional lang>\n ... \n```
    pattern_pre = re.compile(
        r'(?:^|\n)'                          # start of string or newline
        r'[ \t]*'                            # optional leading whitespace
        r'(?:\*{0,2}`?)'                     # optional bold / backtick prefix
        r'([\w][\w./\\-]*\.\w+)'             # captured filename (must have extension)
        r'(?:`?\*{0,2})'                     # optional backtick / bold suffix
        r'[ \t]*\n'                          # end of filename line
        r'```[^\n]*\n'                       # opening fence (``` with optional info)
        r'(.*?)'                             # captured content (non-greedy)
        r'\n```',                            # closing fence
        re.DOTALL,
    )

    for m in pattern_pre.finditer(response_text):
        filepath = m.group(1).strip()
        content = m.group(2)
        if filepath and content is not None:
            saved.append((filepath, content))

    # ---- Strategy 2: filename embedded in the info-string -------------------
    # Matches ```lang:path/to/file.ext  or  ```path/to/file.ext
    # Only used for blocks NOT already captured by Strategy 1.
    pattern_info = re.compile(
        r'```'
        r'(?:[\w]+:)?'                       # optional lang: prefix
        r'([\w][\w./\\-]*\.\w+)'             # captured filename
        r'[ \t]*\n'
        r'(.*?)'                             # captured content
        r'\n```',
        re.DOTALL,
    )

    # Build a set of already-captured content spans to avoid duplicates
    captured_spans = {(m.start(), m.end()) for m in pattern_pre.finditer(response_text)}

    for m in pattern_info.finditer(response_text):
        # Skip if this block overlaps with one already captured
        if any(m.start() >= cs[0] and m.end() <= cs[1] for cs in captured_spans):
            continue
        filepath = m.group(1).strip()
        content = m.group(2)
        if filepath and content is not None:
            saved.append((filepath, content))

    # ---- Strategy 2b: filename as first line inside the code block ----------
    # Handles the pattern where the LLM places the filename as the first
    # non-empty line *inside* the fenced block (not on the fence line and
    # not on a preceding line).  Example:
    #   ```
    #   my_report.csv
    #   col1,col2,col3
    #   ...
    #   ```
    # We recognise a first line as a filename if it matches word.ext with a
    # known file extension and contains no spaces (to avoid false positives
    # on prose or data lines).
    KNOWN_EXTENSIONS = {
        'csv', 'json', 'xml', 'yaml', 'yml', 'md', 'txt', 'sql', 'html',
        'toml', 'ini', 'py', 'js', 'ts', 'sh', 'cfg', 'log', 'xlsx',
    }
    pattern_inner_name = re.compile(
        r'```[^\n]*\n'                       # opening fence (``` with optional info)
        r'(.*?)'                             # captured full content
        r'\n```',                            # closing fence
        re.DOTALL,
    )
    # Build set of already-captured spans (from Strategies 1 & 2)
    captured_spans_2b = set()
    for m in pattern_pre.finditer(response_text):
        captured_spans_2b.add((m.start(), m.end()))
    for m in pattern_info.finditer(response_text):
        if not any(m.start() >= cs[0] and m.end() <= cs[1] for cs in captured_spans_2b):
            captured_spans_2b.add((m.start(), m.end()))

    for m in pattern_inner_name.finditer(response_text):
        # Skip blocks already captured by earlier strategies
        if any(m.start() >= cs[0] and m.end() <= cs[1] for cs in captured_spans_2b):
            continue
        content = m.group(1)
        if not content or not content.strip():
            continue
        # Check if the first non-empty line looks like a filename
        lines = content.split('\n')
        first_line = ''
        first_line_idx = 0
        for i, line in enumerate(lines):
            if line.strip():
                first_line = line.strip()
                first_line_idx = i
                break
        if not first_line:
            continue
        # A filename candidate: no spaces, has a dot, extension is known
        if ' ' not in first_line and '.' in first_line:
            ext = first_line.rsplit('.', 1)[-1].lower()
            if ext in KNOWN_EXTENSIONS:
                filepath = first_line
                # Remaining lines (after the filename line) become the content
                remaining = '\n'.join(lines[first_line_idx + 1:])
                if remaining.strip():
                    saved.append((filepath, remaining))
                    log.debug(f'Strategy 2b: first-line filename "{filepath}" '
                              f'inside code block')

    # ---- Strategy 3: auto-save fallback for unnamed data blocks -------------
    # When no named files were found by Strategies 1-2, look for fenced blocks
    # whose info-string is a known data format and auto-save as llm_output.<ext>.
    # If multiple blocks share the same extension, number them (llm_output_2.csv, etc).
    AUTO_SAVE_EXTS = {
        'csv': 'csv', 'json': 'json', 'xml': 'xml', 'yaml': 'yaml',
        'yml': 'yaml', 'md': 'md', 'markdown': 'md', 'txt': 'txt',
        'sql': 'sql', 'html': 'html', 'toml': 'toml', 'ini': 'ini',
    }

    if not saved:
        # Find all fenced blocks with an info-string
        pattern_auto = re.compile(
            r'```(\w+)[ \t]*\n'              # opening fence with info-string
            r'(.*?)'                          # captured content
            r'\n```',                         # closing fence
            re.DOTALL,
        )
        ext_counts = {}  # track how many blocks per extension for numbering
        for m in pattern_auto.finditer(response_text):
            info = m.group(1).lower()
            content = m.group(2)
            if info in AUTO_SAVE_EXTS and content and content.strip():
                ext = AUTO_SAVE_EXTS[info]
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
                count = ext_counts[ext]
                # Naming: llm_output_file1.csv, llm_output_file2.csv, etc.
                filepath = f'llm_output_file{count}.{ext}'
                saved.append((filepath, content))
                log.debug(f'Auto-save fallback: {info} block -> {filepath}')

    # ---- Write files --------------------------------------------------------
    written = []
    for filepath, content in saved:
        try:
            # Create parent directories if needed
            parent = os.path.dirname(filepath)
            if parent:
                os.makedirs(parent, exist_ok=True)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
                # Ensure file ends with a newline
                if content and not content.endswith('\n'):
                    f.write('\n')

            # ---- CSV validation: repair rows with wrong column count --------
            # LLMs sometimes emit CSV with unquoted commas inside fields
            # (e.g. "12.1.0.0.72,78" in a summary).  Detect and repair by
            # re-reading with the csv module and merging excess columns back
            # into the widest text field (typically 'summary').
            if filepath.lower().endswith('.csv'):
                validate_and_repair_csv(filepath)

            written.append(filepath)
            log.info(f'Saved extracted file: {filepath} ({len(content)} chars)')
        except Exception as e:
            log.warning(f'Failed to save extracted file {filepath}: {e}')
            output(f'  WARNING: could not save {filepath}: {e}')

    return written


def _invoke_llm(prompt_text, attachments=None, timeout=None, model=None):
    '''
    Send a prompt to the configured LLM with optional file attachments.

    This is the shared core logic extracted from cmd_invoke_llm() so it can
    be reused by workflow commands.

    Input:
        prompt_text: The prompt string to send.
        attachments: Optional list of file paths to attach.
        timeout: Optional timeout in seconds.
        model: Optional model name override.  When provided, this overrides
               the CORNELIS_LLM_MODEL / OPENAI_MODEL / etc. env-var default.

    Output:
        Tuple of (response_content, saved_files, token_info) where:
          - response_content: str, the full LLM response text
          - saved_files: list of file paths extracted/saved from the response
          - token_info: dict with keys prompt_tokens, completion_tokens, total_tokens,
                        model, finish_reason, elapsed, estimated_cost

    Raises:
        Exception if the LLM call fails.
    '''
    log.debug(f'Entering _invoke_llm(prompt_len={len(prompt_text)}, '
              f'attachments={attachments}, timeout={timeout}, model={model})')

    import base64
    import mimetypes
    from llm.config import get_llm_client
    from llm.base import Message

    # ---- classify attachments -----------------------------------------------
    IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'}
    TEXT_EXTS = {
        '.md', '.txt', '.csv', '.json', '.yaml', '.yml', '.xml',
        '.py', '.js', '.ts', '.html', '.css', '.sh', '.sql',
        '.log', '.cfg', '.ini', '.toml',
    }

    image_data_uris = []   # base64 data URIs for vision API
    text_blocks = []       # fenced code blocks to append to prompt

    for filepath in (attachments or []):
        if not os.path.isfile(filepath):
            output(f'WARNING: attachment not found, skipping: {filepath}')
            log.warning(f'Attachment not found: {filepath}')
            continue

        ext = os.path.splitext(filepath)[1].lower()

        if ext in IMAGE_EXTS:
            # Encode image as base64 data URI for the vision API
            mime_type = mimetypes.guess_type(filepath)[0] or 'image/png'
            with open(filepath, 'rb') as img_f:
                b64 = base64.b64encode(img_f.read()).decode('utf-8')
            data_uri = f'data:{mime_type};base64,{b64}'
            image_data_uris.append(data_uri)
            log.debug(f'Attached image: {filepath} ({mime_type})')
            output(f'  Attached image: {filepath}')
        else:
            # Attempt to read as text
            try:
                with open(filepath, 'r', encoding='utf-8') as txt_f:
                    content = txt_f.read()
                # Determine language hint for fenced block
                lang = ext.lstrip('.') if ext in TEXT_EXTS else ''
                text_blocks.append(f'\n\n--- Attachment: {os.path.basename(filepath)} ---\n```{lang}\n{content}\n```')
                log.debug(f'Attached text file: {filepath} ({len(content)} chars)')
                output(f'  Attached text: {filepath} ({len(content)} chars)')
            except (UnicodeDecodeError, IOError) as e:
                output(f'WARNING: cannot read attachment as text, skipping: {filepath} ({e})')
                log.warning(f'Cannot read attachment {filepath}: {e}')

    # ---- build final prompt with inlined text attachments -------------------
    if text_blocks:
        prompt_text = prompt_text + '\n' + ''.join(text_blocks)

    # ---- send to LLM -------------------------------------------------------
    output('')
    total_chars = len(prompt_text)
    timeout_display = f'{timeout}s' if timeout else 'default'
    output(f'Sending to LLM... ({total_chars} chars, timeout={timeout_display})')

    # Use vision client if images are present, otherwise standard client.
    # When a model override is supplied via --model, pass it through to the
    # factory so it takes precedence over the env-var default.
    if image_data_uris:
        client = get_llm_client(for_vision=True, timeout=timeout, model=model)
        log.info(f'+  Using LLM model: {client.model}')
        output(f'Using vision model: {client.model} ({len(image_data_uris)} image(s))')
        messages = [Message.user(prompt_text)]
    else:
        client = get_llm_client(timeout=timeout, model=model)
        log.info(f'+  Using LLM model: {client.model}')
        output(f'Using model: {client.model}')
        messages = [Message.user(prompt_text)]

    # ---- call LLM -----------------------------------------------------------
    # Heartbeat "Still waiting on LLM return..." messages are now emitted
    # inside CornelisLLM.chat() / chat_with_vision() themselves, so no
    # wrapper thread is needed here.
    import time as _time
    _llm_start = _time.monotonic()
    if image_data_uris:
        response = client.chat_with_vision(messages, image_data_uris)
    else:
        response = client.chat(messages)
    elapsed_total = _time.monotonic() - _llm_start

    # ---- display response ---------------------------------------------------
    output('')
    output('=' * 60)
    output('LLM RESPONSE')
    output('=' * 60)
    output('')
    output(response.content)
    output('')
    output('-' * 60)

    log.info(f'LLM response received: {len(response.content)} chars, '
             f'tokens={response.usage}')

    # ---- token usage & cost table -------------------------------------------
    prompt_tok = 0
    completion_tok = 0
    total_tok = 0
    if response.usage:
        prompt_tok = response.usage.get('prompt_tokens', 0)
        completion_tok = response.usage.get('completion_tokens', 0)
        total_tok = response.usage.get('total_tokens', 0)

    # Estimate cost using typical per-token pricing (rough approximation).
    # These rates are ballpark for GPT-4o-class models; adjust as needed.
    COST_PER_1K_PROMPT = 0.0025       # $2.50 / 1M prompt tokens
    COST_PER_1K_COMPLETION = 0.0100   # $10.00 / 1M completion tokens
    estimated_cost = (
        (prompt_tok / 1000.0) * COST_PER_1K_PROMPT
        + (completion_tok / 1000.0) * COST_PER_1K_COMPLETION
    )

    elapsed_str = f'{elapsed_total:.1f}s'

    # Build the summary box using ==== banner style
    banner = '=' * 80
    log.info(banner)
    log.info(f'  LLM totals: prompt_tokens={prompt_tok}, completion_tokens={completion_tok}')
    log.info(f'  Model: {response.model or "unknown"}')
    log.info(f'  Finish reason: {response.finish_reason or "n/a"}')
    log.info(f'  Elapsed: {elapsed_str}')
    log.info(f'  Estimated LLM cost: ${estimated_cost:.4f}')
    log.info(banner)

    # Token usage & metadata table — ==== banner style, key:  value alignment
    token_table = (
        f'\n'
        f'{banner}\n'
        f'LLM Token Usage\n'
        f'{banner}\n'
        f'{"Prompt tokens (in):":<30}  {prompt_tok:>12,}\n'
        f'{"Completion tokens (out):":<30}  {completion_tok:>12,}\n'
        f'{"Total tokens:":<30}  {total_tok:>12,}\n'
        f'{banner}\n'
        f'{"Model:":<30}  {(response.model or "unknown"):>12}\n'
        f'{"Finish reason:":<30}  {(response.finish_reason or "n/a"):>12}\n'
        f'{"Elapsed:":<30}  {elapsed_str:>12}\n'
        f'{"Estimated cost:":<30}  {f"${estimated_cost:.4f}":>12}\n'
        f'{banner}'
    )
    output(token_table)

    # ---- save full response as llm_output.md --------------------------------
    all_created_files = []   # (filepath, size_chars, source) tuples

    try:
        with open('llm_output.md', 'w', encoding='utf-8') as f:
            f.write(response.content)
            if response.content and not response.content.endswith('\n'):
                f.write('\n')
        all_created_files.append(('llm_output.md', len(response.content), 'full response'))
        log.info(f'Saved full LLM response: llm_output.md ({len(response.content)} chars)')
    except Exception as e:
        log.warning(f'Failed to save llm_output.md: {e}')
        output(f'WARNING: could not save llm_output.md: {e}')

    # ---- extract and save any file content from the response ----------------
    saved_files = _extract_and_save_files(response.content)
    for sf in saved_files:
        try:
            sz = os.path.getsize(sf)
        except OSError:
            sz = 0
        all_created_files.append((sf, sz, 'extracted'))

    # ---- file-creation summary table — ==== banner style --------------------
    if all_created_files:
        banner = '=' * 80
        max_name = max(len(f[0]) for f in all_created_files)
        max_name = max(max_name, 4)  # minimum width for header "File"
        row_fmt = f'{{:<4}}{{:<{max_name + 3}}}{{:>10}}   {{:<12}}'

        file_table_lines = [
            '',
            banner,
            'LLM Created Files',
            banner,
            row_fmt.format('#', 'File', 'Size', 'Source'),
        ]
        for idx, (fpath, fsize, fsource) in enumerate(all_created_files, 1):
            size_str = f'{fsize:,} ch' if fsize else '0 ch'
            file_table_lines.append(row_fmt.format(str(idx), fpath, size_str, fsource))
        file_table_lines.append(banner)

        file_table = '\n'.join(file_table_lines)
        output(file_table)

    # ---- build token_info dict for callers ----------------------------------
    token_info = {
        'prompt_tokens': prompt_tok,
        'completion_tokens': completion_tok,
        'total_tokens': total_tok,
        'model': response.model or 'unknown',
        'finish_reason': response.finish_reason or 'n/a',
        'elapsed': elapsed_total,
        'estimated_cost': estimated_cost,
    }

    return response.content, saved_files, token_info


def cmd_invoke_llm(args):
    '''
    Send a prompt to the configured LLM, optionally with file attachments.

    The prompt argument can be:
      - A path to a .md or .txt file whose contents become the prompt
      - An inline string used directly as the prompt

    Attachments are classified by extension:
      - Image files (.png, .jpg, .jpeg, .gif, .bmp, .webp, .svg) are sent
        via the vision API as base64-encoded images.
      - Text files (.md, .txt, .csv, .json, .yaml, .yml, .xml, .py, .js,
        .ts, .html, .css, .sh, .sql, .log, .cfg, .ini, .toml) are read
        and inlined into the prompt as fenced code blocks.
      - Other extensions are attempted as text; binary files are skipped
        with a warning.

    This is a thin wrapper around _invoke_llm() that resolves the prompt
    from args and delegates to the shared helper.
    '''
    log.debug(f'cmd_invoke_llm(prompt={args.prompt}, attachments={args.attachments})')

    # ---- resolve prompt text ------------------------------------------------
    prompt_arg = args.prompt
    if os.path.isfile(prompt_arg):
        log.debug(f'Reading prompt from file: {prompt_arg}')
        with open(prompt_arg, 'r', encoding='utf-8') as f:
            prompt_text = f.read().strip()
        output(f'Prompt loaded from {prompt_arg} ({len(prompt_text)} chars)')
    else:
        prompt_text = prompt_arg
        output(f'Using inline prompt ({len(prompt_text)} chars)')

    # ---- delegate to shared helper ------------------------------------------
    # Pass --model override if the user provided one on the CLI
    model_override = getattr(args, 'model', None)
    try:
        response_content, saved_files, token_info = _invoke_llm(
            prompt_text, attachments=args.attachments, timeout=args.timeout,
            model=model_override)
        return 0
    except Exception as e:
        log.error(f'LLM invocation failed: {e}', exc_info=True)
        output(f'ERROR: {e}')
        return 1


def cmd_workflow(args):
    '''
    Run a named workflow. Dispatches to the appropriate workflow handler.

    Input:
        args: Parsed argparse namespace with workflow_name and workflow-specific options.

    Output:
        int: Exit code (0 = success, 1 = error).

    Side Effects:
        Delegates to the workflow handler which may connect to Jira, invoke the LLM,
        and create output files.
    '''
    log.debug(f'Entering cmd_workflow(workflow_name={args.workflow_name})')

    # Registry of available workflows
    WORKFLOWS = {
        'bug-report': _workflow_bug_report,
        'feature-plan': _workflow_feature_plan,
    }

    handler = WORKFLOWS.get(args.workflow_name)
    if not handler:
        available = ', '.join(sorted(WORKFLOWS.keys()))
        output(f'ERROR: Unknown workflow "{args.workflow_name}". Available: {available}')
        return 1

    return handler(args)


# ---------------------------------------------------------------------------
# Shared workflow summary helper
# ---------------------------------------------------------------------------

def _print_workflow_summary(workflow_name: str, created_files: list[tuple[str, str]]):
    '''Print a standardised "WORKFLOW COMPLETE" banner with a file table.

    Input:
        workflow_name:  Short name shown in the banner (e.g. "bug-report").
        created_files:  List of (filepath, description) tuples.
    '''
    banner = '=' * 80
    output('')
    output(banner)
    output(f'WORKFLOW COMPLETE: {workflow_name}')
    output(banner)

    if created_files:
        max_name = max(len(f[0]) for f in created_files)
        max_name = max(max_name, 4)  # minimum column width
        row_fmt = f'{{:<4}}{{:<{max_name + 3}}}{{:<}}'

        file_table_lines = [
            '',
            banner,
            'Workflow Output Files',
            banner,
            row_fmt.format('#', 'File', 'Description'),
        ]
        for idx, (fpath, fdesc) in enumerate(created_files, 1):
            file_table_lines.append(row_fmt.format(str(idx), fpath, fdesc))
        file_table_lines.append(banner)

        output('\n'.join(file_table_lines))

    output('')


def _workflow_bug_report(args):
    '''
    Bug report workflow: filter lookup → run filter → LLM analysis → Excel conversion.

    Steps:
      1. Connect to Jira
      2. Look up filter by name from favourite filters
      3. Run the filter to get tickets with latest comments
      4. Dump tickets to JSON file
      5. Send JSON + prompt to LLM
      6. Convert any extracted CSV to styled Excel

    Input:
        args: Parsed argparse namespace with:
            - workflow_filter: str, the Jira filter name to look up
            - workflow_prompt: str or None, path to the prompt file
            - timeout: float or None, LLM timeout in seconds
            - limit: int or None, max tickets to retrieve
            - output: str or None, output filename override

    Output:
        int: Exit code (0 = success, 1 = error).

    Side Effects:
        Creates JSON dump file, llm_output.md, extracted CSV/Excel files.
    '''
    log.debug(f'Entering _workflow_bug_report(filter={args.workflow_filter}, '
              f'prompt={args.workflow_prompt}, limit={args.limit}, timeout={args.timeout})')

    filter_name = args.workflow_filter
    prompt_path = args.workflow_prompt or 'config/prompts/cn5000_bugs_clean.md'
    all_created_files = []  # (filepath, description) tuples for final summary

    # ---- Step 1/6: Connect to Jira ------------------------------------------
    output('')
    output('=' * 60)
    output('WORKFLOW: bug-report')
    output('=' * 60)
    output('')
    output('Step 1/6: Connecting to Jira...')
    try:
        jira = jira_api.get_connection()
        log.info('Jira connection established')
    except Exception as e:
        log.error(f'Step 1/6 failed: Jira connection error: {e}', exc_info=True)
        output(f'ERROR: Failed to connect to Jira: {e}')
        return 1

    # ---- Step 2/6: Look up filter by name -----------------------------------
    output('')
    output(f'Step 2/6: Looking up filter "{filter_name}" from favourite filters...')
    try:
        filters = jira_utils.list_filters(jira, favourite_only=True)
        # Search for exact match on filter name
        matched_filter = None
        for f in filters:
            if f.get('name') == filter_name:
                matched_filter = f
                break

        if not matched_filter:
            # Show available filter names to help the user
            available_names = [f.get('name', '(unnamed)') for f in filters]
            output(f'ERROR: Filter "{filter_name}" not found in favourite filters.')
            if available_names:
                output(f'  Available favourite filters:')
                for fn in available_names:
                    output(f'    - {fn}')
            return 1

        filter_id = matched_filter.get('id')
        filter_jql = matched_filter.get('jql', '')
        log.info(f'Found filter: id={filter_id}, name={filter_name}, jql={filter_jql}')
        output(f'  Found filter ID: {filter_id}')
        output(f'  JQL: {filter_jql}')
    except Exception as e:
        log.error(f'Step 2/6 failed: Filter lookup error: {e}', exc_info=True)
        output(f'ERROR: Failed to look up filter: {e}')
        return 1

    # ---- Step 3/6: Run the filter to get tickets ----------------------------
    output('')
    output(f'Step 3/6: Running filter to retrieve tickets...')
    try:
        # Set the global _include_comments flag so run_jql_query fetches comment
        # fields and dump_tickets_to_file applies the 'latest' filter.
        jira_utils._include_comments = 'latest'
        log.info('Set _include_comments = "latest" for comment extraction')

        issues = jira_utils.run_filter(jira, filter_id, limit=args.limit)
        if not issues:
            output('WARNING: Filter returned 0 tickets. Nothing to process.')
            return 0
        log.info(f'Filter returned {len(issues)} tickets')
        output(f'  Retrieved {len(issues)} tickets')
    except Exception as e:
        log.error(f'Step 3/6 failed: Filter execution error: {e}', exc_info=True)
        output(f'ERROR: Failed to run filter: {e}')
        return 1

    # ---- Step 4/6: Dump tickets to JSON file --------------------------------
    output('')
    output(f'Step 4/6: Dumping tickets to JSON...')
    try:
        # Derive dump filename from filter name (sanitize for filesystem)
        safe_name = re.sub(r'[^\w\s-]', '', filter_name).strip().lower()
        safe_name = re.sub(r'[\s]+', '_', safe_name)
        dump_basename = args.output or safe_name or 'bug_report'
        # Strip any extension the user may have provided — we force .json here
        dump_basename = os.path.splitext(dump_basename)[0]

        dump_path = jira_api.dump_tickets_to_file(
            issues, dump_basename, 'json', include_comments='latest')
        log.info(f'Tickets dumped to: {dump_path}')
        output(f'  Saved: {dump_path}')
        all_created_files.append((dump_path, 'ticket JSON dump'))
    except Exception as e:
        log.error(f'Step 4/6 failed: Dump error: {e}', exc_info=True)
        output(f'ERROR: Failed to dump tickets: {e}')
        return 1

    # ---- Step 5/6: Send JSON + prompt to LLM --------------------------------
    output('')
    output(f'Step 5/6: Sending tickets + prompt to LLM...')
    try:
        # Read the prompt file
        if not os.path.isfile(prompt_path):
            output(f'ERROR: Prompt file not found: {prompt_path}')
            return 1
        with open(prompt_path, 'r', encoding='utf-8') as pf:
            prompt_text = pf.read().strip()
        log.info(f'Loaded prompt from {prompt_path} ({len(prompt_text)} chars)')
        output(f'  Prompt: {prompt_path} ({len(prompt_text)} chars)')

        # Pass --model override if the user provided one on the CLI
        model_override = getattr(args, 'model', None)
        response_content, saved_files, token_info = _invoke_llm(
            prompt_text, attachments=[dump_path], timeout=args.timeout,
            model=model_override)

        # Track llm_output.md if it was created
        if os.path.isfile('llm_output.md'):
            all_created_files.append(('llm_output.md', 'LLM full response'))
        for sf in saved_files:
            all_created_files.append((sf, 'LLM extracted'))

    except Exception as e:
        log.error(f'Step 5/6 failed: LLM invocation error: {e}', exc_info=True)
        output(f'ERROR: LLM invocation failed: {e}')
        return 1

    # ---- Step 6/6: Convert CSV files to styled Excel ------------------------
    output('')
    output(f'Step 6/6: Converting CSV output to Excel...')
    csv_files = [sf for sf in saved_files if sf.lower().endswith('.csv')]

    # Canonical CSV name derived from the filter / output basename.
    # We always rename the final CSV to this so the deliverable has a
    # predictable, clean filename regardless of what the LLM chose.
    canonical_csv = f'{dump_basename}.csv'

    # Deduplicate: when the LLM emits multiple CSV blocks (e.g. an original
    # and a "corrected" version), keep only the LAST one — it is typically the
    # most complete / corrected.
    #
    # Edge case: the LLM may emit multiple blocks with the SAME filename.
    # In that case the second write already overwrote the first on disk, so
    # there is only one physical file.  We must NOT os.remove() it because
    # that would delete the surviving copy.  We also must not strip ALL
    # tracking entries for that name — we need to keep exactly one.
    if len(csv_files) > 1:
        keep = csv_files[-1]           # last CSV is the corrected one
        discard = csv_files[:-1]
        log.info(f'LLM emitted {len(csv_files)} CSV files; keeping last: {keep}')

        # Collect unique discard paths that differ from keep — safe to delete
        unique_discard = set(d for d in discard if d != keep)
        same_name_count = sum(1 for d in discard if d == keep)
        if same_name_count:
            log.info(f'{same_name_count} duplicate(s) share the same filename as keep ({keep}); skipping remove')

        for d in unique_discard:
            try:
                os.remove(d)
                log.info(f'Removed duplicate CSV: {d}')
            except OSError as rm_err:
                log.warning(f'Could not remove {d}: {rm_err}')

        # Rebuild tracking lists: remove ALL csv entries, then re-add the
        # single keep entry.  This avoids the problem where same-name
        # duplicates cause the keep entry to be removed too.
        discard_set = set(csv_files)  # all csv filenames (including keep)
        all_created_files[:] = [
            (f, desc) for f, desc in all_created_files if f not in discard_set]
        all_created_files.append((keep, 'LLM extracted'))
        saved_files = [sf for sf in saved_files if sf not in discard_set]
        saved_files.append(keep)

        csv_files = [keep]
        output(f'  Deduplicated: keeping {keep}')

    # Rename the surviving CSV to the canonical name so the deliverable
    # filename is predictable (e.g. sw_1211_p0p1_bugs.csv) regardless of
    # whatever name the LLM invented for the file.
    if len(csv_files) == 1 and csv_files[0] != canonical_csv:
        keep = csv_files[0]
        try:
            os.rename(keep, canonical_csv)
            log.info(f'Renamed {keep} -> {canonical_csv}')
            # Update tracking lists
            all_created_files[:] = [
                (canonical_csv if f == keep else f, desc)
                for f, desc in all_created_files]
            saved_files = [
                canonical_csv if sf == keep else sf for sf in saved_files]
            csv_files = [canonical_csv]
            output(f'  Renamed: {keep} -> {canonical_csv}')
        except OSError as ren_err:
            log.warning(f'Could not rename {keep} -> {canonical_csv}: {ren_err}')

    if not csv_files:
        output('  No CSV files found in LLM output — skipping Excel conversion.')
        log.info('No CSV files to convert to Excel')
    else:
        # Pass the Jira base URL so ticket-key cells become clickable links
        # in the Excel output (e.g. https://cornelisnetworks.atlassian.net/browse/STL-76582).
        jira_base_url = getattr(jira_utils, 'JIRA_URL', None)
        dashboard_columns = getattr(args, 'dashboard_columns', None)
        for csv_path in csv_files:
            try:
                xlsx_path = excel_utils.convert_from_csv(
                    csv_path, jira_base_url=jira_base_url,
                    dashboard_columns=dashboard_columns)
                log.info(f'Converted {csv_path} -> {xlsx_path}')
                output(f'  Converted: {csv_path} -> {xlsx_path}')
                all_created_files.append((xlsx_path, 'Excel workbook'))
            except Exception as e:
                log.error(f'Excel conversion failed for {csv_path}: {e}', exc_info=True)
                output(f'  WARNING: Failed to convert {csv_path} to Excel: {e}')

    _print_workflow_summary('bug-report', all_created_files)
    return 0


def _workflow_feature_plan(args):
    '''
    Feature planning workflow: research → HW analysis → scoping → Jira plan.

    Takes a high-level feature request and produces a Jira project plan with
    Epics and Stories.  Dry-run by default; use --execute to create tickets.

    Input:
        args: Parsed argparse namespace with:
            - project: Jira project key
            - feature: Feature description string
            - docs: Optional list of document paths
            - output: Optional output file path
            - execute: Whether to create tickets in Jira

    Output:
        int: Exit code (0 = success, 1 = error).
    '''
    log.debug('Entering _workflow_feature_plan()')

    project_key = args.project
    plan_file = getattr(args, 'plan_file', None)
    execute = getattr(args, 'execute', False)
    initiative_key = getattr(args, 'initiative', None)
    force = getattr(args, 'force', False)
    cleanup_csv = getattr(args, 'cleanup', None)

    # ------------------------------------------------------------------
    # Cleanup path: --cleanup CSV deletes all tickets listed in the CSV
    # produced by a previous --execute run.  Dry-run by default; add
    # --execute to actually delete.  The CSV is already in child-first
    # order so parents are deleted last.
    # ------------------------------------------------------------------
    if cleanup_csv:
        output('Feature Planning Workflow — Cleanup (Leave No Trace)')
        output(f'  CSV file:  {cleanup_csv}')
        output(f'  Execute:   {"YES — will DELETE tickets" if execute else "DRY RUN"}')
        if force:
            output(f'  Force:     YES — skip confirmation prompt')
        output('')

        if not os.path.isfile(cleanup_csv):
            output(f'ERROR: Cleanup CSV not found: {cleanup_csv}')
            return 1

        try:
            jira = jira_api.get_connection()
            jira_utils.bulk_delete_tickets(
                jira,
                input_file=cleanup_csv,
                delete_subtasks=True,
                dry_run=not execute,
                force=force,
            )
            return 0
        except Exception as e:
            output(f'ERROR: Cleanup failed: {e}')
            log.error(f'Cleanup error: {e}', exc_info=True)
            return 1

    # ------------------------------------------------------------------
    # Fast path: --plan-file loads a previously generated plan.json and
    # optionally pushes it into Jira (--execute).  No LLM / agentic
    # phases are invoked.
    # ------------------------------------------------------------------
    if plan_file:
        output(f'Feature Planning Workflow — Execute from Plan File')
        output(f'  Project:      {project_key}')
        output(f'  Plan file:    {plan_file}')
        if initiative_key:
            output(f'  Initiative:   {initiative_key} (supplied)')
        else:
            output(f'  Initiative:   (will be auto-created on --execute)')
        output(f'  Force:        {"YES — skip duplicate prompts" if force else "no (interactive)"}')
        output(f'  Execute:      {"YES — will create Jira tickets" if execute else "DRY RUN"}')
        output('')

        try:
            from agents.feature_planning_orchestrator import FeaturePlanningOrchestrator

            orchestrator = FeaturePlanningOrchestrator()
            response = orchestrator.run({
                'project_key': project_key,
                'feature_request': '',          # not needed for execute-plan
                'mode': 'execute-plan',
                'plan_file': plan_file,
                'execute': execute,
                'initiative_key': initiative_key,
                'force': force,
                'feature_tag': getattr(args, 'feature_tag', None),
                'timeout': getattr(args, 'timeout', None),
            })

            if response.success:
                output(response.content)

                # Surface the created_tickets.csv path if it was produced
                csv_path = response.metadata.get('created_csv_path', '')
                if csv_path and os.path.isfile(csv_path):
                    output(f'\nCreated tickets CSV: {csv_path}')

                # If this was a dry-run, remind the user
                if not execute:
                    output('')
                    output('This was a DRY RUN. To create tickets in Jira, '
                           're-run with --execute.')
                return 0
            else:
                output(f'ERROR: {response.error}')
                return 1

        except ImportError as e:
            output(f'ERROR: Missing dependency: {e}')
            log.error(f'Import error: {e}', exc_info=True)
            return 1
        except Exception as e:
            output(f'ERROR: Plan execution failed: {e}')
            log.error(f'Plan execution error: {e}', exc_info=True)
            return 1

    # ------------------------------------------------------------------
    # Standard path: agentic workflow (research → HW → scoping → plan)
    # ------------------------------------------------------------------

    # --feature-prompt FILE takes precedence over --feature "string"
    feature_prompt_file = getattr(args, 'feature_prompt', None)
    if feature_prompt_file:
        log.info(f'Reading feature prompt from file: {feature_prompt_file}')
        with open(feature_prompt_file, 'r', encoding='utf-8') as fp:
            feature_request = fp.read().strip()
        if not feature_request:
            output(f'ERROR: Feature prompt file is empty: {feature_prompt_file}')
            return 1
        log.info(f'Feature prompt loaded: {len(feature_request)} chars from {feature_prompt_file}')
    else:
        feature_request = args.feature
    doc_paths = args.docs or []
    scope_doc = getattr(args, 'scope_doc', None) or ''

    # Determine the workflow mode:
    #   --scope-doc  → 'scope-to-plan' (skip research/HW/scoping, jump to plan)
    #   default      → 'full' (run all phases)
    mode = 'scope-to-plan' if scope_doc else 'full'

    # Resolve the output directory.
    #
    # The standard subdir structure is:  plans/<PROJECT>-<slug>/
    # --output-dir ROOT  → ROOT/plans/<PROJECT>-<slug>/
    # --output FILE      → dirname(FILE)  (explicit path, no slug)
    # (neither)          → plans/<PROJECT>-<slug>/  (relative to cwd)
    explicit_output_dir = getattr(args, 'output_dir', None)
    output_file = args.output or 'feature_plan.json'

    # Build the <PROJECT>-<slug> component used by the standard layout.
    # When using --feature-prompt, derive slug from the filename stem
    # (the full file content would be too long for a directory name).
    if feature_prompt_file:
        slug = os.path.splitext(os.path.basename(feature_prompt_file))[0].lower()
    else:
        slug = feature_request[:40].lower()
    slug = slug.replace(' ', '-').replace('/', '-')
    slug = ''.join(c for c in slug if c.isalnum() or c == '-')
    slug = slug.strip('-')
    plans_subdir = os.path.join('plans', f'{project_key}-{slug}')

    if explicit_output_dir:
        # --output-dir ROOT → ROOT/plans/<PROJECT>-<slug>/
        output_dir = os.path.join(explicit_output_dir, plans_subdir)
    else:
        output_dir = os.path.dirname(output_file)

    if not output_dir:
        # Default: plans/<PROJECT>-<slug>/ relative to cwd
        output_dir = plans_subdir

    output(f'Feature Planning Workflow')
    output(f'  Project:  {project_key}')
    if feature_prompt_file:
        output(f'  Prompt:   {feature_prompt_file} ({len(feature_request)} chars)')
    else:
        output(f'  Feature:  {feature_request}')
    output(f'  Mode:     {mode}')
    output(f'  Output:   {output_dir}/')
    if scope_doc:
        output(f'  Scope:    {scope_doc}')
    if doc_paths:
        output(f'  Docs:     {len(doc_paths)} file(s)')
        for dp in doc_paths:
            output(f'            - {dp}')
    if initiative_key:
        output(f'  Initiative: {initiative_key} (supplied)')
    else:
        output(f'  Initiative: (will be auto-created on --execute)')
    output(f'  Force:    {"YES — skip duplicate prompts" if force else "no (interactive)"}')
    output(f'  Execute:  {"YES — will create Jira tickets" if execute else "DRY RUN"}')
    output('')

    try:
        from agents.feature_planning_orchestrator import FeaturePlanningOrchestrator

        output('Starting workflow...')
        orchestrator = FeaturePlanningOrchestrator(output_dir=output_dir)

        response = orchestrator.run({
            'feature_request': feature_request,
            'project_key': project_key,
            'doc_paths': doc_paths,
            'mode': mode,
            'execute': execute,
            'initiative_key': initiative_key,
            'force': force,
            'scope_doc': scope_doc,
            'output_dir': output_dir,
            'feature_tag': getattr(args, 'feature_tag', None),
            'timeout': args.timeout,
        })

        if response.success:
            output(response.content)

            # Save the plan to JSON inside the output directory
            jira_plan = response.metadata.get('state', {}).get('jira_plan')
            # Track all output files for the summary table
            all_created_files: list[tuple[str, str]] = []

            # Include intermediate files created by the orchestrator
            # (research.json, hw_profile.json, scope.json, debug/*.md)
            intermediate_files = getattr(orchestrator, '_created_files', [])
            for ifile in intermediate_files:
                if os.path.exists(ifile):
                    basename = os.path.basename(ifile)
                    if 'debug' in ifile:
                        all_created_files.append((ifile, f'Debug: {basename}'))
                    else:
                        desc_map = {
                            'research.json': 'Research findings',
                            'hw_profile.json': 'Hardware profile',
                            'scope.json': 'Feature scope',
                        }
                        all_created_files.append(
                            (ifile, desc_map.get(basename, f'Intermediate: {basename}'))
                        )

            if jira_plan:
                import json
                # Place plan files in the output directory
                os.makedirs(output_dir, exist_ok=True)
                json_path = os.path.join(output_dir, 'plan.json')
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(jira_plan, f, indent=2)
                output(f'Saving plan to: {json_path}')
                all_created_files.append((json_path, 'Feature plan JSON'))

                # Also save Markdown summary
                md_path = os.path.join(output_dir, 'plan.md')
                markdown = jira_plan.get('summary_markdown', '')
                if markdown:
                    with open(md_path, 'w', encoding='utf-8') as f:
                        f.write(markdown)
                    output(f'Markdown saved to: {md_path}')
                    all_created_files.append((md_path, 'Markdown summary'))

                # Export plan to CSV (indented format)
                csv_path = ''
                try:
                    from tools.plan_export_tools import plan_to_csv as _plan_to_csv
                    csv_basename = os.path.join(output_dir, 'plan')
                    csv_result = cast(Any, _plan_to_csv(json_path, output_path=csv_basename))
                    csv_data = getattr(csv_result, 'data', None)
                    if csv_data:
                        csv_path = csv_data.get('output_path', '')
                        if csv_path:
                            output(f'CSV saved to: {csv_path}')
                            all_created_files.append((csv_path, 'Jira CSV (indented)'))
                    else:
                        csv_error = getattr(csv_result, 'error', None)
                        if csv_error:
                            log.warning(f'CSV export warning: {csv_error}')
                except Exception as csv_err:
                    log.warning(f'CSV export failed (plan JSON still saved): {csv_err}')

                # Convert CSV to Excel workbook via excel_utils
                if csv_path:
                    try:
                        xlsx_path = excel_utils.convert_from_csv(csv_path)
                        log.info(f'Converted {csv_path} -> {xlsx_path}')
                        output(f'Excel saved to: {xlsx_path}')
                        all_created_files.append((xlsx_path, 'Excel workbook'))
                    except Exception as xlsx_err:
                        log.warning(f'Excel conversion failed: {xlsx_err}')
                        output(f'  WARNING: Excel conversion failed: {xlsx_err}')

            # Surface the created_tickets.csv path if execution produced one
            created_csv = response.metadata.get('created_csv_path', '')
            if created_csv and os.path.isfile(created_csv):
                all_created_files.append((created_csv, 'Created tickets (for --cleanup)'))

            # Report blocking status
            if response.metadata.get('blocked'):
                questions = response.metadata.get('blocking_questions', [])
                output(f'\n⚠️  Workflow blocked by {len(questions)} question(s).')
                output('Answer the questions above and re-run to continue.')
                return 1

            output('')
            if not execute:
                output('This was a DRY RUN. To create tickets in Jira, re-run with --execute.')

            _print_workflow_summary('feature-plan', all_created_files)
            return 0
        else:
            output(f'ERROR: {response.error}')
            return 1

    except ImportError as e:
        output(f'ERROR: Missing dependency for feature planning: {e}')
        log.error(f'Import error: {e}', exc_info=True)
        return 1
    except Exception as e:
        output(f'ERROR: Feature planning failed: {e}')
        log.error(f'Feature planning error: {e}', exc_info=True)
        return 1


def cmd_resume(args):
    '''
    Resume a saved session.
    '''
    log.debug(f'cmd_resume(session={args.resume})')
    
    from state.session import SessionManager
    from state.persistence import get_persistence
    from agents.orchestrator import ReleasePlanningOrchestrator
    
    persistence = get_persistence(args.persistence_format)
    session_manager = SessionManager(persistence=persistence)
    
    session = session_manager.resume_session(args.resume)
    
    if not session:
        output(f'Session not found: {args.session}')
        return 1
    
    output('')
    output('=' * 60)
    output(f'RESUMING SESSION: {session.session_id}')
    output('=' * 60)
    output('')
    output(f'Project: {session.project_key}')
    output(f'Current step: {session.current_step}')
    output(f'Completed steps: {", ".join(session.completed_steps) or "None"}')
    output('')
    
    # Create orchestrator with session state
    orchestrator = ReleasePlanningOrchestrator()
    orchestrator.state.project_key = session.project_key
    orchestrator.state.roadmap_data = session.roadmap_data
    orchestrator.state.jira_state = session.jira_state
    orchestrator.state.release_plan = session.release_plan
    orchestrator.state.current_step = session.current_step
    
    # Determine what to do based on current step
    if session.current_step == 'analysis':
        output('Resuming from analysis step...')
        result = orchestrator._run_planning()
    elif session.current_step == 'planning':
        output('Plan is ready for review.')
        output(orchestrator._format_plan())
        result = None
    elif session.current_step == 'review':
        output('Resuming review...')
        result = orchestrator._run_execution()
    else:
        output(f'Unknown step: {session.current_step}')
        return 1
    
    if result:
        if result.success:
            output(result.content)
        else:
            output(f'ERROR: {result.error}')
            return 1
    
    return 0


# ****************************************************************************************
# Argument handling
# ****************************************************************************************

def handle_args():
    '''
    Parse and validate command line arguments.
    All commands use -- style flags (e.g. --invoke-llm, --build-excel-map).
    '''
    global _quiet_mode
    
    parser = argparse.ArgumentParser(
        description='Cornelis Agent Pipeline - Release Planning Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s --plan --project PROJ --roadmap slides.pptx
  %(prog)s --analyze --project PROJ --quick
  %(prog)s --vision roadmap.png roadmap2.xlsx
  %(prog)s --build-excel-map STL-74071
  %(prog)s --build-excel-map STL-74071 STL-76297 --hierarchy 2 --output my_map.xlsx
  %(prog)s --invoke-llm prompt.md
  %(prog)s --invoke-llm "Summarize this data" --attachments data.csv
  %(prog)s --invoke-llm prompt.md --attachments screenshot.png report.csv
  %(prog)s --sessions --list-sessions
  %(prog)s --resume abc123
  %(prog)s --workflow feature-plan --project STL --feature "Add PQC device support"
  %(prog)s --workflow feature-plan --project STL --feature "Add PQC device" --docs spec.pdf --execute
  %(prog)s --workflow feature-plan --project STLSB --feature-prompt RedfishRDE.md
  %(prog)s --workflow feature-plan --project STLSB --feature-prompt RedfishRDE.md --output-dir /tmp/out
  %(prog)s --workflow feature-plan --project STL --feature "Add PQC device" --scope-doc scope.json
  %(prog)s --workflow feature-plan --project STL --feature "Add PQC device" --scope-doc scope.md --execute
  %(prog)s --env .env_sandbox --workflow feature-plan --project STLSB --feature "Redfish RDE" --scope-doc RedfishRDE.md
  %(prog)s --workflow feature-plan --project STLSB --plan-file plans/STLSB-redfish/plan.json
  %(prog)s --workflow feature-plan --project STLSB --plan-file plans/STLSB-redfish/plan.json --execute
  %(prog)s --workflow feature-plan --project STL --plan-file plan.json --initiative STL-74071 --execute
        '''
    )
    
    # Global options
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Suppress output to stdout')
    parser.add_argument('--env', default=None, metavar='FILE',
                       help='Path to a .env file to load (overrides the default .env). '
                            'Example: --env .env_sandbox')
    parser.add_argument('--persistence-format', choices=['json', 'sqlite', 'both'],
                       default='json', help='Session persistence format')
    
    # ---- Command flags (mutually exclusive) ------------------------------------
    # --plan: Run release planning workflow
    parser.add_argument('--plan', action='store_true',
                       help='Run release planning workflow')
    # --analyze: Analyze Jira project
    parser.add_argument('--analyze', action='store_true',
                       help='Analyze Jira project')
    # --vision: Analyze roadmap files (takes 1+ file paths)
    parser.add_argument('--vision', nargs='+', default=None, metavar='FILE',
                       help='Analyze roadmap file(s)')
    # --sessions: Manage saved sessions
    parser.add_argument('--sessions', action='store_true',
                       help='Manage saved sessions')
    # --build-excel-map: Build multi-sheet Excel map (takes 1+ ticket keys)
    parser.add_argument('--build-excel-map', nargs='+', default=None, metavar='TICKET',
                       dest='build_excel_map',
                       help='Build multi-sheet Excel map from root ticket key(s)')
    # --invoke-llm: Send a prompt to the configured LLM (takes prompt text or file path)
    parser.add_argument('--invoke-llm', default=None, metavar='PROMPT',
                       dest='invoke_llm',
                       help='Send a prompt (text or .md/.txt file path) to the configured LLM')
    # --resume: Resume a saved session (takes session ID)
    parser.add_argument('--resume', default=None, metavar='SESSION_ID',
                       help='Resume a saved session by ID')
    # --workflow: Run a named multi-step workflow
    parser.add_argument('--workflow', default=None, metavar='NAME',
                       dest='workflow_name',
                       help='Run a named workflow (e.g. "bug-report")')
    
    # ---- Options for --workflow ------------------------------------------------
    parser.add_argument('--filter', default=None, metavar='NAME',
                       dest='workflow_filter',
                       help='Jira filter name to look up (used by --workflow bug-report)')
    parser.add_argument('--prompt', default=None, metavar='FILE',
                       dest='workflow_prompt',
                       help='Prompt file for LLM step (used by --workflow bug-report, '
                            'default: config/prompts/cn5000_bugs_clean.md)')
    parser.add_argument('--d-columns', nargs='+', default=None, metavar='COL',
                       dest='dashboard_columns',
                       help='Column names for the Excel Dashboard sheet '
                            '(used by --workflow bug-report). Each named column '
                            'gets a COUNTIF-based pivot table. Names are '
                            'case-insensitive. '
                            'Example: --d-columns Phase Customer Product Module Priority')
    
    # ---- Options for --workflow feature-plan -----------------------------------
    parser.add_argument('--feature', default=None, metavar='TEXT',
                       help='Feature description for --workflow feature-plan '
                            '(e.g. "Add PQC device support to CN5000 board")')
    parser.add_argument('--feature-prompt', default=None, metavar='FILE',
                       dest='feature_prompt',
                       help='Markdown file with a rich feature prompt. '
                            'When provided, its content is used as the feature '
                            'request and takes precedence over --feature. '
                            'Used by --workflow feature-plan.')
    parser.add_argument('--scope-doc', default=None, metavar='FILE',
                       dest='scope_doc',
                       help='Pre-existing scope document (JSON, Markdown, PDF, DOCX). '
                            'Skips research/HW-analysis/scoping phases and jumps '
                            'straight to Jira plan generation. '
                            'Used by --workflow feature-plan.')
    parser.add_argument('--docs', nargs='*', default=None, metavar='FILE',
                       help='Spec documents / datasheets for --workflow feature-plan')
    parser.add_argument('--plan-file', default=None, metavar='FILE',
                       dest='plan_file',
                       help='Path to a previously generated plan.json. '
                            'Loads the plan and prints a summary (dry-run). '
                            'Combine with --execute to push tickets into Jira. '
                            'Skips all agentic phases. '
                            'Used by --workflow feature-plan.')
    parser.add_argument('--initiative', default=None, metavar='KEY',
                       help='Optional existing Initiative ticket key (e.g. STL-74071). '
                            'If supplied, the ticket is validated as type Initiative '
                            'and all created Epics become its children. '
                            'If omitted, a new Initiative is auto-created from the '
                            'plan feature name. '
                            'Used by --workflow feature-plan.')
    parser.add_argument('--execute', action='store_true',
                       help='Actually create Jira tickets (default: dry-run). '
                            'Used by --workflow feature-plan.')
    parser.add_argument('--force', action='store_true',
                       help='Skip duplicate-ticket confirmation prompts. '
                            'Without --force, the agent pauses and asks before '
                            'creating a ticket whose summary already exists in '
                            'the project. Used by --workflow feature-plan.')
    parser.add_argument('--feature-tag', default=None, metavar='TAG',
                       dest='feature_tag',
                       help='Override the auto-generated [Tag] prefix for Epic '
                            'summaries. E.g. --feature-tag "[K8s]". '
                            'During dry-run the computed tags are shown so you '
                            'can decide whether to override. '
                            'Used by --workflow feature-plan.')
    parser.add_argument('--cleanup', default=None, metavar='CSV',
                       help='Delete all tickets listed in a created_tickets.csv '
                            'file (produced by --execute). Dry-run by default; '
                            'add --execute to actually delete. Children are '
                            'deleted before parents. '
                            'Used by --workflow feature-plan.')
    parser.add_argument('--output-dir', default=None, metavar='DIR',
                       dest='output_dir',
                       help='Root directory for output. The standard '
                            'plans/<PROJECT>-<slug>/ subdir is created '
                            'inside it. Default root: current directory. '
                            'Used by --workflow feature-plan.')
    
    # ---- Options for --plan ----------------------------------------------------
    parser.add_argument('--project', '-p', default=None,
                       help='Jira project key (used by --plan, --analyze, --build-excel-map)')
    parser.add_argument('--roadmap', '-r', action='append', default=None,
                       help='Roadmap file(s) to analyze (used by --plan)')
    parser.add_argument('--org-chart', default=None,
                       help='Organization chart file, draw.io (used by --plan)')
    parser.add_argument('--plan-mode', choices=['full', 'analyze', 'plan'],
                       default='full',
                       help='Workflow mode for --plan (default: full)')
    parser.add_argument('--save-session', action='store_true',
                       help='Save session for later resumption (used by --plan)')
    
    # ---- Options for --analyze -------------------------------------------------
    parser.add_argument('--quick', action='store_true',
                       help='Quick analysis without LLM (used by --analyze)')
    
    # ---- Options for --sessions ------------------------------------------------
    parser.add_argument('--list-sessions', action='store_true',
                       help='List all sessions (used by --sessions)')
    parser.add_argument('--delete-session', default=None, metavar='ID',
                       help='Delete a session by ID (used by --sessions)')
    
    # ---- Options for --build-excel-map -----------------------------------------
    parser.add_argument('--hierarchy', type=int, default=1,
                       help='Depth for related issue traversal (default: 1, used by --build-excel-map)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Max tickets per step (used by --build-excel-map)')
    parser.add_argument('--output', '-o', default=None,
                       help='Output filename (used by --build-excel-map)')
    parser.add_argument('--keep-intermediates', action='store_true',
                       help='Keep temp files instead of cleaning up (used by --build-excel-map)')
    
    # ---- Options for --invoke-llm ----------------------------------------------
    parser.add_argument('--attachments', '-a', nargs='*', default=None,
                       help='File(s) to attach (images via vision API, text inlined; used by --invoke-llm)')
    parser.add_argument('--timeout', type=float, default=None,
                       help='LLM request timeout in seconds (default: 120; used by --invoke-llm)')
    
    # ---- Global LLM model override ---------------------------------------------
    # Allows the user (or a Jenkins Choice Parameter) to select a model at
    # run-time without editing the .env file.  Overrides CORNELIS_LLM_MODEL /
    # OPENAI_MODEL / etc.
    parser.add_argument('--model', '-m', default=None, metavar='MODEL',
                       help='LLM model name override (e.g. developer-opus, gpt-4o). '
                            'Overrides the env-var default for this run.')
    
    # ---- Global verbose flag ---------------------------------------------------
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose (debug-level) logging to stdout')
    
    args = parser.parse_args()
    
    if args.quiet:
        _quiet_mode = True
    
    # ---- Load custom env file (--env) early, before anything reads env vars ----
    # The default .env was already loaded at import time (line 31) with
    # override=False.  When --env is provided we reload from that file with
    # override=True so its values take precedence.
    if args.env:
        if not os.path.exists(args.env):
            parser.error(f'--env file not found: {args.env}')
        load_dotenv(dotenv_path=args.env, override=True)
        log.info(f'Loaded env file: {args.env}')

        # jira_utils.JIRA_URL was captured at import time from the default
        # .env.  Now that --env has overridden os.environ, refresh the
        # module-level URL and drop any cached connection so the next call
        # to get_connection() uses the correct server.
        jira_utils.JIRA_URL = os.getenv('JIRA_URL', jira_utils.DEFAULT_JIRA_URL)
        jira_api.reset_connection()
        log.info(f'Refreshed jira_utils.JIRA_URL -> {jira_utils.JIRA_URL}')
    
    # ---- Verbose mode: add a stdout handler so debug messages appear on console
    if args.verbose:
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.DEBUG)
        sh.setFormatter(logging.Formatter(
            '%(asctime)-15s [%(funcName)25s:%(lineno)-5s] %(levelname)-8s %(message)s'))
        log.addHandler(sh)
        log.debug('Verbose mode enabled (--verbose)')
    
    # ---- Determine which command was requested ---------------------------------
    # Count how many command flags were set to enforce mutual exclusivity
    commands = []
    if args.plan:
        commands.append('plan')
    if args.analyze:
        commands.append('analyze')
    if args.vision is not None:
        commands.append('vision')
    if args.sessions:
        commands.append('sessions')
    if args.build_excel_map is not None:
        commands.append('build-excel-map')
    if args.invoke_llm is not None:
        commands.append('invoke-llm')
    if args.resume is not None:
        commands.append('resume')
    if args.workflow_name is not None:
        commands.append('workflow')
    
    if len(commands) == 0:
        parser.print_help()
        sys.exit(1)
    
    if len(commands) > 1:
        parser.error(f'Only one command may be specified at a time. Got: {", ".join("--" + c for c in commands)}')
    
    command = commands[0]
    
    # ---- Command-specific validation -------------------------------------------
    if command == 'plan':
        if not args.project:
            parser.error('--plan requires --project')
    
    if command == 'analyze':
        if not args.project:
            parser.error('--analyze requires --project')
    
    if command == 'workflow':
        if args.workflow_name == 'bug-report':
            if not args.workflow_filter:
                parser.error('--workflow bug-report requires --filter "FILTER_NAME"')
        elif args.workflow_name == 'feature-plan':
            # --cleanup only needs the CSV file — skip all other validation
            cleanup_csv = getattr(args, 'cleanup', None)
            if cleanup_csv:
                if not os.path.isfile(cleanup_csv):
                    parser.error(f'--cleanup CSV not found: {cleanup_csv}')
            else:
                if not args.project:
                    parser.error('--workflow feature-plan requires --project PROJECT_KEY')
                # --plan-file bypasses the agentic flow; no --feature needed
                plan_file = getattr(args, 'plan_file', None)
                if plan_file:
                    if not os.path.isfile(plan_file):
                        parser.error(f'--plan-file not found: {plan_file}')
                elif not args.feature and not args.feature_prompt:
                    # Require at least one of --feature or --feature-prompt
                    parser.error('--workflow feature-plan requires --feature "DESCRIPTION" '
                                 'or --feature-prompt FILE (or --plan-file FILE)')
                # Validate that the prompt file exists when specified
                if args.feature_prompt and not os.path.isfile(args.feature_prompt):
                    parser.error(f'--feature-prompt file not found: {args.feature_prompt}')
    
    # ---- Map ticket_keys for build-excel-map compatibility ---------------------
    # cmd_build_excel_map expects args.ticket_keys
    if command == 'build-excel-map':
        args.ticket_keys = args.build_excel_map
    
    # ---- Map prompt for invoke-llm compatibility -------------------------------
    # cmd_invoke_llm expects args.prompt
    if command == 'invoke-llm':
        args.prompt = args.invoke_llm
    
    # ---- Map session for resume compatibility ----------------------------------
    # cmd_resume expects args.resume (already set)
    
    # ---- Store resolved command name for dispatch ------------------------------
    args.command = command
    
    # ---- Startup logging box ---------------------------------------------------
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    log.info(f'+  {os.path.basename(sys.argv[0])}')
    log.info(f'+  Python Version: {sys.version.split()[0]}')
    log.info(f'+  Today is: {date.today()}')
    log.info(f'+  Command: --{command}')
    # Command-specific details in the startup box
    if command == 'plan':
        log.info(f'+  Project: {args.project}')
        log.info(f'+  Plan mode: {args.plan_mode}')
        if args.roadmap:
            log.info(f'+  Roadmap files: {len(args.roadmap)}')
        if args.org_chart:
            log.info(f'+  Org chart: {args.org_chart}')
    elif command == 'analyze':
        log.info(f'+  Project: {args.project}')
        if args.quick:
            log.info(f'+  Quick mode: yes')
    elif command == 'vision':
        log.info(f'+  Files: {len(args.vision)}')
        for vf in args.vision:
            log.info(f'+    - {vf}')
    elif command == 'sessions':
        if args.list_sessions:
            log.info(f'+  Action: list')
        elif args.delete_session:
            log.info(f'+  Action: delete {args.delete_session}')
    elif command == 'build-excel-map':
        keys_str = ', '.join(k.upper() for k in args.ticket_keys)
        log.info(f'+  Root ticket(s): {keys_str}')
        log.info(f'+  Hierarchy depth: {args.hierarchy}')
        default_out = f'{args.ticket_keys[0].upper()}.xlsx' if len(args.ticket_keys) == 1 else f'{"_".join(k.upper() for k in args.ticket_keys)}.xlsx'
        log.info(f'+  Output file: {args.output or default_out}')
    elif command == 'invoke-llm':
        prompt_display = args.prompt if len(args.prompt) <= 60 else args.prompt[:57] + '...'
        log.info(f'+  Prompt: {prompt_display}')
        if args.attachments:
            log.info(f'+  Attachments: {len(args.attachments)} file(s)')
            for att in args.attachments:
                log.info(f'+    - {att}')
        if args.timeout:
            log.info(f'+  Timeout: {args.timeout}s')
    elif command == 'resume':
        log.info(f'+  Session: {args.resume}')
    elif command == 'workflow':
        log.info(f'+  Workflow: {args.workflow_name}')
        if args.workflow_name == 'feature-plan':
            log.info(f'+  Project: {args.project}')
            plan_file_arg = getattr(args, 'plan_file', None)
            if plan_file_arg:
                log.info(f'+  Plan file: {plan_file_arg}')
            if args.feature_prompt:
                log.info(f'+  Feature prompt: {args.feature_prompt}')
            if args.feature:
                feature_display = args.feature if len(args.feature) <= 60 else args.feature[:57] + '...'
                log.info(f'+  Feature: {feature_display}')
            if args.docs:
                log.info(f'+  Docs: {len(args.docs)} file(s)')
                for dp in args.docs:
                    log.info(f'+    - {dp}')
            initiative_arg = getattr(args, 'initiative', None)
            if initiative_arg:
                log.info(f'+  Initiative: {initiative_arg}')
            if args.execute:
                log.info(f'+  Execute: YES (will create Jira tickets)')
            else:
                log.info(f'+  Execute: DRY RUN')
            if args.output_dir:
                log.info(f'+  Output dir: {args.output_dir}')
            elif args.output:
                log.info(f'+  Output: {args.output}')
        if args.workflow_filter:
            log.info(f'+  Filter: {args.workflow_filter}')
        if args.workflow_prompt:
            log.info(f'+  Prompt: {args.workflow_prompt}')
        if args.timeout:
            log.info(f'+  Timeout: {args.timeout}s')
        if args.limit:
            log.info(f'+  Limit: {args.limit}')
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    
    return args


# ****************************************************************************************
# Main
# ****************************************************************************************

def main():
    '''
    Entrypoint for the CLI.
    Dispatches to the appropriate cmd_* handler based on args.command.
    '''
    args = handle_args()
    log.debug('Entering main()')
    
    # Dispatch table: command name -> handler function
    dispatch = {
        'plan':            cmd_plan,
        'analyze':         cmd_analyze,
        'vision':          cmd_vision,
        'sessions':        cmd_sessions,
        'build-excel-map': cmd_build_excel_map,
        'invoke-llm':      cmd_invoke_llm,
        'resume':          cmd_resume,
        'workflow':         cmd_workflow,
    }
    
    handler = dispatch.get(args.command)
    if not handler:
        output(f'ERROR: Unknown command: {args.command}')
        sys.exit(1)
    
    try:
        exit_code = handler(args)
        
    except KeyboardInterrupt:
        output('\nOperation cancelled.')
        exit_code = 130
        
    except Exception as e:
        log.error(f'Unexpected error: {e}', exc_info=True)
        output(f'ERROR: {e}')
        exit_code = 1
    
    log.info('Operation complete.')
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
