"""Unit tests for cfi.backtest.strategy — the comparator helper and the example strategy
definitions (documented v1 defaults, never fitted to data)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cfi.backtest.strategy import EXAMPLE_STRATEGIES, compare


def test_compare_gte() -> None:
    assert compare(Decimal(5), "gte", Decimal(5)) is True
    assert compare(Decimal(4), "gte", Decimal(5)) is False


def test_compare_lte() -> None:
    assert compare(Decimal(5), "lte", Decimal(5)) is True
    assert compare(Decimal(6), "lte", Decimal(5)) is False


def test_compare_raises_on_unknown_comparator() -> None:
    with pytest.raises(ValueError, match="unknown comparator"):
        compare(Decimal(1), "eq", Decimal(1))  # type: ignore[arg-type]


def test_example_strategies_are_long_only_with_leverage_capped_at_one() -> None:
    for strategy in EXAMPLE_STRATEGIES.values():
        assert strategy.risk_limits.max_leverage == Decimal(1)
        assert Decimal(0) < strategy.risk_limits.max_exposure_pct <= Decimal(100)


def test_sma_trend_follow_v1_uses_the_sma_crossover_price_signal() -> None:
    strategy = EXAMPLE_STRATEGIES["sma_trend_follow_v1"]
    assert strategy.signal.signal_id == "sma_crossover"
    assert strategy.entry_comparator == "gte"
    assert strategy.exit_comparator == "lte"


def test_whale_accumulation_v1_uses_the_domain_score_signal_and_regime_aligned_thresholds() -> None:
    strategy = EXAMPLE_STRATEGIES["whale_accumulation_v1"]
    assert strategy.signal.signal_id == "domain_score"
    assert strategy.entry_threshold == Decimal(15)
    assert strategy.exit_threshold == Decimal(-15)
