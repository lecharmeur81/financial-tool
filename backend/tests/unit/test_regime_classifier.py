"""Unit tests for cfi.regime.classifier: condition evaluation, per-regime scoring, and the overall
classify() decision (including the mixed_unclear fallback paths). All synthetic — no I/O, no
database."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cfi.regime import classifier as cl
from cfi.regime import parameters as rp
from cfi.regime.snapshot import MetricReading, RegimeSnapshot

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def snapshot(metrics: dict[str, MetricReading]) -> RegimeSnapshot:
    return RegimeSnapshot(asset="BTC", as_of=T0, knowledge_time=T0, metrics=metrics)


def reading(value: str | None = None, condition: str | None = None) -> MetricReading:
    return MetricReading(
        status="ok", value=None if value is None else Decimal(value), condition=condition
    )


UNAVAILABLE = MetricReading(status="unavailable")

# --------------------------------------------------------------------------- _evaluate_condition


def test_evaluate_condition_gte_lte_between() -> None:
    gte = rp.ConditionDef("c", "l", "m", "gte", Decimal("1"), "r", threshold=Decimal(15))
    lte = rp.ConditionDef("c", "l", "m", "lte", Decimal("1"), "r", threshold=Decimal(15))
    between = rp.ConditionDef(
        "c",
        "l",
        "m",
        "between",
        Decimal("1"),
        "r",
        threshold=Decimal(10),
        threshold_high=Decimal(20),
    )

    assert cl._evaluate_condition(gte, snapshot({"m": reading("20")})).matched is True
    assert cl._evaluate_condition(gte, snapshot({"m": reading("10")})).matched is False
    assert cl._evaluate_condition(lte, snapshot({"m": reading("10")})).matched is True
    assert cl._evaluate_condition(between, snapshot({"m": reading("15")})).matched is True
    assert cl._evaluate_condition(between, snapshot({"m": reading("25")})).matched is False


def test_evaluate_condition_categorical() -> None:
    cond = rp.ConditionDef(
        "c", "l", "m", "categorical", Decimal("1"), "r", expected=("downtrend", "mixed")
    )
    down = snapshot({"m": reading(condition="downtrend")})
    up = snapshot({"m": reading(condition="uptrend")})
    assert cl._evaluate_condition(cond, down).matched is True
    assert cl._evaluate_condition(cond, up).matched is False


def test_evaluate_condition_unavailable_when_metric_missing_or_not_ok() -> None:
    cond = rp.ConditionDef("c", "l", "m", "gte", Decimal("1"), "r", threshold=Decimal(15))
    assert cl._evaluate_condition(cond, snapshot({})).matched is None
    assert cl._evaluate_condition(cond, snapshot({"m": UNAVAILABLE})).matched is None


# --------------------------------------------------------------------------- evaluate_regime


def test_evaluate_regime_insufficient_data_below_min_available_weight() -> None:
    definition = rp.ParameterSet(
        version="test",
        regimes=(),
        min_available_weight=Decimal("0.5"),
        min_confidence_assign=Decimal("0.55"),
        tie_margin=Decimal("0.08"),
    )
    rd = rp.RegimeDefinition(
        "r",
        "R",
        "d",
        (
            rp.ConditionDef("c1", "l1", "m1", "gte", Decimal("0.3"), "r", threshold=Decimal(1)),
            rp.ConditionDef("c2", "l2", "m2", "gte", Decimal("0.7"), "r", threshold=Decimal(1)),
        ),
    )
    score = cl.evaluate_regime(
        rd, snapshot({"m1": reading("5")}), min_available_weight=definition.min_available_weight
    )
    assert score.status == "insufficient_data"
    assert score.confidence is None


def test_evaluate_regime_confidence_is_matched_over_available_weight() -> None:
    rd = rp.RegimeDefinition(
        "r",
        "R",
        "d",
        (
            rp.ConditionDef("c1", "l1", "m1", "gte", Decimal("0.5"), "r", threshold=Decimal(1)),
            rp.ConditionDef("c2", "l2", "m2", "gte", Decimal("0.5"), "r", threshold=Decimal(1)),
        ),
    )
    score = cl.evaluate_regime(
        rd, snapshot({"m1": reading("5"), "m2": reading("0")}), min_available_weight=Decimal("0.5")
    )
    assert score.status == "ok"
    assert score.confidence == Decimal("0.50")
    assert len(score.contributing) == 1
    assert len(score.contradicting) == 1


# --------------------------------------------------------------------------- classify


def _accumulation_snapshot() -> RegimeSnapshot:
    return snapshot(
        {
            "market_structure_score": reading("10"),
            "btc_trend": reading(condition="downtrend"),
            "whale_score": reading("30"),
            "institutional_score": reading("5"),
            "retail_activity_score": reading("20"),
            "derivatives_health": reading("70"),
        }
    )


def test_classify_picks_accumulation_when_its_conditions_are_satisfied() -> None:
    result = cl.classify(_accumulation_snapshot(), rp.parameters())
    assert result.regime_id == "accumulation"
    assert result.confidence == Decimal("1.00")
    assert result.status == "ok"
    assert len(result.contributing) == 6
    assert not result.contradicting


def test_classify_returns_mixed_unclear_when_no_regime_has_any_data() -> None:
    result = cl.classify(snapshot({}), rp.parameters())
    assert result.regime_id == cl.MIXED_UNCLEAR
    assert result.status == "insufficient_data"
    assert result.confidence is None
    assert result.reason is not None


def test_classify_returns_mixed_unclear_on_a_close_tie() -> None:
    params = rp.ParameterSet(
        version="tie_test",
        regimes=(
            rp.RegimeDefinition(
                "a",
                "A",
                "d",
                (rp.ConditionDef("c", "l", "m1", "gte", Decimal("1"), "r", threshold=Decimal(1)),),
            ),
            rp.RegimeDefinition(
                "b",
                "B",
                "d",
                (rp.ConditionDef("c", "l", "m2", "gte", Decimal("1"), "r", threshold=Decimal(1)),),
            ),
        ),
        min_available_weight=Decimal("0.5"),
        min_confidence_assign=Decimal("0.55"),
        tie_margin=Decimal("0.08"),
    )
    snap = snapshot({"m1": reading("5"), "m2": reading("5")})
    result = cl.classify(snap, params)
    assert result.regime_id == cl.MIXED_UNCLEAR
    assert result.status == "ok"
    assert result.confidence == Decimal("1.00")  # the top candidate's own confidence, for context
    assert "within" in (result.reason or "")


def test_classify_returns_mixed_unclear_when_best_confidence_is_below_threshold() -> None:
    rd = rp.RegimeDefinition(
        "a",
        "A",
        "d",
        (
            rp.ConditionDef("c1", "l1", "m1", "gte", Decimal("0.5"), "r", threshold=Decimal(1)),
            rp.ConditionDef("c2", "l2", "m2", "gte", Decimal("0.5"), "r", threshold=Decimal(1)),
        ),
    )
    params = rp.ParameterSet(
        version="thresh_test",
        regimes=(rd,),
        min_available_weight=Decimal("0.5"),
        min_confidence_assign=Decimal("0.55"),
        tie_margin=Decimal("0.08"),
    )
    snap = snapshot({"m1": reading("5"), "m2": reading("0")})  # confidence 0.50 < 0.55
    result = cl.classify(snap, params)
    assert result.regime_id == cl.MIXED_UNCLEAR
    assert result.confidence == Decimal("0.50")
    assert "below the" in (result.reason or "")


# --------------------------------------------------------------------------- classify: hysteresis
# (RED_TEAM_REPORT.md finding #4, ADR-0062)


def _hysteresis_params(*, a_confidence: Decimal, b_confidence: Decimal) -> rp.ParameterSet:
    """Two single-metric regimes, A and B, whose confidences are driven to exact target values via
    condition weights (rather than depending on a genuinely fractional match count), so the
    hysteresis margin's boundary can be hit exactly."""
    regime_a = rp.RegimeDefinition(
        "a",
        "A",
        "d",
        (
            rp.ConditionDef(
                "c1", "l1", "m1", "gte", a_confidence, "r", threshold=Decimal(1)
            ),  # matches
            rp.ConditionDef(
                "c2", "l2", "m1b", "gte", Decimal(1) - a_confidence, "r", threshold=Decimal(1)
            ),  # never matches (m1b unset)
        ),
    )
    regime_b = rp.RegimeDefinition(
        "b",
        "B",
        "d",
        (
            rp.ConditionDef("c1", "l1", "m2", "gte", b_confidence, "r", threshold=Decimal(1)),
            rp.ConditionDef(
                "c2", "l2", "m2b", "gte", Decimal(1) - b_confidence, "r", threshold=Decimal(1)
            ),
        ),
    )
    return rp.ParameterSet(
        version="hysteresis_test",
        regimes=(regime_a, regime_b),
        min_available_weight=Decimal("0.5"),
        min_confidence_assign=Decimal("0.55"),
        tie_margin=Decimal("0.01"),  # small, so these scenarios aren't caught by the tie path
        hysteresis_margin=Decimal("0.05"),
    )


