from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import statistics
from typing import Any, Iterable, Mapping, Optional, Sequence

import yaml


_DEFAULT_CLOSED_STATUSES = {'closed', 'done', 'resolved'}


@dataclass
class ReleaseSnapshot:
    release: str
    timestamp: str
    total_tickets: int
    by_status: dict[str, int] = field(default_factory=dict)
    by_priority: dict[str, int] = field(default_factory=dict)
    by_component: dict[str, int] = field(default_factory=dict)
    by_assignee: dict[str, int] = field(default_factory=dict)
    tickets: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReleaseDelta:
    release: str
    period: str
    new_tickets: list[str] = field(default_factory=list)
    closed_tickets: list[str] = field(default_factory=list)
    status_changes: list[dict[str, str]] = field(default_factory=list)
    priority_changes: list[dict[str, str]] = field(default_factory=list)
    new_p0_p1: list[str] = field(default_factory=list)
    velocity: float = 0.0


@dataclass
class CycleTimeStats:
    component: str
    priority: str
    avg_hours: float
    median_hours: float
    sample_size: int


@dataclass
class ReleaseReadiness:
    release: str
    timestamp: str
    total_open: int
    p0_open: int
    p1_open: int
    daily_close_rate: float
    estimated_days_remaining: Optional[float]
    component_risks: list[dict[str, Any]] = field(default_factory=list)
    stale_tickets: list[str] = field(default_factory=list)


@dataclass
class TrackerConfig:
    project: str = ''
    releases: list[str] = field(default_factory=list)
    schedule: str = '0 9 * * *'
    track_priorities: list[str] = field(default_factory=lambda: ['P0-Stopper', 'P1-Critical'])
    cycle_time_window_days: int = 90
    stale_threshold_multiplier: float = 2.0
    velocity_window_days: int = 14
    output: dict[str, Any] = field(default_factory=dict)
    closed_statuses: list[str] = field(default_factory=lambda: ['Closed', 'Done', 'Resolved'])

    @classmethod
    def from_yaml(cls, yaml_input: str | Mapping[str, Any]) -> 'TrackerConfig':
        if isinstance(yaml_input, Mapping):
            payload = dict(yaml_input)
        else:
            parsed = yaml.safe_load(yaml_input) if yaml_input else {}
            if parsed is None:
                parsed = {}
            if not isinstance(parsed, dict):
                raise ValueError('release tracker config must deserialize to a mapping')
            payload = parsed

        learning = payload.get('learning') or {}
        if not isinstance(learning, Mapping):
            learning = {}

        output_cfg = payload.get('output') or {}
        if not isinstance(output_cfg, Mapping):
            output_cfg = {}

        releases = payload.get('releases') or []
        priorities = payload.get('track_priorities') or ['P0-Stopper', 'P1-Critical']
        closed_statuses = payload.get('closed_statuses') or ['Closed', 'Done', 'Resolved']

        return cls(
            project=str(payload.get('project', '') or ''),
            releases=[str(item) for item in releases],
            schedule=str(payload.get('schedule', '0 9 * * *') or '0 9 * * *'),
            track_priorities=[str(item) for item in priorities],
            cycle_time_window_days=int(learning.get('cycle_time_window_days', 90) or 90),
            stale_threshold_multiplier=float(learning.get('stale_threshold_multiplier', 2.0) or 2.0),
            velocity_window_days=int(learning.get('velocity_window_days', 14) or 14),
            output=dict(output_cfg),
            closed_statuses=[str(item) for item in closed_statuses],
        )


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None

        dt = None
        try:
            dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            pass

        if dt is None:
            formats = (
                '%Y-%m-%dT%H:%M:%S.%f%z',
                '%Y-%m-%dT%H:%M:%S%z',
                '%Y-%m-%d',
            )
            for fmt in formats:
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue

        if dt is None:
            return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _to_string(value: Any, default: str = '') -> str:
    if value is None:
        return default

    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
        return default

    if isinstance(value, Mapping):
        for key in ('name', 'value', 'displayName'):
            if key in value:
                return _to_string(value.get(key), default)

    for attr in ('name', 'value', 'displayName'):
        attr_value = getattr(value, attr, None)
        if attr_value is not None:
            return _to_string(attr_value, default)

    return str(value)


