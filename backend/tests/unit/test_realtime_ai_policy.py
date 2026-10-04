"""`cfi.realtime.ai_policy`: the AI-trigger significance gate (Phase 35 testing requirement #10,
"AI trigger gating") — pure, database-free, so every gate can be pinned without a reachable
database."""

from __future__ import annotations

from cfi.alerts.rules import AlertCandidate
from cfi.alerts.service import CandidateDecision
from cfi.realtime.ai_policy import question_for, significant_decisions


def _candidate(**overrides: object) -> AlertCandidate:
    base: dict[str, object] = {
        "alert_type": "anomaly",
        "severity": "critical",
        "domain": "BTC",
        "trigger_condition": "Funding rate is in an anomalous band",
        "observed_value": "extreme_high",
        "reference_value": "normal",
        "evidence_field_ids": ("get_anomalies.anomalies[0].band",),
        "source_tool_id": "get_anomalies",
        "component_status": "ok",
        "dedup_key": "anomaly:funding_rate",
    }
    base.update(overrides)
    return AlertCandidate(**base)  # type: ignore[arg-type]


def _decision(
    action: str = "create", previous: str | None = None, **overrides: object
) -> CandidateDecision:
    return CandidateDecision(
        candidate=_candidate(**overrides),
        action=action,  # type: ignore[arg-type]
        alert_id=1,
        previous_observed_value=previous,
    )


def test_critical_create_is_significant() -> None:
    decisions = (_decision(severity="critical"),)
    assert significant_decisions(decisions) == list(decisions)


def test_elevated_rearm_is_significant() -> None:
    decisions = (_decision(action="rearm", severity="elevated"),)
    assert significant_decisions(decisions) == list(decisions)


def test_notable_severity_is_not_significant() -> None:
    # The vast majority of candidates (every score-band domain's default) are "notable" — this is
    # exactly the per-tick noise the AI-trigger policy must never escalate to Claude.
    decisions = (_decision(severity="notable"),)
    assert significant_decisions(decisions) == []


def test_skip_actions_are_never_significant_even_at_critical_severity() -> None:
    for action in ("skip_unchanged", "skip_cooldown"):
        decisions = (_decision(action=action, severity="critical"),)
        assert significant_decisions(decisions) == []


def test_unusable_component_status_is_not_significant_even_at_critical_severity() -> None:
    # Testing requirement #8/#9: stale/missing data must not be treated as a meaningful signal,
    # and must not be escalated to an AI call either, however severe the (unusable) reading looks.
    for status in ("insufficient_data", "unavailable", "not_applicable"):
        decisions = (_decision(severity="critical", component_status=status),)
        assert significant_decisions(decisions) == []


def test_mixed_batch_keeps_only_the_significant_ones() -> None:
    notable = _decision(severity="notable", dedup_key="liquidity:GLOBAL")
    critical = _decision(severity="critical", dedup_key="anomaly:funding_rate")
    skipped = _decision(action="skip_unchanged", severity="critical", dedup_key="anomaly:oi")
    assert significant_decisions((notable, critical, skipped)) == [critical]


# ------------------------------------------------------------------ question_for


def test_question_names_the_trigger_condition_and_new_value() -> None:
    decision = _decision(severity="critical", trigger_condition="Funding rate is anomalous")
    question = question_for(decision)
    assert "Funding rate is anomalous" in question
    assert "extreme_high" in question


def test_question_includes_the_previous_value_when_one_exists() -> None:
    decision = _decision(severity="critical", previous="notable_high")
    question = question_for(decision)
    assert "notable_high" in question


def test_question_omits_a_previous_value_clause_on_first_occurrence() -> None:
    decision = _decision(severity="critical", previous=None)
    question = question_for(decision)
    assert "was" not in question
