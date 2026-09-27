"""Signal definitions (Phase 16): versioned, named readings a strategy's entry/exit rules compare
against a threshold. Two kinds, each reusing already-tested computation rather than reimplementing
it a third time:

* **Price signals** — computed directly from the in-memory bar history through the decision day
  (no database round-trip per day): ``sma_crossover`` and ``rsi`` both call
  ``cfi.market_structure.metrics``'s own already-tested ``moving_averages``/``rsi`` functions.
* **Domain signals** — one generic adapter (``DomainScoreSignal``) exposing any of the 9 named
  features ``cfi.similarity.snapshot.gather_snapshot`` already extracts (institutional/whale/retail/
  liquidity/funding/OI/volatility/market-structure/macro), reusing that already-tested,
  already-point-in-time-correct extraction rather than a third per-domain reader. Documented cost:
  one snapshot gather (7 domain service calls) per simulated day a domain signal is used — the same
  per-day cost ``cfi.regime.history``/``cfi.similarity.search`` already accept for their own
  backward walks.

Every signal returns a ``SignalReading`` with an explicit ``"ok" | "unavailable"`` status — a
strategy's rules never see a fabricated value for a day a signal could not be computed (R3).

Both kinds share one ``Signal`` protocol with a single, uniform, always-``async`` ``value_at``
signature (``bars_through_today``, ``adapters``, ``as_of``) — a price signal simply ignores the
``adapters``/``as_of`` it does not need and a domain signal ignores the ``bars_through_today`` it
does not need. This is deliberate: a strategy's ``signal`` field only ever needs to be called one
way, so the engine never has to branch on which kind of signal it is holding."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from cfi.divergence.adapters import Adapters
from cfi.market_structure import metrics as ms
from cfi.similarity.snapshot import FEATURE_IDS, gather_snapshot

Status = str  # "ok" | "unavailable"


@dataclass(frozen=True, slots=True)
class SignalReading:
    status: Status
    value: Decimal | None = None
    condition: str | None = None


class Signal(Protocol):
    @property
    def signal_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    async def value_at(
        self, bars_through_today: Sequence[ms.Bar], adapters: Adapters, *, as_of: datetime
    ) -> SignalReading: ...


@dataclass(frozen=True, slots=True)
class SmaCrossoverSignal:
    """Fast SMA minus slow SMA — positive means the fast average is above the slow one
    (conventionally bullish), negative means bearish. Reuses
    ``cfi.market_structure.metrics.moving_averages`` (fixed windows: 20/50/200) rather than a
    fresh SMA implementation."""

    signal_id: str = "sma_crossover"
    version: str = "sma_crossover_v1"
    fast: str = "sma20"
    slow: str = "sma50"

    async def value_at(
        self, bars_through_today: Sequence[ms.Bar], adapters: Adapters, *, as_of: datetime
    ) -> SignalReading:
        ma = ms.moving_averages(bars_through_today)
        fast_value = getattr(ma, self.fast, None)
        slow_value = getattr(ma, self.slow, None)
        if ma.status != "ok" or fast_value is None or slow_value is None:
            return SignalReading(status="unavailable")
        diff = fast_value - slow_value
        condition = "bullish" if diff > 0 else "bearish" if diff < 0 else "flat"
        return SignalReading(status="ok", value=diff, condition=condition)


@dataclass(frozen=True, slots=True)
class RsiSignal:
    """The 14-day RSI value (0..100). Reuses ``cfi.market_structure.metrics.rsi`` rather than a
    fresh RSI implementation."""

    signal_id: str = "rsi"
    version: str = "rsi_v1"
    period: int = 14

    async def value_at(
        self, bars_through_today: Sequence[ms.Bar], adapters: Adapters, *, as_of: datetime
    ) -> SignalReading:
        reading = ms.rsi(bars_through_today, period=self.period)
        if reading.status != "ok" or reading.value is None:
            return SignalReading(status="unavailable")
        return SignalReading(status="ok", value=reading.value, condition=reading.condition)


@dataclass(frozen=True, slots=True)
class DomainScoreSignal:
    """Any one of the 9 named features ``cfi.similarity.snapshot.gather_snapshot`` already
    extracts (see that module for the exact field each one reads). Gathers a fresh snapshot at
    ``as_of = knowledge_time = as_of`` — never the backtest's own later, global ``as_of`` — so a
    decision on day D never reflects a later-ingested revision (R4)."""

    feature_id: str
    signal_id: str = "domain_score"
    version: str = "domain_score_v1"

    def __post_init__(self) -> None:
        if self.feature_id not in FEATURE_IDS:
            raise KeyError(f"unknown domain-score feature id: {self.feature_id!r}")

    async def value_at(
        self, bars_through_today: Sequence[ms.Bar], adapters: Adapters, *, as_of: datetime
    ) -> SignalReading:
        snapshot = await gather_snapshot(adapters, asset="BTC", as_of=as_of, knowledge_time=as_of)
        reading = snapshot.metrics.get(self.feature_id)
        if reading is None or reading.status != "ok" or reading.value is None:
            return SignalReading(status="unavailable")
        return SignalReading(status="ok", value=reading.value)


PRICE_SIGNALS: dict[str, Signal] = {
    "sma_crossover": SmaCrossoverSignal(),
    "rsi": RsiSignal(),
}


def domain_signal(feature_id: str) -> DomainScoreSignal:
    return DomainScoreSignal(feature_id=feature_id)
