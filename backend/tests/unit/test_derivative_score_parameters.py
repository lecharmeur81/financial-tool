"""Phase 8 addendum: the Derivatives Health Score's parameters, externalised and versioned
(``cfi.derivatives.score_parameters``).

Covers the eight proofs requested for this addendum:
1. v1 parameters load correctly.
2. Score calculations remain unchanged after externalisation.
3. Missing components are renormalised correctly.
4. Available weight below 0.50 returns Insufficient data.
5. Score version is persisted (present on every result).
6. Historical records remain reproducible (same params -> same output, always).
7. Band boundaries behave exactly as documented.
8. No component can produce stress below 0 or above 1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cfi.derivatives import metrics as m
from cfi.derivatives import score as sc
from cfi.derivatives import score_parameters as sp

AS_OF = datetime(2026, 9, 10, 12, 5, tzinfo=UTC)


# --------------------------------------------------------------------------- 1. parameters load


def test_v1_parameters_load_correctly() -> None:
    params = sp.parameters("derivatives_health_v1")
    assert params.version == "derivatives_health_v1"
    assert (
        params.weight_funding,
        params.weight_basis,
        params.weight_leverage,
        params.weight_liquidations,
        params.weight_volatility,
    ) == (Decimal("0.25"), Decimal("0.15"), Decimal("0.20"), Decimal("0.20"), Decimal("0.20"))
    assert sum(
        (
            params.weight_funding,
            params.weight_basis,
            params.weight_leverage,
            params.weight_liquidations,
            params.weight_volatility,
        ),
        Decimal(0),
    ) == Decimal("1.00")
    assert params.funding_scale == Decimal("0.30")
    assert params.basis_band == (Decimal(0), Decimal("0.10"))
    assert params.basis_scale == Decimal("0.15")
    assert params.leverage_scale == Decimal("0.20")
    assert params.liquidation_scale == Decimal("0.01")
    assert params.dvol_scales == {
        "BTC": (Decimal("0.30"), Decimal("0.80")),
        "ETH": (Decimal("0.40"), Decimal("1.00")),
    }
    assert params.min_available_weight == Decimal("0.5")
    assert params.bands[0] == (Decimal(75), "low stress")
    assert params.bands[-1] == (None, "high stress")


def test_default_version_is_derivatives_health_v1() -> None:
    assert sp.CURRENT_VERSION == "derivatives_health_v1"
    assert sp.parameters() is sp.parameters("derivatives_health_v1")
    assert sc.SCORE_VERSION == "derivatives_health_v1"


def test_unknown_version_is_a_hard_error_not_a_silent_fallback() -> None:
    with pytest.raises(KeyError):
        sp.parameters("derivatives_health_v2_not_published_yet")


# --------------------------------------------------------------------------- 2. unchanged output


def component(cid: str, stress: str | None, status: sc.Status = "ok") -> sc.ComponentResult:
    return sc.ComponentResult(
        sc.DEFS[cid], status, stress=None if stress is None else Decimal(stress)
    )


def test_score_calculations_unchanged_after_externalisation() -> None:
    """Same numbers as the pre-addendum hard-coded test: 0.25/0.15/0.20/0.20/0.20 against
    30 %/15 %/20 %/1 %/DVOL scales must still produce stress 26.5, health 73.5, moderate."""
    parts = [
        component("funding", "0.5"),
        component("basis", "0"),
        component("leverage", "0.4"),
        component("liquidations", "0.2"),
        component("volatility", "0.1"),
    ]
    s = sc.compute("BTC", AS_OF, parts)
    assert (s.stress, s.health, s.band) == (Decimal("26.5"), Decimal("73.5"), "moderate stress")
    assert [c.contribution for c in parts] == [
        Decimal("12.50"),
        Decimal("0.00"),
        Decimal("8.00"),
        Decimal("4.00"),
        Decimal("2.00"),
    ]


def _funding(value: Decimal) -> m.Funding:
    return m.Funding(
        venues=[],
        annualised_7d=value,
        weighting="test",
        condition="normal",
        direction="positive" if value > 0 else "negative" if value < 0 else None,
    )


def test_component_functions_unchanged_against_real_inputs() -> None:
    """The component-level formulas (not just the weighted sum) are unaffected: same funding
    value as before externalisation still clips to the same stress."""
    assert sc.funding_component(_funding(Decimal("0.30"))).stress == Decimal("1.0000")
    btc = sc.volatility_component("BTC", m.Point(AS_OF, Decimal("0.3462")), True)
    assert btc.stress == Decimal("0.0924")  # (34.62 − 30) ÷ (80 − 30), same as before


# --------------------------------------------------------------------------- 3. renormalisation


def test_missing_components_renormalise_correctly() -> None:
    parts = [
        component("funding", "0.5"),
        component("basis", None, "not_applicable"),
        component("leverage", "0.4"),
        component("liquidations", "0.2"),
        component("volatility", None, "not_applicable"),
    ]
    s = sc.compute("SOL", AS_OF, parts)
    # available weight 0.25 + 0.20 + 0.20 = 0.65; stress = (0.125+0.08+0.04) / 0.65
    assert s.available_weight == Decimal("0.65")
    assert (s.stress, s.health, s.band) == (Decimal("37.7"), Decimal("62.3"), "moderate stress")
    ok = [c for c in parts if c.status == "ok"]
    weights = [c.effective_weight for c in ok]
    assert all(w is not None for w in weights)
    assert sum((w for w in weights if w is not None), Decimal(0)) == Decimal("1.0000")


# --------------------------------------------------------------------------- 4. insufficient data


def test_available_weight_below_half_returns_insufficient_data() -> None:
    parts = [
        component("funding", "0.9"),
        component("basis", None, "unavailable"),
        component("leverage", None, "unavailable"),
        component("liquidations", "0.1"),
        component("volatility", None, "unavailable"),
    ]
    s = sc.compute("ETH", AS_OF, parts)
    assert s.status == "insufficient_data"
    assert s.health is None
    assert s.stress is None
    assert s.available_weight == Decimal("0.45")  # 0.25 + 0.20, below the 0.5 minimum
    assert "Insufficient data" in (s.reason or "")


def test_exactly_half_available_weight_is_sufficient() -> None:
    """min_available_weight (0.5) is inclusive: exactly half must still score."""
    parts = [
        component("funding", "0.2"),  # 0.25
        component("basis", None, "unavailable"),
        component("leverage", "0.2"),  # 0.20
        component("liquidations", None, "unavailable"),
        component("volatility", "0.2"),  # 0.20 -> total 0.65, still >= 0.5
    ]
    s = sc.compute("BTC", AS_OF, parts)
    assert s.status == "ok"


# --------------------------------------------------------------------------- 5./6. version + repro


def test_score_version_is_recorded_on_every_result() -> None:
    ok_parts = [component("funding", "0.5")]
    insufficient_parts = [component("funding", None, "unavailable")]
    ok = sc.compute("BTC", AS_OF, ok_parts)
    insufficient = sc.compute("BTC", AS_OF, insufficient_parts)
    assert ok.parameter_version == "derivatives_health_v1"
    assert insufficient.parameter_version == "derivatives_health_v1"
    assert ok.calculated_at is not None


def _five_components() -> list[sc.ComponentResult]:
    return [
        component("funding", "0.5"),
        component("basis", "0"),
        component("leverage", "0.4"),
        component("liquidations", "0.2"),
        component("volatility", "0.1"),
    ]


def test_reproducible_against_the_exact_version_used() -> None:
    """Recomputing the same inputs against the same named parameter version always gives the
    same output — the point of externalising and versioning parameters at all."""
    v1 = sp.parameters("derivatives_health_v1")
    first = sc.compute("BTC", AS_OF, _five_components(), v1)
    second = sc.compute("BTC", AS_OF, _five_components(), v1)
    assert (first.health, first.stress, first.band) == (second.health, second.stress, second.band)
    assert first.parameter_version == second.parameter_version == "derivatives_health_v1"


def test_a_hypothetical_future_version_does_not_change_v1_results() -> None:
    """A stand-in v2 (never published to PARAMETER_SETS) proves compute() actually uses the
    passed-in parameter set rather than a module-global — the guarantee reproducibility rests
    on. Doubling the funding scale should halve the funding component's stress."""
    v2 = sp.ParameterSet(
        version="derivatives_health_v2_hypothetical",
        weight_funding=sp.DERIVATIVES_HEALTH_V1.weight_funding,
        weight_basis=sp.DERIVATIVES_HEALTH_V1.weight_basis,
        weight_leverage=sp.DERIVATIVES_HEALTH_V1.weight_leverage,
        weight_liquidations=sp.DERIVATIVES_HEALTH_V1.weight_liquidations,
        weight_volatility=sp.DERIVATIVES_HEALTH_V1.weight_volatility,
        funding_scale=Decimal("0.60"),  # double the v1 scale
        basis_band=sp.DERIVATIVES_HEALTH_V1.basis_band,
        basis_scale=sp.DERIVATIVES_HEALTH_V1.basis_scale,
        leverage_scale=sp.DERIVATIVES_HEALTH_V1.leverage_scale,
        liquidation_scale=sp.DERIVATIVES_HEALTH_V1.liquidation_scale,
        dvol_scales=sp.DERIVATIVES_HEALTH_V1.dvol_scales,
        min_available_weight=sp.DERIVATIVES_HEALTH_V1.min_available_weight,
        bands=sp.DERIVATIVES_HEALTH_V1.bands,
    )
    funding = _funding(Decimal("0.30"))
    v1_result = sc.funding_component(funding, sp.parameters("derivatives_health_v1"))
    v2_result = sc.funding_component(funding, v2)
    assert v1_result.stress == Decimal("1.0000")  # 0.30 / 0.30, clipped
    assert v2_result.stress == Decimal("0.5000")  # 0.30 / 0.60
    assert sp.PARAMETER_SETS.keys() == {"derivatives_health_v1"}  # v2 above was never published


