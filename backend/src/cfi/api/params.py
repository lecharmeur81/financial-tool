"""Shared request-parameter helpers."""

from __future__ import annotations

from datetime import datetime

from cfi.core.errors import DataValidationError
from cfi.core.time import ensure_utc, utc_now


def aware(value: datetime | None, name: str) -> datetime | None:
    """A timezone-aware query timestamp in UTC; naive values are rejected, never assumed."""
    if value is None:
        return None
    try:
        return ensure_utc(value, field=name)
    except ValueError as exc:
        raise DataValidationError(f"'{name}' must include a time zone offset (e.g. Z).") from exc


def resolve_query_times(
    as_of: datetime | None, knowledge_time: datetime | None
) -> tuple[datetime, datetime]:
    """Resolve the ``as_of``/``knowledge_time`` pair every point-in-time route accepts.

    ADR-0060 (Phase 18, RED_TEAM_REPORT.md finding #1): ``knowledge_time`` used to default to
    ``now()`` independently of ``as_of``, which made ``ingested_at <= knowledge_time`` a no-op for
    any caller who supplied only ``as_of`` — defeating the revision/leakage gate for exactly the
    single most natural way to call these endpoints ("what did this look like as of date X").

    The corrected rule: when ``as_of`` is supplied and ``knowledge_time`` is not, ``knowledge_time``
    defaults to ``as_of`` (only what was knowable *by that same date* is visible — the safe
    assumption). When both are omitted, both default to "now" (there is no leakage risk in asking
    for the current state). An explicitly supplied ``knowledge_time`` is always honored (capped at
    "now"), including one earlier or later than ``as_of``.
    """
    now = utc_now()
    a = aware(as_of, "as_of")
    k = aware(knowledge_time, "knowledge_time")
    a_resolved = now if a is None else min(a, now)
    k_resolved = (a_resolved if a is not None else now) if k is None else min(k, now)
    return a_resolved, k_resolved
