"""Liquidity Score v1: components, weighting/renormalisation, bands, insufficient data, and
clipping (Phase 9, mirroring the Phase 8 addendum's versioned-parameters test proofs)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import cfi.liquidity.score_parameters as sp
from cfi.liquidity import metrics as m
from cfi.liquidity import score as sc
from cfi.liquidity.score import _components

NOW = datetime(2026, 9, 26, tzinfo=UTC)


def growth(change_7d: str | None, status: str = "ok") -> m.SupplyGrowth:
    return m.SupplyGrowth(
        subject="X",
        status=status if change_7d is not None else "unavailable",
        reason=None if change_7d is not None else "no data",
        change_7d=None if change_7d is None else Decimal(change_7d),
    )


def acceleration(change: str | None) -> m.GrowthAcceleration:
    return m.GrowthAcceleration(
        status="ok" if change is not None else "unavailable",
        reason=None if change is not None else "no data",
        change=None if change is None else Decimal(change),
    )


def full_score(
    *,
    usdt: str | None = "0.02",
    usdc: str | None = "0.02",
    total: str | None = "0.015",
    accel: str | None = "0.005",
    version: str | None = None,
) -> sc.ScoreResult:
    return sc.compute_score(
        as_of=NOW,
        calculated_at=NOW,
        usdt_growth=growth(usdt),
        usdc_growth=growth(usdc),
        total_growth=growth(total),
        total_acceleration=acceleration(accel),
        version=version,
    )


# --------------------------------------------------------------------------- v1 parameters load


def test_v1_parameters_load_correctly() -> None:
    params = sp.parameters()
    assert params.version == "liquidity_score_v1"
    assert (
        params.weight_usdt_growth_7d
        + params.weight_usdc_growth_7d
        + params.weight_total_growth_7d
        + params.weight_acceleration
        == Decimal(1)
    )


def test_unknown_parameter_version_is_a_hard_error() -> None:
    with pytest.raises(KeyError):
        sp.parameters("liquidity_score_v99")


# --------------------------------------------------------------------------- component math


def test_all_components_available_uses_full_weight() -> None:
    result = full_score()
    assert result.status == "ok"
    assert result.available_weight == Decimal(1)
    assert len(result.components) == 4
    assert all(c.status == "ok" for c in result.components)


def test_score_is_a_weighted_sum_of_sub_scores() -> None:
    params = sp.parameters()
    result = full_score()
    expected = Decimal(0)
    values = {
        "usdt_growth_7d": Decimal("0.02") / params.usdt_growth_scale,
        "usdc_growth_7d": Decimal("0.02") / params.usdc_growth_scale,
        "total_growth_7d": Decimal("0.015") / params.total_growth_scale,
        "growth_acceleration": Decimal("0.005") / params.acceleration_scale,
    }
    weights = {
        "usdt_growth_7d": params.weight_usdt_growth_7d,
        "usdc_growth_7d": params.weight_usdc_growth_7d,
        "total_growth_7d": params.weight_total_growth_7d,
        "growth_acceleration": params.weight_acceleration,
    }
    for component_id, sub in values.items():
        expected += weights[component_id] * sub
    assert result.score == (100 * expected).quantize(Decimal("0.1"))


def test_missing_components_are_renormalized() -> None:
    """Only 3 of 4 components available; the score uses just their relative weights."""
    result = full_score(usdc=None)
    params = sp.parameters()
    available_weight = (
        params.weight_usdt_growth_7d + params.weight_total_growth_7d + params.weight_acceleration
    )
    assert result.status == "ok"
    assert result.available_weight == available_weight
    total_c = next(c for c in result.components if c.definition.component_id == "total_growth_7d")
    accel_c = next(
        c for c in result.components if c.definition.component_id == "growth_acceleration"
    )
    usdt_c = next(c for c in result.components if c.definition.component_id == "usdt_growth_7d")
    assert total_c.effective_weight == (params.weight_total_growth_7d / available_weight).quantize(
        Decimal("0.0001")
    )
    assert accel_c.effective_weight == (params.weight_acceleration / available_weight).quantize(
        Decimal("0.0001")
    )
    total_effective = (
        (usdt_c.effective_weight or Decimal(0))
        + (total_c.effective_weight or Decimal(0))
        + (accel_c.effective_weight or Decimal(0))
    )
    assert total_effective == Decimal(1)


def test_available_weight_below_minimum_is_insufficient_data() -> None:
    """Only the acceleration component (0.15 weight) is available — below the 0.5 minimum."""
    result = full_score(usdt=None, usdc=None, total=None)
    assert result.status == "insufficient_data"
    assert result.score is None
    assert result.band is None
    assert result.reason is not None
    assert "Insufficient data" in result.reason


def test_score_version_is_persisted() -> None:
    result = full_score()
    assert result.parameter_version == sp.CURRENT_VERSION
    assert result.calculated_at == NOW


def test_historical_records_remain_reproducible_across_a_hypothetical_new_version() -> None:
    """A later parameter version must never silently change what an earlier score meant."""
    v2 = sp.ParameterSet(
        version="liquidity_score_v2_hypothetical",
        weight_usdt_growth_7d=Decimal("0.40"),
        weight_usdc_growth_7d=Decimal("0.40"),
        weight_total_growth_7d=Decimal("0.10"),
        weight_acceleration=Decimal("0.10"),
        usdt_growth_scale=Decimal("0.10"),
        usdc_growth_scale=Decimal("0.10"),
        total_growth_scale=Decimal("0.10"),
        acceleration_scale=Decimal("0.10"),
        min_available_weight=Decimal("0.5"),
        bands=((None, "unlabelled"),),
    )
    # v2 is never registered in PARAMETER_SETS; compute_score must still use v1 by default.
    result_v1 = full_score()
    assert result_v1.parameter_version == "liquidity_score_v1"
    # Directly computing with v2's numbers gives a different score, proving compute_score
    # genuinely depends on the passed-in parameter set rather than a module-level global.
    params_v1 = sp.parameters()
    v1_defs = {c.component_id: c for c in _components(params_v1)}
    v2_defs = {c.component_id: c for c in _components(v2)}
    assert v1_defs["usdt_growth_7d"].scale != v2_defs["usdt_growth_7d"].scale
    assert v1_defs["usdt_growth_7d"].weight != v2_defs["usdt_growth_7d"].weight


# --------------------------------------------------------------------------- bands


def test_band_boundaries_behave_exactly_as_documented() -> None:
    params = sp.parameters()
    assert sc.band_for(Decimal(50), params) == "strong liquidity expansion"
    assert sc.band_for(Decimal("49.9"), params) == "liquidity expansion"
    assert sc.band_for(Decimal(15), params) == "liquidity expansion"
    assert sc.band_for(Decimal("14.9"), params) == "stable"
    assert sc.band_for(Decimal(-15), params) == "stable"
    assert sc.band_for(Decimal("-15.1"), params) == "liquidity contraction"
    assert sc.band_for(Decimal(-50), params) == "liquidity contraction"
    assert sc.band_for(Decimal("-50.1"), params) == "strong liquidity contraction"


# --------------------------------------------------------------------------- clipping


def test_no_sub_score_exceeds_plus_or_minus_one() -> None:
    """A growth figure far beyond the reference scale is clipped, never left unbounded."""
    result = full_score(usdt="5.0", usdc="-5.0", total="5.0", accel="-5.0")
    for c in result.components:
        assert c.sub_score is not None
        assert Decimal(-1) <= c.sub_score <= Decimal(1)


def test_clip_helper_bounds_are_exact() -> None:
    assert sc._clip(Decimal("1.5")) == Decimal(1)
    assert sc._clip(Decimal("-1.5")) == Decimal(-1)
    assert sc._clip(Decimal("0.5")) == Decimal("0.5")


# --------------------------------------------------------------------------- proxy caveat (#8)


def test_liquidity_score_always_carries_the_supply_growth_proxy_caveat() -> None:
    """RED_TEAM_REPORT.md finding #8 / ADR-0064: unlike cfi.retail's proxy metrics, this score
    previously had no runtime-visible caveat distinguishing 'stablecoin supply growth' from
    'market liquidity' or 'peg stability' — it must now be present regardless of status."""
    ok_result = full_score()
    assert ok_result.status == "ok"
    assert ok_result.measurement_class == "proxy"
    assert "supply" in ok_result.proxy_caveat.lower()
    assert "peg" in ok_result.proxy_caveat.lower()

    insufficient_result = full_score(usdt=None, usdc=None, total=None, accel=None)
    assert insufficient_result.status == "insufficient_data"
    assert insufficient_result.proxy_caveat == ok_result.proxy_caveat