def _to_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        items = [item.strip() for item in value.split(',')]
        return [item for item in items if item]

    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        result: list[str] = []
        for item in value:
            text = _to_string(item)
            if text:
                result.append(text)
        return result

    text = _to_string(value)
    if not text:
        return []
    return [text]


def _ticket_key(ticket: Mapping[str, Any]) -> str:
    return _to_string(ticket.get('key'))


def _ticket_status(ticket: Mapping[str, Any]) -> str:
    return _to_string(ticket.get('status'), 'N/A')


def _ticket_priority(ticket: Mapping[str, Any]) -> str:
    value = (
        ticket.get('priority')
        or ticket.get('priority_name')
        or ticket.get('priorityName')
    )
    return _to_string(value, 'N/A')


def _ticket_assignee(ticket: Mapping[str, Any]) -> str:
    value = (
        ticket.get('assignee')
        or ticket.get('assignee_display')
        or ticket.get('assignee_id')
    )
    return _to_string(value, 'Unassigned')


def _ticket_components(ticket: Mapping[str, Any]) -> list[str]:
    candidates = (
        ticket.get('components'),
        ticket.get('component'),
    )
    for candidate in candidates:
        values = _to_list(candidate)
        if values:
            return values
    return []


def _ticket_fix_versions(ticket: Mapping[str, Any]) -> list[str]:
    candidates = (
        ticket.get('fix_versions'),
        ticket.get('fix_version'),
        ticket.get('fixVersions'),
        ticket.get('fixVersion'),
    )
    for candidate in candidates:
        values = _to_list(candidate)
        if values:
            return values
    return []


def _ticket_matches_release(ticket: Mapping[str, Any], release: str) -> bool:
    if not release:
        return True
    return release in _ticket_fix_versions(ticket)


def _is_closed(status: str, closed_statuses: set[str]) -> bool:
    return status.casefold() in closed_statuses


def _priority_band(priority: str) -> str:
    folded = priority.casefold()
    if folded.startswith('p0') or 'stopper' in folded:
        return 'p0'
    if folded.startswith('p1') or 'critical' in folded:
        return 'p1'
    return 'other'


def _snapshot_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _elapsed_days(start: str, end: str) -> float:
    start_dt = _parse_timestamp(start)
    end_dt = _parse_timestamp(end)
    if start_dt is None or end_dt is None:
        return 1.0

    seconds = (end_dt - start_dt).total_seconds()
    if seconds <= 0:
        return 1.0
    return max(seconds / 86400.0, 1.0 / 24.0)


def build_snapshot(tickets: Sequence[Mapping[str, Any]], release: str) -> ReleaseSnapshot:
    selected_tickets: list[dict[str, Any]] = []
    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_component: dict[str, int] = {}
    by_assignee: dict[str, int] = {}

    for ticket in tickets:
        if not _ticket_matches_release(ticket, release):
            continue

        status = _ticket_status(ticket)
        priority = _ticket_priority(ticket)
        assignee = _ticket_assignee(ticket)
        components = _ticket_components(ticket)

        by_status[status] = by_status.get(status, 0) + 1
        by_priority[priority] = by_priority.get(priority, 0) + 1
        by_assignee[assignee] = by_assignee.get(assignee, 0) + 1

        if components:
            for component in components:
                by_component[component] = by_component.get(component, 0) + 1
        else:
            by_component['Unspecified'] = by_component.get('Unspecified', 0) + 1

        selected_tickets.append(dict(ticket))

    return ReleaseSnapshot(
        release=release,
        timestamp=_snapshot_time(),
        total_tickets=len(selected_tickets),
        by_status=by_status,
        by_priority=by_priority,
        by_component=by_component,
        by_assignee=by_assignee,
        tickets=selected_tickets,
    )


