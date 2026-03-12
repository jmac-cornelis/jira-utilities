#!/usr/bin/env python3
##########################################################################################
#
# Script name: ticket_monitor_cli.py
#
# Description: CLI entry point for the Ticket Monitor Agent.
#              Validates newly created Jira tickets, auto-fills missing fields
#              when confident, and flags creators when not.
#
# Author: Cornelis Networks
#
##########################################################################################

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=False)

log = logging.getLogger(os.path.basename(sys.argv[0]))


def _setup_logging(verbose: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fh = logging.FileHandler('ticket_monitor.log', mode='w')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)-15s [%(funcName)25s:%(lineno)-5s] %(levelname)-8s %(message)s'
    ))
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(logging.Formatter('%(levelname)-8s %(message)s'))
    root.addHandler(ch)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='ticket_monitor_cli.py',
        description='Ticket Monitor Agent — validate and enrich newly created Jira tickets.',
    )

    parser.add_argument(
        '--project',
        default=None,
        help='Jira project key (default: from config YAML)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help='Validate and report without updating tickets or posting comments',
    )
    parser.add_argument(
        '--since',
        default=None,
        help='ISO date/time string — override last_checked (e.g. "2026-03-01")',
    )
    parser.add_argument(
        '--learn-only',
        action='store_true',
        default=False,
        help='Process tickets to build the learning store without taking any actions',
    )
    parser.add_argument(
        '--reset-learning',
        action='store_true',
        default=False,
        help='Clear the learning store and start fresh',
    )
    parser.add_argument(
        '--config',
        default=os.path.join('config', 'ticket_monitor.yaml'),
        help='Path to config YAML (default: config/ticket_monitor.yaml)',
    )
    parser.add_argument(
        '--db-dir',
        default='state',
        help='Directory for SQLite databases (default: state/)',
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        default=False,
        help='Increase logging verbosity (DEBUG level)',
    )
    parser.add_argument(
        '--status',
        action='store_true',
        default=False,
        help='Show current state and learning stats, then exit',
    )
    parser.add_argument(
        '--report',
        action='store_true',
        default=False,
        help='Generate a categorized ticket report with missing-field flags',
    )

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)

    from agents.ticket_monitor import TicketMonitorAgent

    agent = TicketMonitorAgent(
        config_path=args.config,
        db_dir=args.db_dir,
        dry_run=args.dry_run,
    )

    try:
        if args.status:
            status = agent.get_status()
            log.info('Current status:\n%s', json.dumps(status, indent=2, default=str))
            return 0

        if args.report:
            overrides_r: dict = {}
            if args.project:
                overrides_r['project'] = args.project
            response = agent.generate_report(
                project=overrides_r.get('project'),
                since=args.since,
            )
            print(response.content)
            return 0 if response.success else 1

        if args.reset_learning:
            agent.learning.reset()
            log.info('Learning store reset.')
            return 0

        if args.learn_only:
            response = agent.run_learning_only(since=args.since)
            log.info(response.content)
            return 0 if response.success else 1

        overrides = {}
        if args.project:
            overrides['project'] = args.project
        if args.since:
            overrides['since'] = args.since

        response = agent.run(input_data=overrides if overrides else None)
        log.info(response.content)
        return 0 if response.success else 1

    except KeyboardInterrupt:
        log.info('Interrupted by user.')
        return 1
    finally:
        agent.close()


if __name__ == '__main__':
    sys.exit(main())
