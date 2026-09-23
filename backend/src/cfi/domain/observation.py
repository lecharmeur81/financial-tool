"""Canonical observed-data records (L1): the only shapes provider data may take once normalised.

Fields follow DATA_DICTIONARY.md §2 and CLAUDE.md R3. Every record answers:

| Question | Field(s) |
|---|---|
| What was measured? | ``metric`` (+ ``dataset_id``) |
| When did it occur? | ``event_time`` (and ``period``) |
| When was it knowable / ingested? | ``available_at`` (+ ``_estimated``), ``ingested_at`` |
| Where did it come from? | ``original_source``, ``raw_ref`` (archived payload) |
| Which provider supplied it? | ``source_provider`` |
| What unit? | ``unit`` |
| What asset? | ``asset`` (+ ``subject_ref``, ``venue``) |
| How reliable? | ``quality_status``, ``quality_note``, ``confidence``, ``pit_reliability`` |
| Was it transformed? | ``transformations`` (empty = value stored exactly as reported) |

Two record families share this provenance (ADR-0017):

- :class:`CanonicalObservation` — one scalar ``value`` (stored in ``obs.observation``);
- :class:`CanonicalBar` — an OHLCV bar (stored in ``obs.market_bar``);
- :class:`CanonicalFlow` — capital flow / holdings of an identified institutional vehicle or
  entity (stored in ``obs.institutional_flow``).

Invariants enforced here:
- all timestamps are timezone-aware and converted to UTC;
- a missing value is ``None`` **with** ``quality_status = missing`` — never zero, never silent;
- a non-``ok`` status always carries a note; confidence, when given, is within [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Self

from cfi.core.time import ensure_utc
from cfi.domain.enums import EvidenceClass, PitReliability, QualityStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservedRecord:
    """Provenance shared by every L1 record family."""

    dataset_id: str
    metric: str
    asset: str | None
    subject_ref: str
    period: str
    unit: str
    event_time: datetime
    available_at: datetime
    available_at_estimated: bool
    ingested_at: datetime
    source_provider: str
    original_source: str
    quality_status: QualityStatus
    pit_reliability: PitReliability
    revision: int = 0
    quality_note: str | None = None
    confidence: Decimal | None = None
    raw_ref: int | None = None
    venue: str | None = None
    transformations: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_time", ensure_utc(self.event_time, field="event_time"))
        object.__setattr__(
            self, "available_at", ensure_utc(self.available_at, field="available_at")
        )
        object.__setattr__(self, "ingested_at", ensure_utc(self.ingested_at, field="ingested_at"))

        if self.is_missing and self.quality_status is not QualityStatus.MISSING:
            raise ValueError("value is None but quality_status is not 'missing' (R3)")
        if self.quality_status is QualityStatus.MISSING and not self.is_missing:
            raise ValueError("quality_status is 'missing' but a value was provided")
        if self.quality_status is not QualityStatus.OK and not self.quality_note:
            raise ValueError("quality_note is required when quality_status is not 'ok'")
        if self.confidence is not None and not (Decimal(0) <= self.confidence <= Decimal(1)):
            raise ValueError("confidence must be within [0, 1]")
        if self.revision < 0:
            raise ValueError("revision must be >= 0")
        for name in ("dataset_id", "metric", "subject_ref", "period", "unit", "source_provider"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")
        if not self.original_source:
            raise ValueError("original_source must not be empty (use 'unknown' if not provided)")

    # -- family-specific behaviour used by the ingestion engine ------------------------------

    @property
    def is_missing(self) -> bool:
        """True when the record carries no value (an explicit gap)."""
        raise NotImplementedError

    def comparable(self) -> object:
        """The values that decide duplicate vs. revision (same key, same values = duplicate)."""
        raise NotImplementedError

    @property
    def conflict_value(self) -> Decimal | None:
        """The value compared across providers for conflict detection."""
        raise NotImplementedError

    def describe(self) -> str:
        """Human-readable value, used in quality findings."""
        raise NotImplementedError

    def consistency_problems(self) -> list[str]:
        """Internal consistency checks; violations mark the record ``suspect`` (kept, flagged)."""
        return []

    # -- shared helpers ----------------------------------------------------------------------

    @property
    def transformed(self) -> bool:
        """True if the value or its timestamp was converted from the provider's representation."""
        return bool(self.transformations)

    def with_quality(self, status: QualityStatus, note: str) -> Self:
        return replace(self, quality_status=status, quality_note=note)

    def with_revision(self, revision: int) -> Self:
        return replace(self, revision=revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalObservation(ObservedRecord):
    """A single scalar value (price snapshot, market cap, ETF flow, …)."""

    value: Decimal | None

    @property
    def is_missing(self) -> bool:
        return self.value is None

    def comparable(self) -> object:
        return self.value

    @property
    def conflict_value(self) -> Decimal | None:
        return self.value

    def describe(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalBar(ObservedRecord):
    """An OHLCV bar. ``event_time`` is the bar **open** time; the bar covers one ``period``.

    Prices are in ``unit`` (the quote currency, e.g. ``usd`` or ``usdt``); ``volume_base`` is in
    units of ``asset``; ``volume_quote`` is in ``unit``. ``volume_quote`` and ``trade_count`` are
    ``None`` when the provider does not report them — they are never estimated here.
    A missing bar has every price and volume ``None``.
    """

    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume_base: Decimal | None
    volume_quote: Decimal | None = None
    trade_count: int | None = None

    def __post_init__(self) -> None:
        prices = (self.open, self.high, self.low, self.close)
        if any(p is None for p in prices) and not all(p is None for p in prices):
            raise ValueError("a bar has either all four prices or none")
        if self.close is None and (self.volume_base is not None or self.volume_quote is not None):
            raise ValueError("a missing bar cannot carry volume")
        ObservedRecord.__post_init__(self)

    @property
    def is_missing(self) -> bool:
        return self.close is None

    def comparable(self) -> object:
        return (
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume_base,
            self.volume_quote,
            self.trade_count,
        )

    @property
    def conflict_value(self) -> Decimal | None:
        return self.close

    def describe(self) -> str:
        if self.is_missing:
            return "missing"
        return f"O={self.open} H={self.high} L={self.low} C={self.close} V={self.volume_base}"

    def consistency_problems(self) -> list[str]:
        """OHLC sanity checks. Violations mark the bar ``suspect`` (kept, flagged), never fixed."""
        if self.is_missing:
            return []
        o, h, lo, c = self.open, self.high, self.low, self.close
        if o is None or h is None or lo is None or c is None:  # pragma: no cover — invariant
            return ["incomplete prices"]
        problems = []
        if h < max(o, c, lo):
            problems.append("high is below open, close or low")
        if lo > min(o, c, h):
            problems.append("low is above open, close or high")
        if min(o, h, lo, c) <= 0:
            problems.append("non-positive price")
        if self.volume_base is not None and self.volume_base < 0:
            problems.append("negative volume")
        if self.volume_quote is not None and self.volume_quote < 0:
            problems.append("negative quote volume")
        if self.trade_count is not None and self.trade_count < 0:
            problems.append("negative trade count")
        return problems


ENTITY_TYPES = frozenset({"etf_group", "etf_fund", "public_company", "public_company_group"})


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalFlow(ObservedRecord):
    """Capital flow and holdings of one identified entity (an ETF, a group of ETFs, a listed
    company, or all tracked listed companies) for one ``event_time``.

    Sign convention: a positive flow is capital entering the entity (ETF creations, coins
    acquired); a negative flow is capital leaving it (redemptions, coins sold).

    ``unit`` is the unit of every ``*_usd`` column (``usd``); ``*_native`` columns are in units of
    ``asset``. ``premium_discount`` is a ratio (0.001 = 0.1 %). Any field the provider does not
    report is ``None`` — never estimated. A missing record has no flow and no holdings.

    ``entity_type`` / ``evidence_class`` state *who* the flow is attributed to and how directly
    that is evidenced (R5). An ETF flow is direct evidence of ETF creations/redemptions — not of
    who bought the ETF shares (end investors include retail).
    """

    entity_type: str
    evidence_class: EvidenceClass
    entity_name: str | None = None
    flow_usd: Decimal | None = None
    flow_native: Decimal | None = None
    holdings_usd: Decimal | None = None
    holdings_native: Decimal | None = None
    cum_flow_usd: Decimal | None = None
    value_traded_usd: Decimal | None = None
    premium_discount: Decimal | None = None
    unit_cost_usd: Decimal | None = None

    def __post_init__(self) -> None:
        if self.entity_type not in ENTITY_TYPES:
            raise ValueError(f"unknown entity_type {self.entity_type!r}")
        if self.evidence_class is EvidenceClass.INFERRED:
            raise ValueError("inferred actor labels are not accepted as institutional flow (R5)")
        ObservedRecord.__post_init__(self)

    @property
    def is_missing(self) -> bool:
        return all(
            v is None
            for v in (self.flow_usd, self.flow_native, self.holdings_usd, self.holdings_native)
        )

    def comparable(self) -> object:
        return (
            self.flow_usd,
            self.flow_native,
            self.holdings_usd,
            self.holdings_native,
            self.cum_flow_usd,
            self.value_traded_usd,
            self.premium_discount,
            self.unit_cost_usd,
        )

    @property
    def conflict_value(self) -> Decimal | None:
        return self.flow_usd if self.flow_usd is not None else self.holdings_native

    def describe(self) -> str:
        if self.is_missing:
            return "missing"
        parts = [
            f"{name}={value}"
            for name, value in (
                ("flow_usd", self.flow_usd),
                ("flow_native", self.flow_native),
                ("holdings_usd", self.holdings_usd),
                ("holdings_native", self.holdings_native),
            )
            if value is not None
        ]
        return " ".join(parts)

    def consistency_problems(self) -> list[str]:
        """Sanity checks. Violations mark the record ``suspect`` (kept, flagged), never fixed."""
        if self.is_missing:
            return []
        problems = []
        for name in ("holdings_usd", "holdings_native", "value_traded_usd"):
            value = getattr(self, name)
            if value is not None and value < 0:
                problems.append(f"negative {name}")
        if (
            self.flow_usd is not None
            and self.flow_native is not None
            and self.flow_usd != 0
            and self.flow_native != 0
            and (self.flow_usd > 0) != (self.flow_native > 0)
        ):
            problems.append("flow in USD and flow in coins have opposite signs")
        if (
            self.unit_cost_usd is not None
            and self.flow_usd is not None
            and self.flow_native not in (None, 0)
        ):
            assert self.flow_native is not None  # noqa: S101 — narrowed above
            implied = abs(self.flow_usd / self.flow_native)
            if self.unit_cost_usd <= 0 or abs(implied - self.unit_cost_usd) > (
                self.unit_cost_usd * UNIT_COST_TOLERANCE
            ):
                problems.append(
                    f"unit cost {self.unit_cost_usd} differs from flow_usd / flow_native "
                    f"= {implied:.2f} by more than {UNIT_COST_TOLERANCE:%}"
                )
        return problems


# Reported per-unit cost may be rounded or include fees; beyond this relative difference the
# three reported numbers do not describe the same transaction.
UNIT_COST_TOLERANCE = Decimal("0.02")
