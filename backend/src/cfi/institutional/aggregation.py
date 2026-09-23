"""Daily, weekly and monthly aggregation of ETF flows (pure functions — no I/O).

Aggregation happens at read time from the stored daily rows, so it always reflects the
point-in-time view it is given (the caller has already applied ``as_of`` / ``knowledge_time``).

Per bucket, every US trading day is accounted for exactly once:

- **present** — a stored row with values;
- **missing** — due (its data should be public by ``as_of``) and within stored coverage, but no
  value (absent, or stored as an explicit missing row);
- **not loaded** — before the first stored day (the provider serves limited history);
- **not due** — after ``due_until`` and not received yet (e.g. the current week).

Sums cover present days only; a bucket with missing or not-loaded days is reported ``partial``
and says how many days its totals are made of. Nothing is interpolated.

Bucket status: ``complete`` (every trading day present), ``partial`` (some missing or not loaded),
``in_progress`` (present so far, later days not due yet), ``not_due`` (nothing due yet),
``not_loaded`` (entirely before stored history) or ``no_data`` (due days, none received).

Buckets: ``1d`` = one trading date; ``1w`` = Monday–Sunday week (ADR-0039: weeks start on
Monday); ``1mo`` = calendar month. Net assets (AUM) of a bucket are those of its last present day.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from cfi.core.calendars import (
    is_us_trading_day,
    new_york_time,
    next_us_trading_day,
    us_trading_days,
)
from cfi.core.time import ensure_utc

Interval = Literal["1d", "1w", "1mo"]
INTERVALS: tuple[Interval, ...] = ("1d", "1w", "1mo")
BucketStatus = Literal["complete", "partial", "in_progress", "not_due", "not_loaded", "no_data"]
FLAGGED = ("suspect", "conflicting")

# ETF flows for trading date D count as due at 18:00 New York time on the next trading day
# (the conservative availability estimate of the ETF datasets).
ETF_DUE_OFFSET = timedelta(hours=18)


@dataclass(frozen=True, slots=True)
class DailyPoint:
    """One stored daily row, as visible under the caller's point-in-time cut-offs."""

    day: date
    flow_usd: Decimal | None
    holdings_usd: Decimal | None
    value_traded_usd: Decimal | None
    quality_status: str
    revision: int
    pit_reliability: str
    available_at_estimated: bool
    available_at: datetime
    ingested_at: datetime

    @property
    def has_value(self) -> bool:
        return self.quality_status != "missing" and self.flow_usd is not None


@dataclass(slots=True)
class Bucket:
    start: date
    end: date  # exclusive
    net_flow_usd: Decimal | None = None
    holdings_usd_end: Decimal | None = None
    holdings_date: date | None = None
    value_traded_usd: Decimal | None = None
    trading_days: int = 0
    present: int = 0
    missing_days: list[date] = field(default_factory=list)
    not_loaded: int = 0
    not_due: int = 0
    flagged: int = 0
    revised: int = 0
    backfilled: int = 0
    estimated_availability: int = 0
    inflow_days: int = 0
    outflow_days: int = 0

    @property
    def status(self) -> BucketStatus:
        if self.present == 0:
            if self.missing_days:
                return "no_data"
            if self.not_due:
                return "not_due"
            return "not_loaded" if self.not_loaded else "no_data"
        if self.missing_days or self.not_loaded:
            return "partial"
        if self.not_due:
            return "in_progress"
        return "complete"


def etf_due_date(as_of: datetime) -> date:
    """The latest US trading date whose ETF figures should be public by ``as_of``."""
    as_of = ensure_utc(as_of, field="as_of")
    day = as_of.date() + timedelta(days=1)
    while True:
        day -= timedelta(days=1)
        if not is_us_trading_day(day):
            continue
        due = new_york_time(next_us_trading_day(day), time(0)) + ETF_DUE_OFFSET
        if due <= as_of:
            return day


def bucket_start(day: date, interval: Interval) -> date:
    if interval == "1d":
        return day
    if interval == "1w":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def bucket_end(start: date, interval: Interval) -> date:
    if interval == "1d":
        return start + timedelta(days=1)
    if interval == "1w":
        return start + timedelta(days=7)
    return date(start.year + (start.month == 12), start.month % 12 + 1, 1)


def aggregate(
    points: Iterable[DailyPoint],
    *,
    interval: Interval,
    start: date,
    end: date,
    due_until: date,
    coverage_start: date | None,
) -> list[Bucket]:
    """Buckets covering the trading days in [start, end), oldest first."""
    by_day = {p.day: p for p in points if start <= p.day < end}
    buckets: dict[date, Bucket] = {}
    for day in us_trading_days(start, end):
        key = bucket_start(day, interval)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = buckets[key] = Bucket(start=max(key, start), end=bucket_end(key, interval))
        bucket.end = min(bucket.end, end)
        bucket.trading_days += 1
        point = by_day.get(day)
        if point is not None and point.has_value:
            _add(bucket, point)
        elif coverage_start is None or day < coverage_start:
            bucket.not_loaded += 1
        elif day > due_until and point is None:
            bucket.not_due += 1
        else:
            bucket.missing_days.append(day)
    return [buckets[k] for k in sorted(buckets)]


def _add(bucket: Bucket, point: DailyPoint) -> None:
    flow = point.flow_usd
    assert flow is not None  # noqa: S101 — has_value
    bucket.present += 1
    bucket.net_flow_usd = (bucket.net_flow_usd or Decimal(0)) + flow
    if point.value_traded_usd is not None:
        bucket.value_traded_usd = (bucket.value_traded_usd or Decimal(0)) + point.value_traded_usd
    if point.holdings_usd is not None and (
        bucket.holdings_date is None or point.day > bucket.holdings_date
    ):
        bucket.holdings_usd_end = point.holdings_usd
        bucket.holdings_date = point.day
    if flow > 0:
        bucket.inflow_days += 1
    elif flow < 0:
        bucket.outflow_days += 1
    bucket.flagged += point.quality_status in FLAGGED
    bucket.revised += point.revision > 0
    bucket.backfilled += point.pit_reliability == "backfilled_latest"
    bucket.estimated_availability += point.available_at_estimated


def trading_window(end_day: date, days: int) -> list[date]:
    """The ``days`` US trading dates ending at ``end_day`` (inclusive), oldest first."""
    out: list[date] = []
    cursor = end_day
    while len(out) < days:
        if is_us_trading_day(cursor):
            out.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(out))


def to_points(rows: Sequence[dict[str, object]]) -> list[DailyPoint]:
    """Query rows → points (one per day; the query already returns the latest revision)."""
    points = []
    for r in rows:
        event_time = r["event_time"]
        assert isinstance(event_time, datetime)  # noqa: S101 — database type
        points.append(
            DailyPoint(
                day=event_time.date(),
                flow_usd=r["flow_usd"],  # type: ignore[arg-type]
                holdings_usd=r["holdings_usd"],  # type: ignore[arg-type]
                value_traded_usd=r["value_traded_usd"],  # type: ignore[arg-type]
                quality_status=str(r["quality_status"]),
                revision=int(r["revision"]),  # type: ignore[call-overload]
                pit_reliability=str(r["pit_reliability"]),
                available_at_estimated=bool(r["available_at_estimated"]),
                available_at=r["available_at"],  # type: ignore[arg-type]
                ingested_at=r["ingested_at"],  # type: ignore[arg-type]
            )
        )
    return points
