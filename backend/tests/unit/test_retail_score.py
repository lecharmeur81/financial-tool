"""Retail Activity Score and Retail Speculation Score v1: parameter loading, weighted combination,
renormalisation, insufficient-data floor, bands, clipping, and the meme-trending component's
always-nonnegative (non-directional) behaviour (Phase 10)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import cfi.retail.score_parameters as sp
from cfi.retail import metrics as m
from cfi.retail import score as sc

NOW = datetime(2026, 9, 26, tzinfo=UTC)


def percentile(value: str | None, sample_size: int = 30) -> m.PercentileResult:
    if value is None:
        return m.PercentileResult(status="insufficient_history", reason="no data", sample_size=0)
    return m.PercentileResult(
        status="ok", value=Decimal(value), percentile=Decimal(value), sample_size=sample_size
    )


def full_activity_score(
    *, small_tx: str | None = "70", meme: str | None = "40", deriv_turnover: str | None = "60"
) -> sc.ScoreResult:
    return sc.compute_activity_score(
        as_of=NOW,
        calculated_at=NOW,
        small_tx_percentile=percentile(small_tx),
        meme_trending_percentile=percentile(meme),
        derivatives_turnover_percentile=percentile(deriv_turnover),
    )


def derivatives_proxy(
    *, funding: str | None = "0.0002", ratio: str | None = "1.10", status: str = "ok"
) -> m.DerivativesProxy:
    if status != "ok":
        return m.DerivativesProxy(status=status, reason="no reading")
    return m.DerivativesProxy(
        status="ok",
        assets_used=("BTC",),
        funding_rate_avg=None if funding is None else Decimal(funding),
        account_ratio_avg=None if ratio is None else Decimal(ratio),
        funding_condition="unknown",
        ratio_condition="unknown",
    )


def meme_activity(count: int | None) -> m.MemeCoinActivity:
    if count is None:
        return m.MemeCoinActivity(status="unavailable", reason="no snapshot")
    return m.MemeCoinActivity(
        status="ok", as_of_snapshot=NOW, trending_meme_coins=(), meme_coins_trending_count=count
    )


def full_speculation_score(
    *,
    funding: str | None = "0.0002",
    ratio: str | None = "1.10",
    deriv_status: str = "ok",
    meme_count: int | None = 1,
) -> sc.ScoreResult:
    return sc.compute_speculation_score(
        as_of=NOW,
        calculated_at=NOW,
        derivatives=derivatives_proxy(funding=funding, ratio=ratio, status=deriv_status),
        meme_activity=meme_activity(meme_count),
    )


# --------------------------------------------------------------------------- parameter loading


def test_activity_v1_parameters_load_and_weights_sum_to_one() -> None:
    params = sp.activity_parameters()
    assert params.version == "retail_activity_score_v1"
    assert (
        params.weight_small_tx_percentile
        + params.weight_meme_trending_percentile
        + params.weight_derivatives_turnover_percentile
        == Decimal(1)
    )


def test_speculation_v1_parameters_load_and_weights_sum_to_one() -> None:
    params = sp.speculation_parameters()
    assert params.version == "retail_speculation_score_v1"
    assert (
        params.weight_funding_rate_bias
        + params.weight_account_ratio_skew
        + params.weight_meme_trending
        == Decimal(1)
    )


def test_unknown_activity_parameter_version_is_a_hard_error() -> None:
    with pytest.raises(KeyError):
        sp.activity_parameters("retail_activity_score_v99")


def test_unknown_speculation_parameter_version_is_a_hard_error() -> None:
    with pytest.raises(KeyError):
        sp.speculation_parameters("retail_speculation_score_v99")


# --------------------------------------------------------------------------- activity score math


def test_activity_score_all_components_available_uses_full_weight() -> None:
    result = full_activity_score()
    assert result.status == "ok"
    assert result.available_weight == Decimal(1)
    assert len(result.components) == 3
    assert all(c.status == "ok" for c in result.components)
    assert result.score_id == sc.ACTIVITY_SCORE_ID


def test_activity_score_is_weighted_average_of_percentiles() -> None:
    params = sp.activity_parameters()
    result = full_activity_score(small_tx="70", meme="40", deriv_turnover="60")
    expected = (
        params.weight_small_tx_percentile * Decimal("0.70")
        + params.weight_meme_trending_percentile * Decimal("0.40")
        + params.weight_derivatives_turnover_percentile * Decimal("0.60")
    )
    assert result.score == (100 * expected).quantize(Decimal("0.1"))


def test_activity_score_renormalizes_when_a_component_is_missing() -> None:
    result = full_activity_score(meme=None)
    params = sp.activity_parameters()
    available_weight = (
        params.weight_small_tx_percentile + params.weight_derivatives_turnover_percentile
    )
    assert result.status == "ok"
    assert result.available_weight == available_weight
    meme_c = next(
        c for c in result.components if c.definition.component_id == "meme_trending_percentile"
    )
    assert meme_c.status == "unavailable"
    assert meme_c.reason == "no data"


def test_activity_score_insufficient_data_below_minimum_weight() -> None:
    """Only derivatives_turnover (weight 0.35) available — below the 0.5 minimum."""
    result = full_activity_score(small_tx=None, meme=None, deriv_turnover="60")
    assert result.status == "insufficient_data"
    assert result.score is None
    assert result.band is None
    assert result.reason is not None
    assert "Insufficient data" in result.reason


def test_activity_score_version_is_persisted() -> None:
    result = full_activity_score()
    assert result.parameter_version == sp.CURRENT_ACTIVITY_VERSION
    assert result.calculated_at == NOW


def test_activity_score_band_boundaries() -> None:
    params = sp.activity_parameters()
    assert sc.band_for(Decimal(80), params.bands) == "elevated retail-proxy activity"
    assert sc.band_for(Decimal("79.9"), params.bands) == "above-normal retail-proxy activity"
    assert sc.band_for(Decimal(60), params.bands) == "above-normal retail-proxy activity"
    assert sc.band_for(Decimal("59.9"), params.bands) == "typical retail-proxy activity"
    assert sc.band_for(Decimal(40), params.bands) == "typical retail-proxy activity"
    assert sc.band_for(Decimal("39.9"), params.bands) == "below-normal retail-proxy activity"
    assert sc.band_for(Decimal(20), params.bands) == "below-normal retail-proxy activity"
    assert sc.band_for(Decimal("19.9"), params.bands) == "quiet retail-proxy activity"


# --------------------------------------------------------------------------- speculation score math


def test_speculation_score_all_components_available_uses_full_weight() -> None:
    result = full_speculation_score()
    assert result.status == "ok"
    assert result.available_weight == Decimal(1)
    assert len(result.components) == 3
    assert result.score_id == sc.SPECULATION_SCORE_ID


def test_speculation_score_is_weighted_sum_of_clipped_sub_scores() -> None:
    params = sp.speculation_parameters()
    result = full_speculation_score(funding="0.0002", ratio="1.10", meme_count=1)
    funding_sub = Decimal("0.0002") / params.funding_rate_scale
    ratio_sub = (Decimal("1.10") - 1) / params.account_ratio_skew_scale
    meme_sub = Decimal(1) / params.meme_trending_scale
    expected = (
        params.weight_funding_rate_bias * funding_sub
        + params.weight_account_ratio_skew * ratio_sub
        + params.weight_meme_trending * meme_sub
    )
    assert result.score == (100 * expected).quantize(Decimal("0.1"))


def test_speculation_score_renormalizes_when_funding_component_is_missing() -> None:
    """Only funding is missing (ratio and meme still available) — weight 0.60 clears the 0.4
    minimum, so the score renormalizes rather than going insufficient."""
    result = full_speculation_score(funding=None, ratio="1.10", meme_count=1)
    params = sp.speculation_parameters()
    available_weight = params.weight_account_ratio_skew + params.weight_meme_trending
    assert result.status == "ok"
    assert result.available_weight == available_weight
    funding_c = next(
        c for c in result.components if c.definition.component_id == "funding_rate_bias"
    )
    assert funding_c.status == "unavailable"


def test_speculation_score_insufficient_data_below_minimum_weight() -> None:
    """Only meme_trending (weight 0.20) available — below the 0.4 minimum."""
    result = full_speculation_score(deriv_status="unavailable", meme_count=2)
    assert result.status == "insufficient_data"
    assert result.score is None


def test_speculation_score_meme_component_is_never_negative() -> None:
    """Zero meme coins trending contributes a neutral 0, never a negative reading."""
    result = full_speculation_score(meme_count=0)
    meme_c = next(c for c in result.components if c.definition.component_id == "meme_trending")
    assert meme_c.status == "ok"
    assert meme_c.sub_score == Decimal(0)
    assert meme_c.definition.directional is False


def test_speculation_score_meme_component_is_clipped_at_one_even_with_a_huge_count() -> None:
    result = full_speculation_score(meme_count=999)
    meme_c = next(c for c in result.components if c.definition.component_id == "meme_trending")
    assert meme_c.sub_score == Decimal(1)


def test_speculation_score_other_components_are_directional_by_default() -> None:
    result = full_speculation_score()
    funding_c = next(
        c for c in result.components if c.definition.component_id == "funding_rate_bias"
    )
    ratio_c = next(
        c for c in result.components if c.definition.component_id == "account_ratio_skew"
    )
    assert funding_c.definition.directional is True
    assert ratio_c.definition.directional is True


def test_speculation_score_version_is_persisted() -> None:
    result = full_speculation_score()
    assert result.parameter_version == sp.CURRENT_SPECULATION_VERSION
    assert result.calculated_at == NOW


def test_speculation_score_band_boundaries() -> None:
    params = sp.speculation_parameters()
    assert sc.band_for(Decimal(50), params.bands) == "strong long-biased speculative skew"
    assert sc.band_for(Decimal("49.9"), params.bands) == "long-biased speculative skew"
    assert sc.band_for(Decimal(15), params.bands) == "long-biased speculative skew"
    assert sc.band_for(Decimal("14.9"), params.bands) == "balanced"
    assert sc.band_for(Decimal(-15), params.bands) == "balanced"
    assert sc.band_for(Decimal("-15.1"), params.bands) == "short-biased speculative skew"
    assert sc.band_for(Decimal(-50), params.bands) == "short-biased speculative skew"
    assert sc.band_for(Decimal("-50.1"), params.bands) == "strong short-biased speculative skew"


# --------------------------------------------------------------------------- clipping


def test_directional_sub_scores_are_clipped_to_plus_or_minus_one() -> None:
    result = full_speculation_score(funding="5.0", ratio="500")
    for c in result.components:
        if c.sub_score is not None:
            assert Decimal(-1) <= c.sub_score <= Decimal(1)


def test_clip_helper_bounds_are_exact() -> None:
    assert sc._clip(Decimal("1.5")) == Decimal(1)
    assert sc._clip(Decimal("-1.5")) == Decimal(-1)
    assert sc._clip(Decimal("0.5")) == Decimal("0.5")


# --------------------------------------------------------------------------- shared-input notes


def test_speculation_score_discloses_the_shared_funding_rate_input() -> None:
    """RED_TEAM_REPORT.md finding #7 / ADR-0064: the overlap with Derivatives Health Score's
    funding component must be runtime-visible, not just documented in a docstring."""
    result = full_speculation_score()
    assert result.shared_input_note is not None
    assert "Derivatives Health" in result.shared_input_note
    assert "funding" in result.shared_input_note.lower()


def test_activity_score_carries_no_shared_input_note() -> None:
    """The shared-input overlap is specific to the Speculation score's funding component; the
    Activity score has no such overlap and must not carry a fabricated one."""
    result = full_activity_score()
    assert result.shared_input_note is None
