"""Macro Environment Score v1: parameter loading, weighted combination, renormalisation,
insufficient-data floor, bands, clipping, and inverted-direction components (Phase 11)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import cfi.macro.score_parameters as sp
from cfi.macro import metrics as m
from cfi.macro import score as sc

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def yc(slope: str | None = "0.50", status: str = "ok") -> m.YieldCurveReading:
    if status != "ok":
        return m.YieldCurveReading(status=status, reason="no reading")
    slope_pp = None if slope is None else Decimal(slope)
    return m.YieldCurveReading(status="ok", reason=None, slope_pp=slope_pp)


def real_rate(value: str | None = "0.00", status: str = "ok") -> m.RealPolicyRateReading:
    if status != "ok":
        return m.RealPolicyRateReading(status=status, reason="no reading")
    real_rate_pp = None if value is None else Decimal(value)
    return m.RealPolicyRateReading(status="ok", reason=None, real_rate_pp=real_rate_pp)


def vix(value: str | None = "20", status: str = "ok") -> m.VixReading:
    if status != "ok":
        return m.VixReading(status=status, reason="no reading")
    return m.VixReading(status="ok", reason=None, value=None if value is None else Decimal(value))


def trend(metric: str, change: str | None = "0.00", status: str = "ok") -> m.TrendReading:
    if status != "ok":
        return m.TrendReading(metric=metric, status=status, reason="no reading")
    change_pct = None if change is None else Decimal(change)
    return m.TrendReading(metric=metric, status="ok", reason=None, change_pct=change_pct)


def full_score(
    *,
    yield_curve: str | None = "0.00",
    real_rate_pp: str | None = "0.00",
    vix_value: str | None = "20",
    equity: str | None = "0.00",
    dollar: str | None = "0.00",
    net_liquidity: str | None = "0.00",
    oil: str | None = "0.00",
) -> sc.ScoreResult:
    return sc.compute_score(
        as_of=NOW,
        calculated_at=NOW,
        yield_curve=yc(yield_curve),
        real_policy_rate=real_rate(real_rate_pp),
        vix=vix(vix_value),
        equity_trend=trend("sp500", equity),
        dollar_trend=trend("dxy", dollar),
        net_liquidity_trend=trend("net_liquidity", net_liquidity),
        oil_trend=trend("oil", oil),
    )


# --------------------------------------------------------------------------- parameters


def test_parameters_default_version_is_current() -> None:
    params = sp.parameters()
    assert params.version == sp.CURRENT_VERSION


def test_parameters_unknown_version_raises() -> None:
    with pytest.raises(KeyError):
        sp.parameters("does_not_exist")


def test_component_weights_sum_to_one() -> None:
    params = sp.parameters()
    total = (
        params.weight_yield_curve
        + params.weight_real_policy_rate
        + params.weight_vix
        + params.weight_equity_trend
        + params.weight_dollar_trend
        + params.weight_net_liquidity_trend
        + params.weight_oil_trend
    )
    assert total == Decimal("1.00")


# --------------------------------------------------------------------------- full-weight scoring


def test_full_weight_neutral_inputs_score_near_zero() -> None:
    result = full_score()
    assert result.status == "ok"
    assert result.available_weight == Decimal("1.00")
    assert result.score == Decimal("0.0")
    assert result.band == "neutral / mixed macro backdrop"


def test_accommodative_inputs_produce_a_positive_score() -> None:
    result = full_score(
        yield_curve="1.00",  # steep -> +1 sub-score
        real_rate_pp="-2.00",  # negative real rate -> +1 (inverted direction)
        vix_value="10",  # calm, 10 below reference of 20 -> +1 (inverted direction)
        equity="0.10",  # rising equities -> +1
        dollar="-0.05",  # weakening dollar -> +1 (inverted direction)
        net_liquidity="0.05",  # expanding liquidity -> +1
        oil="-0.15",  # falling oil -> +1 (inverted direction)
    )
    assert result.status == "ok"
    assert result.score == Decimal("100.0")
    assert result.band == "broadly accommodative macro backdrop"


def test_restrictive_inputs_produce_a_negative_score() -> None:
    result = full_score(
        yield_curve="-1.00",
        real_rate_pp="2.00",
        vix_value="30",
        equity="-0.10",
        dollar="0.05",
        net_liquidity="-0.05",
        oil="0.15",
    )
    assert result.status == "ok"
    assert result.score == Decimal("-100.0")
    assert result.band == "broadly restrictive macro backdrop"


def test_sub_scores_are_clipped_beyond_the_scale() -> None:
    result = full_score(yield_curve="5.00")  # far beyond the 1.00 pp scale
    component = next(
        c for c in result.components if c.definition.component_id == "yield_curve_slope"
    )
    assert component.sub_score == Decimal("1.0000")


# --------------------------------------------------------------------------- renormalisation


def test_renormalizes_when_one_component_is_unavailable() -> None:
    """Only the yield curve is missing; the remaining 0.80 weight clears the 0.5 minimum, so the
    score renormalizes rather than going insufficient."""
    result = full_score(yield_curve=None)
    params = sp.parameters()
    expected_weight = Decimal("1.00") - params.weight_yield_curve
    assert result.status == "ok"
    assert result.available_weight == expected_weight
    yc_component = next(
        c for c in result.components if c.definition.component_id == "yield_curve_slope"
    )
    assert yc_component.status == "unavailable"


def test_insufficient_data_when_available_weight_below_minimum() -> None:
    """Dropping four of the seven components (weight 0.20+0.20+0.15+0.15 = 0.70 missing) leaves
    only 0.30 available, below the 0.5 minimum."""
    result = full_score(yield_curve=None, real_rate_pp=None, vix_value=None, equity=None)
    assert result.status == "insufficient_data"
    assert result.score is None
    assert result.band is None
    assert result.reason is not None


# --------------------------------------------------------------------------- component statuses


def test_unavailable_component_carries_its_reason() -> None:
    result = sc.compute_score(
        as_of=NOW,
        calculated_at=NOW,
        yield_curve=yc(),
        real_policy_rate=real_rate(),
        vix=vix(),
        equity_trend=trend("sp500"),
        dollar_trend=trend("dxy"),
        net_liquidity_trend=trend("net_liquidity"),
        oil_trend=trend("oil", status="unavailable"),
    )
    oil_component = next(c for c in result.components if c.definition.component_id == "oil_trend")
    assert oil_component.status == "unavailable"
    assert oil_component.reason == "no reading"
    assert oil_component.value is None
    assert oil_component.sub_score is None
