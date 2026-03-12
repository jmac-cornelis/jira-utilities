#!/usr/bin/env python3
##########################################################################################
#
# Script name: release_tracker_cli.py
#
# Description: CLI entry point for the Release Tracker Agent.
#              Monitors releases, tracks status changes, generates summaries,
#              and predicts release readiness.
#
# Usage:
#     python release_tracker_cli.py --project STL --release "12.1.1.x"
#     python release_tracker_cli.py --predict --format json --output report.json
#     python release_tracker_cli.py --status
#
# Author: Cornelis Networks
#
##########################################################################################

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(os.path.basename(sys.argv[0]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Release Tracker — monitor releases, track changes, predict readiness',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''examples:
  %(prog)s                                    Track all configured releases
  %(prog)s --release 12.1.1.x                 Track a specific release
  %(prog)s --release 12.1.1.x --release 12.2.0.x  Track multiple releases
  %(prog)s --predict --format json -o out.json     JSON output with predictions
  %(prog)s --status                            Show current tracking stats
''',
    )

    parser.add_argument(
        '--project',
        default=None,
        help='Jira project key (default: from config)',
    )
    parser.add_argument(
        '--release',
        action='append',
        default=None,
        dest='releases',
        help='Release to track (repeatable; default: all from config)',
    )
    parser.add_argument(
        '--format',
        choices=['table', 'json', 'csv', 'excel'],
        default=None,
        help='Output format (default: table)',
    )
    parser.add_argument(
        '--output', '-o',
        default=None,
        help='Output file path (default: stdout)',
    )
    parser.add_argument(
        '--predict',
        action='store_true',
        default=False,
        help='Include cycle time predictions and readiness estimate',
    )
    parser.add_argument(
        '--config',
        default='config/release_tracker.yaml',
        help='Path to config YAML (default: config/release_tracker.yaml)',
    )
    parser.add_argument(
        '--db-dir',
        default='state',
        help='Directory for SQLite databases (default: state/)',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        default=False,
        help='Enable debug logging',
    )
    parser.add_argument(
        '--status',
        action='store_true',
        default=False,
        help='Show current tracking stats, then exit',
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format='%(levelname)s %(name)s: %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(message)s')

    from agents.release_tracker import ReleaseTrackerAgent

    try:
        agent = ReleaseTrackerAgent(
            config_path=args.config,
            db_dir=args.db_dir,
        )
    except Exception as exc:
        log.error('Failed to initialise ReleaseTrackerAgent: %s', exc)
        return 1

    # --status: print stats and exit
    if args.status:
        status = agent.get_status()
        print(json.dumps(status, indent=2, default=str))
        agent.close()
        return 0

    # Override project if specified on CLI.
    if args.project:
        agent.tracker_config.project = args.project

    # Build input overrides for the agent.
    output_format = args.format or agent.tracker_config.output.get('format', 'table')

    # Excel format is handled as a post-processing step on CSV output.
    effective_format = 'csv' if output_format == 'excel' else output_format

    input_data: dict[str, object] = {
        'predict': args.predict,
        'format': effective_format,
    }
    if args.releases:
        input_data['releases'] = args.releases

    response = agent.run(input_data)

    # Write output.
    content = response.content or ''

    if args.output:
        _write_output(content, args.output, output_format)
        log.info('Output written to %s', args.output)
    else:
        if content:
            print(content)

    agent.close()

    return 0 if response.success else 1


def _write_output(content: str, output_path: str, output_format: str) -> None:
    if output_format == 'excel':
        _write_excel(content, output_path)
    else:
        with open(output_path, 'w', encoding='utf-8') as fh:
            fh.write(content)


def _write_excel(csv_content: str, output_path: str) -> None:
    try:
        from tools.excel_tools import csv_to_excel
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False, encoding='utf-8',
        ) as tmp:
            tmp.write(csv_content)
            tmp_path = tmp.name

        try:
            result = csv_to_excel(tmp_path, output_path)
            if hasattr(result, 'is_success') and not result.is_success:
                log.warning('Excel conversion returned error: %s', getattr(result, 'error', ''))
                with open(output_path, 'w', encoding='utf-8') as fh:
                    fh.write(csv_content)
        finally:
            os.unlink(tmp_path)
    except ImportError:
        log.warning('excel_tools not available — writing CSV instead')
        with open(output_path, 'w', encoding='utf-8') as fh:
            fh.write(csv_content)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nInterrupted.', file=sys.stderr)
        sys.exit(1)
