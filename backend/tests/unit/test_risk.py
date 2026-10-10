"""Risk & Invalidation (Phase 48; ADR-0085): ``cfi.intelligence.risk``.

Synthetic chains are built exactly as the endpoint builds them (unified -> confirmation ->
opportunities -> ranking), plus a synthetic ``risk_view.v0`` standing in for the decision engine, so
each risk level, cap state, evidence state and gate is exercised without the decision engine. The
real decision-engine adapter is covered in ``test_risk_view.py``."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest

from cfi.decision.universe import SCOPE_DOMAINS
from cfi.intelligence import (
    RiskInputError,
    build_confirmation,
    build_opportunities,
    build_ranking,
    build_risk_invalidation,
)
from cfi.intelligence.risk import CONTRACT_VERSION, _invalidation
from cfi.intelligence.risk_universe import (
    CHECKS,
    DECLARED_UNAVAILABLE,
    INVALIDATION_RESULTS,
    RESULTS,
    RISK_PARAMS_V0,
)
from tests.unit.test_confirmation import _context, _unified

SCOPES = tuple(SCOPE_DOMAINS)
Mutate = Callable[[dict[str, Any]], None]
ALL = {"institutional": "S", "whale": "S", "liquidity": "S"}  # every asset is a candidate
BOTH = {"institutional": "S", "whale": "S"}
DIMS = ("market", "liquidity", "leverage", "volatility", "narrative", "data_quality")
FIELDS: dict[str, list[str]] = {
    "market": ["get_regime.score.band", "get_market_structure.score.band", "get_macro.score.band"],
    "liquidity": ["get_liquidity.score.band"],
    "leverage": ["get_derivatives.score.band"],
    "volatility": ["get_anomaly.score.band"],
    "narrative": ["get_retail.score.band"],
    "data_quality": [],
}
RESULT_IDS = {r for r, _ in RESULTS}
INV_IDS = {r for r, _ in INVALIDATION_RESULTS}
IDENTITY = (
    "row_id",
    "uuid",
    "row_created_at",
    "as_of",
    "knowledge_time",
    "snapshot_version",
    "producer_payload_hash",
    "producer_hash_check",
    "decision_input_hash",
)


# ------------------------------------------------------------------------------- builders
def _prep(u: dict[str, Any]) -> None:
    u["snapshot"].update(
        snapshot_data_quality_state="ok", source_conflicts=False, producer_hash_check="verified"
    )
    u["data_quality"].update(unavailable_tools=[], degraded_tools=[], conflicting_tools=[])
    u["global_domains"].append(_context("retail", "Risk", "S"))


def _all_entries(u: dict[str, Any]) -> list[dict[str, Any]]:
    return [*u["global_domains"], *(e for a in u["assets"].values() for e in a["domains"])]


def _unverify(u: dict[str, Any], *domains: str) -> None:
    """Make a context source's freshness unverifiable (as risk-role sources are live)."""
    for e in _all_entries(u):
        if e["domain"] in domains:
            e.update(freshness="not_assessed", freshness_records=[])


def _view(
    opp: dict[str, Any],
    levels: dict[str, str] | None = None,
    *,
    evaluated: bool = True,
    caps: tuple[tuple[str, bool], ...] = (),
    source: dict[str, str] | None = None,
    cap_u: tuple[str, ...] = (),
) -> dict[str, Any]:
    levels = levels or {}
    cap_fields = {
        "RC-01": ["get_derivatives.score.band"],
        "RC-02": ["get_anomaly.score.band"],
        "RC-03": ["get_regime.score.band"],
        "RC-04": ["get_regime.score.band"],
    }
    scope_view = {
        "caps_evaluated": evaluated,
        "risks": [
            {
                "dimension": d,
                "level": levels.get(d, "Low"),
                "reason_ids": [f"RK-{d}"],
                "field_ids": list(FIELDS[d]),
            }
            for d in DIMS
        ],
        "max_risk": "Low",
        "observed_caps": [
            {
                "rule_id": rule,
                "binding": binding,
                "source_field_ids": cap_fields[rule],
                "reason_id": f"CAP-{rule}",
            }
            for rule, binding in caps
        ],
        "cap_u": [
            {
                "rule_id": rule,
                "cap_source": "derivatives",
                "source_field_id": "get_derivatives.score.band",
                "binding": False,
                "reason_id": "CAP-U",
            }
            for rule in cap_u
        ],
        "source_status": {"regime": "ok", "derivatives": "ok", "anomaly": "ok", **(source or {})},
    }
    return {
        "contract_version": "risk_view.v0",
        "source": "decision_engine",
        "decision": {"methodology_version": "m.v0", "parameter_version": "p.v0"},
        "identity": {k: opp["snapshot"].get(k) for k in IDENTITY},
        "scopes": {s: copy.deepcopy(scope_view) for s in SCOPES},
    }


def _chain(
    codes: dict[str, str] | None = None,
    *,
    mutate: Mutate | None = None,
    **view_args: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    u = _unified(ALL if codes is None else codes)
    _prep(u)
    if mutate is not None:
        mutate(u)
    opp = build_opportunities(u, build_confirmation(u))
    return opp, build_ranking(opp), _view(opp, **view_args)


def _run(
    codes: dict[str, str] | None = None, *, mutate: Mutate | None = None, **view_args: Any
) -> dict[str, Any]:
    opp, ranking, view = _chain(codes, mutate=mutate, **view_args)
    return build_risk_invalidation(opp, ranking, view)


def _f(out: dict[str, Any], check_id: str, scope: str = "BTC") -> dict[str, Any]:
    findings = (
        out["market_risks"]["findings"]
        if check_id in {"RI-MKT-01", "RI-LIQ-01", "RI-VOL-01", "RI-NAR-01"}
        else out["integrity"]["findings"]
        if check_id.startswith("RI-INT")
        else out["assets"][scope]["findings"]
    )
    return next(f for f in findings if f["check_id"] == check_id)


def _inv(out: dict[str, Any], cid: str, scope: str = "BTC") -> dict[str, Any]:
    return next(
        c for c in out["assets"][scope]["invalidation"]["conditions"] if c["condition_id"] == cid
    )


def _refused(
    fn: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None], match: str | None = None
) -> None:
    opp, ranking, view = _chain()
    fn(opp, ranking, view)
    with pytest.raises(RiskInputError, match=match):
        build_risk_invalidation(opp, ranking, view)


