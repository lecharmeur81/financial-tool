"""Phase 53: the Advisor Brief composes two finished contracts without deciding anything.

Pure and database-free. Covers verbatim copying, layer labelling, traceability, data gaps
(missing / insufficient / unavailable evidence is a gap, never neutral), conflict and cap
reporting, unsupported-claim language, determinism and input validation."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from cfi.advisor import NOT_CLAIMED, AdvisorInputError, build_advisor_brief
from cfi.advisor.brief import DOMAIN_LAYERS, LAYERS, _layer
from cfi.analyst.universe import BANNED_PATTERNS
from cfi.decision.read_service import build_decision_view
from cfi.intelligence import (
    build_confirmation,
    build_investment_decision,
    build_opportunities,
    build_ranking,
    build_risk_invalidation,
    build_risk_view,
    build_unified_snapshot,
)
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload


def _stored(payload: dict[str, Any]) -> dict[str, Any]:
    payload["snapshot_version"] = "analyst_snapshot.v1"
    return payload


def _contracts(
    payload: dict[str, Any], asset: str = "BTC"
) -> tuple[dict[str, Any], dict[str, Any]]:
    view = build_decision_view(payload, asset)
    unified = build_unified_snapshot(payload)
    opportunities = build_opportunities(unified, build_confirmation(unified))
    ranking = build_ranking(opportunities)
    risk_view = build_risk_view(payload)
    risk = build_risk_invalidation(opportunities, ranking, risk_view)
    return view, build_investment_decision(opportunities, ranking, risk, risk_view)


def _brief(payload: dict[str, Any], asset: str = "BTC") -> dict[str, Any]:
    view, investment = _contracts(payload, asset)
    return build_advisor_brief(view, investment, asset)


def _bullish() -> dict[str, Any]:
    return _stored(make_payload(["S2", "S1", "N", "S1", "S2"]))


# ------------------------------------------------------------------ verbatim, never decided here


def test_stance_and_investment_state_are_copied_verbatim() -> None:
    payload = _bullish()
    view, investment = _contracts(payload)
    brief = build_advisor_brief(view, investment, "BTC")
    assert brief["contract_version"] == "advisor_brief.v0"
    assert brief["assessment"]["stance"] == view["stance"]
    state = brief["assessment"]["investment_state"]
    assert state["decision_state"] == investment["assets"]["BTC"]["decision_state"]
    assert state["decision_reasons"] == investment["assets"]["BTC"]["decision_reasons"]
    assert brief["risk"]["max_decision_risk"] == view["max_risk"]
    assert brief["answered_from"]["decision_view"] == "decision_view.v0"
    assert brief["answered_from"]["investment_decision"] == "investment_decision.v0"
    assert brief["snapshot"] == view["snapshot"]


def test_inputs_are_not_mutated_and_the_brief_is_deterministic() -> None:
    view, investment = _contracts(_bullish())
    before = (copy.deepcopy(view), copy.deepcopy(investment))
    first = build_advisor_brief(view, investment, "BTC")
    second = build_advisor_brief(view, investment, "BTC")
    assert (view, investment) == before
    assert first == second


@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP"])
def test_every_supported_asset_is_briefed_from_its_own_contracts(asset: str) -> None:
    payload = _stored(
        make_payload(
            ["S1", "N", "S1", "S1"] if asset in ("SOL", "XRP") else ["S1", "N", "S1", "S1", "S1"],
            scope=asset,
        )
    )
    brief = _brief(payload, asset)
    assert brief["asset"] == asset


# ------------------------------------------------------------------ layers


def test_every_item_carries_a_known_layer_and_regime_is_not_a_signal() -> None:
    brief = _brief(_bullish())
    items = brief["signals"] + brief["readings"]
    assert items
    assert all(i["layer"] in LAYERS for i in items)
    regime = next(r for r in brief["readings"] if r["domain"] == "regime")
    assert regime["layer"] == "regime_assessment"
    assert all(s["domain"] != "regime" for s in brief["signals"])
    assert brief["assessment"]["layer"] == "deterministic_assessment"


def test_hypotheses_and_analogues_are_labelled_and_unknown_domains_are_context() -> None:
    assert DOMAIN_LAYERS["rotation"] == "hypothesis"
    assert DOMAIN_LAYERS["similarity"] == "historical_analogue"
    assert DOMAIN_LAYERS["derivatives"] == "risk_reading"
    assert _layer("a_domain_nobody_declared") == "context_reading"
    assert set(DOMAIN_LAYERS.values()) <= set(LAYERS)


# ------------------------------------------------------------------ gaps are not neutral


def test_live_state_missing_evidence_is_a_gap_and_never_a_signal() -> None:
    brief = _brief(_stored(live_state_payload()))
    assert brief["assessment"]["stance"]["final"] == "Insufficient Evidence"
    assert brief["data_gaps"]["has_gaps"] is True
    unusable = {
        g["domain"] for g in brief["data_gaps"]["items"] if g["kind"] == "reading_not_usable"
    }
    assert {"institutional", "liquidity", "macro", "market_structure"} <= unusable
    counted = {s["domain"] for s in brief["signals"]}
    assert counted.isdisjoint({"institutional", "liquidity", "macro", "market_structure"})
    reasons = [
        r
        for g in brief["data_gaps"]["items"]
        if g["kind"] == "reading_not_usable"
        for r in g["reasons"]
    ]
    assert reasons  # the source's own reason text is carried, not paraphrased
    assert brief["uncertainty"]["confidence"] == "Insufficient Evidence"


def test_a_missing_cap_source_is_reported_and_never_strengthens_the_stance() -> None:
    full = _brief(_bullish())
    payload = _stored(make_payload(["S2", "S1", "N", "S1", "S2"], regime=None))
    brief = _brief(payload)
    view, _ = _contracts(payload)
    assert brief["assessment"]["stance"] == view["stance"]
    assert brief["uncertainty"]["limited_by_caps"] is True
    assert brief["uncertainty"]["binding_caps"]
    assert full["uncertainty"]["limited_by_caps"] is False
    assert any(
        g["kind"] in ("unavailable_component", "unavailable_tool", "reading_not_usable")
        for g in brief["data_gaps"]["items"]
    )


def test_a_clean_snapshot_reports_conflict_state_exactly_as_the_source_does() -> None:
    payload = _stored(make_payload(["S2", "S1", "N", "S1", "S2"], has_conflicts=True))
    view, _ = _contracts(payload)
    brief = _brief(payload)
    u = brief["uncertainty"]
    assert u["directional_conflict"] == view["conflict"]["directional"]
    assert u["conflicting_tools"] == view["conflict"]["conflicting_tools"]
    assert u["contradictions"] == view["conflict"]["contradictions"]


def test_investment_state_not_conclusive_reasons_appear_as_gaps() -> None:
    view, investment = _contracts(_bullish())
    brief = build_advisor_brief(view, investment, "BTC")
    wanted = investment["assets"]["BTC"]["why_not_conclusive"]
    got = [g for g in brief["data_gaps"]["items"] if g["kind"] == "investment_state_not_conclusive"]
    assert [(g["reason_id"], g["ref"]) for g in got] == [(w["reason_id"], w["ref"]) for w in wanted]


def test_a_gated_assessment_is_reported_as_gated() -> None:
    view, investment = _contracts(_bullish())
    gated = copy.deepcopy(investment)
    gated["assessment"] = {"performed": False, "gate_reasons": ["DI-GATE-INTEGRITY"]}
    brief = build_advisor_brief(view, gated, "BTC")
    assert brief["assessment"]["investment_state"]["gated"] is True
    assert brief["assessment"]["investment_state"]["gate_reasons"] == ["DI-GATE-INTEGRITY"]


# ------------------------------------------------------------------ risk, invalidation, trace


def test_invalidation_conditions_and_results_are_copied_with_their_monitor_fields() -> None:
    view, investment = _contracts(_bullish())
    brief = build_advisor_brief(view, investment, "BTC")
    source = investment["assets"]["BTC"]["invalidation"]
    assert brief["invalidation"]["summary"] == source["summary"]
    assert [(c["condition_id"], c["result"]) for c in brief["invalidation"]["conditions"]] == [
        (c["condition_id"], c["result"]) for c in source["conditions"]
    ]
    assert brief["reassessment"]
    assert brief["risk"]["findings"] is not None
    assert brief["risk"]["investment_risk_assessment"]["state"] == "assessed"


def test_without_a_risk_assessment_findings_and_invalidation_are_absent_not_invented() -> None:
    brief = _brief(_stored(live_state_payload()))
    assert brief["risk"]["findings"] is None
    assert brief["invalidation"] is None
    assert brief["risk"]["investment_risk_assessment"]["state"] == "not_applicable"


def test_every_referenced_field_is_traceable_and_unknown_ones_say_so() -> None:
    brief = _brief(_bullish())
    referenced = {f for s in brief["signals"] for f in s["field_ids"]}
    referenced |= {f for c in brief["invalidation"]["conditions"] for f in c["monitor_field_ids"]}
    referenced |= {f for r in brief["reassessment"] for f in r["field_ids"]}
    assert referenced
    assert referenced <= set(brief["field_trace"])
    assert all("display" in entry for entry in brief["field_trace"].values())


def test_known_snapshot_fields_resolve_to_their_display_and_category() -> None:
    view, investment = _contracts(_bullish())
    fid = view["evidence"]["supportive"][0]["field_ids"][0]
    view = copy.deepcopy(view)
    view["technical"]["fields"] = [
        {
            "field_id": fid,
            "display": "12.3 (fixture)",
            "evidence_category": "calculated",
            "quality_status": "ok",
            "unit": None,
            "source": "fixture",
        }
    ]
    brief = build_advisor_brief(view, investment, "BTC")
    assert brief["field_trace"][fid]["display"] == "12.3 (fixture)"
    assert brief["field_trace"][fid]["evidence_category"] == "calculated"


# ------------------------------------------------------------------ unsupported claims


def test_the_briefs_own_text_has_no_directive_certainty_or_verdict_language() -> None:
    texts = [n["text"] for n in NOT_CLAIMED] + list(LAYERS.values())
    for text in texts:
        for name, pattern in BANNED_PATTERNS.items():
            assert not pattern.search(text), (name, text)


def test_not_claimed_states_the_required_boundaries() -> None:
    ids = {n["id"] for n in NOT_CLAIMED}
    assert ids >= {
        "ADV-NOT-ADVICE",
        "ADV-NOT-PREDICTION",
        "ADV-NOT-PROFITABILITY",
        "ADV-HYPOTHESES-ARE-NOT-FACTS",
        "ADV-NO-TRADING",
        "ADV-UNAVAILABLE-IS-NOT-NEUTRAL",
    }
    assert _brief(_bullish())["not_claimed"] == [dict(n) for n in NOT_CLAIMED]


# ------------------------------------------------------------------ input validation


def test_mismatched_asset_snapshot_or_version_is_refused() -> None:
    view, investment = _contracts(_bullish())
    with pytest.raises(AdvisorInputError):
        build_advisor_brief(view, investment, "ETH")

    other = _stored(make_payload(["N", "N", "N", "N", "N"]))
    _, other_investment = _contracts(other)
    with pytest.raises(AdvisorInputError, match="different snapshots"):
        build_advisor_brief(view, other_investment, "BTC")

    bad = copy.deepcopy(view)
    bad["contract_version"] = "decision_view.v9"
    with pytest.raises(AdvisorInputError):
        build_advisor_brief(bad, investment, "BTC")
    bad_inv = copy.deepcopy(investment)
    bad_inv["contract_version"] = "investment_decision.v9"
    with pytest.raises(AdvisorInputError):
        build_advisor_brief(view, bad_inv, "BTC")
