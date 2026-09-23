"""Data-quality detection — pure functions, no I/O (ADR-0031, R3).

- duplicates: same key, same value → skipped (counted, never stored twice)
- revisions:  same key, different value from the same provider → stored as a new revision
- conflicts:  different providers disagree beyond the dataset's tolerance → flagged, both kept
- missing:    expected points not delivered → explicit ``missing`` rows, never interpolated
- stale:      newest point older than the dataset's freshness limit → reported
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from cfi.core.time import ensure_utc, floor_to_period
from cfi.domain.observation import ObservedRecord


class CheckName(StrEnum):
    DUPLICATE = "duplicate"
    REVISION = "revision"
    CONFLICT = "cross_provider_conflict"
    MISSING_VALUE = "missing_value"
    GAP = "completeness_gap"
    FRESHNESS = "freshness"
    REJECTED = "rejected_record"
    SCHEMA = "schema"
    CONSISTENCY = "consistency"
    INCONSISTENT_BATCH = "inconsistent_duplicate_in_response"


@dataclass(frozen=True, slots=True)
class QualityFinding:
    dataset_id: str
    check_name: CheckName
    status: str
    checked_at: datetime
    series_id: int | None = None
    provider_id: str | None = None
    job_run_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- batch duplicates


def _key(obs: ObservedRecord) -> tuple[str, str | None, str, datetime]:
    return (obs.subject_ref, obs.venue, obs.period, obs.event_time)


@dataclass(frozen=True, slots=True)
class BatchSplit[R: ObservedRecord]:
    unique: list[R]
    duplicates: list[R]
    inconsistent: list[tuple[R, R]]


def split_batch[R: ObservedRecord](observations: Iterable[R]) -> BatchSplit[R]:
    """Within one delivery: identical repeats are duplicates; same key with a *different* value is
    inconsistent (the first is kept, the other rejected and reported — never silently chosen)."""
    seen: dict[tuple[str, str | None, str, datetime], R] = {}
    duplicates: list[R] = []
    inconsistent: list[tuple[R, R]] = []
    for obs in observations:
        key = _key(obs)
        first = seen.get(key)
        if first is None:
            seen[key] = obs
        elif first.comparable() == obs.comparable():
            duplicates.append(obs)
        else:
            inconsistent.append((first, obs))
    return BatchSplit(list(seen.values()), duplicates, inconsistent)


# --------------------------------------------------------------------------- against stored data


class Classification(StrEnum):
    NEW = "new"
    DUPLICATE = "duplicate"
    REVISION = "revision"


def classify(
    obs: ObservedRecord, existing: tuple[int, object] | None
) -> tuple[Classification, int]:
    """Compare with the latest stored revision (its ``comparable()`` values) from the same provider.

    Returns the classification and the revision number to store (only meaningful for NEW/REVISION).
    """
    if existing is None:
        return Classification.NEW, 0
    revision, value = existing
    if value == obs.comparable():
        return Classification.DUPLICATE, revision
    return Classification.REVISION, revision + 1


@dataclass(frozen=True, slots=True)
class Conflict:
    other_provider: str
    other_value: Decimal
    relative_difference: Decimal


def relative_difference(a: Decimal, b: Decimal) -> Decimal:
    scale = max(abs(a), abs(b))
    if scale == 0:
        return Decimal(0)
    return abs(a - b) / scale


def find_conflicts(
    value: Decimal | None, others: Sequence[tuple[str, Decimal | None]], tolerance: Decimal
) -> list[Conflict]:
    """Other providers' values for the same point that differ by more than ``tolerance``."""
    if value is None:
        return []
    conflicts = []
    for provider, other in others:
        if other is None:
            continue
        diff = relative_difference(value, other)
        if diff > tolerance:
            conflicts.append(Conflict(provider, other, diff))
    return conflicts


def conflict_note(conflicts: Sequence[Conflict], tolerance: Decimal) -> str:
    parts = [
        f"{c.other_provider}={c.other_value} (differs by {c.relative_difference * 100:.2f}%)"
        for c in conflicts
    ]
    return f"disagrees beyond tolerance {tolerance * 100:.2f}% with: " + "; ".join(parts)


# --------------------------------------------------------------------------- completeness


def expected_points(
    start: datetime, end: datetime, period: timedelta, *, not_after: datetime
) -> list[datetime]:
    """Period-aligned timestamps in [start, end) whose period has closed by ``not_after``."""
    start, end, not_after = ensure_utc(start), ensure_utc(end), ensure_utc(not_after)
    first = floor_to_period(start, period)
    if first < start:
        first += period
    points = []
    current = first
    while current < end and current + period <= not_after:
        points.append(current)
        current += period
    return points


def find_gaps(expected: Iterable[datetime], present: Iterable[datetime]) -> list[datetime]:
    have = set(present)
    return [t for t in expected if t not in have]


# --------------------------------------------------------------------------- freshness


def is_stale(latest_event_time: datetime | None, freshness_limit: timedelta, now: datetime) -> bool:
    """Stale if there is no value at all, or the newest one is older than the limit."""
    if latest_event_time is None:
        return True
    return ensure_utc(now) - ensure_utc(latest_event_time) > freshness_limit