# --------------------------------------------------------------- structure and vocabulary
def test_a_candidate_is_assessed_with_the_full_check_catalogue() -> None:
    out = _run()
    assert out["contract_version"] == CONTRACT_VERSION == "risk_invalidation.v0"
    assert out["checks"]["version"] == "risk_checks.v0"
    assert out["parameters"] == {
        "version": "risk_params.v0",
        "detected_levels": ["Elevated", "High"],
        "visible_levels": ["Moderate"],
        "experimental": True,
    }
    assert [i["check_id"] for i in out["checks"]["items"]] == [c[0] for c in CHECKS]
    assert list(out["assets"]) == list(SCOPES)
    a = out["assets"]["BTC"]
    assert a["assessment"] == "assessed"
    assert a["assessment_reasons"] == ["RI-ASSESSED"]
    assert [f["check_id"] for f in a["findings"]] == [
        "RI-LEV-01",
        "RI-DQ-01",
        "RI-EVD-01",
        "RI-EVD-02",
        "RI-EVD-03",
        "RI-EVD-04",
        "RI-EVD-05",
        "RI-CAP-01",
        "RI-CAP-02",
        "RI-CAP-03",
        "RI-CAP-04",
    ]
    assert [f["check_id"] for f in out["market_risks"]["findings"]] == [
        "RI-MKT-01",
        "RI-LIQ-01",
        "RI-VOL-01",
        "RI-NAR-01",
    ]
    assert [f["check_id"] for f in out["integrity"]["findings"]] == [
        "RI-INT-01",
        "RI-INT-02",
        "RI-INT-03",
    ]
    assert a["ranking_context"]["used_for_risk"] is False
    assert out["assessment"] == {"performed": True, "gate_reasons": []}


def test_every_result_is_in_the_declared_vocabulary() -> None:
    for out in (_run(), _run(levels={"leverage": "High", "market": "Not assessed"})):
        findings = [
            *out["integrity"]["findings"],
            *out["market_risks"]["findings"],
            *(f for a in out["assets"].values() for f in a["findings"]),
        ]
        assert {f["result"] for f in findings} <= RESULT_IDS
        for a in out["assets"].values():
            if a["invalidation"]:
                assert {c["result"] for c in a["invalidation"]["conditions"]} <= INV_IDS


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_there_is_no_score_probability_rating_or_recommendation_field() -> None:
    out = _run(levels={"leverage": "High"}, caps=(("RC-01", True),))
    banned = ("probab", "safe", "rating", "recommend", "buy", "sell", "target", "position")
    exact = {"score", "risk_score", "confidence", "grade", "action", "signal"}
    for key in _keys(out):
        assert key.lower() not in exact, key
        assert not any(b in key.lower() for b in banned), key
    assert out["notice"]["id"] == "risk_findings_not_a_safety_rating"
    assert "not a probability of loss" in out["notice"]["text"]


def test_the_output_is_json_serialisable_and_lists_the_limitations() -> None:
    out = _run()
    assert json.loads(json.dumps(out)) == out
    ids = {x["id"] for x in out["limitations"]}
    assert {
        "risk_levels_are_design_judgments",
        "risk_role_freshness_unverified",
        "overlapping_inputs",
        "caps_depend_on_raw_stance",
        "cap_invalidation_not_established",
    } <= ids


# ------------------------------------------------------------------- level -> result
@pytest.mark.parametrize("verified", [True, False])
@pytest.mark.parametrize(
    ("level", "verified_result", "unverified_result"),
    [
        ("Low", "passed", "unverified"),
        ("Moderate", "passed", "unverified"),
        ("Elevated", "detected", "detected"),
        ("High", "detected", "detected"),
        ("Not assessed", "unavailable", "unavailable"),
    ],
)
def test_a_leverage_level_maps_to_an_explicit_result(
    level: str, verified_result: str, unverified_result: str, verified: bool
) -> None:
    out = _run(
        mutate=None if verified else lambda u: _unverify(u, "derivatives"),
        levels={"leverage": level},
    )
    f = _f(out, "RI-LEV-01")
    assert f["result"] == (verified_result if verified else unverified_result)
    assert f["level"] == level
    if level != "Not assessed":
        assert f["freshness_verified"] is verified
    if level == "Moderate":
        assert "RI-LEVEL-MODERATE-VISIBLE" in f["reason_ids"]  # visible, never detected
    else:
        assert "RI-LEVEL-MODERATE-VISIBLE" not in f["reason_ids"]
    if not verified and level in ("Low", "Moderate"):
        assert "RI-FRESHNESS-UNVERIFIED" in f["reason_ids"]


def test_elevated_and_high_are_detected_and_moderate_is_not() -> None:
    for level, result in (("Elevated", "detected"), ("High", "detected"), ("Moderate", "passed")):
        assert _f(_run(levels={"narrative": level}), "RI-NAR-01")["result"] == result
    assert RISK_PARAMS_V0.detected_levels == ("Elevated", "High")


@pytest.mark.parametrize(
    ("check", "dim"),
    [
        ("RI-MKT-01", "market"),
        ("RI-LIQ-01", "liquidity"),
        ("RI-VOL-01", "volatility"),
        ("RI-NAR-01", "narrative"),
    ],
)
def test_market_wide_risks_are_reported_once_and_listed_on_every_candidate(
    check: str, dim: str
) -> None:
    out = _run(levels={dim: "High"})
    assert _f(out, check)["result"] == "detected"
    assert all(check not in {f["check_id"] for f in a["findings"]} for a in out["assets"].values())
    assert all(a["market_risks_detected"] == [check] for a in out["assets"].values())


def test_the_decision_engines_reason_ids_are_carried_unchanged() -> None:
    f = _f(_run(levels={"leverage": "Elevated"}), "RI-LEV-01")
    assert f["engine_reason_ids"] == ["RK-leverage"]
    assert f["field_ids"] == ["get_derivatives.score.band"]
    assert f["source_ids"] == ["get_derivatives"]


def test_the_data_quality_level_comes_from_counts_so_a_low_reading_is_never_passed() -> None:
    f = _f(_run(), "RI-DQ-01")
    assert f["freshness_verified"] is None
    assert f["result"] == "unverified"
    assert f["reason_ids"] == ["RI-FRESHNESS-NOT-APPLICABLE"]
    assert _f(_run(levels={"data_quality": "High"}), "RI-DQ-01")["result"] == "detected"


def test_an_adverse_reading_is_reported_even_when_freshness_is_unverified() -> None:
    out = _run(mutate=lambda u: _unverify(u, "derivatives"), levels={"leverage": "High"})
    f = _f(out, "RI-LEV-01")
    assert (f["result"], f["freshness_verified"]) == ("detected", False)


def test_a_pass_requires_verified_fresh_evidence_for_every_contributor() -> None:
    def stale(u: dict[str, Any]) -> None:
        for e in _all_entries(u):
            if e["domain"] == "derivatives":
                e.update(freshness="stale", freshness_records=[{"path": "p", "status": "stale"}])

    f = _f(_run(mutate=stale), "RI-LEV-01")
    assert f["result"] == "unverified"  # stale is not proof of risk, and not reassurance
    assert f["freshness_verified"] is False


