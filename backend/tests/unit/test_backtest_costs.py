"""Unit tests for cfi.backtest.costs — the versioned fee/slippage/liquidity-cap model."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cfi.backtest.costs import (
    COST_MODEL_V1,
    COST_MODEL_V2,
    CURRENT_VERSION,
    apply_fee,
    liquidity_cap,
    parameters,
    slipped_price,
)


def test_parameters_defaults_to_current_version() -> None:
    assert parameters() is COST_MODEL_V2
    assert parameters(CURRENT_VERSION) is COST_MODEL_V2
    assert CURRENT_VERSION == "cost_model_v2"


def test_v1_is_still_registered_and_unchanged_for_reproducibility() -> None:
    """Phase 18 introduced v2 as the new default (ADR-0061); v1 stays registered byte-for-byte
    so any run recorded with parameter_version='cost_model_v1' remains exactly reproducible."""
    assert parameters("cost_model_v1") is COST_MODEL_V1
    assert COST_MODEL_V1.participation_impact_coefficient == Decimal("0")


def test_parameters_raises_on_unknown_version() -> None:
    with pytest.raises(KeyError):
        parameters("no_such_version")


def test_apply_fee_is_proportional_to_notional() -> None:
    fee = apply_fee(Decimal(10_000), COST_MODEL_V1)
    assert fee == Decimal(10_000) * COST_MODEL_V1.fee_bps / Decimal(10_000)
    assert fee == Decimal("10")  # 10 bps of 10,000 = 10


def test_slipped_price_buy_is_adverse_upward() -> None:
    price = Decimal(1000)
    slipped = slipped_price(price, direction="buy", params=COST_MODEL_V1)
    assert slipped > price


def test_slipped_price_sell_is_adverse_downward() -> None:
    price = Decimal(1000)
    slipped = slipped_price(price, direction="sell", params=COST_MODEL_V1)
    assert slipped < price


def test_liquidity_cap_is_none_when_volume_is_missing() -> None:
    assert liquidity_cap(None, Decimal(100), COST_MODEL_V1) is None


def test_liquidity_cap_scales_with_trailing_volume_and_participation_pct() -> None:
    cap = liquidity_cap(Decimal(1000), Decimal(100), COST_MODEL_V1)
    # 1000 base * $100 * 5% participation = $5,000 notional cap
    assert cap == Decimal(1000) * Decimal(100) * COST_MODEL_V1.max_participation_pct / Decimal(100)
    assert cap == Decimal(5000)


def test_v1_slippage_is_flat_regardless_of_participation_fraction() -> None:
    """cost_model_v1's coefficient is 0 — participation_fraction must be a no-op, so every run
    ever recorded against v1 stays exactly reproducible."""
    price = Decimal(1000)
    small = slipped_price(
        price, direction="buy", params=COST_MODEL_V1, participation_fraction=Decimal("0.01")
    )
    large = slipped_price(
        price, direction="buy", params=COST_MODEL_V1, participation_fraction=Decimal("1")
    )
    unset = slipped_price(price, direction="buy", params=COST_MODEL_V1, participation_fraction=None)
    assert small == large == unset


def test_v2_slippage_is_convex_in_participation_fraction() -> None:
    """RED_TEAM_REPORT.md finding #5: a trade at the participation cap must pay strictly more
    slippage (as a %) than a negligibly small one under the same cost model."""
    price = Decimal(1000)
    tiny = slipped_price(
        price, direction="buy", params=COST_MODEL_V2, participation_fraction=Decimal("0.001")
    )
    at_cap = slipped_price(
        price, direction="buy", params=COST_MODEL_V2, participation_fraction=Decimal("1")
    )
    baseline = slipped_price(
        price, direction="buy", params=COST_MODEL_V2, participation_fraction=None
    )
    assert baseline < tiny < at_cap
    # exact: coefficient=1 -> bps_effective = 5 * (1 + 1*1) = 10 bps at fraction=1
    assert at_cap == price + price * Decimal(10) / Decimal(10_000)


def test_v2_participation_fraction_is_clamped_to_zero_and_one() -> None:
    price = Decimal(1000)
    negative = slipped_price(
        price, direction="buy", params=COST_MODEL_V2, participation_fraction=Decimal("-5")
    )
    zero = slipped_price(
        price, direction="buy", params=COST_MODEL_V2, participation_fraction=Decimal("0")
    )
    over_cap = slipped_price(
        price, direction="buy", params=COST_MODEL_V2, participation_fraction=Decimal("50")
    )
    at_cap = slipped_price(
        price, direction="buy", params=COST_MODEL_V2, participation_fraction=Decimal("1")
    )
    assert negative == zero
    assert over_cap == at_cap
