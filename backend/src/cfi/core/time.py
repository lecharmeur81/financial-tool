"""Time utilities. All timestamps are timezone-aware UTC (ADR-0010, ADR-0039).

Normalisation rules:
- aware datetimes / ISO strings with an offset are converted to UTC;
- epoch numbers need an explicit unit (``s`` or ``ms``) — the unit is never guessed;
- naive values are accepted only when the provider's time zone is declared, and are then
  localised with that zone (daylight-saving transitions handled by ``zoneinfo``);
- anything else is rejected.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EpochUnit = Literal["s", "ms"]

_PERIOD = re.compile(r"^(\d+)(m|h|d|w)$")
_PERIOD_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=UTC)


def ensure_utc(value: datetime, *, field: str = "timestamp") -> datetime:
    """Return ``value`` converted to UTC. Naive datetimes are rejected, never assumed."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field} must be timezone-aware; naive datetimes are not allowed")
    return value.astimezone(UTC)


def from_epoch(value: int | float | str | Decimal, unit: EpochUnit) -> datetime:
    """Convert an epoch number in an explicitly declared unit to UTC."""
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"not an epoch number: {value!r}") from exc
    seconds = number / 1000 if unit == "ms" else number
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=float(seconds))


def parse_timestamp(value: str, *, source_timezone: str | None = None) -> datetime:
    """Parse an ISO-8601 string to UTC.

    Strings with an offset (``Z``, ``+08:00``) are converted directly. Naive strings are
    localised with ``source_timezone`` (an IANA name such as ``America/New_York``); without it
    they are rejected.
    """
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"not an ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is not None and parsed.tzinfo.utcoffset(parsed) is not None:
        return parsed.astimezone(UTC)
    if source_timezone is None:
        raise ValueError(f"timestamp {value!r} has no offset and no source time zone was declared")
    try:
        zone = ZoneInfo(source_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown time zone: {source_timezone!r}") from exc
    return parsed.replace(tzinfo=zone).astimezone(UTC)


def parse_period(period: str) -> timedelta | None:
    """``'1h'`` → 1 hour. ``'event'`` (irregular series) → ``None``."""
    if period == "event":
        return None
    match = _PERIOD.fullmatch(period)
    if not match:
        raise ValueError(f"unsupported period {period!r} (use e.g. 1m, 5m, 1h, 8h, 1d, 1w, event)")
    amount, unit = int(match.group(1)), match.group(2)
    if amount <= 0:
        raise ValueError("period must be positive")
    return timedelta(**{_PERIOD_UNITS[unit]: amount})


def floor_to_period(value: datetime, period: timedelta) -> datetime:
    """Align a UTC timestamp down to the period grid anchored at the Unix epoch."""
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    value = ensure_utc(value)
    steps = (value - epoch) // period
    return epoch + steps * period
