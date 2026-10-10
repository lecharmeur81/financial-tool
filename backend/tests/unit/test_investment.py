"""Investment Decision (Phase 49; ADR-0086): ``cfi.intelligence.investment``.

Synthetic chains reuse the Phase 48 builders (unified -> confirmation -> opportunities -> ranking ->
risk), so each decision state is reached through the public contracts. The two states that valid
public contracts cannot reach (``candidate_no_findings_detected`` and
``candidate_invalidation_triggered``) are tested through the isolated classification logic only;
no production integrity requirement is bypassed."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest

from cfi.decision.universe import SCOPE_DOMAINS
from cfi.intelligence import (
    InvestmentInputError,
    build_investment_decision,
    build_ranking,
    build_risk_invalidation,
)
from cfi.intelligence.investment import CONTRACT_VERSION, _classify_candidate
from cfi.intelligence.investment_universe import DETECTED_LIMITATION_CHECKS, PRECEDENCE, STATES
from tests.unit.test_risk import (
    ALL,
    BOTH,
    _chain,
    _mismatch,
    _unverify,
    _violation,
)

SCOPES = tuple(SCOPE_DOMAINS)
STATE_IDS = [s for s, _ in STATES]
UNREACHABLE = {"candidate_no_findings_detected", "candidate_invalidation_triggered"}


def _run_chain(
    codes: dict[str, str] | None = None, **kw: Any
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    opp, ranking, view = _chain(codes, **kw)
    risk = build_risk_invalidation(opp, ranking, view)
    return opp, ranking, risk, view


def _run(codes: dict[str, str] | None = None, **kw: Any) -> dict[str, Any]:
    return build_investment_decision(*_run_chain(codes, **kw))


def _state(out: dict[str, Any], scope: str = "BTC") -> str:
    return str(out["assets"][scope]["decision_state"])


def _refs(out: dict[str, Any], group: str, scope: str = "BTC") -> set[str]:
    return {r["check_id"] for r in out["assets"][scope]["risk_findings"][group]}


# ------------------------------------------------------------------ findings for isolated logic
def _f(check_id: str, result: str, category: str = "x") -> dict[str, Any]:
    return {"check_id": check_id, "result": result, "category": category}


def _inv(summary: str = "none_triggered", *results: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "conditions": [
            {"condition_id": f"INV-0{i}", "result": r}
            for i, r in enumerate(results or ("not_triggered",), 1)
        ],
    }


# ---------------------------------------------------------------------------- structure
def test_the_contract_carries_versions_states_precedence_and_provenance() -> None:
    out = _run()
    assert out["contract_version"] == CONTRACT_VERSION == "investment_decision.v0"
    assert out["parameters"] == {
        "version": "investment_params.v0",
        "states_version": "investment_states.v0",
        "precedence": list(PRECEDENCE),
        "experimental": True,
    }
    assert [s["id"] for s in out["states"]] == STATE_IDS
    assert len(STATE_IDS) == 8
    assert out["source_contracts"]["risk"] == "risk_invalidation.v0"
    assert out["source_contracts"]["ranking"] == "opportunity_ranking.v0"
    assert out["source_contracts"]["opportunity"] == "opportunity_discovery.v0"
    assert out["source_contracts"]["risk_view"] == "risk_view.v0"
    assert out["source_contracts"]["risk_checks"] == "risk_checks.v0"
    assert list(out["assets"]) == list(SCOPES)
    assert sum(out["counts"].values()) == 4
    assert set(out["counts"]) == set(STATE_IDS)
    assert out["evidence_dependence"]["independent_confirmation"] is False
    assert out["notice"]["id"] == "research_state_not_a_recommendation"
    assert out["upstream_limitations"]
    assert {x["id"] for x in out["limitations"]} >= {
        "state_is_not_a_thesis",
        "strongest_states_not_reachable_on_live_data",
    }


def test_the_precedence_runs_from_most_restrictive_to_least() -> None:
    assert PRECEDENCE[0] == "withheld_integrity_gate"
    assert PRECEDENCE[1] == "candidate_invalidation_triggered"
    assert PRECEDENCE[-1] == "candidate_no_findings_detected"
    assert PRECEDENCE.index("candidate_risk_findings_detected") < PRECEDENCE.index(
        "candidate_unresolved"
    )


# ------------------------------------------------------------------------ each state
@pytest.mark.parametrize(
    ("codes", "scope", "status", "state", "reason"),
    [
        ({}, "BTC", "no_candidate", "no_opportunity", "DI-NO-OPPORTUNITY"),
        (
            {
                "institutional": "U",
                "whale": "U",
                "liquidity": "U",
                "macro": "U",
                "market_structure": "U",
            },
            "BTC",
            "insufficient_evidence",
            "insufficient_evidence",
            "DI-INSUFFICIENT-EVIDENCE",
        ),
        (
            {"institutional": "S", "whale": "A"},
            "BTC",
            "conflicting_evidence",
            "contradicted_evidence",
            "DI-CONTRADICTED",
        ),
    ],
)
def test_a_non_candidate_status_maps_to_its_state(
    codes: dict[str, str], scope: str, status: str, state: str, reason: str
) -> None:
    out = _run(codes)
    a = out["assets"][scope]
    assert a["status"] == status
    assert a["decision_state"] == state
    assert a["decision_reasons"] == [reason]
    assert a["risk_findings"] is None
    assert a["invalidation"] is None
    assert a["risk_assessment"] == {
        "state": "not_applicable",
        "reasons": ["RI-NOT-A-CANDIDATE"],
        "counts": dict.fromkeys(
            ("passed", "detected", "unverified", "unavailable", "not_applicable", "withheld"), 0
        ),
    }
    assert a["why_not_conclusive"] == [
        {"reason_id": reason, "ref": status},
        {"reason_id": "DI-NO-RISK-ASSESSMENT", "ref": scope},
    ]
    assert a["reassessment"] == []


def test_insufficient_evidence_is_not_contradicted_evidence() -> None:
    out = _run(
        {
            "institutional": "U",
            "whale": "U",
            "liquidity": "U",
            "macro": "U",
            "market_structure": "U",
        }
    )
    assert {_state(out, s) for s in SCOPES} == {"insufficient_evidence"}
    for s in SCOPES:
        assert out["assets"][s]["evidence"]["contradicting"] == []


@pytest.mark.parametrize("mutate", [_violation, _mismatch])
def test_an_integrity_gate_withholds_every_asset_and_takes_precedence(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    out = _run(ALL, mutate=mutate)
    assert out["assessment"]["performed"] is False
    assert {_state(out, s) for s in SCOPES} == {"withheld_integrity_gate"}
    for s in SCOPES:
        a = out["assets"][s]
        assert a["status"] == "blocked"
        assert a["decision_reasons"][0] == "DI-GATE-WITHHELD"
        assert "DI-UNDERLYING-STATUS" in a["decision_reasons"]
        # Phase 48 returns no per-asset findings or invalidation under a gate: null stays truthful,
        # and the withheld assessment is stated, never implied to be a clean or performed result.
        assert a["risk_assessment"]["state"] == "withheld"
        assert a["risk_assessment"]["reasons"] == ["RI-WITHHELD-BLOCKED"]
        assert sum(a["risk_assessment"]["counts"].values()) == 0
        assert a["risk_findings"] is None
        assert a["invalidation"] is None
        assert a["reassessment"] == []
        gate = out["assessment"]["gate_reasons"]
        assert a["why_not_conclusive"] == [
            *({"reason_id": "DI-GATE-WITHHELD", "ref": g} for g in gate),
            {"reason_id": "DI-NO-RISK-ASSESSMENT", "ref": s},
        ]
        assert "DI-CANDIDATE-IS-NOT-A-THESIS" not in {
            w["reason_id"] for w in a["why_not_conclusive"]
        }
    assert out["assessment"]["gate_reasons"] == (
        ["DI-GATE-LOOK-AHEAD"] if mutate is _violation else ["DI-GATE-INTEGRITY"]
    )


def test_a_gate_never_produces_an_assessed_candidate_result() -> None:
    for mutate in (_violation, _mismatch):
        out = _run(ALL, mutate=mutate)
        for a in out["assets"].values():
            assert a["risk_assessment"]["state"] != "assessed"
            assert a["risk_findings"] is None
            assert a["invalidation"] is None
            assert a["decision_state"] == "withheld_integrity_gate"
        # the diagnostics Phase 48 does return are preserved at top level, labelled as withheld
        assert {f["result"] for f in out["market_risks"]} == {"withheld"}
        assert any(f["result"] == "detected" for f in out["integrity"])
        assert len(out["declared_unavailable"]) == 6


def test_a_withheld_market_level_is_the_engines_reading_not_an_assessed_result() -> None:
    out = _run(ALL, mutate=_violation, levels={"market": "Elevated"})
    market = next(f for f in out["market_risks"] if f["check_id"] == "RI-MKT-01")
    assert market["level"] == "Elevated"
    assert market["result"] == "withheld"
    assert all(a["market_risks_detected"] == [] for a in out["assets"].values())


def test_risk_assessment_is_copied_from_phase_48_unchanged() -> None:
    opp, ranking, risk, view = _run_chain(ALL, levels={"leverage": "High"})
    out = build_investment_decision(opp, ranking, risk, view)
    for scope in SCOPES:
        ra = risk["assets"][scope]
        assert out["assets"][scope]["risk_assessment"] == {
            "state": ra["assessment"],
            "reasons": ra["assessment_reasons"],
            "counts": ra["counts"],
        }
    btc = out["assets"]["BTC"]["risk_assessment"]
    assert btc["state"] == "assessed"
    assert btc["reasons"] == ["RI-ASSESSED"]
    assert btc["counts"]["detected"] >= 1


def test_a_gate_keeps_the_underlying_status_of_a_non_candidate_and_still_withholds() -> None:
    def both(u: dict[str, Any]) -> None:
        _violation(u)
        _mismatch(u)

    out = _run({**BOTH, "liquidity": "A"}, mutate=both)
    a = out["assets"]["BTC"]
    assert a["status"] == "conflicting_evidence"  # preserved
    assert a["decision_state"] == "withheld_integrity_gate"  # gate wins over any other state
    assert out["assessment"]["gate_reasons"] == ["DI-GATE-LOOK-AHEAD", "DI-GATE-INTEGRITY"]


def test_a_gate_never_yields_a_favourable_state() -> None:
    for mutate in (_violation, _mismatch):
        out = _run(ALL, mutate=mutate)
        assert not (UNREACHABLE | {"candidate_unresolved"}) & {_state(out, s) for s in SCOPES}


def test_a_candidate_with_unresolved_checks_is_candidate_unresolved() -> None:
    out = _run(ALL)
    assert {_state(out, s) for s in SCOPES} == {"candidate_unresolved"}
    a = out["assets"]["BTC"]
    assert a["decision_reasons"][0] == "DI-UNRESOLVED"
    assert "DI-UNVERIFIED-CHECKS" in a["decision_reasons"]
    assert "DI-CANDIDATE-IS-NOT-A-THESIS" in a["decision_reasons"]
    assert "DI-DECLARED-CHECKS-NOT-EVALUATED" in a["decision_reasons"]
    assert a["why_not_conclusive"]


def test_a_detected_risk_finding_is_candidate_risk_findings_detected() -> None:
    out = _run(ALL, levels={"leverage": "High"})
    a = out["assets"]["BTC"]
    assert a["decision_state"] == "candidate_risk_findings_detected"
    assert a["decision_reasons"][0] == "DI-RISK-FINDINGS-DETECTED"
    assert "RI-LEV-01" in _refs(out, "detected")
    # a risk finding is not an invalidation
    assert a["invalidation"]["summary"] != "triggered"
    assert "candidate_invalidation_triggered" not in {_state(out, s) for s in SCOPES}


def test_a_market_wide_risk_applies_to_every_candidate() -> None:
    out = _run(ALL, levels={"market": "Elevated"})
    assert {_state(out, s) for s in SCOPES} == {"candidate_risk_findings_detected"}
    assert all("RI-MKT-01" in _refs(out, "detected", s) for s in SCOPES)
    assert out["assets"]["BTC"]["market_risks_detected"] == ["RI-MKT-01"]


def test_an_observed_cap_is_a_risk_finding_not_an_invalidation() -> None:
    out = _run(ALL, caps=(("RC-03", True),))
    a = out["assets"]["BTC"]
    assert a["decision_state"] == "candidate_risk_findings_detected"
    assert "RI-CAP-03" in _refs(out, "detected")
    inv = {c["condition_id"]: c["result"] for c in a["invalidation"]["conditions"]}
    assert inv["INV-06"] == "cannot_evaluate"
    assert a["invalidation"]["summary"] == "not_fully_evaluable"


def test_conflicting_or_degraded_sources_are_a_detected_integrity_finding() -> None:
    out = _run(ALL, mutate=lambda u: u["data_quality"].update(conflicting_tools=["get_x"]))
    a = out["assets"]["BTC"]
    assert a["decision_state"] == "candidate_risk_findings_detected"
    assert "DI-SOURCE-CONFLICT" in a["decision_reasons"]


def test_missing_evidence_is_an_evidence_limitation_not_a_risk_finding() -> None:
    out = _run({**BOTH, "market_structure": "U"})
    a = out["assets"]["BTC"]
    assert a["decision_state"] == "candidate_unresolved"  # never candidate_risk_findings_detected
    assert "DI-EVIDENCE-INCOMPLETE" in a["decision_reasons"]
    assert "RI-EVD-03" in _refs(out, "detected")
    assert {"market_structure"} <= {m["domain"] for m in a["evidence"]["missing_or_unusable"]}
    assert all(m["domain"] != "market_structure" for m in a["evidence"]["contradicting"])
    assert {"reason_id": "DI-EVIDENCE-INCOMPLETE", "ref": "RI-EVD-03"} in a["why_not_conclusive"]


def test_thin_and_shared_evidence_are_limitations_that_keep_a_candidate_unresolved() -> None:
    out = _run(ALL)
    sol = out["assets"]["SOL"]
    assert sol["decision_state"] == "candidate_unresolved"
    assert "DI-EVIDENCE-THIN" in sol["decision_reasons"]
    assert "DI-SHARED-EVIDENCE" in sol["decision_reasons"]
    assert set(DETECTED_LIMITATION_CHECKS) == {"RI-EVD-03", "RI-EVD-04", "RI-EVD-05"}


# ---------------------------------------------------------- isolated classification (all states)
def test_no_findings_detected_requires_every_evaluated_check_passed_and_nothing_unresolved() -> (
    None
):
    findings = [_f("RI-LEV-01", "passed"), _f("RI-MKT-01", "passed"), _f("RI-INT-01", "passed")]
    state, reasons, unresolved = _classify_candidate(
        findings, _inv("none_triggered", "not_triggered")
    )
    assert state == "candidate_no_findings_detected"
    assert reasons == ["DI-NO-FINDINGS-DETECTED"]
    assert unresolved == []


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        ("unverified", "DI-UNVERIFIED-CHECKS"),
        ("unavailable", "DI-UNAVAILABLE-CHECKS"),
        ("not_applicable", "DI-NOT-APPLICABLE-CHECKS"),
    ],
)
def test_a_favourable_finding_never_hides_an_unresolved_check(result: str, reason: str) -> None:
    findings = [_f("RI-LEV-01", "passed"), _f("RI-CAP-01", result)]
    state, reasons, unresolved = _classify_candidate(findings, _inv())
    assert state == "candidate_unresolved"
    assert reason in reasons
    assert {"reason_id": reason, "ref": "RI-CAP-01"} in unresolved


def test_an_invalidation_that_cannot_be_evaluated_keeps_a_candidate_unresolved() -> None:
    state, reasons, unresolved = _classify_candidate(
        [_f("RI-LEV-01", "passed")], _inv("not_fully_evaluable", "not_triggered", "cannot_evaluate")
    )
    assert state == "candidate_unresolved"
    assert "DI-INVALIDATION-NOT-FULLY-EVALUABLE" in reasons
    assert unresolved == [{"reason_id": "DI-INVALIDATION-NOT-FULLY-EVALUABLE", "ref": "INV-02"}]


def test_a_triggered_invalidation_takes_precedence_over_a_risk_finding_and_keeps_both() -> None:
    findings = [_f("RI-LEV-01", "detected"), _f("RI-CAP-01", "unverified")]
    state, reasons, unresolved = _classify_candidate(
        findings, _inv("triggered", "triggered", "cannot_evaluate")
    )
    assert state == "candidate_invalidation_triggered"
    assert reasons[0] == "DI-INVALIDATION-TRIGGERED"
    assert "DI-UNVERIFIED-CHECKS" in reasons  # unresolved items are still reported
    assert unresolved


def test_a_risk_finding_without_a_triggered_invalidation_is_not_an_invalidation() -> None:
    state, _, _ = _classify_candidate(
        [_f("RI-LEV-01", "detected")], _inv("none_triggered", "not_triggered")
    )
    assert state == "candidate_risk_findings_detected"


def test_a_risk_finding_takes_precedence_over_unresolved_but_unresolved_is_kept() -> None:
    state, reasons, unresolved = _classify_candidate(
        [_f("RI-DQ-01", "detected"), _f("RI-INT-02", "unverified")], _inv()
    )
    assert state == "candidate_risk_findings_detected"
    assert reasons[:2] == ["DI-RISK-FINDINGS-DETECTED", "DI-UNVERIFIED-CHECKS"]
    assert unresolved == [{"reason_id": "DI-UNVERIFIED-CHECKS", "ref": "RI-INT-02"}]


@pytest.mark.parametrize("check", sorted(DETECTED_LIMITATION_CHECKS))
def test_a_detected_limitation_is_unresolved_never_a_risk_finding(check: str) -> None:
    state, reasons, _ = _classify_candidate([_f(check, "detected", "coverage")], _inv())
    assert state == "candidate_unresolved"
    assert DETECTED_LIMITATION_CHECKS[check] in reasons


def test_the_two_strongest_states_are_not_reachable_through_valid_public_contracts() -> None:
    seen: set[str] = set()
    for codes, kw in (
        (ALL, {}),
        (BOTH, {}),
        (ALL, {"levels": {"leverage": "High"}}),
        (ALL, {"caps": (("RC-01", True),)}),
        (ALL, {"evaluated": False}),
        ({}, {}),
        ({**BOTH, "liquidity": "A"}, {}),
    ):
        out = _run(codes, **kw)
        seen |= {_state(out, s) for s in SCOPES}
    assert not UNREACHABLE & seen  # documented limitation, not a defect


def test_the_data_quality_check_alone_keeps_every_live_candidate_from_the_top_state() -> None:
    out = _run(ALL)
    dq = next(
        f
        for f in out["assets"]["BTC"]["risk_findings"]["unverified"]
        if f["check_id"] == "RI-DQ-01"
    )
    assert dq["reason_ids"] == ["RI-FRESHNESS-NOT-APPLICABLE"]


# -------------------------------------------------------------------------- preservation
def test_every_finding_is_preserved_whichever_state_takes_precedence() -> None:
    out = _run(ALL, levels={"leverage": "High"}, caps=(("RC-01", False),))
    a = out["assets"]["BTC"]
    _, _, risk, _ = _run_chain(ALL, levels={"leverage": "High"}, caps=(("RC-01", False),))
    expected = {
        f["check_id"]
        for f in [
            *risk["integrity"]["findings"],
            *risk["market_risks"]["findings"],
            *risk["assets"]["BTC"]["findings"],
        ]
    }
    kept = {r["check_id"] for group in a["risk_findings"].values() for r in group}
    assert kept == expected
    assert a["decision_state"] == "candidate_risk_findings_detected"
    assert a["risk_findings"]["unverified"]  # unresolved checks survive beside the detected one
    assert [c["condition_id"] for c in a["invalidation"]["conditions"]] == [
        f"INV-0{i}" for i in range(1, 7)
    ]
    assert out["declared_unavailable"] == risk["unavailable_checks"]
    assert {i["check_id"] for i in out["declared_unavailable"]} >= {
        "RI-UNV-EXECUTION",
        "RI-UNV-PORTFOLIO",
    }
    assert out["integrity"]
    assert out["market_risks"]


def test_a_finding_reference_keeps_its_freshness_levels_and_provenance() -> None:
    out = _run(ALL, levels={"leverage": "Elevated"})
    f = next(
        r for r in out["assets"]["BTC"]["risk_findings"]["detected"] if r["check_id"] == "RI-LEV-01"
    )
    assert f["level"] == "Elevated"
    assert f["engine_reason_ids"] == ["RK-leverage"]
    assert f["field_ids"] == ["get_derivatives.score.band"]
    assert f["freshness_verified"] is True
    assert f["source_ids"] == ["get_derivatives"]


def test_evidence_references_separate_supporting_other_and_missing_evidence() -> None:
    out = _run({**BOTH, "market_structure": "U", "macro": "N"})
    ev = out["assets"]["BTC"]["evidence"]
    assert {r["domain"] for r in ev["supporting"]} == {"institutional", "whale"}
    assert all(r["state"] == "supportive" and r["freshness_verified"] for r in ev["supporting"])
    assert {r["domain"] for r in ev["other_eligible"]} == {"liquidity", "macro"}
    assert {r["domain"] for r in ev["missing_or_unusable"]} == {"market_structure"}
    assert ev["contradicting"] == []
    assert all(r["field_ids"] for r in ev["supporting"])


def test_contradicting_evidence_is_listed_for_a_conflicting_asset() -> None:
    out = _run({"institutional": "S", "whale": "A"})
    ev = out["assets"]["BTC"]["evidence"]
    assert {r["domain"] for r in ev["supporting"]} == {"institutional"}
    assert {r["domain"] for r in ev["contradicting"]} == {"whale"}


def test_repeated_evidence_is_listed_once() -> None:
    opp, _, view = _chain(ALL)
    refs = opp["assets"]["BTC"]["evidence_refs"]
    refs.append(copy.deepcopy(next(m for m in refs if m["domain"] == "institutional")))
    ranking = build_ranking(opp)
    risk = build_risk_invalidation(opp, ranking, view)
    out = build_investment_decision(opp, ranking, risk, view)
    supporting = out["assets"]["BTC"]["evidence"]["supporting"]
    assert [r["domain"] for r in supporting].count("institutional") == 1


# ------------------------------------------------- unverified or stale never reassures
def test_unverified_or_stale_evidence_never_moves_a_state_up() -> None:
    base = {s: PRECEDENCE.index(_state(_run(ALL), s)) for s in SCOPES}
    for domains in (("derivatives",), ("derivatives", "anomaly", "regime"), ("liquidity",)):
        out = _run(ALL, mutate=lambda u, d=domains: _unverify(u, *d))
        for s in SCOPES:
            assert PRECEDENCE.index(_state(out, s)) <= base[s], (domains, s)


def test_a_detected_risk_on_unverified_evidence_is_still_reported() -> None:
    out = _run(ALL, mutate=lambda u: _unverify(u, "derivatives"), levels={"leverage": "High"})
    f = next(
        r for r in out["assets"]["BTC"]["risk_findings"]["detected"] if r["check_id"] == "RI-LEV-01"
    )
    assert f["freshness_verified"] is False
    assert _state(out) == "candidate_risk_findings_detected"


def test_unverified_support_does_not_become_supporting_evidence() -> None:
    def unverified(u: dict[str, Any]) -> None:
        for a in u["assets"].values():
            for e in a["domains"]:
                if e["domain"] == "institutional":
                    e.update(freshness="not_assessed", freshness_records=[])

    out = _run(ALL, mutate=unverified)
    for scope, a in out["assets"].items():
        assert "institutional" not in {r["domain"] for r in a["evidence"]["supporting"]}, scope
        assert any(r["domain"] == "institutional" for r in a["evidence"]["missing_or_unusable"])


# ------------------------------------------------------------------- ranking and context
def test_ranking_is_context_only_and_never_chooses_the_state() -> None:
    out = _run(ALL)
    assert (
        out["assets"]["BTC"]["ranking_context"]["evidence_depth"]
        != (out["assets"]["SOL"]["ranking_context"]["evidence_depth"])
    )
    for a in out["assets"].values():
        assert a["ranking_context"]["used_for_decision"] is False
        assert a["ranking_context"]["used_for_risk"] is False
        assert a["decision_state"] == "candidate_unresolved"  # same state at different depths


def test_ranking_values_are_copied_from_phase_47_unchanged() -> None:
    opp, ranking, risk, view = _run_chain(ALL)
    out = build_investment_decision(opp, ranking, risk, view)
    for s in SCOPES:
        ctx = out["assets"][s]["ranking_context"]
        assert ctx["evidence_depth"] == ranking["assets"][s]["evidence_depth"]
        assert ctx["rank"] == ranking["assets"][s]["rank"]
        assert ctx["rank_scope"] == ranking["assets"][s]["rank_scope"]


# ---------------------------------------------------------------------------- reassessment
def test_reassessment_reuses_phase_48_monitor_fields_and_states_what_cannot_be_evaluated() -> None:
    opp, ranking, risk, view = _run_chain(ALL, evaluated=False)
    out = build_investment_decision(opp, ranking, risk, view)
    items = out["assets"]["BTC"]["reassessment"]
    monitor = risk["assets"]["BTC"]["invalidation"]["monitor"]
    mine = [i for i in items if i["kind"] == "monitor_condition"]
    assert [(i["ref"], i["field_ids"], i["when"]) for i in mine] == [
        (m["condition_id"], m["field_ids"], m["when"]) for m in monitor
    ]
    inv06 = next(i for i in mine if i["ref"] == "INV-06")
    assert inv06["evaluable"] is False
    assert inv06["condition_result"] == "cannot_evaluate"
    declared = [i for i in items if i["ref"].startswith("RI-UNV-")]
    assert len(declared) == len(risk["unavailable_checks"])
    assert all(i["kind"] == "cannot_evaluate" and i["evaluable"] is False for i in declared)
    verify = [i for i in items if i["kind"] == "verify_freshness"]
    assert verify
    assert all(i["field_ids"] or not i["evaluable"] for i in verify)


def test_reassessment_contains_no_numeric_threshold_target_or_timing_rule() -> None:
    out = _run(ALL, levels={"leverage": "High"})
    for item in out["assets"]["BTC"]["reassessment"]:
        assert set(item) == {"kind", "ref", "condition_result", "when", "field_ids", "evaluable"}
        assert not any(
            isinstance(v, int | float) and not isinstance(v, bool) for v in item.values()
        )


# ------------------------------------------------------------- vocabulary and determinism
def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_there_is_no_score_probability_recommendation_stance_or_posture_field() -> None:
    out = _run(ALL, levels={"leverage": "High"}, caps=(("RC-01", True),))
    banned = (
        "probab",
        "safe",
        "rating",
        "recommend",
        "buy",
        "sell",
        "target",
        "position",
        "stance",
    )
    exact = {"score", "risk_score", "confidence", "grade", "action", "signal", "posture", "size"}
    for key in _keys(out):
        assert key.lower() not in exact, key
        assert not any(b in key.lower() for b in banned), key


def test_no_state_name_is_an_action_or_a_safety_claim() -> None:
    for state in STATE_IDS:
        assert not any(
            w in state for w in ("buy", "sell", "hold", "safe", "confirmed_thesis", "invest")
        )
    meanings = " ".join(m for _, m in STATES).lower()
    assert "not a confirmed thesis and not safe" in meanings


def test_the_output_is_deterministic_json_and_does_not_mutate_or_alias_inputs() -> None:
    opp, ranking, risk, view = _run_chain(ALL, levels={"leverage": "Elevated"})
    before = copy.deepcopy((opp, ranking, risk, view))
    first = build_investment_decision(opp, ranking, risk, view)
    second = build_investment_decision(opp, ranking, risk, view)
    assert first == second
    assert json.dumps(first) == json.dumps(second)
    assert json.loads(json.dumps(first)) == first
    assert (opp, ranking, risk, view) == before
    first["assets"]["BTC"]["risk_findings"]["detected"].clear()
    first["assets"]["BTC"]["invalidation"]["conditions"].clear()
    first["snapshot"]["row_id"] = -1
    first["data_quality"]["platform_limits"].append("x")
    assert (opp, ranking, risk, view) == before


def test_the_supplied_risk_and_ranking_are_the_ones_reported() -> None:
    opp, ranking, risk, view = _run_chain(ALL)
    out = build_investment_decision(opp, ranking, risk, view)
    assert out["source_contracts"]["risk"] == risk["contract_version"]
    assert out["snapshot"] == risk["snapshot"] == opp["snapshot"]
    assert out["gates"] == risk["gates"]
    assert out["assessment"] == risk["assessment"] | {"gate_reasons": []}
    assert out["risk_decision_engine"] == risk["decision"]


# -------------------------------------------------------------------------------- refusals
def _refused(fn: Callable[..., None], match: str | None = None) -> None:
    opp, ranking, risk, view = _run_chain(ALL)
    fn(opp, ranking, risk, view)
    with pytest.raises(InvestmentInputError, match=match):
        build_investment_decision(opp, ranking, risk, view)


def test_a_risk_output_not_derived_from_these_inputs_is_refused_not_replaced() -> None:
    _refused(
        lambda o, r, k, v: k["assets"]["BTC"].update(assessment="not_applicable"), "not derived"
    )
    _refused(
        lambda o, r, k, v: k["assets"]["BTC"]["findings"][1].update(result="passed"), "not derived"
    )


def test_a_ranking_not_derived_from_the_opportunities_is_refused() -> None:
    _refused(lambda o, r, k, v: r["assets"]["BTC"].update(evidence_depth=4), "risk validation")


@pytest.mark.parametrize(
    "fn",
    [
        lambda o, r, k, v: k.update(contract_version="risk_invalidation.v1"),
        lambda o, r, k, v: r.update(contract_version="opportunity_ranking.v1"),
        lambda o, r, k, v: v.update(contract_version="risk_view.v1"),
        lambda o, r, k, v: o.update(contract_version="opportunity_discovery.v1"),
        lambda o, r, k, v: v["identity"].update(row_id=123),
        lambda o, r, k, v: v["scopes"].pop("XRP"),
        lambda o, r, k, v: v["scopes"]["BTC"]["risks"].pop(),
        lambda o, r, k, v: o["assets"].pop("XRP"),
        lambda o, r, k, v: o.pop("gates"),
        lambda o, r, k, v: o["data_quality"].pop("degraded_tools"),
    ],
)
def test_unsupported_mismatched_or_malformed_inputs_are_refused(fn: Callable[..., None]) -> None:
    _refused(fn)


@pytest.mark.parametrize("position", [0, 1, 2, 3])
@pytest.mark.parametrize("bad", [None, [], "x", 3])
def test_a_non_mapping_input_is_refused_for_each_argument(position: int, bad: object) -> None:
    args: list[object] = list(_run_chain(ALL))
    args[position] = bad
    with pytest.raises(InvestmentInputError):
        build_investment_decision(*args)  # type: ignore[arg-type]


def test_a_malformed_evidence_member_on_a_non_candidate_is_refused() -> None:
    opp, ranking, view = _chain({"institutional": "S", "whale": "A"})
    opp["assets"]["BTC"]["evidence_refs"][0]["domain"] = 7
    risk = build_risk_invalidation(opp, ranking, view)
    with pytest.raises(InvestmentInputError, match="domain"):
        build_investment_decision(opp, ranking, risk, view)


def test_a_candidate_below_the_family_minimums_is_refused_through_phase_48() -> None:
    opp, _, view = _chain(ALL)
    a = opp["assets"]["SOL"]
    a["evidence_refs"] = [
        m
        for m in a["evidence_refs"]
        if m["state"] != "supportive" or m["shared_across_assets"] is False
    ]
    a["basis"]["supportive_families"] = list(a["basis"]["asset_specific_supporting_families"])
    a["basis"]["market_wide_supporting_families"] = []
    ranking = build_ranking(opp)
    with pytest.raises(InvestmentInputError, match="minimums"):
        build_investment_decision(opp, ranking, {"contract_version": "risk_invalidation.v0"}, view)


def test_a_failed_request_returns_no_partial_result() -> None:
    opp, ranking, risk, view = _run_chain(ALL)
    risk["assets"]["XRP"]["findings"].pop()
    with pytest.raises(InvestmentInputError):
        build_investment_decision(opp, ranking, risk, view)


# ----------------------------------------------------------------------------- real chains
def _real(payload: dict[str, Any]) -> dict[str, Any]:
    from cfi.intelligence import (
        build_confirmation,
        build_opportunities,
        build_ranking,
        build_risk_view,
        build_unified_snapshot,
    )

    unified = build_unified_snapshot(payload)
    opp = build_opportunities(unified, build_confirmation(unified))
    ranking = build_ranking(opp)
    view = build_risk_view(payload)
    risk = build_risk_invalidation(opp, ranking, view)
    return build_investment_decision(opp, ranking, risk, view)


def test_the_real_fixture_chain_is_decided_end_to_end() -> None:
    from tests.decision_builders import make_payload

    payload = make_payload(["S2", "S1", "N", "S1", "S2"])
    payload["snapshot_version"] = "analyst_snapshot.v1"
    out = _real(payload)
    assert out["assets"]["BTC"]["decision_state"] == "candidate_unresolved"
    assert not UNREACHABLE & {a["decision_state"] for a in out["assets"].values()}
    assert out["assets"]["BTC"]["why_not_conclusive"]
    assert json.loads(json.dumps(out)) == out


def test_the_live_state_snapshot_has_no_opportunity_and_nothing_favourable() -> None:
    from tests.decision_live_payload import live_state_payload

    out = _real(live_state_payload())
    states = {a["decision_state"] for a in out["assets"].values()}
    assert states <= {"insufficient_evidence", "no_opportunity"}
    assert all(a["risk_findings"] is None for a in out["assets"].values())
    assert "passed" not in {f["result"] for f in out["market_risks"]}
