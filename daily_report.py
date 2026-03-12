#!/usr/bin/env python3
"""Daily Jira report: tickets created today, bugs without affects version,
and automation-triggered status changes.

Thin CLI wrapper over core/reporting.py — all logic lives there so that
agent tools, MCP endpoints, and this CLI share the same implementation.

Usage:
    .venv/bin/python3 daily_report.py
    .venv/bin/python3 daily_report.py --date 2026-03-12
    .venv/bin/python3 daily_report.py --project STL
    .venv/bin/python3 daily_report.py --output report.xlsx
    .venv/bin/python3 daily_report.py --output report --format csv
"""

import argparse
import logging
import os
import sys
from datetime import date

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load environment and core modules
# ---------------------------------------------------------------------------
load_dotenv()

# Ensure project root is on sys.path so core/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jira_utils import connect_to_jira
from core.reporting import daily_report, export_daily_report


# ---------------------------------------------------------------------------
# Pretty-print helpers (CLI only — core/reporting returns dicts)
# ---------------------------------------------------------------------------

def _print_created_tickets(tickets: list[dict]) -> None:
    """Print the 'tickets created today' section."""
    print(f'\n📋 Tickets Created')
    if not tickets:
        print('   (none found)')
        return

    print(f'   {"Key":<14} {"Type":<10} {"Status":<14} Summary')
    print(f'   {"─"*13}  {"─"*9}  {"─"*13}  {"─"*50}')
    for r in tickets:
        print(f'   {r["key"]:<14} {r["issue_type"]:<10} {r["status"]:<14} {r["summary"][:60]}')
    print(f'\n   Total: {len(tickets)} ticket(s)')


def _print_bugs_missing_field(bugs: dict) -> None:
    """Print the 'bugs missing field' section."""
    field = bugs.get('field', 'affectedVersion')
    flagged = bugs.get('flagged', [])
    total = bugs.get('total_open_count', 0)

    print(f'\n🐛 Bugs Missing {field}')
    if flagged:
        print(f'   ⚠️  {len(flagged)} bug(s) created today missing {field}:')
        for r in flagged:
            print(f'      • {r["key"]}: {r["summary"][:65]}')
    else:
        print(f'   ✅ All bugs created today have {field} set.')

    print(f'\n   📊 Total open bugs missing {field}: {total}')


def _print_status_changes(changes: dict) -> None:
    """Print the 'status changes' section."""
    auto = changes.get('automation', [])
    human = changes.get('human', [])
    total = changes.get('total', 0)

    print(f'\n🤖 Status Changes')

    if auto:
        print(f'   🤖 {len(auto)} automation-triggered status change(s):')
        print(f'   {"Key":<14} {"From":<16} {"To":<16} {"Time (UTC)":<20} Author')
        print(f'   {"─"*13}  {"─"*15}  {"─"*15}  {"─"*19}  {"─"*20}')
        for t in auto:
            time_short = t['time'][11:16] if len(t['time']) > 16 else t['time']
            print(f'   {t["key"]:<14} {t["from"]:<16} {t["to"]:<16} {time_short:<20} {t["author"]}')
    else:
        print('   (no automation status changes found)')

    if human:
        humans = set(t['author'] for t in human)
        print(f'\n   👤 {len(human)} human status change(s) by {len(humans)} user(s):')
        for t in human:
            time_short = t['time'][11:16] if len(t['time']) > 16 else t['time']
            print(f'      {t["key"]:<14} {t["from"]:<16} → {t["to"]:<16} {time_short}  {t["author"]}')

    print(f'\n   Total: {total} status transition(s) '
          f'({len(auto)} automation, {len(human)} human)')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Daily Jira report')
    parser.add_argument('--project', default='STL',
                        help='Jira project key (default: STL)')
    parser.add_argument('--date', default=None,
                        help='Target date YYYY-MM-DD (default: today)')
    parser.add_argument('--field', default='affectedVersion',
                        help='Field to check for bugs (default: affectedVersion)')
    parser.add_argument('--output', '-o', default=None,
                        help='Export report to file (e.g. report.xlsx)')
    parser.add_argument('--format', '-f', default='excel',
                        choices=['excel', 'csv'],
                        help='Export format (default: excel)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable debug logging')
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO, format='%(message)s')

    target_date = args.date or date.today().isoformat()
    project = args.project

    print(f'═══════════════════════════════════════════════════════════')
    print(f'  Daily Jira Report — {project} — {target_date}')
    print(f'═══════════════════════════════════════════════════════════')

    # Connect to Jira and run the composite report
    jira = connect_to_jira()
    report = daily_report(
        jira, project, target_date,
        missing_field=args.field,
    )

    # Pretty-print to stdout
    _print_created_tickets(report['created_tickets'])
    _print_bugs_missing_field(report['bugs_missing_field'])
    _print_status_changes(report['status_changes'])

    # Summary
    bugs = report['bugs_missing_field']
    changes = report['status_changes']
    print(f'\n═══════════════════════════════════════════════════════════')
    print(f'  Summary')
    print(f'═══════════════════════════════════════════════════════════')
    print(f'  📋 Tickets created today:          {len(report["created_tickets"])}')
    print(f'  🐛 Bugs missing {args.field}:   {len(bugs["flagged"])}')
    print(f'  🤖 Automation status changes:       {len(changes["automation"])}')
    print(f'═══════════════════════════════════════════════════════════')

    # Optional export
    if args.output:
        path = export_daily_report(report, args.output, fmt=args.format)
        print(f'\n  📁 Exported to: {path}')


if __name__ == '__main__':
    main()
