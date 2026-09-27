"""Unit tests for cfi.backtest.signals — price signals computed directly from an in-memory bar
slice (no database), and the domain-score signal's feature-id validation.

Every ``Signal`` implementation shares one uniform, always-``async`` ``value_at(bars_through_today,
adapters, *, as_of)`` call (see the module docstring); price signals simply ignore the
``adapters``/``as_of`` they do not need, so these tests pass a placeholder ``Adapters`` that is
never actually touched."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.backtest.signals import PRICE_SIGNALS, RsiSignal, SmaCrossoverSignal, domain_signal
from cfi.divergence.adapters import Adapters
from cfi.market_structure.metrics import Bar

DAY = timedelta(days=1)
T0 = datetime(2024, 1, 1, tzinfo=UTC)
_UNUSED_ADAPTERS = Adapters(engine=None)


def _bars(closes: list[float]) -> list[Bar]:
    out = []
    for i, c in enumerate(closes):
        close = Decimal(str(c))
        out.append(
            Bar(
                time=T0 + DAY * i,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=Decimal(100),
            )
        )
    return out


async def test_sma_crossover_unavailable_with_fewer_than_50_bars() -> None:
    reading = await SmaCrossoverSignal().value_at(_bars([100.0] * 49), _UNUSED_ADAPTERS, as_of=T0)
    assert reading.status == "unavailable"


async def test_sma_crossover_bullish_when_fast_average_is_above_slow() -> None:
    # 30 bars flat at 100 (part of the SMA50 window), then 20 bars at 200 (the SMA20 window) —
    # fast (SMA20=200) is clearly above slow (SMA50 blends the two), so the signal is bullish.
    closes = [100.0] * 30 + [200.0] * 20
    reading = await SmaCrossoverSignal().value_at(_bars(closes), _UNUSED_ADAPTERS, as_of=T0)
    assert reading.status == "ok"
    assert reading.condition == "bullish"
    assert reading.value is not None
    assert reading.value > 0


async def test_sma_crossover_bearish_when_fast_average_is_below_slow() -> None:
    closes = [200.0] * 30 + [100.0] * 20
    reading = await SmaCrossoverSignal().value_at(_bars(closes), _UNUSED_ADAPTERS, as_of=T0)
    assert reading.status == "ok"
    assert reading.condition == "bearish"
    assert reading.value is not None
    assert reading.value < 0


async def test_rsi_unavailable_with_fewer_than_period_plus_one_bars() -> None:
    reading = await RsiSignal().value_at(_bars([100.0] * 14), _UNUSED_ADAPTERS, as_of=T0)
    assert reading.status == "unavailable"


async def test_rsi_ok_once_enough_bars_exist() -> None:
    closes = [100.0 + i for i in range(20)]  # steady rise -> high RSI
    reading = await RsiSignal().value_at(_bars(closes), _UNUSED_ADAPTERS, as_of=T0)
    assert reading.status == "ok"
    assert reading.value is not None
    assert reading.value > Decimal(50)


def test_price_signals_registry_has_both_built_ins() -> None:
    assert set(PRICE_SIGNALS) == {"sma_crossover", "rsi"}


def test_domain_signal_factory_rejects_unknown_feature_id() -> None:
    with pytest.raises(KeyError):
        domain_signal("not_a_real_feature")


def test_domain_signal_factory_accepts_a_known_feature_id() -> None:
    signal = domain_signal("whale_score")
    assert signal.feature_id == "whale_score"
    assert signal.signal_id == "domain_score"
