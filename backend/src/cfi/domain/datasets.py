"""Dataset specifications (the dataset registry, ADR-0021).

A dataset is *what* is measured (e.g. hourly close price). Providers are *who* supplies it.
The spec decides how the engine treats incoming data: canonical unit, period, when values become
publicly knowable, how fresh data must be, and how far providers may disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from cfi.core.calendars import new_york_time, next_us_trading_day
from cfi.core.errors import NotYetFinalError
from cfi.core.time import ensure_utc, parse_period
from cfi.domain.enums import PitReliability

AvailabilityKind = Literal["provider", "period_end_plus", "event_time_plus", "next_us_trading_day"]
RecordKind = Literal["scalar", "bar", "flow"]


@dataclass(frozen=True, slots=True)
class AvailabilityRule:
    """How ``available_at`` is set (point-in-time correctness, ADR-0018).

    - ``provider``: the provider states a publication time; if a record lacks it, the conservative
      fallback is the ingestion time (flagged as estimated).
    - ``period_end_plus``: knowable at the end of the period plus ``delay`` (bars: close + latency).
    - ``event_time_plus``: knowable at the event time plus ``delay``.
    - ``next_us_trading_day``: ``event_time`` labels a US trading date; the value is knowable on
      the next US trading day at 00:00 New York time plus ``delay`` (e.g. ETF flows settled T+1).

    ``known_when_received``: the rule is a conservative *estimate*. When a value is actually
    received earlier than the estimate, it was evidently public by then, so ``available_at`` is the
    receipt time instead of the value being treated as not final. Use it only for data that is
    final whenever it is published (never for bars, which change until they close).
    """

    kind: AvailabilityKind
    delay: timedelta = timedelta(0)
    known_when_received: bool = False

    def __post_init__(self) -> None:
        if self.known_when_received and self.kind in ("provider", "period_end_plus"):
            raise ValueError("known_when_received applies to estimated availability rules only")

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "delay_seconds": int(self.delay.total_seconds()),
            "known_when_received": self.known_when_received,
        }


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    dataset_id: str
    metric: str
    unit: str
    period: str
    availability: AvailabilityRule
    freshness_limit: timedelta
    conflict_tolerance: Decimal
    revisable: bool = False
    expect_continuous: bool = False
    description: str = ""
    kind: RecordKind = "scalar"
    # False for sporadic event datasets (e.g. treasury purchases): the age of the newest *event*
    # says nothing about pipeline health, so ingestion jobs do not flag them stale.
    check_freshness: bool = True

    def __post_init__(self) -> None:
        parse_period(self.period)  # validates
        if self.conflict_tolerance < 0:
            raise ValueError("conflict_tolerance must be >= 0")
        if self.expect_continuous and self.period_length is None:
            raise ValueError("expect_continuous requires a fixed period")
        if self.availability.kind == "period_end_plus" and self.period_length is None:
            raise ValueError("period_end_plus availability requires a fixed period")

    @property
    def period_length(self) -> timedelta | None:
        return parse_period(self.period)

    def available_at(
        self, event_time: datetime, published_at: datetime | None, ingested_at: datetime
    ) -> tuple[datetime, bool]:
        """Return ``(available_at, estimated)`` for one record.

        Raises ``NotYetFinalError`` when the value could not yet have been final at ingestion
        (e.g. a bar whose period has not closed) — such data is skipped, never stored as final.
        """
        event_time = ensure_utc(event_time, field="event_time")
        ingested_at = ensure_utc(ingested_at, field="ingested_at")
        rule = self.availability
        if rule.kind == "provider":
            if published_at is not None:
                return ensure_utc(published_at, field="published_at"), False
            return ingested_at, True
        if rule.kind == "period_end_plus":
            period = self.period_length
            assert period is not None  # noqa: S101 — enforced in __post_init__
            available = event_time + period + rule.delay
        elif rule.kind == "next_us_trading_day":
            next_day = next_us_trading_day(event_time.date())
            available = new_york_time(next_day, time(0)) + rule.delay
        else:
            available = event_time + rule.delay
        if available > ingested_at and rule.known_when_received:
            return ingested_at, True
        if available > ingested_at:
            raise NotYetFinalError(
                f"value for {event_time.isoformat()} was not final at ingestion "
                f"(knowable from {available.isoformat()})",
                dataset_id=self.dataset_id,
            )
        return available, True

    def pit_reliability(self, available_at: datetime, ingested_at: datetime) -> PitReliability:
        """``native`` when we recorded the value while it was current (within the freshness limit
        after it became knowable); otherwise ``backfilled_latest`` — history as the provider shows
        it today, which may include later corrections (ADR-0032)."""
        lag = ensure_utc(ingested_at) - ensure_utc(available_at)
        if lag <= self.freshness_limit:
            return PitReliability.NATIVE
        return PitReliability.BACKFILLED_LATEST