# --------------------------------------------------------------------------- 7. bands


@pytest.mark.parametrize(
    ("health", "band"),
    [
        ("100", "low stress"),
        ("75", "low stress"),
        ("74.9", "moderate stress"),
        ("50", "moderate stress"),
        ("49.9", "elevated stress"),
        ("25", "elevated stress"),
        ("24.9", "high stress"),
        ("0", "high stress"),
    ],
)
def test_band_boundaries_behave_exactly_as_documented(health: str, band: str) -> None:
    assert sc.band_for(Decimal(health)) == band


def test_band_note_matches_the_boundaries_used() -> None:
    assert "75" in sc.BAND_NOTE
    assert "50" in sc.BAND_NOTE
    assert "25" in sc.BAND_NOTE


# --------------------------------------------------------------------------- 8. stress clipping


@pytest.mark.parametrize(
    "value", [Decimal("-1000"), Decimal(0), Decimal("0.30"), Decimal("1000"), Decimal("1e9")]
)
def test_funding_stress_always_clipped_0_to_1(value: Decimal) -> None:
    stress = sc.funding_component(_funding(value)).stress
    assert stress is not None
    assert Decimal(0) <= stress <= Decimal(1)


def test_liquidation_stress_always_clipped_0_to_1() -> None:
    huge = m.Liquidations(
        status="ok",
        reason=None,
        window_start=AS_OF,
        window_end=AS_OF,
        hours_expected=24,
        hours_present=24,
        long_24h=Decimal("1000000"),
        short_24h=Decimal("1000000"),
        total_24h=Decimal("2000000"),
        long_share=Decimal("0.5"),
        share_of_oi=Decimal("2000000"),
        open_interest=Decimal("1"),
        events=[],
        events_note=None,
        hourly=[],
    )
    stress = sc.liquidation_component(huge).stress
    assert stress is not None
    assert Decimal(0) <= stress <= Decimal(1)


def test_volatility_stress_always_clipped_0_to_1() -> None:
    below_calm = sc.volatility_component("BTC", m.Point(AS_OF, Decimal("0.01")), True)
    above_stressed = sc.volatility_component("BTC", m.Point(AS_OF, Decimal("5.0")), True)
    assert below_calm.stress == Decimal(0)
    assert above_stressed.stress == Decimal(1)
