"""Market Structure Score v1: parameter loading, weighted combination, renormalisation,
insufficient-data floor, bands, clipping, and the inverted-direction volatility component
(Phase 12)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import cfi.market_structure.score_parameters as sp
from cfi.market_structure import metrics as m
from cfi.market_structure import score as sc

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def ma(
    close: str | None = "200", sma200: str | None = "200", status: m.Status = "ok"
) -> m.MovingAverageReading:
    if status != "ok":
        return m.MovingAverageReading(status=status, reason="no reading")
    return m.MovingAverageReading(
        status="ok",
        close=None if close is None else Decimal(close),
        sma200=None if sma200 is None else Decimal(sma200),
    )


def rsi(value: str | None = "50", status: m.Status = "ok") -> m.RsiReading:
    if status != "ok":
        return m.RsiReading(status=status, reason="no reading")
    return m.RsiReading(status="ok", value=None if value is None else Decimal(value))


def breadth(fraction: str | None = "0.5", status: m.Status = "ok") -> m.BreadthReading:
    if status != "ok":
        return m.BreadthReading(status=status, reason="no reading")
    return m.BreadthReading(status="ok", fraction=None if fraction is None else Decimal(fraction))


def rs(spread: str, status: m.Status = "ok") -> m.RelativeStrengthReading:
    if status != "ok":
        return m.RelativeStrengthReading(status=status, reason="no reading")
    return m.RelativeStrengthReading(status="ok", spread_pp=Decimal(spread))


def vol(percentile: str | None = "50", status: m.Status = "ok") -> m.VolatilityReading:
    if status != "ok":
        return m.VolatilityReading(status=status, reason="no reading")
    return m.VolatilityReading(
        status="ok", percentile=None if percentile is None else Decimal(percentile)
    )


def full_score(
    *,
    close: str | None = "200",
    sma200: str | None = "200",
    rsi_value: str | None = "50",
    breadth_fraction: str | None = "0.5",
    altcoin_spreads: list[str] | None = None,
    vol_percentile: str | None = "50",
) -> sc.ScoreResult:
    # Two readings by default: finding #6 (ADR-0063) requires at least MIN_ALTCOIN_COUNT (2)
    # available altcoin readings before this component counts as "ok".
    spreads = ["0.00", "0.00"] if altcoin_spreads is None else altcoin_spreads
    return sc.compute_score(
        as_of=NOW,
        calculated_at=NOW,
        price_trend=ma(close, sma200),
        momentum=rsi(rsi_value),
        breadth=breadth(breadth_fraction),
        altcoin_relative_strength=[rs(s) for s in spreads],
        volatility_regime=vol(vol_percentile),
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
        params.weight_price_trend
        + params.weight_momentum
        + params.weight_breadth
        + params.weight_altcoin_relative_strength
        + params.weight_volatility_regime
    )
    assert total == Decimal("1.00")


# --------------------------------------------------------------------------- full-weight scoring


def test_full_weight_neutral_inputs_score_near_zero() -> None:
    result = full_score()
    assert result.status == "ok"
    assert result.available_weight == Decimal("1.00")
    assert result.score == Decimal("0.0")
    assert result.band == "neutral / mixed technical structure"


def test_constructive_inputs_produce_a_positive_score() -> None:
    result = full_score(
        close="240",  # 20% above SMA200 -> +1 sub-score (scale 0.20)
        rsi_value="100",  # +50 from neutral -> +1 (scale 50)
        breadth_fraction="1.0",  # +0.5 from neutral -> +1 (scale 0.5)
        altcoin_spreads=["0.15", "0.15"],  # +1 (scale 0.15); 2 readings to clear MIN_ALTCOIN_COUNT
        vol_percentile="0",  # -50 from neutral, inverted -> +1 (scale 50)
    )
    assert result.status == "ok"
    assert result.score == Decimal("100.0")
    assert result.band == "broadly constructive technical structure"


def test_deteriorated_inputs_produce_a_negative_score() -> None:
    result = full_score(
        close="160",  # 20% below SMA200 -> -1
        rsi_value="0",  # -50 from neutral -> -1
        breadth_fraction="0.0",  # -1
        altcoin_spreads=["-0.15", "-0.15"],  # -1; 2 readings to clear MIN_ALTCOIN_COUNT
        vol_percentile="100",  # +50 from neutral, inverted -> -1
    )
    assert result.status == "ok"
    assert result.score == Decimal("-100.0")
    assert result.band == "broadly weak technical structure"


def test_sub_scores_are_clipped_beyond_the_scale() -> None:
    result = full_score(close="1000", sma200="200")  # far beyond the 0.20 scale
    component = next(c for c in result.components if c.definition.component_id == "price_trend")
    assert component.sub_score == Decimal("1.0000")


def test_altcoin_relative_strength_averages_available_readings() -> None:
    result = full_score(altcoin_spreads=["0.15", "-0.15", "0.15"])
    component = next(
        c for c in result.components if c.definition.component_id == "altcoin_relative_strength"
    )
    assert component.status == "ok"
    assert component.value == Decimal("0.05").quantize(Decimal("0.000001"))


def test_altcoin_relative_strength_uses_only_available_readings() -> None:
    """2 of 3 available (ETH/SOL ok, XRP unavailable) still clears MIN_ALTCOIN_COUNT (2)."""
    result = sc.compute_score(
        as_of=NOW,
        calculated_at=NOW,
        price_trend=ma(),
        momentum=rsi(),
        breadth=breadth(),
        altcoin_relative_strength=[rs("0.15"), rs("0.05"), rs("0", status="unavailable")],
        volatility_regime=vol(),
    )
    component = next(
        c for c in result.components if c.definition.component_id == "altcoin_relative_strength"
    )
    assert component.status == "ok"
    assert component.value == Decimal("0.10").quantize(Decimal("0.000001"))


def test_altcoin_relative_strength_is_unavailable_below_min_altcoin_count() -> None:
    """RED_TEAM_REPORT.md finding #6 / ADR-0063: only 1 of 3 altcoins available must NOT be
    silently averaged and reported "ok" at the full 0.20 weight from a single asset."""
    result = sc.compute_score(
        as_of=NOW,
        calculated_at=NOW,
        price_trend=ma(),
        momentum=rsi(),
        breadth=breadth(),
        altcoin_relative_strength=[
            rs("0.15"),
            rs("0", status="unavailable"),
            rs("0", status="unavailable"),
        ],
        volatility_regime=vol(),
    )
    component = next(
        c for c in result.components if c.definition.component_id == "altcoin_relative_strength"
    )
    assert component.status == "unavailable"
    assert component.value is None
    assert "1 of 3" in (component.reason or "")
    # The score renormalizes over the remaining 0.80 weight, exactly like any other missing
    # component (breadth, volatility, ...) rather than treating this one specially.
    assert result.status == "ok"
    assert (
        result.available_weight
        == Decimal("1.00") - sp.parameters().weight_altcoin_relative_strength
    )


# --------------------------------------------------------------------------- renormalisation


def test_renormalizes_when_one_component_is_unavailable() -> None:
    """Only breadth is missing; the remaining 0.80 weight clears the 0.5 minimum, so the score
    renormalizes rather than going insufficient."""
    result = full_score(breadth_fraction=None)
    params = sp.parameters()
    expected_weight = Decimal("1.00") - params.weight_breadth
    assert result.status == "ok"
    assert result.available_weight == expected_weight
    breadth_component = next(
        c for c in result.components if c.definition.component_id == "market_breadth"
    )
    assert breadth_component.status == "unavailable"


def test_insufficient_data_when_available_weight_below_minimum() -> None:
    """Dropping three of the five components (weight 0.25+0.20+0.20 = 0.65 missing) leaves only
    0.35 available, below the 0.5 minimum."""
    result = full_score(close=None, rsi_value=None, breadth_fraction=None)
    assert result.status == "insufficient_data"
    assert result.score is None
    assert result.band is None
    assert result.reason is not None


# --------------------------------------------------------------------------- component statuses


def test_unavailable_component_carries_its_reason() -> None:
    result = sc.compute_score(
        as_of=NOW,
        calculated_at=NOW,
        price_trend=ma(),
        momentum=rsi(),
        breadth=breadth(),
        altcoin_relative_strength=[rs("0", status="unavailable")],
        volatility_regime=vol(status="unavailable"),
    )
    vol_component = next(
        c for c in result.components if c.definition.component_id == "volatility_regime"
    )
    assert vol_component.status == "unavailable"
    assert vol_component.value is None
    assert vol_component.sub_score is None

    altcoin_component = next(
        c for c in result.components if c.definition.component_id == "altcoin_relative_strength"
    )
    assert altcoin_component.status == "unavailable"