def compute_delta(current: ReleaseSnapshot, previous: ReleaseSnapshot) -> ReleaseDelta:
    current_map = {
        _ticket_key(ticket): ticket
        for ticket in current.tickets
        if _ticket_key(ticket)
    }
    previous_map = {
        _ticket_key(ticket): ticket
        for ticket in previous.tickets
        if _ticket_key(ticket)
    }

    current_keys = set(current_map)
    previous_keys = set(previous_map)
    shared_keys = current_keys & previous_keys

    new_tickets = sorted(current_keys - previous_keys)

    closed_tickets: set[str] = set()
    for key in previous_keys - current_keys:
        closed_tickets.add(key)

    for key in shared_keys:
        old_status = _ticket_status(previous_map[key])
        new_status = _ticket_status(current_map[key])
        if not _is_closed(old_status, _DEFAULT_CLOSED_STATUSES) and _is_closed(new_status, _DEFAULT_CLOSED_STATUSES):
            closed_tickets.add(key)

    status_changes: list[dict[str, str]] = []
    priority_changes: list[dict[str, str]] = []

    for key in sorted(shared_keys):
        old_status = _ticket_status(previous_map[key])
        new_status = _ticket_status(current_map[key])
        if old_status != new_status:
            status_changes.append({'key': key, 'from': old_status, 'to': new_status})

        old_priority = _ticket_priority(previous_map[key])
        new_priority = _ticket_priority(current_map[key])
        if old_priority != new_priority:
            priority_changes.append({'key': key, 'from': old_priority, 'to': new_priority})

    new_p0_p1 = [
        key for key in new_tickets
        if _priority_band(_ticket_priority(current_map[key])) in {'p0', 'p1'}
    ]

    elapsed_days = _elapsed_days(previous.timestamp, current.timestamp)
    velocity = len(closed_tickets) / elapsed_days if elapsed_days > 0 else float(len(closed_tickets))

    return ReleaseDelta(
        release=current.release,
        period=f'{previous.timestamp} -> {current.timestamp}',
        new_tickets=new_tickets,
        closed_tickets=sorted(closed_tickets),
        status_changes=status_changes,
        priority_changes=priority_changes,
        new_p0_p1=new_p0_p1,
        velocity=velocity,
    )


def _sort_snapshots(snapshots: Sequence[ReleaseSnapshot]) -> list[ReleaseSnapshot]:
    return sorted(
        snapshots,
        key=lambda snapshot: _parse_timestamp(snapshot.timestamp) or datetime.min.replace(tzinfo=timezone.utc),
    )


def compute_velocity(snapshots: Sequence[ReleaseSnapshot], window_days: int) -> dict[str, Any]:
    if not snapshots:
        return {
            'window_days': window_days,
            'snapshots_used': 0,
            'opened': 0,
            'closed': 0,
            'net': 0,
            'daily_open_rate': 0.0,
            'daily_close_rate': 0.0,
            'daily_net_rate': 0.0,
        }

    ordered = _sort_snapshots(snapshots)
    latest_time = _parse_timestamp(ordered[-1].timestamp)

    if latest_time is None:
        active = ordered
    else:
        threshold = latest_time - timedelta(days=max(window_days, 1))
        active = [
            snapshot for snapshot in ordered
            if (_parse_timestamp(snapshot.timestamp) or latest_time) >= threshold
        ]

    if len(active) < 2:
        return {
            'window_days': window_days,
            'snapshots_used': len(active),
            'opened': 0,
            'closed': 0,
            'net': 0,
            'daily_open_rate': 0.0,
            'daily_close_rate': 0.0,
            'daily_net_rate': 0.0,
        }

    opened = 0
    closed = 0

    for previous, current in zip(active, active[1:]):
        delta = compute_delta(current, previous)
        opened += len(delta.new_tickets)
        closed += len(delta.closed_tickets)

    span_days = _elapsed_days(active[0].timestamp, active[-1].timestamp)
    daily_open_rate = opened / span_days
    daily_close_rate = closed / span_days

    return {
        'window_days': window_days,
        'snapshots_used': len(active),
        'opened': opened,
        'closed': closed,
        'net': closed - opened,
        'daily_open_rate': daily_open_rate,
        'daily_close_rate': daily_close_rate,
        'daily_net_rate': daily_close_rate - daily_open_rate,
    }