def test_a_dimension_without_a_matching_source_entry_is_never_passed() -> None:
    opp, ranking, view = _chain()
    for s in SCOPES:
        view["scopes"][s]["risks"][1]["field_ids"] = ["get_missing.score.band"]
    g = _f(build_risk_invalidation(opp, ranking, view), "RI-LIQ-01")
    assert g["result"] == "unverified"
    assert g["freshness_verified"] is False
    assert g["contributors"] == []


# ------------------------------------------------------------------------------- caps
@pytest.mark.parametrize(
    ("rule", "check"),
    [
        ("RC-01", "RI-CAP-01"),
        ("RC-02", "RI-CAP-02"),
        ("RC-03", "RI-CAP-03"),
        ("RC-04", "RI-CAP-04"),
    ],
)
@pytest.mark.parametrize("binding", [True, False])
def test_an_observed_cap_is_a_risk_finding_and_binding_is_reported_separately(
    rule: str, check: str, binding: bool
) -> None:
    out = _run(caps=((rule, binding),))
    f = _f(out, check)
    assert f["result"] == "detected"
    assert f["reason_ids"] == ["RI-CAP-OBSERVED"]
    assert f["detail"]["observed"] is True
    assert f["detail"]["binding"] is binding
    others = [c for c in ("RI-CAP-01", "RI-CAP-02", "RI-CAP-03", "RI-CAP-04") if c != check]
    assert all(_f(out, c)["result"] == "passed" for c in others)
    inv = _inv(out, "INV-06")
    assert inv["detail"]["observed"] == [rule]
    assert inv["detail"]["binding"] == ([rule] if binding else [])


@pytest.mark.parametrize("caps", [(("RC-01", True),), (("RC-01", False), ("RC-03", True))])
def test_a_cap_is_never_treated_as_an_invalidation(caps: tuple[tuple[str, bool], ...]) -> None:
    out = _run(caps=caps)
    inv = _inv(out, "INV-06")
    assert inv["result"] == "cannot_evaluate"
    assert inv["reason_ids"] == ["RI-INV-CAP-RELATIONSHIP-NOT-ESTABLISHED"]
    assert out["assets"]["BTC"]["invalidation"]["summary"] == "not_fully_evaluable"
    assert "triggered" not in {
        c["result"] for c in out["assets"]["BTC"]["invalidation"]["conditions"]
    }


def test_caps_evaluated_for_a_bullish_stance_and_none_observed_pass_on_verified_sources() -> None:
    out = _run()
    for c in ("RI-CAP-01", "RI-CAP-02", "RI-CAP-03", "RI-CAP-04"):
        f = _f(out, c)
        assert (f["result"], f["freshness_verified"]) == ("passed", True)
    assert _inv(out, "INV-06")["result"] == "not_triggered"
    assert out["assets"]["BTC"]["invalidation"]["summary"] == "none_triggered"


def test_caps_not_evaluated_are_not_applicable_and_never_read_as_absent() -> None:
    out = _run(evaluated=False)
    for c in ("RI-CAP-01", "RI-CAP-02", "RI-CAP-03", "RI-CAP-04"):
        f = _f(out, c)
        assert f["result"] == "not_applicable"
        assert f["applicable"] is False
        assert f["reason_ids"] == ["RI-CAP-NOT-EVALUATED-RAW-NOT-BULLISH"]
        assert f["detail"]["caps_evaluated"] is False
    inv = _inv(out, "INV-06")
    assert inv["result"] == "cannot_evaluate"
    assert inv["reason_ids"] == ["RI-CAP-NOT-EVALUATED-RAW-NOT-BULLISH"]


def test_an_observed_cap_is_reported_even_if_the_view_marks_caps_unevaluated() -> None:
    out = _run(evaluated=False, caps=(("RC-02", False),))
    assert _f(out, "RI-CAP-02")["result"] == "detected"
    assert _f(out, "RI-CAP-01")["result"] == "not_applicable"


def test_an_unevaluable_cap_source_is_unavailable_not_passed_and_not_adverse() -> None:
    out = _run(
        source={"derivatives": "unavailable", "regime": "insufficient_data"}, cap_u=("CAP-U",)
    )
    assert _f(out, "RI-CAP-01")["result"] == "unavailable"
    assert _f(out, "RI-CAP-01")["reason_ids"] == ["RI-CAP-SOURCE-NOT-EVALUABLE"]
    assert _f(out, "RI-CAP-03")["result"] == "unavailable"
    assert _f(out, "RI-CAP-04")["result"] == "unavailable"
    assert _f(out, "RI-CAP-02")["result"] == "passed"
    inv = _inv(out, "INV-06")
    assert inv["result"] == "cannot_evaluate"
    assert inv["reason_ids"] == ["RI-CAP-SOURCE-NOT-EVALUABLE"]
    assert inv["detail"]["cap_u"] == ["CAP-U"]


def test_unverified_cap_sources_yield_unverified_never_passed() -> None:
    out = _run(mutate=lambda u: _unverify(u, "derivatives", "anomaly", "regime"))
    for c in ("RI-CAP-01", "RI-CAP-02", "RI-CAP-03", "RI-CAP-04"):
        f = _f(out, c)
        assert (f["result"], f["freshness_verified"]) == ("unverified", False)
        assert f["reason_ids"] == ["RI-FRESHNESS-UNVERIFIED"]
    assert _inv(out, "INV-06")["result"] == "cannot_evaluate"


def test_an_observed_cap_on_unverified_evidence_is_still_reported() -> None:
    out = _run(mutate=lambda u: _unverify(u, "regime"), caps=(("RC-03", True),))
    f = _f(out, "RI-CAP-03")
    assert (f["result"], f["freshness_verified"]) == ("detected", False)


