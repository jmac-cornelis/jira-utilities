#!/usr/bin/env python3
##########################################################################################
#
# Script name: main.py
#
# Description: CLI entry point for Cornelis Agent Pipeline.
#              Provides commands for release planning workflow.
#
# Author: Cornelis Networks
#
# Usage:
#   python main.py --help
#   python main.py plan --project PROJ --roadmap slides.pptx
#   python main.py analyze --project PROJ
#   python main.py resume --session abc123
#
##########################################################################################

import argparse
import logging
import sys
import os
from datetime import date

from dotenv import load_dotenv

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


def output(message=''):
    '''
    Print user-facing output, respecting quiet mode.
    '''
    if message:
        record = logging.LogRecord(
            name=log.name,
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=f'OUTPUT: {message}',
            args=(),
            exc_info=None,
            func='output'
        )
        fh.emit(record)
    
    if not _quiet_mode:
        print(message)


# ****************************************************************************************
# Command handlers
# ****************************************************************************************

def cmd_plan(args):
    '''
    Run the release planning workflow.
    '''
    log.debug(f'cmd_plan(project={args.project})')
    
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
        'mode': args.mode
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
    log.debug(f'cmd_analyze(project={args.project})')
    
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
    log.debug(f'cmd_vision(files={args.files})')
    
    from agents.vision_analyzer import VisionAnalyzerAgent
    
    output('')
    output('=' * 60)
    output('ROADMAP ANALYSIS')
    output('=' * 60)
    output('')
    
    analyzer = VisionAnalyzerAgent()
    
    if len(args.files) == 1:
        result = analyzer.analyze_file(args.files[0])
    else:
        result = analyzer.analyze_multiple(args.files)
    
    if 'error' in result:
        output(f'ERROR: {result["error"]}')
        return 1
    
    output(f"Files analyzed: {len(result.get('files_analyzed', [args.files[0]]))}")
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
    log.debug(f'cmd_sessions()')
    
    from state.session import SessionManager
    from state.persistence import get_persistence
    
    persistence = get_persistence(args.persistence_format)
    session_manager = SessionManager(persistence=persistence)
    
    if args.delete:
        if session_manager.delete_session(args.delete):
            output(f'Deleted session: {args.delete}')
        else:
            output(f'Failed to delete session: {args.delete}')
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


def cmd_resume(args):
    '''
    Resume a saved session.
    '''
    log.debug(f'cmd_resume(session={args.session})')
    
    from state.session import SessionManager
    from state.persistence import get_persistence
    from agents.orchestrator import ReleasePlanningOrchestrator
    
    persistence = get_persistence(args.persistence_format)
    session_manager = SessionManager(persistence=persistence)
    
    session = session_manager.resume_session(args.session)
    
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
    '''
    global _quiet_mode
    
    parser = argparse.ArgumentParser(
        description='Cornelis Agent Pipeline - Release Planning Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s plan --project PROJ --roadmap slides.pptx
  %(prog)s analyze --project PROJ --quick
  %(prog)s vision roadmap.png roadmap2.xlsx
  %(prog)s sessions --list
  %(prog)s resume --session abc123
        '''
    )
    
    # Global options
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Suppress output to stdout')
    parser.add_argument('--persistence-format', choices=['json', 'sqlite', 'both'],
                       default='json', help='Session persistence format')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Plan command
    plan_parser = subparsers.add_parser('plan', help='Run release planning workflow')
    plan_parser.add_argument('--project', '-p', required=True,
                            help='Jira project key')
    plan_parser.add_argument('--roadmap', '-r', action='append',
                            help='Roadmap file(s) to analyze')
    plan_parser.add_argument('--org-chart', '-o',
                            help='Organization chart file (draw.io)')
    plan_parser.add_argument('--mode', choices=['full', 'analyze', 'plan'],
                            default='full', help='Workflow mode')
    plan_parser.add_argument('--save-session', action='store_true',
                            help='Save session for later resumption')
    plan_parser.set_defaults(func=cmd_plan)
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze Jira project')
    analyze_parser.add_argument('--project', '-p', required=True,
                               help='Jira project key')
    analyze_parser.add_argument('--quick', action='store_true',
                               help='Quick analysis without LLM')
    analyze_parser.set_defaults(func=cmd_analyze)
    
    # Vision command
    vision_parser = subparsers.add_parser('vision', help='Analyze roadmap files')
    vision_parser.add_argument('files', nargs='+',
                              help='Files to analyze')
    vision_parser.set_defaults(func=cmd_vision)
    
    # Sessions command
    sessions_parser = subparsers.add_parser('sessions', help='Manage saved sessions')
    sessions_parser.add_argument('--list', '-l', action='store_true',
                                help='List all sessions')
    sessions_parser.add_argument('--delete', '-d',
                                help='Delete a session by ID')
    sessions_parser.set_defaults(func=cmd_sessions)
    
    # Resume command
    resume_parser = subparsers.add_parser('resume', help='Resume a saved session')
    resume_parser.add_argument('--session', '-s', required=True,
                              help='Session ID to resume')
    resume_parser.set_defaults(func=cmd_resume)
    
    args = parser.parse_args()
    
    if args.quiet:
        _quiet_mode = True
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    log.info(f'+  {os.path.basename(sys.argv[0])}')
    log.info(f'+  Python Version: {sys.version.split()[0]}')
    log.info(f'+  Today is: {date.today()}')
    log.info(f'+  Command: {args.command}')
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    
    return args


# ****************************************************************************************
# Main
# ****************************************************************************************

def main():
    '''
    Entrypoint for the CLI.
    '''
    args = handle_args()
    log.debug('Entering main()')
    
    try:
        exit_code = args.func(args)
        
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