def compute_cycle_time_stats(
    cycle_times: Sequence[Mapping[str, Any]],
    component: str,
    priority: str,
) -> CycleTimeStats:
    component_key = component.casefold()
    priority_key = priority.casefold()

    durations: list[float] = []

    for entry in cycle_times:
        entry_component = _to_string(entry.get('component')).casefold()
        entry_priority = _to_string(entry.get('priority')).casefold()

        if component_key and component_key not in {'*', 'all'} and entry_component != component_key:
            continue
        if priority_key and priority_key not in {'*', 'all'} and entry_priority != priority_key:
            continue

        raw_duration = entry.get('duration_hours')
        if raw_duration is None:
            raw_duration = entry.get('hours')
        if raw_duration is None:
            raw_duration = entry.get('cycle_time_hours')
        if raw_duration is None:
            continue

        try:
            duration = float(raw_duration)
        except (TypeError, ValueError):
            continue

        if duration < 0:
            continue
        durations.append(duration)

    if not durations:
        return CycleTimeStats(
            component=component,
            priority=priority,
            avg_hours=0.0,
            median_hours=0.0,
            sample_size=0,
        )

    return CycleTimeStats(
        component=component,
        priority=priority,
        avg_hours=sum(durations) / len(durations),
        median_hours=float(statistics.median(durations)),
        sample_size=len(durations),
    )


def _normalize_cycle_stats(cycle_stats: Any) -> list[CycleTimeStats]:
    if cycle_stats is None:
        return []

    if isinstance(cycle_stats, CycleTimeStats):
        return [cycle_stats]

    if isinstance(cycle_stats, Mapping):
        values = cycle_stats.values()
        normalized: list[CycleTimeStats] = []
        for value in values:
            normalized.extend(_normalize_cycle_stats(value))
        return normalized

    if isinstance(cycle_stats, Iterable) and not isinstance(cycle_stats, (str, bytes, bytearray)):
        normalized = []
        for item in cycle_stats:
            if isinstance(item, CycleTimeStats):
                normalized.append(item)
                continue
            if isinstance(item, Mapping):
                normalized.append(CycleTimeStats(
                    component=_to_string(item.get('component')),
                    priority=_to_string(item.get('priority')),
                    avg_hours=_coerce_float(item.get('avg_hours', 0.0), 0.0),
                    median_hours=_coerce_float(item.get('median_hours', 0.0), 0.0),
                    sample_size=_coerce_int(item.get('sample_size', 0), 0),
                ))
        return normalized

    return []


def _cycle_baseline_hours(
    stats: list[CycleTimeStats],
    component: str,
    priority: str,
) -> Optional[float]:
    component_key = component.casefold()
    priority_key = priority.casefold()

    exact = [
        stat.avg_hours for stat in stats
        if stat.avg_hours > 0
        and stat.component.casefold() == component_key
        and stat.priority.casefold() == priority_key
    ]
    if exact:
        return sum(exact) / len(exact)

    by_component = [
        stat.avg_hours for stat in stats
        if stat.avg_hours > 0 and stat.component.casefold() == component_key
    ]
    if by_component:
        return sum(by_component) / len(by_component)

    global_values = [stat.avg_hours for stat in stats if stat.avg_hours > 0]
    if global_values:
        return sum(global_values) / len(global_values)

    return None