# -------------------------------------------------------------------------- invalidation
def _asset_and_caps(
    codes: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    opp, ranking, view = _chain(codes)
    out = build_risk_invalidation(opp, ranking, view)
    caps = [f for f in out["assets"]["BTC"]["findings"] if f["category"] == "decision_caps"]
    return copy.deepcopy(opp["assets"]["BTC"]), caps, view["scopes"]["BTC"]


def _call(a: dict[str, Any], caps: list[dict[str, Any]], sv: dict[str, Any]) -> dict[str, Any]:
    result = _invalidation("BTC", a, caps, sv)
    return {c["condition_id"]: c for c in result["conditions"]} | {"_": result}


def test_every_invalidation_condition_is_listed_in_a_fixed_order_with_monitor_fields() -> None:
    out = _run()
    inv = out["assets"]["BTC"]["invalidation"]
    assert [c["condition_id"] for c in inv["conditions"]] == [f"INV-0{i}" for i in range(1, 7)]
    assert [m["condition_id"] for m in inv["monitor"]] == [f"INV-0{i}" for i in range(1, 7)]
    assert all(c["meaning"] and c["name"] for c in inv["conditions"])
    assert _inv(out, "INV-01")["monitor_field_ids"] == [
        "get_institutional.score.band",
        "get_whale.score.band",
    ]
    assert {c["result"] for c in inv["conditions"]} == {"not_triggered"}
    assert inv["summary"] == "none_triggered"


def test_inv_01_triggers_when_no_asset_specific_family_supports_and_not_otherwise() -> None:
    a, caps, sv = _asset_and_caps()
    a["basis"]["asset_specific_supporting_families"] = []
    c = _call(a, caps, sv)
    assert c["INV-01"]["result"] == "triggered"
    assert c["_"]["summary"] == "triggered"


def test_inv_02_triggers_below_the_confirmation_minimum() -> None:
    a, caps, sv = _asset_and_caps()
    a["basis"]["supportive_families"] = ["institutional_flows"]
    c = _call(a, caps, sv)
    assert c["INV-02"]["result"] == "triggered"
    assert c["INV-02"]["detail"]["minimum"] == 2


def test_inv_03_triggers_on_adverse_families_only() -> None:
    a, caps, sv = _asset_and_caps()
    assert _call(a, caps, sv)["INV-03"]["result"] == "not_triggered"
    a["basis"]["adverse_families"] = ["derivatives_positioning"]
    c = _call(a, caps, sv)
    assert c["INV-03"]["result"] == "triggered"
    assert c["INV-03"]["detail"]["adverse_families"] == ["derivatives_positioning"]


_UNVERIFIED_STATES = {
    "stale": {"freshness": "stale", "freshness_records": [{"path": "p", "status": "stale"}]},
    "not_assessed": {"freshness": "not_assessed", "freshness_records": []},
    "no_records": {"freshness": "fresh", "freshness_records": []},
    "no_data": {"freshness": "no_data", "freshness_records": [{"path": "p", "status": "no_data"}]},
    "partial": {"quality_flags": ["partial"]},
}


def _single_family_candidate(opp: dict[str, Any]) -> None:
    """Self-consistent but contradictory: confirmed_supportive on a single supporting family."""
    a = opp["assets"]["SOL"]
    a["evidence_refs"] = [
        m
        for m in a["evidence_refs"]
        if m["state"] != "supportive" or m["shared_across_assets"] is False
    ]
    a["basis"]["supportive_families"] = list(a["basis"]["asset_specific_supporting_families"])
    a["basis"]["market_wide_supporting_families"] = []


def test_a_candidate_below_the_family_minimums_is_refused_not_reported_as_invalidated() -> None:
    opp, _, view = _chain(ALL)
    _single_family_candidate(opp)
    ranking = build_ranking(opp)  # Phase 47 re-verification accepts it; Phase 48 must not
    with pytest.raises(RiskInputError, match="minimums"):
        build_risk_invalidation(opp, ranking, view)


def test_a_candidate_with_no_asset_specific_family_is_refused() -> None:
    def tamper(o: dict[str, Any], r: dict[str, Any], v: dict[str, Any]) -> None:
        o["assets"]["BTC"]["basis"]["asset_specific_supporting_families"] = []

    _refused(tamper)


def test_every_valid_candidate_meets_the_minimums_so_inv_01_and_inv_02_are_not_triggered() -> None:
    for codes in (ALL, BOTH, {"institutional": "S", "liquidity": "S"}):
        out = _run(codes)
        for scope, asset in out["assets"].items():
            if asset["assessment"] == "assessed":
                assert _inv(out, "INV-01", scope)["result"] == "not_triggered"
                assert _inv(out, "INV-02", scope)["result"] == "not_triggered"


@pytest.mark.parametrize("state", sorted(_UNVERIFIED_STATES))
def test_inv_04_is_cannot_evaluate_for_stale_or_unverified_support_never_triggered(
    state: str,
) -> None:
    a, caps, sv = _asset_and_caps()
    for m in a["evidence_refs"]:
        if m["domain"] == "institutional":
            m.update(_UNVERIFIED_STATES[state])
    c = _call(a, caps, sv)
    assert c["INV-04"]["result"] == "cannot_evaluate"
    assert c["INV-04"]["reason_ids"] == [
        "RI-FRESHNESS-UNVERIFIED",
        "RI-FRESHNESS-LOSS-NOT-OBSERVABLE",
    ]
    assert c["INV-04"]["detail"]["verified_members"] < c["INV-04"]["detail"]["supporting_members"]
    # unverified support makes the other support conditions unestablished too, not invalid
    assert c["INV-01"]["result"] == "cannot_evaluate"
    assert c["INV-02"]["result"] == "cannot_evaluate"
    assert c["_"]["summary"] == "not_fully_evaluable"  # nothing was invalidated


def test_inv_04_is_not_triggered_only_when_every_supporting_member_is_verified() -> None:
    a, caps, sv = _asset_and_caps()
    c = _call(a, caps, sv)
    assert c["INV-04"]["result"] == "not_triggered"
    assert c["INV-04"]["reason_ids"] == []
    assert c["INV-04"]["detail"]["verified_members"] == c["INV-04"]["detail"]["supporting_members"]


def test_inv_04_never_triggers_and_states_why() -> None:
    from cfi.intelligence.risk_universe import INVALIDATION_CONDITIONS, LIMITATIONS

    meaning = next(m for i, _, m in INVALIDATION_CONDITIONS if i == "INV-04")
    assert "never triggered" in meaning
    assert "freshness_loss_not_observable" in {i for i, _ in LIMITATIONS}
    # live-style input: a stale member yields cannot_evaluate end to end, not an invalidation
    out = _run(ALL, mutate=lambda u: _unverify(u, "institutional"))
    for scope, asset in out["assets"].items():
        if asset["assessment"] == "assessed":
            assert _inv(out, "INV-04", scope)["result"] != "triggered"


def test_a_genuine_invalidation_is_still_triggered_whatever_the_freshness() -> None:
    a, caps, sv = _asset_and_caps()
    a["basis"]["adverse_families"] = ["derivatives_positioning"]
    for m in a["evidence_refs"]:
        m.update(_UNVERIFIED_STATES["stale"])
    c = _call(a, caps, sv)
    assert c["INV-03"]["result"] == "triggered"  # adverse evidence is a current fact
    assert c["INV-04"]["result"] == "cannot_evaluate"
    assert c["_"]["summary"] == "triggered"


def test_inv_05_is_not_triggered_because_a_gate_withholds_the_whole_assessment() -> None:
    assert _inv(_run(), "INV-05")["result"] == "not_triggered"


def test_unverified_support_is_not_counted_as_support() -> None:
    def unverified(u: dict[str, Any]) -> None:
        for e in _all_entries(u):
            if e["domain"] == "institutional":
                e.update(freshness="not_assessed", freshness_records=[])

    out = _run(ALL, mutate=unverified)
    assessed = [s for s, a in out["assets"].items() if a["assessment"] == "assessed"]
    assert assessed  # the asset-specific whale family still supports BTC and ETH
    for scope in assessed:
        assert "get_institutional.score.band" not in _inv(out, "INV-01", scope)["monitor_field_ids"]
        assert "get_institutional.score.band" not in _inv(out, "INV-04", scope)["monitor_field_ids"]


# --------------------------------------------------------------------------- evidence
def test_evd_01_and_02_describe_only_the_eligible_members_they_examined() -> None:
    from cfi.intelligence.risk_universe import CHECKS

    out = _run()
    for c in ("RI-EVD-01", "RI-EVD-02"):
        f = _f(out, c)
        assert f["result"] == "passed"
        assert f["freshness_verified"] is True  # computed from the examined members, not assumed
        assert f["detail"]["examined"] == "eligible_members_only"
        assert f["detail"]["adverse_members"] == 0
        assert f["detail"]["members"] == len(f["contributors"])
        text = next(t for i, _, _, t in CHECKS if i == c)
        assert text.startswith("Among the eligible")
        assert "not examined" in text
        assert "safe" not in text.lower()
    assert _f(out, "RI-EVD-01")["field_ids"] == [
        "get_institutional.score.band",
        "get_whale.score.band",
    ]
    assert "get_liquidity.score.band" in _f(out, "RI-EVD-02")["field_ids"]
    assert "evidence_checks_limited_in_scope" in {x["id"] for x in out["limitations"]}


def test_a_pass_on_excluded_evidence_is_not_claimed() -> None:
    out = _run({**BOTH, "market_structure": "U"})
    f = _f(out, "RI-EVD-02")
    assert f["result"] == "passed"  # the unusable member is not examined by this check ...
    assert "market_structure" not in {c["domain"] for c in f["contributors"]}
    assert _f(out, "RI-EVD-03")["result"] == "detected"  # ... and is reported by RI-EVD-03


def test_an_empty_scope_is_unavailable_not_passed() -> None:
    from cfi.intelligence.risk import _evidence

    a, _, _ = _asset_and_caps()
    a["evidence_refs"] = [m for m in a["evidence_refs"] if m["shared_across_assets"] is False]
    f = next(x for x in _evidence("BTC", a) if x["check_id"] == "RI-EVD-02")
    assert f["result"] == "unavailable"
    assert f["reason_ids"] == ["RI-NO-ELIGIBLE-MEMBERS-IN-SCOPE"]
    assert f["freshness_verified"] is None


def test_evd_01_is_unverified_when_an_examined_member_is_not_verified() -> None:
    from cfi.intelligence.risk import _evidence

    a, _, _ = _asset_and_caps()
    for m in a["evidence_refs"]:
        if m["domain"] == "institutional":
            m.update(freshness="not_assessed", freshness_records=[])
    f = next(x for x in _evidence("BTC", a) if x["check_id"] == "RI-EVD-01")
    assert f["result"] == "unverified"  # never a pass on unverified evidence
    assert f["freshness_verified"] is False
    assert f["reason_ids"] == ["RI-FRESHNESS-UNVERIFIED"]


def test_count_based_checks_do_not_claim_verified_freshness() -> None:
    from cfi.intelligence.risk_universe import CHECKS

    out = _run()
    for c in ("RI-EVD-04", "RI-EVD-05"):
        assert _f(out, c)["freshness_verified"] is None
        text = next(t for i, _, _, t in CHECKS if i == c)
        assert "count" in text
    assert _f(out, "RI-EVD-04")["result"] == "passed"


def test_adverse_eligible_evidence_on_a_candidate_is_an_inconsistent_input() -> None:
    def adverse(opp: dict[str, Any], ranking: dict[str, Any], view: dict[str, Any]) -> None:
        opp["assets"]["BTC"]["evidence_refs"][0]["state"] = "adverse"

    _refused(adverse)


def test_missing_evidence_is_reported_as_coverage_and_never_as_adverse() -> None:
    out = _run({**BOTH, "market_structure": "U"})
    f = _f(out, "RI-EVD-03")
    assert f["result"] == "detected"
    assert f["reason_ids"] == ["RI-MISSING-NOT-ADVERSE"]
    assert f["detail"]["unusable_domains"][0]["domain"] == "market_structure"
    assert _f(out, "RI-EVD-01")["result"] == "passed"
    assert _f(out, "RI-EVD-02")["result"] == "passed"
    assert _inv(out, "INV-03")["result"] == "not_triggered"


def test_partial_and_stale_evidence_is_missing_evidence_not_adverse() -> None:
    for code in ("U", "N~", "N*"):
        out = _run({**BOTH, "macro": code})
        assert _f(out, "RI-EVD-03")["result"] == "detected", code
        assert _f(out, "RI-EVD-01")["result"] == "passed", code
        assert _inv(out, "INV-03")["result"] == "not_triggered", code


def test_full_coverage_passes_the_coverage_check() -> None:
    f = _f(_run(), "RI-EVD-03")
    assert f["result"] == "passed"
    assert f["detail"]["coverage"]["met"] is True


def test_evidence_resting_on_one_family_is_flagged_thin() -> None:
    out = _run(ALL)
    assert _f(out, "RI-EVD-04", "BTC")["result"] == "passed"
    assert _f(out, "RI-EVD-04", "SOL")["result"] == "detected"  # no whale family for SOL
    assert _f(out, "RI-EVD-04", "SOL")["detail"]["asset_specific_supporting_families"] == [
        "institutional_flows"
    ]


def test_shared_market_wide_evidence_is_reported_and_never_a_reassurance() -> None:
    out = _run()
    f = _f(out, "RI-EVD-05")
    assert f["result"] == "detected"
    assert f["detail"]["shares_market_wide_evidence_with"] == ["ETH", "SOL", "XRP"]
    assert f["detail"]["market_wide_supporting_families"] == ["stablecoin_liquidity"]
    assert out["evidence_dependence"] == {
        "single_snapshot": True,
        "inputs": ["opportunity_ranking.v0", "opportunity_discovery.v0", "risk_view.v0"],
        "independent_confirmation": False,
        "note": out["evidence_dependence"]["note"],
    }


def test_evidence_appearing_in_several_inputs_is_counted_once() -> None:
    def duplicate(u: dict[str, Any]) -> None:
        for s in SCOPES:
            ctx = u["assets"][s]["domains"]
            ctx.append(copy.deepcopy(next(e for e in ctx if e["domain"] == "derivatives")))
        u["global_domains"].append(
            copy.deepcopy(next(e for e in u["global_domains"] if e["domain"] == "regime"))
        )

    base = _f(_run(), "RI-LEV-01")
    dup = _f(_run(mutate=duplicate), "RI-LEV-01")
    assert dup["field_ids"] == base["field_ids"] == ["get_derivatives.score.band"]
    assert len(dup["contributors"]) == len(base["contributors"]) == 1
    assert dup["result"] == base["result"]
    assert len(_f(_run(mutate=duplicate), "RI-MKT-01")["field_ids"]) == len(FIELDS["market"])


def test_duplicate_member_evidence_does_not_change_any_result() -> None:
    def duplicate(opp: dict[str, Any]) -> None:
        refs = opp["assets"]["BTC"]["evidence_refs"]
        refs.append(copy.deepcopy(next(m for m in refs if m["domain"] == "institutional")))

    opp, _, view = _chain()
    base = build_risk_invalidation(opp, build_ranking(opp), view)
    duplicate(opp)
    dup = build_risk_invalidation(opp, build_ranking(opp), view)
    assert _f(dup, "RI-EVD-01")["field_ids"] == _f(base, "RI-EVD-01")["field_ids"]
    assert len(_f(dup, "RI-EVD-01")["contributors"]) == len(_f(base, "RI-EVD-01")["contributors"])
    assert [f["result"] for f in dup["assets"]["BTC"]["findings"]] == [
        f["result"] for f in base["assets"]["BTC"]["findings"]
    ]
    assert (
        dup["assets"]["BTC"]["invalidation"]["summary"]
        == base["assets"]["BTC"]["invalidation"]["summary"]
    )


# ------------------------------------------------------------------ non-candidates
def test_non_candidates_keep_their_phase_46_status_and_reasons_and_are_never_low_risk() -> None:
    opp, ranking, view = _chain({})
    out = build_risk_invalidation(opp, ranking, view)
    for s in SCOPES:
        a = out["assets"][s]
        src = opp["assets"][s]
        assert a["status"] == src["status"] != "candidate"
        assert a["reasons"] == src["reasons"]
        assert a["assessment"] == "not_applicable"
        assert a["assessment_reasons"] == ["RI-NOT-A-CANDIDATE"]
        assert a["findings"] == []
        assert a["invalidation"] is None
        assert a["market_risks_detected"] == []
        assert a["counts"] == dict.fromkeys(RESULT_IDS, 0)
        assert a["ranking_context"]["scored"] is False


def test_a_conflicting_asset_is_not_assessed_and_its_status_is_preserved() -> None:
    opp, ranking, view = _chain({**BOTH, "liquidity": "A"})
    out = build_risk_invalidation(opp, ranking, view)
    a = out["assets"]["BTC"]
    assert a["status"] == "conflicting_evidence"
    assert a["assessment"] == "not_applicable"
    assert a["findings"] == []


def test_candidates_and_non_candidates_coexist() -> None:
    out = _run(BOTH)
    states = {s: out["assets"][s]["assessment"] for s in SCOPES}
    assert "assessed" in states.values()
    assert "not_applicable" in states.values()
    for s, state in states.items():
        if state == "assessed":
            assert out["assets"][s]["status"] == "candidate"


def test_ranking_context_is_displayed_but_never_used() -> None:
    out = _run(ALL)
    a = out["assets"]["BTC"]["ranking_context"]
    assert a["scored"] is True
    assert isinstance(a["evidence_depth"], int)
    assert a["used_for_risk"] is False
    # an asset with a different depth gets identical risk results: rank is not a risk input
    sol = out["assets"]["SOL"]
    assert sol["ranking_context"]["evidence_depth"] != a["evidence_depth"]
    assert [f["result"] for f in sol["findings"] if f["category"] == "decision_caps"] == [
        f["result"] for f in out["assets"]["BTC"]["findings"] if f["category"] == "decision_caps"
    ]


# ------------------------------------------------------------------------------ gates
def _violation(u: dict[str, Any]) -> None:
    u["data_quality"]["look_ahead_violations"] = ["tool_results.x.freshness"]


def _mismatch(u: dict[str, Any]) -> None:
    u["snapshot"]["producer_hash_check"] = "mismatch"


@pytest.mark.parametrize(
    ("mutate", "reasons", "int01", "int02"),
    [
        (_violation, ["RI-GATE-LOOK-AHEAD"], "detected", "passed"),
        (_mismatch, ["RI-GATE-INTEGRITY"], "passed", "detected"),
    ],
)
def test_an_integrity_gate_withholds_every_assessment(
    mutate: Mutate, reasons: list[str], int01: str, int02: str
) -> None:
    out = _run(mutate=mutate)
    assert out["assessment"] == {"performed": False, "gate_reasons": reasons}
    assert _f(out, "RI-INT-01")["result"] == int01
    assert _f(out, "RI-INT-02")["result"] == int02
    assert {f["result"] for f in out["market_risks"]["findings"]} == {"withheld"}
    for s in SCOPES:
        a = out["assets"][s]
        assert a["status"] == "blocked"
        assert a["assessment"] == "withheld"
        assert a["assessment_reasons"] == ["RI-WITHHELD-BLOCKED"]
        assert a["findings"] == []
        assert a["invalidation"] is None
        assert a["market_risks_detected"] == []


def test_a_gate_never_produces_a_reassuring_assessment() -> None:
    for mutate in (_violation, _mismatch):
        out = _run(mutate=mutate)
        everything = [
            *out["market_risks"]["findings"],
            *(f for a in out["assets"].values() for f in a["findings"]),
        ]
        assert "passed" not in {f["result"] for f in everything}
        assert all(a["invalidation"] is None for a in out["assets"].values())


def test_both_gates_are_reported_together_and_non_candidates_keep_their_status() -> None:
    def both(u: dict[str, Any]) -> None:
        _violation(u)
        _mismatch(u)

    out = _run({**BOTH, "liquidity": "A"}, mutate=both)
    assert out["assessment"]["gate_reasons"] == ["RI-GATE-LOOK-AHEAD", "RI-GATE-INTEGRITY"]
    assert _f(out, "RI-INT-01")["result"] == "detected"
    assert _f(out, "RI-INT-02")["result"] == "detected"
    a = out["assets"]["BTC"]
    assert a["status"] == "conflicting_evidence"  # never converted to blocked
    assert a["assessment"] == "not_applicable"


@pytest.mark.parametrize("check", ["verified", "unverified", None])
def test_other_hash_results_do_not_gate_but_only_a_verified_hash_passes(check: str | None) -> None:
    def set_check(u: dict[str, Any]) -> None:
        u["snapshot"]["producer_hash_check"] = check

    out = _run(mutate=set_check, caps=())
    assert out["assessment"]["performed"] is True
    expected = "passed" if check == "verified" else "unverified"
    assert _f(out, "RI-INT-02")["result"] == expected
    if check != "verified":
        assert _f(out, "RI-INT-02")["reason_ids"] == ["RI-HASH-UNVERIFIED"]


def test_conflicting_or_degraded_sources_are_a_detected_integrity_finding() -> None:
    for key in ("conflicting_tools", "degraded_tools"):
        out = _run(mutate=lambda u, k=key: u["data_quality"].update({k: ["get_x"]}))  # type: ignore[misc]
        f = _f(out, "RI-INT-03")
        assert f["result"] == "detected"
        assert f["reason_ids"] == ["RI-SOURCE-CONFLICT"]
        assert out["assessment"]["performed"] is True  # reported, not a gate


def test_source_conflicts_flag_and_degraded_state_are_detected() -> None:
    assert (
        _f(_run(mutate=lambda u: u["snapshot"].update(source_conflicts=True)), "RI-INT-03")[
            "result"
        ]
        == "detected"
    )
    out = _run(mutate=lambda u: u["snapshot"].update(snapshot_data_quality_state="degraded"))
    assert _f(out, "RI-INT-03")["result"] == "detected"


def test_unknown_data_quality_state_is_unverified_not_passed() -> None:
    out = _run(mutate=lambda u: u["snapshot"].update(snapshot_data_quality_state="unknown"))
    assert _f(out, "RI-INT-03")["result"] == "unverified"
    assert _f(_run(), "RI-INT-03")["result"] == "passed"


# ------------------------------------------------------------------ declared unavailable
def test_checks_without_a_verified_source_are_declared_unavailable_with_reason_codes() -> None:
    out = _run()
    items = out["unavailable_checks"]
    assert [i["check_id"] for i in items] == [d[0] for d in DECLARED_UNAVAILABLE]
    assert {i["result"] for i in items} == {"unavailable"}
    reasons = {i["check_id"]: i["reason_ids"] for i in items}
    assert reasons["RI-UNV-PORTFOLIO"] == ["RI-NOT-KNOWN-TO-PLATFORM"]
    assert reasons["RI-UNV-EXECUTION"] == ["RI-NO-VERIFIED-DATA"]
    assert all(i["note"] for i in items)


# ------------------------------------------------------------------------- counts
def test_counts_reconcile_with_the_findings() -> None:
    out = _run(levels={"leverage": "High"}, caps=(("RC-01", True),))
    a = out["assets"]["BTC"]
    for r in RESULT_IDS:
        assert a["counts"][r] == sum(1 for f in a["findings"] if f["result"] == r)
    assert sum(a["counts"].values()) == len(a["findings"])


# -------------------------------------------------- determinism, immutability, ordering
def test_the_output_is_deterministic_and_does_not_mutate_its_inputs() -> None:
    opp, ranking, view = _chain(levels={"leverage": "Elevated"}, caps=(("RC-02", False),))
    before = copy.deepcopy((opp, ranking, view))
    first = build_risk_invalidation(opp, ranking, view)
    second = build_risk_invalidation(opp, ranking, view)
    assert first == second
    assert json.dumps(first) == json.dumps(second)
    assert (opp, ranking, view) == before


def test_the_output_does_not_alias_its_inputs() -> None:
    opp, ranking, view = _chain()
    out = build_risk_invalidation(opp, ranking, view)
    out["snapshot"]["row_id"] = -1
    out["gates"]["look_ahead"]["triggered"] = True
    out["data_quality"]["platform_limits"].append("x")
    assert opp["snapshot"]["row_id"] != -1
    assert opp["gates"]["look_ahead"]["triggered"] is False
    assert "x" not in opp["data_quality"]["platform_limits"]


def test_asset_order_is_fixed_whatever_the_input_order() -> None:
    opp, ranking, view = _chain()
    reordered = {k: view["scopes"][k] for k in reversed(SCOPES)}
    view["scopes"] = reordered
    assert list(build_risk_invalidation(opp, ranking, view)["assets"]) == list(SCOPES)


def test_the_snapshot_identity_and_versions_are_carried_through() -> None:
    opp, ranking, view = _chain()
    out = build_risk_invalidation(opp, ranking, view)
    assert out["snapshot"] == opp["snapshot"]
    assert out["decision"] == view["decision"]
    assert out["source_contracts"]["ranking"] == "opportunity_ranking.v0"
    assert out["source_contracts"]["opportunity"] == "opportunity_discovery.v0"
    assert out["source_contracts"]["risk_view"] == "risk_view.v0"
    assert out["source_contracts"]["unified"] == "unified_snapshot.v0"
    assert out["gates"] == opp["gates"]
    assert out["data_quality"] == opp["data_quality"]


# --------------------------------------------------------------------------- refusals
def test_a_ranking_not_derived_from_these_opportunities_is_refused() -> None:
    _refused(lambda o, r, v: r["assets"]["BTC"].update(evidence_depth=4), "not derived")


@pytest.mark.parametrize(
    "fn",
    [
        lambda o, r, v: r.update(contract_version="opportunity_ranking.v1"),
        lambda o, r, v: v.update(contract_version="risk_view.v1"),
        lambda o, r, v: v.update(source="other"),
        lambda o, r, v: o.update(contract_version="opportunity_discovery.v1"),
        lambda o, r, v: o["source_contracts"].update(unified="unified_snapshot.v1"),
        lambda o, r, v: v["decision"].pop("methodology_version"),
    ],
)
def test_unsupported_versions_are_refused(fn: Callable[..., None]) -> None:
    _refused(fn)


@pytest.mark.parametrize("key", ["row_id", "as_of", "knowledge_time", "snapshot_version"])
def test_a_risk_view_for_a_different_snapshot_is_refused(key: str) -> None:
    _refused(lambda o, r, v: v["identity"].update({key: "different"}), "different snapshots")


def test_an_opportunity_snapshot_identity_that_differs_from_the_view_is_refused() -> None:
    def hash_differs(o: dict[str, Any], r: dict[str, Any], v: dict[str, Any]) -> None:
        v["identity"]["decision_input_hash"] = "other"

    _refused(hash_differs, "decision_input_hash")


@pytest.mark.parametrize(
    "fn",
    [
        lambda o, r, v: v["scopes"].pop("XRP"),
        lambda o, r, v: v["scopes"].update(DOGE=copy.deepcopy(v["scopes"]["XRP"])),
        lambda o, r, v: v["scopes"].update(BTC="not a mapping"),
        lambda o, r, v: v["scopes"]["BTC"].update(caps_evaluated="yes"),
        lambda o, r, v: v["scopes"]["BTC"]["risks"].pop(),
        lambda o, r, v: v["scopes"]["BTC"]["risks"][0].update(level="Catastrophic"),
        lambda o, r, v: v["scopes"]["BTC"]["risks"][0].update(dimension="vibes"),
        lambda o, r, v: v["scopes"]["BTC"]["risks"][0].update(field_ids="x"),
        lambda o, r, v: v["scopes"]["BTC"]["risks"][0].update(reason_ids=[1]),
        lambda o, r, v: v["scopes"]["BTC"].update(max_risk="Safe"),
        lambda o, r, v: v["scopes"]["BTC"].update(observed_caps=[{"rule_id": "RC-99"}]),
        lambda o, r, v: v["scopes"]["BTC"].update(
            observed_caps=[{"rule_id": "RC-01", "binding": "yes", "source_field_ids": []}]
        ),
        lambda o, r, v: v["scopes"]["BTC"].update(cap_u=["x"]),
        lambda o, r, v: v["scopes"]["BTC"]["source_status"].pop("regime"),
        lambda o, r, v: v["scopes"]["BTC"].pop("source_status"),
        lambda o, r, v: v.pop("identity"),
        lambda o, r, v: v.pop("scopes"),
    ],
)
def test_a_malformed_risk_view_is_refused(fn: Callable[..., None]) -> None:
    _refused(fn)


@pytest.mark.parametrize("dim", ["market", "liquidity", "volatility", "narrative"])
def test_market_wide_dimensions_that_differ_between_assets_are_refused(dim: str) -> None:
    def differ(o: dict[str, Any], r: dict[str, Any], v: dict[str, Any]) -> None:
        risk = next(x for x in v["scopes"]["ETH"]["risks"] if x["dimension"] == dim)
        risk["level"] = "High"

    _refused(differ, "differs between")


@pytest.mark.parametrize(
    "fn",
    [
        lambda o, r, v: o["data_quality"].pop("degraded_tools"),
        lambda o, r, v: o["data_quality"].update(conflicting_tools="x"),
        lambda o, r, v: o["data_quality"].update(unavailable_tools=[1]),
        lambda o, r, v: o["assets"]["BTC"]["context"].update(used_for_discovery=True),
        lambda o, r, v: o["assets"]["BTC"]["context"]["entries"][0].update(field_ids="x"),
        lambda o, r, v: o["assets"]["BTC"]["context"]["entries"][0].update(domain=None),
        lambda o, r, v: o["assets"]["BTC"]["evidence_refs"][0].update(field_ids=[3]),
        lambda o, r, v: o["assets"]["BTC"]["excluded_members"].append("x"),
    ],
)
def test_malformed_opportunity_context_is_refused(fn: Callable[..., None]) -> None:
    _refused(fn)


@pytest.mark.parametrize(
    "fn",
    [
        lambda o, r, v: o.pop("assets"),
        lambda o, r, v: o.pop("snapshot"),
        lambda o, r, v: o.pop("gates"),
        lambda o, r, v: o["assets"].pop("XRP"),
        lambda o, r, v: o["assets"]["BTC"].update(status="promoted"),
        lambda o, r, v: o["gates"]["look_ahead"].update(triggered=True),
        lambda o, r, v: o["gates"]["producer_hash"].update(check="mismatch"),
    ],
)
def test_inconsistent_or_malformed_opportunities_are_refused(fn: Callable[..., None]) -> None:
    _refused(fn)


@pytest.mark.parametrize("bad", [None, [], "x", 3])
def test_a_non_mapping_input_is_refused_for_each_argument(bad: object) -> None:
    opp, ranking, view = _chain()
    with pytest.raises(RiskInputError):
        build_risk_invalidation(bad, ranking, view)  # type: ignore[arg-type]
    with pytest.raises(RiskInputError):
        build_risk_invalidation(opp, bad, view)  # type: ignore[arg-type]
    with pytest.raises(RiskInputError):
        build_risk_invalidation(opp, ranking, bad)  # type: ignore[arg-type]


def test_a_candidate_beside_a_triggered_gate_is_refused() -> None:
    def gate(o: dict[str, Any], r: dict[str, Any], v: dict[str, Any]) -> None:
        o["gates"]["look_ahead"] = {"triggered": True, "violations": ["x"]}
        o["data_quality"]["look_ahead_violations"] = ["x"]

    _refused(gate)


def test_integrity_failure_is_distinct_from_an_unavailable_check() -> None:
    with pytest.raises(RiskInputError):
        build_risk_invalidation(*_tampered_view_identity())
    out = _run(source={"derivatives": "unavailable"})  # unavailable check: a normal result
    assert _f(out, "RI-CAP-01")["result"] == "unavailable"
    assert out["assessment"]["performed"] is True


def _tampered_view_identity() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    opp, ranking, view = _chain()
    view["identity"]["row_id"] = 123
    return opp, ranking, view


def test_a_failed_request_returns_no_partial_assessment() -> None:
    opp, ranking, view = _chain()
    view["scopes"]["XRP"]["risks"][0]["level"] = "Catastrophic"
    with pytest.raises(RiskInputError):
        build_risk_invalidation(opp, ranking, view)


# ------------------------------------------------------------------- the real fixtures
def test_the_real_fixture_chain_is_assessed_end_to_end() -> None:
    from cfi.intelligence import build_risk_view, build_unified_snapshot
    from tests.decision_builders import make_payload

    payload = make_payload(["S2", "S1", "N", "S1", "S2"])
    payload["snapshot_version"] = "analyst_snapshot.v1"
    unified = build_unified_snapshot(payload)
    opp = build_opportunities(unified, build_confirmation(unified))
    out = build_risk_invalidation(opp, build_ranking(opp), build_risk_view(payload))
    assert out["assets"]["BTC"]["assessment"] == "assessed"
    assert out["assets"]["BTC"]["findings"]
    assert _inv(out, "INV-06")["result"] != "triggered"
    assert json.loads(json.dumps(out)) == out
    # no stored producer hash is supplied here, so the hash can only be unverified, not passed
    assert _f(out, "RI-INT-02")["result"] == "unverified"


def test_the_live_state_snapshot_assesses_nothing_and_never_passes() -> None:
    from cfi.intelligence import build_risk_view, build_unified_snapshot
    from tests.decision_live_payload import live_state_payload

    payload = live_state_payload()
    unified = build_unified_snapshot(payload)
    opp = build_opportunities(unified, build_confirmation(unified))
    out = build_risk_invalidation(opp, build_ranking(opp), build_risk_view(payload))
    assert all(a["assessment"] == "not_applicable" for a in out["assets"].values())
    assert all(a["findings"] == [] for a in out["assets"].values())
    assert "passed" not in {f["result"] for f in out["market_risks"]["findings"]}
