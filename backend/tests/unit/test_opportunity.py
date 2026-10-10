"""Opportunity Discovery Engine (Phase 46): ``unified_snapshot.v0`` + confirmation -> candidates.

Pure: no database, network, clock or model. Inputs are built with the Phase 45 test helper (one
code per directional domain: ``S`` supportive, ``A`` adverse, ``N`` neutral, ``U`` unavailable;
suffix ``~`` stale, ``*`` partial, ``?`` freshness not assessed)."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from cfi.decision.universe import SCOPE_DOMAINS
from cfi.intelligence import (
    OpportunityInputError,
    build_confirmation,
    build_opportunities,
    build_unified_snapshot,
)
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload
from tests.unit.test_confirmation import _unified

SCOPES = tuple(SCOPE_DOMAINS)


def _run(
    codes: dict[str, str] | None = None, *, mutate: Any = None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    unified = _unified(codes)
    if mutate is not None:
        mutate(unified)
    confirmation = build_confirmation(unified)
    return unified, confirmation, build_opportunities(unified, confirmation)


def _asset(codes: dict[str, str], scope: str = "BTC") -> dict[str, Any]:
    return _run(codes)[2]["assets"][scope]  # type: ignore[no-any-return]


# ------------------------------------------------------------------------ outcome mapping
def test_asset_led_candidate_needs_two_asset_specific_families() -> None:
    a = _asset({"institutional": "S", "whale": "S"})
    assert a["status"] == "candidate"
    assert a["discovery_type"] == "asset_led_confirmation"
    assert a["reasons"] == ["OD-CANDIDATE"]
    assert a["basis"]["asset_specific_supporting_families"] == [
        "institutional_flows",
        "onchain_large_holders",
    ]
    assert a["basis"]["market_wide_supporting_families"] == []


def test_market_aligned_candidate_has_one_asset_specific_and_market_wide_families() -> None:
    for scope in SCOPES:  # SOL / XRP have no whale data and can still be market aligned
        a = _asset({"institutional": "S", "liquidity": "S"}, scope)
        assert a["status"] == "candidate"
        assert a["discovery_type"] == "market_aligned_confirmation"
        assert a["basis"]["asset_specific_supporting_families"] == ["institutional_flows"]
        assert a["basis"]["market_wide_supporting_families"] == ["stablecoin_liquidity"]


def test_mixed_is_conflicting_evidence_never_a_candidate() -> None:
    a = _asset({"institutional": "S", "whale": "S", "liquidity": "A"})
    assert a["status"] == "conflicting_evidence"
    assert a["discovery_type"] is None
    assert a["reasons"] == ["OD-CONFLICT"]
    assert a["basis"]["confirmation_agreement"] == "mixed"


def test_insufficient_coverage_is_insufficient_evidence() -> None:
    a = _asset({"institutional": "S", "whale": "U", "liquidity": "U", "macro": "U"})
    assert a["status"] == "insufficient_evidence"
    assert a["reasons"] == ["OD-INSUFFICIENT"]
    assert a["discovery_type"] is None


def test_unconfirmed_is_not_a_candidate() -> None:
    a = _asset({"institutional": "S"})
    assert a["status"] == "no_candidate"
    assert a["reasons"] == ["OD-UNCONFIRMED"]
    only_market = _asset({"liquidity": "S", "macro": "S", "market_structure": "S"})
    assert only_market["status"] == "no_candidate"  # no asset-specific confirmer


def test_adverse_confirmation_is_a_review_outcome_never_an_opportunity() -> None:
    a = _asset({"institutional": "A", "whale": "A"})
    assert a["status"] == "no_candidate"
    assert a["discovery_type"] == "adverse_confirmation"
    assert a["reasons"] == ["OD-ADVERSE-CONFIRMATION"]
    result = _run({"institutional": "A", "whale": "A"})[2]
    assert result["market_context"]["candidate_assets"] == []


@pytest.mark.parametrize("code", ["S~", "S*", "S?", "U"])
def test_ineligible_evidence_never_creates_a_candidate(code: str) -> None:
    # Two families would confirm; the ineligible one must not count.
    a = _asset({"institutional": "S", "liquidity": code})
    assert a["status"] != "candidate"
    ineligible = {m["domain"] for m in a["excluded_members"]}
    assert "liquidity" in ineligible


@pytest.mark.parametrize("records", [[], [{"path": "p", "status": "no_data"}], None])
def test_unverified_freshness_never_creates_a_candidate(records: Any) -> None:
    def mutate(u: dict[str, Any]) -> None:
        for entry in u["global_domains"]:
            if entry["domain"] == "liquidity":
                entry["freshness_records"] = records

    out = _run({"institutional": "S", "liquidity": "S"}, mutate=mutate)[2]
    assert out["assets"]["BTC"]["status"] != "candidate"
    member = next(m for m in out["assets"]["BTC"]["excluded_members"] if m["domain"] == "liquidity")
    assert member["exclusion_reason"] == "freshness_unverified"


def test_not_tracked_whale_is_not_a_supporting_member() -> None:
    a = _asset({"institutional": "S", "liquidity": "S"}, "SOL")
    assert a["comparability"]["not_tracked_domains"] == ["whale"]
    assert "whale" not in {m["domain"] for m in a["evidence_refs"]}
    assert "whale" in {m["domain"] for m in a["excluded_members"]}


# --------------------------------------------------- defensive checks on the Phase 45 input
def test_a_candidate_requires_an_asset_specific_confirmer_even_if_the_input_claims_one() -> None:
    unified = _unified({"liquidity": "S", "macro": "S", "market_structure": "S"})
    confirmation = build_confirmation(unified)
    block = confirmation["assets"]["BTC"]
    assert block["agreement"] == "unconfirmed"
    block["agreement"] = "confirmed_supportive"  # a tampered / buggy input
    block["key_layer"]["supportive"] = True
    out = build_opportunities(unified, confirmation)["assets"]["BTC"]
    assert out["status"] == "no_candidate"
    assert out["reasons"] == ["OD-NO-ASSET-SPECIFIC-CONFIRMER"]


def test_a_supporting_member_without_verified_freshness_blocks_the_candidate() -> None:
    unified = _unified({"institutional": "S", "liquidity": "S"})
    confirmation = build_confirmation(unified)
    for m in confirmation["assets"]["BTC"]["members"]:
        if m["domain"] == "liquidity":
            m["freshness_records"] = []
    out = build_opportunities(unified, confirmation)["assets"]["BTC"]
    assert out["status"] == "no_candidate"
    assert out["reasons"] == ["OD-UNVERIFIED-SUPPORT"]


def test_a_confirmation_whose_members_disagree_with_its_families_is_refused() -> None:
    unified = _unified({"institutional": "S", "liquidity": "S"})
    confirmation = build_confirmation(unified)
    confirmation["assets"]["BTC"]["supportive_families"] = ["institutional_flows"]
    with pytest.raises(OpportunityInputError, match="inconsistent"):
        build_opportunities(unified, confirmation)


# ----------------------------------------------------------------------- integrity gates
def test_look_ahead_violations_block_candidates_and_keep_the_diagnostics() -> None:
    def mutate(u: dict[str, Any]) -> None:
        u["data_quality"]["look_ahead_violations"] = ["tool_results.x.freshness", "as_of"]

    _, _, out = _run({"institutional": "S", "whale": "S"}, mutate=mutate)
    btc = out["assets"]["BTC"]
    assert btc["status"] == "blocked"
    assert btc["discovery_type"] is None
    assert btc["reasons"] == ["OD-LOOK-AHEAD-VIOLATION"]
    assert btc["basis"]["confirmation_agreement"] == "confirmed_supportive"  # still visible
    assert out["gates"]["look_ahead"] == {
        "triggered": True,
        "violations": ["tool_results.x.freshness", "as_of"],
    }
    assert out["market_context"]["candidate_assets"] == []


def test_a_producer_hash_mismatch_blocks_candidates() -> None:
    def mutate(u: dict[str, Any]) -> None:
        u["snapshot"]["producer_hash_check"] = "mismatch"

    _, _, out = _run({"institutional": "S", "whale": "S"}, mutate=mutate)
    assert out["assets"]["BTC"]["status"] == "blocked"
    assert out["assets"]["BTC"]["reasons"] == ["OD-SNAPSHOT-INTEGRITY"]
    assert out["gates"]["producer_hash"] == {"check": "mismatch", "triggered": True}


def test_both_gates_report_both_reasons_and_other_outcomes_keep_their_status() -> None:
    def mutate(u: dict[str, Any]) -> None:
        u["snapshot"]["producer_hash_check"] = "mismatch"
        u["data_quality"]["look_ahead_violations"] = ["as_of"]

    _, _, out = _run({"institutional": "S", "whale": "S", "liquidity": "A"}, mutate=mutate)
    btc = out["assets"]["BTC"]
    assert btc["status"] == "conflicting_evidence"  # gates only block would-be candidates
    assert btc["reasons"] == ["OD-CONFLICT", "OD-LOOK-AHEAD-VIOLATION", "OD-SNAPSHOT-INTEGRITY"]


@pytest.mark.parametrize("check", ["verified", "unverified"])
def test_verified_or_unverified_hash_does_not_block(check: str) -> None:
    def mutate(u: dict[str, Any]) -> None:
        u["snapshot"]["producer_hash_check"] = check

    assert (
        _run({"institutional": "S", "whale": "S"}, mutate=mutate)[2]["assets"]["BTC"]["status"]
        == "candidate"
    )


# --------------------------------------------------------------------- input consistency
def test_matching_inputs_are_accepted_and_identity_is_preserved() -> None:
    unified, confirmation, out = _run({"institutional": "S"})
    assert out["snapshot"] == unified["snapshot"] == confirmation["snapshot"]
    assert out["source_contracts"] == {
        "unified": "unified_snapshot.v0",
        "confirmation": "cross_domain_confirmation.v0",
        "confirmation_parameters": "confirmation_params.v0",
        "confirmation_families": "evidence_families.v0",
    }


@pytest.mark.parametrize(
    ("field", "value"), [("row_id", 10), ("as_of", "2030-01-01"), ("uuid", "x")]
)
def test_confirmation_from_another_snapshot_is_refused(field: str, value: Any) -> None:
    unified = _unified({"institutional": "S"})
    other = copy.deepcopy(unified)
    other["snapshot"][field] = value
    with pytest.raises(OpportunityInputError, match=field):
        build_opportunities(unified, build_confirmation(other))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda u, c: u.update(contract_version="unified_snapshot.v9"),
        lambda u, c: c.update(contract_version="cross_domain_confirmation.v9"),
        lambda u, c: c.update(source_contract="unified_snapshot.v9"),
        lambda u, c: c["parameters"].update(version="confirmation_params.v9"),
        lambda u, c: c["parameters"].update(families_version="evidence_families.v9"),
    ],
)
def test_unsupported_contract_versions_are_refused(mutate: Any) -> None:
    unified = _unified({"institutional": "S"})
    confirmation = build_confirmation(unified)
    mutate(unified, confirmation)
    with pytest.raises(OpportunityInputError):
        build_opportunities(unified, confirmation)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda u, c: c["assets"].pop("SOL"),
        lambda u, c: c["assets"]["BTC"].update(agreement="strongly_confirmed"),
        lambda u, c: c["assets"]["BTC"].update(members={}),
        lambda u, c: c["assets"]["BTC"]["members"].append("not a mapping"),
        lambda u, c: c["assets"]["BTC"]["members"][0].pop("eligible"),
        lambda u, c: c["assets"]["BTC"].pop("key_layer"),
        lambda u, c: u["assets"].pop("XRP"),
        lambda u, c: u.update(global_domains=None),
        lambda u, c: u.update(data_quality=None),
        lambda u, c: c.update(snapshot=None),
    ],
)
def test_malformed_inputs_are_refused_explicitly(mutate: Any) -> None:
    unified = _unified({"institutional": "S"})
    confirmation = build_confirmation(unified)
    mutate(unified, confirmation)
    with pytest.raises(OpportunityInputError):
        build_opportunities(unified, confirmation)
    with pytest.raises(OpportunityInputError):
        build_opportunities("nope", {})  # type: ignore[arg-type]


# ----------------------------------------------------- shared evidence and comparability
def test_assets_confirmed_through_the_same_market_wide_evidence_are_not_independent() -> None:
    out = _run({"institutional": "S", "liquidity": "S"})[2]
    assert out["market_context"]["candidate_assets"] == list(SCOPES)
    assert out["market_context"]["shared_market_wide_evidence"] == [
        {"family": "stablecoin_liquidity", "assets": list(SCOPES)}
    ]
    assert out["market_context"]["candidates_independent_of_each_other"] is False
    btc = out["assets"]["BTC"]
    assert btc["independence"]["shares_market_wide_evidence_with"] == ["ETH", "SOL", "XRP"]
    assert "OD-SHARED-MARKET-WIDE-EVIDENCE" in btc["notes"]


def test_asset_specific_only_candidates_share_nothing() -> None:
    out = _run({"institutional": "S", "whale": "S"})[2]
    assert out["market_context"]["candidate_assets"] == ["BTC", "ETH"]
    assert out["market_context"]["shared_market_wide_evidence"] == []
    assert out["market_context"]["candidates_independent_of_each_other"] is True
    assert out["assets"]["BTC"]["independence"]["shares_market_wide_evidence_with"] == []


def test_coverage_comparability_is_explicit() -> None:
    out = _run({"institutional": "S"})[2]
    btc, sol = out["assets"]["BTC"], out["assets"]["SOL"]
    assert btc["comparability"]["comparable_with"] == ["ETH"]
    assert btc["comparability"]["not_comparable_with"] == ["SOL", "XRP"]
    assert sol["comparability"]["comparable_with"] == ["XRP"]
    assert "whale" not in sol["comparability"]["expected_domains"]
    for scope in SCOPES:
        assert "OD-NOT-COMPARABLE-COVERAGE" in out["assets"][scope]["notes"]


def test_assets_keep_a_fixed_order_regardless_of_the_evidence() -> None:
    for codes in ({"institutional": "S", "whale": "S"}, {"institutional": "A"}, {}):
        assert list(_run(codes)[2]["assets"]) == list(SCOPES)


def test_risk_and_context_entries_are_displayed_but_never_used() -> None:
    base = _run({"institutional": "S", "whale": "S"})[2]["assets"]["BTC"]

    def mutate(u: dict[str, Any]) -> None:
        for entry in [*u["global_domains"], *u["assets"]["BTC"]["domains"]]:
            if entry["independent_vote"] is False:
                entry.update(status="unavailable", freshness="stale", band="extreme")

    changed = _run({"institutional": "S", "whale": "S"}, mutate=mutate)[2]["assets"]["BTC"]
    assert changed["status"] == base["status"] == "candidate"
    assert changed["context"]["used_for_discovery"] is False
    domains = {e["domain"] for e in base["context"]["entries"]}
    assert {"regime", "derivatives", "anomaly"} <= domains
    for entry in base["context"]["entries"]:
        assert "direction" not in entry
        assert entry["domain"] not in ("institutional", "whale", "liquidity", "macro")


# ---------------------------------------------------- provenance, purity, vocabulary
def test_evidence_provenance_and_exclusions_are_preserved() -> None:
    unified, confirmation, out = _run({"institutional": "S", "whale": "S", "liquidity": "S~"})
    btc = out["assets"]["BTC"]
    members = {m["domain"]: m for m in confirmation["assets"]["BTC"]["members"]}
    for ref in btc["evidence_refs"]:
        source = members[ref["domain"]]
        assert ref["freshness_records"] == source["freshness_records"]
        assert ref["source_ids"] == source["source_ids"]
        assert ref["field_ids"] == source["field_ids"]
        assert ref["strength"] == source["strength"]
    stale = next(m for m in btc["excluded_members"] if m["domain"] == "liquidity")
    assert stale["state"] == "stale"
    assert stale["exclusion_reason"] == "stale"
    assert out["data_quality"] == unified["data_quality"]
    ids = {item["id"] for item in out["limitations"]}
    assert {"confirmation_is_agreement_not_performance", "experimental_parameters"} <= ids
    assert out["parameters"]["experimental"] is True
    assert out["notice"]["id"] == "research_candidates_only"


def test_deterministic_pure_and_does_not_mutate_either_input() -> None:
    unified = _unified({"institutional": "S", "whale": "S", "liquidity": "A~"})
    confirmation = build_confirmation(unified)
    before = copy.deepcopy((unified, confirmation))
    first = build_opportunities(unified, confirmation)
    assert first == build_opportunities(unified, confirmation)
    assert (unified, confirmation) == before
    json.dumps(first)


def _keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


def test_no_scores_rankings_recommendations_or_price_targets() -> None:
    out = _run({"institutional": "S", "whale": "S", "liquidity": "S"})[2]
    forbidden_keys = {"score", "rank", "ranking", "rating", "target", "price_target", "size"}
    assert not {k.lower() for k in _keys(out)} & forbidden_keys
    # The notice and limitations legitimately say what the output is *not*; scan the rest.
    body = {k: v for k, v in out.items() if k not in ("notice", "limitations")}
    text = json.dumps(body).lower()
    for word in ("recommend", "buy", "sell", "target price", "position size", "stance", "posture"):
        assert word not in text


# ----------------------------------------------------------------------- the real chain
def test_real_chain_fresh_evidence_yields_candidates() -> None:
    payload = make_payload(["S2", "S1", "S1", "S1", "S2"])
    payload["snapshot_version"] = "analyst_snapshot.v1"
    unified = build_unified_snapshot(payload)
    out = build_opportunities(unified, build_confirmation(unified))
    assert out["assets"]["BTC"]["status"] == "candidate"
    assert out["assets"]["BTC"]["discovery_type"] == "asset_led_confirmation"
    assert out["snapshot"] == unified["snapshot"]


def test_real_chain_live_state_yields_no_candidates() -> None:
    unified = build_unified_snapshot(live_state_payload())
    out = build_opportunities(unified, build_confirmation(unified))
    assert out["market_context"]["candidate_assets"] == []
    for scope in SCOPES:
        assert out["assets"][scope]["status"] == "insufficient_evidence"