def assess_readiness(
    snapshot: ReleaseSnapshot,
    velocity: Mapping[str, Any],
    cycle_stats: Any,
    config: TrackerConfig,
) -> ReleaseReadiness:
    closed_statuses = {
        status.casefold() for status in (config.closed_statuses or ['Closed', 'Done', 'Resolved'])
    }

    open_tickets = [
        ticket for ticket in snapshot.tickets
        if not _is_closed(_ticket_status(ticket), closed_statuses)
    ]

    p0_open = 0
    p1_open = 0
    for ticket in open_tickets:
        band = _priority_band(_ticket_priority(ticket))
        if band == 'p0':
            p0_open += 1
        elif band == 'p1':
            p1_open += 1

    daily_close_rate = float(velocity.get('daily_close_rate', 0.0) or 0.0)
    estimated_days_remaining: Optional[float]
    if daily_close_rate > 0:
        estimated_days_remaining = len(open_tickets) / daily_close_rate
    else:
        estimated_days_remaining = None

    normalized_stats = _normalize_cycle_stats(cycle_stats)
    now = datetime.now(timezone.utc)

    component_risk_map: dict[str, dict[str, Any]] = {}
    stale_tickets: list[str] = []

    for ticket in open_tickets:
        key = _ticket_key(ticket)
        priority = _ticket_priority(ticket)
        band = _priority_band(priority)
        components = _ticket_components(ticket) or ['Unspecified']

        updated_time = _parse_timestamp(ticket.get('updated'))
        if updated_time is None:
            updated_time = _parse_timestamp(ticket.get('created'))
        age_hours = 0.0
        if updated_time is not None:
            age_hours = max(0.0, (now - updated_time).total_seconds() / 3600.0)

        component_for_baseline = components[0]
        baseline_hours = _cycle_baseline_hours(normalized_stats, component_for_baseline, priority)
        threshold_hours = None
        if baseline_hours is not None and baseline_hours > 0:
            threshold_hours = baseline_hours * max(config.stale_threshold_multiplier, 0.0)

        if threshold_hours is not None and age_hours > threshold_hours and key:
            stale_tickets.append(key)

        for component in components:
            row = component_risk_map.setdefault(component, {
                'component': component,
                'open': 0,
                'p0': 0,
                'p1': 0,
                'avg_cycle_hours': 0.0,
                'risk_score': 0.0,
            })
            row['open'] += 1
            if band == 'p0':
                row['p0'] += 1
            if band == 'p1':
                row['p1'] += 1

    for component, row in component_risk_map.items():
        baseline = _cycle_baseline_hours(normalized_stats, component, '*') or 0.0
        row['avg_cycle_hours'] = baseline
        row['risk_score'] = (
            (row['p0'] * 3.0)
            + (row['p1'] * 2.0)
            + row['open']
            + (baseline / 24.0)
        )

    component_risks = sorted(
        component_risk_map.values(),
        key=lambda row: (-float(row['risk_score']), str(row['component'])),
    )

    return ReleaseReadiness(
        release=snapshot.release,
        timestamp=snapshot.timestamp,
        total_open=len(open_tickets),
        p0_open=p0_open,
        p1_open=p1_open,
        daily_close_rate=daily_close_rate,
        estimated_days_remaining=estimated_days_remaining,
        component_risks=component_risks,
        stale_tickets=sorted(set(stale_tickets)),
    )


def format_summary(delta: ReleaseDelta, readiness: ReleaseReadiness) -> str:
    eta = 'unknown'
    if readiness.estimated_days_remaining is not None:
        eta = f'{readiness.estimated_days_remaining:.1f} days'

    lines = [
        f'Release {delta.release}: {delta.period}',
        f'New tickets: {len(delta.new_tickets)} | Closed tickets: {len(delta.closed_tickets)}',
        f'Status changes: {len(delta.status_changes)} | Priority changes: {len(delta.priority_changes)}',
        f'P0/P1 new tickets: {len(delta.new_p0_p1)} | Velocity: {delta.velocity:.2f} tickets/day',
        f'Open tickets: {readiness.total_open} (P0={readiness.p0_open}, P1={readiness.p1_open})',
        f'Daily close rate: {readiness.daily_close_rate:.2f} | ETA: {eta}',
    ]

    if readiness.stale_tickets:
        lines.append(f'Stale tickets: {", ".join(readiness.stale_tickets)}')

    return '\n'.join(lines)
