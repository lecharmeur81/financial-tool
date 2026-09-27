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
