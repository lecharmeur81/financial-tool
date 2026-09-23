"""Time utilities. All timestamps are timezone-aware UTC (ADR-0010, ADR-0039)."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=UTC)


def ensure_utc(value: datetime, *, field: str = "timestamp") -> datetime:
    """Return ``value`` converted to UTC. Naive datetimes are rejected, never assumed."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field} must be timezone-aware; naive datetimes are not allowed")
    return value.astimezone(UTC)
