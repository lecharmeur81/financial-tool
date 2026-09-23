from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from cfi.core.time import ensure_utc, utc_now


def test_utc_now_is_timezone_aware_utc() -> None:
    now = utc_now()
    assert now.tzinfo is UTC


def test_ensure_utc_converts_offsets() -> None:
    manila = timezone(timedelta(hours=8))
    local = datetime(2026, 9, 23, 8, 0, tzinfo=manila)
    assert ensure_utc(local) == datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
    assert ensure_utc(local).tzinfo is UTC


def test_ensure_utc_rejects_naive_datetimes() -> None:
    naive = datetime(2026, 9, 23, 8, 0)  # noqa: DTZ001 — deliberately naive for this test
    with pytest.raises(ValueError, match="timezone-aware"):
        ensure_utc(naive, field="event_time")