def _hysteresis_snapshot() -> RegimeSnapshot:
    # m1/m2 "match" (>= 1); m1b/m2b are present but fail their own "gte 1" condition (value 0) —
    # available but non-matching, so confidence == the matching condition's own weight exactly
    # (matched_weight / available_weight, with both conditions' weights summing to 1).
    return snapshot(
        {
            "m1": reading("5"),
            "m1b": reading("0"),
            "m2": reading("5"),
            "m2b": reading("0"),
        }
    )


def test_hysteresis_keeps_the_previous_regime_when_the_challenger_barely_wins() -> None:
    params = _hysteresis_params(a_confidence=Decimal("0.90"), b_confidence=Decimal("0.93"))
    result = cl.classify(_hysteresis_snapshot(), params, previous_regime_id="a")
    assert result.regime_id == "a"  # B's 0.03 lead does not clear the 0.05 hysteresis margin
    assert result.held_by_hysteresis is True
    assert result.confidence == Decimal("0.90")
    assert "Held from the prior classification" in (result.reason or "")


def test_hysteresis_yields_once_the_challenger_clears_the_margin() -> None:
    params = _hysteresis_params(a_confidence=Decimal("0.80"), b_confidence=Decimal("0.93"))
    result = cl.classify(_hysteresis_snapshot(), params, previous_regime_id="a")
    assert result.regime_id == "b"  # B's 0.13 lead clears the 0.05 margin
    assert result.held_by_hysteresis is False
    assert result.confidence == Decimal("0.93")


