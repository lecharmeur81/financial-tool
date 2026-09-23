"""Dataset specifications (the dataset registry, ADR-0021).

A dataset is *what* is measured (e.g. hourly close price). Providers are *who* supplies it.
The spec decides how the engine treats incoming data: canonical unit, period, when values become
publicly knowable, how fresh data must be, and how far providers may disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from cfi.core.errors import DataValidationError
from cfi.core.time import ensure_utc, parse_period

AvailabilityKind = Literal["provider", "period_end_plus", "event_time_plus"]


@dataclass(frozen=True, slots=True)
class AvailabilityRule:
    """How ``available_at`` is set (point-in-time correctness, ADR-0018).

    - ``provider``: the provider states a publication time; if a record lacks it, the conservative
      fallback is the ingestion time (flagged as estimated).
    - ``period_end_plus``: knowable at the end of the period plus ``delay`` (bars: close + latency).
    - ``event_time_plus``: knowable at the event time plus ``delay``.
    """

    kind: AvailabilityKind
    delay: timedelta = timedelta(0)

    def as_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "delay_seconds": int(self.delay.total_seconds())}


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

        Raises ``DataValidationError`` when the value could not yet have been final at ingestion
        (e.g. a bar whose period has not closed) — such data is rejected, never stored as final.
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
        else:
            available = event_time + rule.delay
        if available > ingested_at:
            raise DataValidationError(
                f"value for {event_time.isoformat()} was not final at ingestion "
                f"(knowable from {available.isoformat()})",
                dataset_id=self.dataset_id,
            )
        return available, True
