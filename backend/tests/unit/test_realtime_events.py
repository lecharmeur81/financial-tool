"""`cfi.realtime.events`: pure, database-free helpers for turning one alert-evaluation decision
into an intelligence event's extra fields (Phase 35 testing requirements #4/#5/#14/#15)."""

from __future__ import annotations

from decimal import Decimal

from cfi.alerts.rules import AlertCandidate
from cfi.alerts.service import CandidateDecision
from cfi.realtime.events import (
    change_magnitude,
    correlation_key_for,
    detection_method_for,
    is_meaningful_decision,
)


def _candidate(**overrides: object) -> AlertCandidate:
    base: dict[str, object] = {
        "alert_type": "anomaly",
        "severity": "critical",
        "domain": "BTC",
        "trigger_condition": "funding rate is anomalous",
        "observed_value": "extreme_high",
        "reference_value": "normal",
        "evidence_field_ids": ("get_anomalies.anomalies[0].band",),
        "source_tool_id": "get_anomalies",
        "component_status": "ok",
        "dedup_key": "anomaly:funding_rate",
    }
    base.update(overrides)
    return AlertCandidate(**base)  # type: ignore[arg-type]


def _decision(action: str, **overrides: object) -> CandidateDecision:
    return CandidateDecision(
        candidate=_candidate(**overrides),
        action=action,  # type: ignore[arg-type]
        alert_id=1,
        previous_observed_value=None,
    )


# ------------------------------------------------------------------ detection_method_for


def test_detection_method_names_the_evaluator_1_to_1() -> None:
    assert detection_method_for("regime_change") == "cfi.alerts.rules.evaluate_regime_change"
    assert detection_method_for("anomaly") == "cfi.alerts.rules.evaluate_anomaly"


# ------------------------------------------------------------------ change_magnitude


def test_change_magnitude_is_the_numeric_difference_when_both_sides_parse() -> None:
    assert change_magnitude("100", "110") == Decimal(10)
    assert change_magnitude("50.5", "40.0") == Decimal("-10.5")


def test_change_magnitude_is_none_without_a_previous_value() -> None:
    # Timestamp correctness/first-ever-occurrence case (testing requirement #15): a brand-new
    # dedup key has no prior reading to diff against — never fabricate one (R3).
    assert change_magnitude(None, "110") is None


def test_change_magnitude_is_none_for_non_numeric_categorical_bands() -> None:
    # Most domains report band labels, not raw numbers — a magnitude is correctly undefined, not
    # a parse error swallowed into 0 (R3: missing is a first-class state).
    assert change_magnitude("notable_high", "extreme_high") is None


# ------------------------------------------------------------------ correlation_key_for


def test_correlation_key_groups_by_the_triggering_snapshot() -> None:
    assert correlation_key_for(42) == "snapshot:42"
    # Two events from the same cycle (same snapshot_id) always share one key.
    assert correlation_key_for(42) == correlation_key_for(42)
    # Two different cycles never collide.
    assert correlation_key_for(42) != correlation_key_for(43)


# ------------------------------------------------------------------ is_meaningful_decision


def test_create_and_rearm_are_meaningful() -> None:
    assert is_meaningful_decision(_decision("create")) is True
    assert is_meaningful_decision(_decision("rearm")) is True


def test_skip_unchanged_and_skip_cooldown_are_not_meaningful() -> None:
    # Testing requirement #5: a non-meaningful/noisy change must never produce an event — this is
    # exactly the noise ``cfi.alerts.lifecycle.decide`` already filters, not re-detected here.
    assert is_meaningful_decision(_decision("skip_unchanged")) is False
    assert is_meaningful_decision(_decision("skip_cooldown")) is False
