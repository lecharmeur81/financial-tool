"""Opportunity Scoring & Ranking (Phase 47): ``opportunity_discovery.v0`` -> evidence depth.

Pure: no database, network, clock or model. Inputs come from the real Phase 44 -> 46 chain, built
with the Phase 45 test helper (one code per directional domain: ``S`` supportive, ``A`` adverse,
``N`` neutral, ``U`` unavailable); tampering is done on the Phase 46 output, the engine's only
input."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest

from cfi.decision.universe import SCOPE_DOMAINS
from cfi.intelligence import (
    RankingInputError,
    build_confirmation,
    build_opportunities,
    build_ranking,
    build_unified_snapshot,
)
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload
from tests.unit.test_confirmation import _unified

SCOPES = tuple(SCOPE_DOMAINS)
Mutate = Callable[[dict[str, Any]], None]


def _set(u: dict[str, Any], scope: str, domain: str, **fields: Any) -> None:
    entry = next(e for e in u["assets"][scope]["domains"] if e["domain"] == domain)
    entry.update(fields)


def _opp(
    codes: dict[str, str] | None = None, *, mutate: Mutate | None = None, **strength: Any
) -> dict[str, Any]:
    unified = _unified(codes, **strength)
    if mutate is not None:
        mutate(unified)
    return build_opportunities(unified, build_confirmation(unified))


def _rank(
    codes: dict[str, str] | None = None, *, mutate: Mutate | None = None, **strength: Any
) -> dict[str, Any]:
    return build_ranking(_opp(codes, mutate=mutate, **strength))


def _tampered(fn: Mutate, codes: dict[str, str] | None = None, **strength: Any) -> dict[str, Any]:
    opp = _opp(codes or ALL, **strength)
    fn(opp)
    return opp


def _ref(opp: dict[str, Any], scope: str, domain: str) -> dict[str, Any]:
    return next(m for m in opp["assets"][scope]["evidence_refs"] if m["domain"] == domain)


def _refused(fn: Mutate, match: str | None = None, **strength: Any) -> None:
    with pytest.raises(RankingInputError, match=match):
        build_ranking(_tampered(fn, **strength))


BOTH = {"institutional": "S", "whale": "S"}
INST = {"institutional": "S", "liquidity": "S"}
ALL = {"institutional": "S", "whale": "S", "liquidity": "S"}  # every asset is a candidate


# ------------------------------------------------------------------------------- formula
@pytest.mark.parametrize(
    ("codes", "strength", "depth"),
    [
        (BOTH, {}, 2),
        (BOTH, {"institutional": "Strong"}, 3),
        (BOTH, {"whale": "Strong"}, 3),
        (BOTH, {"institutional": "Strong", "whale": "Strong"}, 4),
        (INST, {}, 1),
        (INST, {"institutional": "Strong"}, 2),
    ],
)
def test_evidence_depth_is_families_plus_strong_families(
    codes: dict[str, str], strength: dict[str, Any], depth: int
) -> None:
    a = _rank(codes, **strength)["assets"]["BTC"]
    assert a["scored"] is True
    assert a["evidence_depth"] == depth
    c = a["components"]
    assert c["base_points"] + c["strong_bonus_points"] == depth
    assert a["ranking_reasons"][0] == "RK-SCORED"


def test_solana_and_ripple_have_no_whale_family_and_cap_at_two() -> None:
    out = _rank(INST, institutional="Strong")["assets"]
    for scope in ("SOL", "XRP"):
        assert out[scope]["evidence_depth"] == 2
        assert out[scope]["max_attainable_depth"] == 2
        assert out[scope]["components"]["asset_specific_families"] == ["institutional_flows"]
    for scope in ("BTC", "ETH"):
        assert out[scope]["max_attainable_depth"] == 4


def test_market_wide_evidence_contributes_zero_even_when_strong() -> None:
    plain = _rank({**INST, "macro": "S"})["assets"]["BTC"]
    strong = _rank({**INST, "macro": "S"}, liquidity="Strong", macro="Strong")["assets"]["BTC"]
    assert plain["evidence_depth"] == strong["evidence_depth"] == 1
    assert strong["components"]["market_wide"] == {
        "families": ["macro_backdrop", "stablecoin_liquidity"],
        "points": 0,
    }


def test_neutral_members_are_not_supporting_members() -> None:
    a = _rank({**INST, "whale": "N"}, whale="Strong")["assets"]["BTC"]
    assert a["components"]["asset_specific_families"] == ["institutional_flows"]
    assert a["evidence_depth"] == 1


def test_duplicate_members_never_inflate_the_depth() -> None:
    def duplicate(opp: dict[str, Any]) -> None:
        refs = opp["assets"]["BTC"]["evidence_refs"]
        for _ in range(3):
            copy_ = copy.deepcopy(_ref(opp, "BTC", "institutional"))
            copy_["strength"] = "Strong"
            refs.append(copy_)

    a = build_ranking(_tampered(duplicate))["assets"]["BTC"]
    assert a["components"]["asset_specific_families"] == [
        "institutional_flows",
        "onchain_large_holders",
    ]
    assert a["components"]["strong_families"] == ["institutional_flows"]  # one bonus, not three
    assert a["evidence_depth"] == 3
    detail = {d["family"]: d for d in a["components"]["family_detail"]}
    assert detail["institutional_flows"]["member_count"] == 4
    assert detail["institutional_flows"]["strong_bonus_points"] == 1


def test_a_family_with_a_strong_member_earns_the_bonus_once() -> None:
    def add_strong(opp: dict[str, Any]) -> None:
        extra = copy.deepcopy(_ref(opp, "BTC", "whale"))
        extra["strength"] = "Strong"
        opp["assets"]["BTC"]["evidence_refs"].append(extra)

    assert build_ranking(_tampered(add_strong))["assets"]["BTC"]["evidence_depth"] == 3


def test_components_reconcile_and_keep_provenance_and_versions() -> None:
    opp = _opp(BOTH, institutional="Strong")
    out = build_ranking(opp)
    a = out["assets"]["BTC"]
    detail = {d["family"]: d for d in a["components"]["family_detail"]}
    inst = _ref(opp, "BTC", "institutional")
    member = detail["institutional_flows"]["members"][0]
    for key in ("source_ids", "field_ids", "freshness_records", "quality_flags", "strength"):
        assert member[key] == inst[key]
    assert sum(d["base_points"] + d["strong_bonus_points"] for d in detail.values()) == 3
    assert out["contract_version"] == "opportunity_ranking.v0"
    assert out["parameters"]["version"] == "ranking_params.v0"
    assert out["components"]["version"] == "ranking_components.v0"
    assert out["source_contracts"]["opportunity"] == "opportunity_discovery.v0"
    assert out["source_contracts"]["opportunity_parameters"] == "opportunity_params.v0"
    assert out["snapshot"] == opp["snapshot"]
    assert out["parameters"]["experimental"] is True


# ------------------------------------------------------------- eligibility, withheld scores
@pytest.mark.parametrize(
    ("codes", "status"),
    [
        ({"institutional": "S", "liquidity": "A"}, "conflicting_evidence"),
        ({}, "insufficient_evidence"),
        ({"institutional": "S"}, "no_candidate"),
        ({"institutional": "A", "liquidity": "A"}, "no_candidate"),
        ({"liquidity": "S", "macro": "S"}, "no_candidate"),
    ],
)
def test_no_other_status_is_scored(codes: dict[str, str], status: str) -> None:
    assert status in {"conflicting_evidence", "insufficient_evidence", "no_candidate"}

    def blank(u: dict[str, Any]) -> None:
        if not codes:
            for scope in SCOPES:
                for e in u["assets"][scope]["domains"]:
                    e.update(status="insufficient_data", insufficient_data=True)

    opp = _opp(codes, mutate=blank)
    out = build_ranking(opp)
    for scope in SCOPES:
        a = out["assets"][scope]
        p46 = opp["assets"][scope]
        assert a["status"] == p46["status"]
        assert a["reasons"] == p46["reasons"]  # Phase 46 reasons preserved verbatim
        assert a["discovery_type"] == p46["discovery_type"]
        if a["status"] != "candidate":
            assert a["scored"] is False
            assert a["evidence_depth"] is None  # withheld, never 0
            assert a["components"] is None
            assert a["rank"] is None
            assert a["score_withheld_reason"] == a["status"]
            assert "RK-WITHHELD-NOT-CANDIDATE" in a["ranking_reasons"]


def test_adverse_confirmation_keeps_its_review_type_and_is_not_scored() -> None:
    a = _rank({"institutional": "A", "liquidity": "A"})["assets"]["BTC"]
    assert a["status"] == "no_candidate"
    assert a["discovery_type"] == "adverse_confirmation"
    assert a["evidence_depth"] is None


@pytest.mark.parametrize("mark", ["~", "*", "?"])
def test_stale_partial_and_unverified_evidence_cannot_be_scored(mark: str) -> None:
    out = _rank({"institutional": "S" + mark, "whale": "S" + mark, "liquidity": "S"})
    a = out["assets"]["BTC"]
    assert a["scored"] is False
    assert a["evidence_depth"] is None


def test_missing_evidence_only_lowers_the_depth() -> None:
    full = _rank(BOTH, institutional="Strong")["assets"]["BTC"]
    missing = _rank({"institutional": "S", "whale": "U", "liquidity": "S"}, institutional="Strong")[
        "assets"
    ]["BTC"]
    assert missing["evidence_depth"] < full["evidence_depth"]


# --------------------------------------------------------------------- integrity gates
def _violation(u: dict[str, Any]) -> None:
    u["data_quality"]["look_ahead_violations"] = ["tool_results.x.freshness"]


def _mismatch(u: dict[str, Any]) -> None:
    u["snapshot"]["producer_hash_check"] = "mismatch"


def test_a_look_ahead_violation_scores_and_ranks_nothing() -> None:
    out = _rank(ALL, mutate=_violation)
    assert out["scoring"] == {"performed": False, "gate_reasons": ["RK-GATE-LOOK-AHEAD"]}
    for scope in SCOPES:
        a = out["assets"][scope]
        assert a["status"] == "blocked"
        assert a["reasons"] == ["OD-LOOK-AHEAD-VIOLATION"]  # preserved, not rewritten
        assert a["evidence_depth"] is None
        assert a["rank"] is None
        assert a["rank_scope"] is None
        assert a["components"] is None
        assert a["score_withheld_reason"] == "blocked_by_integrity_gate"
        assert a["ranking_reasons"] == ["RK-GATE-LOOK-AHEAD", "RK-WITHHELD-BLOCKED"]
    assert out["gates"]["look_ahead"]["triggered"] is True


def test_a_producer_hash_mismatch_scores_and_ranks_nothing() -> None:
    out = _rank(ALL, mutate=_mismatch)
    assert out["scoring"]["gate_reasons"] == ["RK-GATE-INTEGRITY"]
    assert all(out["assets"][s]["status"] == "blocked" for s in SCOPES)
    for scope in SCOPES:
        a = out["assets"][scope]
        assert a["evidence_depth"] is None
        assert a["rank"] is None
        assert a["rank_scope"] is None
        assert a["ranking_reasons"] == ["RK-GATE-INTEGRITY", "RK-WITHHELD-BLOCKED"]


def test_both_gates_report_both_and_non_candidates_keep_their_status() -> None:
    def both(u: dict[str, Any]) -> None:
        _violation(u)
        _mismatch(u)

    out = _rank({**BOTH, "liquidity": "A"}, mutate=both)
    a = out["assets"]["BTC"]
    assert a["status"] == "conflicting_evidence"  # never converted
    assert a["score_withheld_reason"] == "conflicting_evidence"
    assert (a["evidence_depth"], a["rank"], a["rank_scope"]) == (None, None, None)
    assert a["ranking_reasons"] == [
        "RK-GATE-LOOK-AHEAD",
        "RK-GATE-INTEGRITY",
        "RK-WITHHELD-NOT-CANDIDATE",
    ]
    assert a["reasons"][-2:] == ["OD-LOOK-AHEAD-VIOLATION", "OD-SNAPSHOT-INTEGRITY"]


@pytest.mark.parametrize("check", ["verified", "unverified", None])
def test_other_hash_results_do_not_gate(check: str | None) -> None:
    def set_check(u: dict[str, Any]) -> None:
        u["snapshot"]["producer_hash_check"] = check

    out = _rank(BOTH, mutate=set_check)
    assert out["scoring"]["performed"] is True
    assert out["assets"]["BTC"]["scored"] is True


def test_a_candidate_beside_a_triggered_gate_is_refused() -> None:
    def gate(opp: dict[str, Any]) -> None:
        opp["gates"]["look_ahead"] = {"triggered": True, "violations": ["x"]}
        opp["data_quality"]["look_ahead_violations"] = ["x"]

    _refused(gate, "cannot coexist")


def test_blocked_without_a_gate_is_refused() -> None:
    def fake(opp: dict[str, Any]) -> None:
        opp["assets"]["BTC"]["status"] = "blocked"
        opp["assets"]["BTC"]["discovery_type"] = None

    _refused(fake, "without a triggered")


@pytest.mark.parametrize(
    "fn",
    [
        lambda o: o["gates"]["look_ahead"].update(triggered=True),
        lambda o: o["gates"]["look_ahead"].update(violations=["x"]),
        lambda o: o["data_quality"].update(look_ahead_violations=["x"]),
        lambda o: o["gates"]["producer_hash"].update(triggered=True),
        lambda o: o["gates"]["producer_hash"].update(check="mismatch"),
        lambda o: o["snapshot"].update(producer_hash_check="mismatch"),
        lambda o: o["gates"].pop("look_ahead"),
    ],
)
def test_contradictory_gate_fields_are_refused(fn: Mutate) -> None:
    _refused(fn)


# ----------------------------------------------------------- tampered candidates are refused
@pytest.mark.parametrize(
    "fn",
    [
        lambda o: o["assets"]["BTC"]["basis"].update(asset_specific_supporting_families=[]),
        lambda o: o["assets"]["BTC"]["basis"].update(
            asset_specific_supporting_families=["institutional_flows"]
        ),
        lambda o: o["assets"]["BTC"]["basis"].update(market_wide_supporting_families=["x"]),
        lambda o: o["assets"]["BTC"]["basis"].update(supportive_families=["institutional_flows"]),
        lambda o: o["assets"]["BTC"]["basis"].update(adverse_families=["macro_backdrop"]),
        lambda o: o["assets"]["BTC"]["basis"].update(confirmation_agreement="mixed"),
        lambda o: o["assets"]["BTC"].update(discovery_type="market_aligned_confirmation"),
        lambda o: o["assets"]["BTC"].update(discovery_type="adverse_confirmation"),
        lambda o: o["assets"]["BTC"].update(discovery_type=None),
        lambda o: o["assets"]["BTC"].update(reasons=["OD-CANDIDATE", "OD-CONFLICT"]),
        lambda o: _ref(o, "BTC", "institutional").update(freshness_records=[]),
        lambda o: _ref(o, "BTC", "institutional").update(
            freshness_records=[{"path": "p", "status": "stale"}]
        ),
        lambda o: _ref(o, "BTC", "institutional").update(quality_flags=["stale"]),
        lambda o: _ref(o, "BTC", "institutional").update(strength="Weak"),
        lambda o: _ref(o, "BTC", "institutional").update(strength="Missing"),
        lambda o: _ref(o, "BTC", "institutional").update(strength=None),
        lambda o: _ref(o, "BTC", "institutional").update(direction="A"),
        lambda o: _ref(o, "BTC", "institutional").update(state="adverse"),
        lambda o: _ref(o, "BTC", "institutional").update(family="macro_backdrop"),
        lambda o: _ref(o, "BTC", "institutional").update(shared_across_assets=True),
        lambda o: _ref(o, "BTC", "institutional").update(scope_basis="market_wide"),
        lambda o: _ref(o, "BTC", "institutional").update(domain="made_up"),
        lambda o: _ref(o, "BTC", "institutional").update(domain=["institutional"]),
        lambda o: _ref(o, "BTC", "institutional").update(domain={"institutional": 1}),
        lambda o: _ref(o, "BTC", "institutional").update(domain=None),
        lambda o: _ref(o, "BTC", "institutional").pop("freshness_records"),
        lambda o: o["assets"]["BTC"]["evidence_refs"].append(
            {**copy.deepcopy(_ref(o, "BTC", "liquidity")), "state": "adverse"}
        ),
        lambda o: o["assets"]["SOL"]["evidence_refs"].append(
            copy.deepcopy(_ref(o, "BTC", "whale"))
        ),
    ],
)
def test_an_inconsistent_candidate_refuses_the_whole_request(fn: Mutate) -> None:
    _refused(fn)


def test_relabelled_market_wide_evidence_cannot_raise_the_depth() -> None:
    def relabel(opp: dict[str, Any]) -> None:
        ref = _ref(opp, "BTC", "liquidity")
        ref.update(shared_across_assets=False, scope_basis="asset")
        ref["state"] = "supportive"
        opp["assets"]["BTC"]["basis"]["asset_specific_supporting_families"].append(
            "stablecoin_liquidity"
        )

    with pytest.raises(RankingInputError, match="mislabelled"):
        build_ranking(_tampered(relabel, {**BOTH, "liquidity": "S"}))


# ----------------------------------------------------------------- versions and malformed
@pytest.mark.parametrize(
    "fn",
    [
        lambda o: o.update(contract_version="opportunity_discovery.v1"),
        lambda o: o["parameters"].update(version="opportunity_params.v1"),
        lambda o: o["parameters"].update(min_asset_specific_confirmers=0),
        lambda o: o["parameters"].update(asset_led_min_asset_specific=1),
        lambda o: o["discovery_types"].update(version="discovery_types.v1"),
        lambda o: o["source_contracts"].update(unified="unified_snapshot.v1"),
        lambda o: o["source_contracts"].update(confirmation="cross_domain_confirmation.v1"),
        lambda o: o["source_contracts"].update(confirmation_parameters="confirmation_params.v1"),
        lambda o: o["source_contracts"].update(confirmation_families="evidence_families.v1"),
    ],
)
def test_unsupported_versions_are_refused(fn: Mutate) -> None:
    _refused(fn)


@pytest.mark.parametrize(
    "fn",
    [
        lambda o: o.pop("assets"),
        lambda o: o.pop("snapshot"),
        lambda o: o.pop("gates"),
        lambda o: o.pop("data_quality"),
        lambda o: o.pop("market_context"),
        lambda o: o.pop("parameters"),
        lambda o: o["assets"].pop("XRP"),
        lambda o: o["assets"].update(DOGE=copy.deepcopy(o["assets"]["XRP"])),
        lambda o: o["assets"].update(BTC="not a mapping"),
        lambda o: o["assets"]["BTC"].pop("basis"),
        lambda o: o["assets"]["BTC"].update(status="promoted"),
        lambda o: o["assets"]["BTC"].update(reasons="OD-CANDIDATE"),
        lambda o: o["assets"]["BTC"].update(evidence_refs={}),
        lambda o: o["assets"]["BTC"]["basis"].update(coverage={"eligible": "5", "expected": 5}),
        lambda o: o["assets"]["BTC"]["basis"].update(coverage={"eligible": True, "expected": 5}),
        lambda o: o["assets"]["ETH"]["evidence_refs"].append("not a mapping"),
    ],
)
def test_malformed_input_is_refused(fn: Mutate) -> None:
    _refused(fn)


@pytest.mark.parametrize("bad", [None, [], "x", 3])
def test_a_non_mapping_input_is_refused(bad: object) -> None:
    with pytest.raises(RankingInputError):
        build_ranking(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------- comparability and rank
def test_normal_groups_are_btc_eth_and_sol_xrp() -> None:
    out = _rank(BOTH)
    assert [g["group_id"] for g in out["groups"]] == ["BTC+ETH", "SOL+XRP"]
    assert all(g["comparability_verified"] for g in out["groups"])
    assert out["groups"][0]["expected_domains"] == list(SCOPE_DOMAINS["BTC"])
    assert out["groups"][1]["expected_domains"] == list(SCOPE_DOMAINS["SOL"])
    btc = out["assets"]["BTC"]
    assert btc["rank_scope"] == "BTC+ETH"
    assert btc["not_ranked_against"] == ["SOL", "XRP"]
    assert btc["comparability"] == {
        "group_id": "BTC+ETH",
        "verified": True,
        "comparable_with": ["ETH"],
    }
    assert "RK-NOT-COMPARABLE-ACROSS-GROUPS" in btc["notes"]


def test_a_higher_depth_ranks_above_a_lower_one_inside_a_group() -> None:
    def weaker_eth(u: dict[str, Any]) -> None:
        _set(u, "ETH", "whale", direction="N")

    out = _rank(ALL, mutate=weaker_eth)["assets"]
    assert (out["BTC"]["evidence_depth"], out["BTC"]["rank"]) == (2, 1)
    assert (out["ETH"]["evidence_depth"], out["ETH"]["rank"]) == (1, 2)
    assert out["BTC"]["ranking_reasons"] == ["RK-SCORED", "RK-RANKED"]


def test_equal_keys_share_a_rank_and_are_listed_in_fixed_order() -> None:
    out = _rank(BOTH)
    for scope, other in (("BTC", "ETH"), ("ETH", "BTC")):
        a = out["assets"][scope]
        assert a["rank"] == 1
        assert a["tied_with"] == [other]
    assert out["groups"][0]["scored_assets"] == ["BTC", "ETH"]


def test_equal_depth_with_a_broader_family_set_ranks_higher() -> None:
    def shape(u: dict[str, Any]) -> None:
        _set(u, "BTC", "whale", direction="N")  # BTC: one Strong family -> depth 2
        _set(u, "BTC", "institutional", strength="Strong")  # ETH: two Moderate -> depth 2

    out = _rank(ALL, mutate=shape)["assets"]
    assert out["BTC"]["evidence_depth"] == out["ETH"]["evidence_depth"] == 2
    assert out["ETH"]["rank"] == 1
    assert out["BTC"]["rank"] == 2
    assert out["BTC"]["tied_with"] == []


def test_a_group_ranks_dense_with_a_gap_free_sequence() -> None:
    def depths(u: dict[str, Any]) -> None:
        _set(u, "ETH", "whale", direction="N")
        _set(u, "BTC", "institutional", strength="Strong")

    out = _rank(ALL, mutate=depths)["assets"]
    assert (out["BTC"]["evidence_depth"], out["BTC"]["rank"]) == (3, 1)
    assert (out["ETH"]["evidence_depth"], out["ETH"]["rank"]) == (1, 2)


def test_assets_are_never_ranked_across_groups() -> None:
    out = _rank(ALL, institutional="Strong", whale="Strong")["assets"]
    assert out["BTC"]["evidence_depth"] == 4
    assert out["SOL"]["evidence_depth"] == 2
    assert out["BTC"]["rank_scope"] != out["SOL"]["rank_scope"]
    assert "SOL" in out["BTC"]["not_ranked_against"]
    assert "BTC" in out["SOL"]["not_ranked_against"]
    assert out["SOL"]["rank"] == 1  # the head of its own group, not of a global order


def test_a_sole_scored_asset_keeps_its_depth_but_has_no_rank() -> None:
    def alone(u: dict[str, Any]) -> None:
        _set(u, "ETH", "institutional", direction="N")
        _set(u, "ETH", "whale", direction="N")

    out = _rank(INST | {"whale": "S"}, mutate=alone)["assets"]
    assert out["ETH"]["scored"] is False
    btc = out["BTC"]
    assert btc["scored"] is True
    assert btc["evidence_depth"] == 2
    assert btc["rank"] is None
    assert btc["ranking_reasons"] == ["RK-SCORED", "RK-NOT-RANKED-SOLE-IN-GROUP"]


def test_unequal_eligible_coverage_is_reported_with_the_values() -> None:
    def thin_eth(u: dict[str, Any]) -> None:
        _set(u, "ETH", "whale", status="insufficient_data", insufficient_data=True)

    out = _rank(ALL, mutate=thin_eth)
    for scope in ("BTC", "ETH"):
        assert "RK-UNEQUAL-ELIGIBLE-COVERAGE" in out["assets"][scope]["notes"]
    cov = out["groups"][0]["eligible_coverage"]
    assert cov["BTC"]["eligible"] == 5
    assert cov["ETH"]["eligible"] == 4
    assert out["assets"]["BTC"]["coverage"]["eligible"] == 5
    assert out["assets"]["ETH"]["coverage"]["eligible"] == 4


def test_equal_coverage_adds_no_coverage_note() -> None:
    out = _rank(BOTH)
    assert "RK-UNEQUAL-ELIGIBLE-COVERAGE" not in out["assets"]["BTC"]["notes"]


def test_a_non_reciprocal_relationship_isolates_the_affected_assets() -> None:
    def claim(opp: dict[str, Any]) -> None:
        c = opp["assets"]["BTC"]["comparability"]
        c["comparable_with"] = ["ETH", "SOL"]
        c["not_comparable_with"] = ["XRP"]

    out = build_ranking(_tampered(claim))
    btc, sol = out["assets"]["BTC"], out["assets"]["SOL"]
    for a in (btc, sol):
        assert a["evidence_depth"] is not None  # valid depth retained
        assert a["rank"] is None
        assert "RK-NOT-RANKED-COMPARABILITY-UNVERIFIED" in a["ranking_reasons"]
        assert a["comparability"]["verified"] is False
        assert a["comparability"]["comparable_with"] == []
    assert btc["rank_scope"] == "BTC"
    ids = [g["group_id"] for g in out["groups"]]
    assert "BTC" in ids
    assert "SOL" in ids


def test_a_declaration_that_disagrees_with_the_expected_domains_isolates_it() -> None:
    def deny(opp: dict[str, Any]) -> None:
        c = opp["assets"]["BTC"]["comparability"]
        c["comparable_with"] = []
        c["not_comparable_with"] = ["ETH", "SOL", "XRP"]

    out = build_ranking(_tampered(deny))["assets"]
    assert out["BTC"]["rank"] is None
    assert out["ETH"]["rank"] is None  # BTC's denial is not reciprocal with ETH's claim
    assert out["BTC"]["comparability"]["verified"] is False
    assert out["ETH"]["comparability"]["verified"] is False
    assert out["SOL"]["rank"] == 1  # unaffected group


@pytest.mark.parametrize(
    "fn",
    [
        lambda o: o["assets"]["BTC"]["comparability"].update(expected_domains=["institutional"]),
        lambda o: o["assets"]["SOL"]["comparability"].update(
            expected_domains=list(SCOPE_DOMAINS["BTC"]), not_tracked_domains=[]
        ),
        lambda o: o["assets"]["BTC"]["comparability"].update(
            expected_domains=[*SCOPE_DOMAINS["BTC"], "institutional"]
        ),
        lambda o: o["assets"]["BTC"]["comparability"].update(comparable_with=["ETH", "ETH"]),
        lambda o: o["assets"]["BTC"]["comparability"].update(comparable_with=["BTC"]),
        lambda o: o["assets"]["BTC"]["comparability"].update(not_comparable_with=["SOL"]),
        lambda o: o["assets"]["BTC"]["comparability"].pop("comparable_with"),
        lambda o: o["assets"]["BTC"].update(comparability=None),
    ],
)
def test_malformed_comparability_is_refused(fn: Mutate) -> None:
    _refused(fn)


# --------------------------------------------------------------------------- shared evidence
def test_shared_market_wide_evidence_is_reported_and_never_scored() -> None:
    out = _rank(INST)
    for scope in SCOPES:
        a = out["assets"][scope]
        assert "RK-SHARED-MARKET-WIDE-EVIDENCE" in a["notes"]
        assert a["components"]["market_wide"]["points"] == 0
    assert out["market_context"]["candidates_independent_of_each_other"] is False


def test_asset_specific_only_candidates_carry_no_shared_note() -> None:
    out = _rank(BOTH)
    assert "RK-SHARED-MARKET-WIDE-EVIDENCE" not in out["assets"]["BTC"]["notes"]


# ------------------------------------------------------------------------ purity and shape
def test_deterministic_pure_and_independent_of_input_ordering() -> None:
    opp = _opp(BOTH, institutional="Strong")
    before = copy.deepcopy(opp)
    first = build_ranking(opp)
    assert opp == before  # no input mutated
    assert build_ranking(opp) == first
    first["assets"]["BTC"]["components"]["family_detail"][0]["members"][0]["field_ids"].append("x")
    first["gates"]["look_ahead"]["violations"].append("x")
    assert opp == before  # the output shares no structure with the input
    shuffled = {**opp, "assets": {s: opp["assets"][s] for s in reversed(SCOPES)}}
    out = build_ranking(shuffled)
    assert list(out["assets"]) == list(SCOPES)
    assert out == build_ranking(opp)


def test_output_has_fixed_asset_order_notice_and_limitations() -> None:
    out = _rank(BOTH)
    assert list(out["assets"]) == ["BTC", "ETH", "SOL", "XRP"]
    assert out["notice"]["id"] == "evidence_depth_not_a_forecast"
    assert {item["id"] for item in out["limitations"]} >= {
        "heuristic_not_validated",
        "market_wide_evidence_not_counted",
    }
    assert [i["id"] for i in out["components"]["items"]] == [
        "family_base",
        "strong_bonus",
        "market_wide_context",
    ]


_FORBIDDEN = (
    "probab",
    "confidence",
    "recommend",
    "target",
    "profit",
    "return",
    "buy",
    "sell",
    "position",
    "forecast",
    "predict",
)


def _walk(node: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
    found: list[tuple[tuple[str, ...], str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            found.append((path, str(k)))
            found.extend(_walk(v, (*path, str(k))))
    elif isinstance(node, list):
        for v in node:
            found.extend(_walk(v, path))
    elif isinstance(node, str):
        found.append((path, node))
    return found


def test_no_probability_confidence_recommendation_or_target_vocabulary() -> None:
    out = _rank(BOTH)
    for path, text in _walk(out):
        if path and path[0] in {"notice", "limitations", "components"}:
            continue  # the fixed prose that disclaims those ideas
        lowered = text.lower()
        assert not any(word in lowered for word in _FORBIDDEN), (path, text)
    assert json.dumps(out)  # JSON serialisable


def test_the_real_chain_scores_fresh_evidence() -> None:
    payload = make_payload(["S2", "S1", "N", "S1", "S2"])
    payload["snapshot_version"] = "analyst_snapshot.v1"
    unified = build_unified_snapshot(payload)
    out = build_ranking(build_opportunities(unified, build_confirmation(unified)))
    assert out["assets"]["BTC"]["scored"] is True
    assert out["assets"]["BTC"]["evidence_depth"] >= 1


def test_the_live_state_is_all_withheld_with_no_zero_scores() -> None:
    unified = build_unified_snapshot(live_state_payload())
    out = build_ranking(build_opportunities(unified, build_confirmation(unified)))
    for scope in SCOPES:
        a = out["assets"][scope]
        assert a["scored"] is False
        assert a["evidence_depth"] is None
        assert a["rank"] is None
