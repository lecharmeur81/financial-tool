"""Unit tests for cfi.similarity.parameters — version resolution, weight integrity, and the
normalization function's fixed, data-independent bounds."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cfi.similarity import parameters as sp


def test_current_version_resolves_and_unknown_version_raises_keyerror() -> None:
    params = sp.parameters()
    assert params.version == sp.CURRENT_VERSION
    assert sp.parameters("similarity_v1").version == "similarity_v1"
    with pytest.raises(KeyError):
        sp.parameters("no-such-version")


def test_feature_weights_sum_to_one() -> None:
    params = sp.parameters()
    assert sum(f.weight for f in params.features) == Decimal("1.00")


def test_nine_features_matching_the_spec() -> None:
    params = sp.parameters()
    ids = {f.feature_id for f in params.features}
    assert ids == {
        "institutional_score",
        "whale_score",
        "retail_activity_score",
        "liquidity_score",
        "funding_annualised_7d_pct",
        "oi_change_7d_pct",
        "volatility_percentile",
        "market_structure_score",
        "macro_score",
    }


def test_clamp_linear_features_have_bounds_and_others_do_not() -> None:
    params = sp.parameters()
    for f in params.features:
        if f.normalization == "clamp_linear":
            assert f.clamp_min is not None
            assert f.clamp_max is not None
            assert f.clamp_min < f.clamp_max
        else:
            assert f.clamp_min is None
            assert f.clamp_max is None


def test_normalize_identity_passes_through() -> None:
    f = next(f for f in sp.parameters().features if f.normalization == "identity_0_100")
    assert sp.normalize(Decimal("37.4"), f) == Decimal("37.4")


def test_normalize_shift_pm100_maps_range_to_0_100() -> None:
    f = next(f for f in sp.parameters().features if f.normalization == "shift_pm100_to_0_100")
    assert sp.normalize(Decimal("-100"), f) == Decimal("0")
    assert sp.normalize(Decimal("0"), f) == Decimal("50")
    assert sp.normalize(Decimal("100"), f) == Decimal("100")


def test_normalize_clamp_linear_clamps_outside_bounds_and_scales_inside() -> None:
    f = next(f for f in sp.parameters().features if f.feature_id == "funding_annualised_7d_pct")
    assert f.clamp_min is not None
    assert f.clamp_max is not None
    assert sp.normalize(f.clamp_min, f) == Decimal("0")
    assert sp.normalize(f.clamp_max, f) == Decimal("100")
    # Way outside the documented bounds — clamped, never extrapolated beyond 0..100.
    assert sp.normalize(f.clamp_min - 1000, f) == Decimal("0")
    assert sp.normalize(f.clamp_max + 1000, f) == Decimal("100")
    midpoint = (f.clamp_min + f.clamp_max) / 2
    assert sp.normalize(midpoint, f) == Decimal("50")