def test_hysteresis_is_a_no_op_with_zero_margin_regime_classifier_v1() -> None:
    """cost_model_v1-style reproducibility: regime_classifier_v1's hysteresis_margin is 0, so the
    highest-confidence regime always wins, exactly like before Phase 18."""
    params = _hysteresis_params(a_confidence=Decimal("0.90"), b_confidence=Decimal("0.93"))
    params_v1_style = rp.ParameterSet(
        version="v1_style",
        regimes=params.regimes,
        min_available_weight=params.min_available_weight,
        min_confidence_assign=params.min_confidence_assign,
        tie_margin=params.tie_margin,
        hysteresis_margin=Decimal("0"),
    )
    result = cl.classify(_hysteresis_snapshot(), params_v1_style, previous_regime_id="a")
    assert result.regime_id == "b"
    assert result.held_by_hysteresis is False


def test_hysteresis_does_not_apply_without_a_previous_regime_id() -> None:
    params = _hysteresis_params(a_confidence=Decimal("0.90"), b_confidence=Decimal("0.93"))
    result = cl.classify(_hysteresis_snapshot(), params, previous_regime_id=None)
    assert result.regime_id == "b"
    assert result.held_by_hysteresis is False


def test_hysteresis_does_not_hold_a_regime_that_no_longer_qualifies_at_all() -> None:
    """If the previous regime's OWN confidence has fallen below min_confidence_assign, hysteresis
    must not resurrect it — it no longer qualifies on its own merits, hysteresis or not."""
    params = _hysteresis_params(a_confidence=Decimal("0.40"), b_confidence=Decimal("0.42"))
    result = cl.classify(_hysteresis_snapshot(), params, previous_regime_id="a")
    assert result.regime_id == cl.MIXED_UNCLEAR
    assert result.held_by_hysteresis is False


def test_default_classify_call_has_no_hysteresis_previous_regime_id_omitted() -> None:
    """Reproducibility: calling classify() the old way (no previous_regime_id argument at all)
    must behave exactly as before Phase 18."""
    result = cl.classify(_accumulation_snapshot(), rp.parameters())
    assert result.held_by_hysteresis is False
