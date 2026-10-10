"""Cross-Domain Confirmation Engine (Phase 45): ``unified_snapshot.v0`` -> confirmation.

Pure: no database, network, clock or model. Most tests build a minimal ``unified_snapshot.v0``
directly (one code per directional domain) so each rule is pinned in isolation; a few run the real
chain from a stored-shaped payload.

Codes: ``S`` supportive, ``A`` adverse, ``N`` neutral, ``U`` unavailable; a suffix marks the
reading's quality: ``~`` stale, ``*`` partial, ``?`` freshness not assessed."""

from __future__ import annotations

import copy
import itertools
import json
from typing import Any

import pytest

import cfi.intelligence.confirmation as confirmation_module
from cfi.decision.universe import SCOPE_DOMAINS
from cfi.intelligence import (
    ConfirmationInputError,
    build_confirmation,
    build_unified_snapshot,
)
from cfi.intelligence.confirmation_universe import EVIDENCE_FAMILIES, EvidenceFamily
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload

ASSET_DOMAINS = ("institutional", "whale")
GLOBAL_DOMAINS = ("liquidity", "macro", "market_structure")
ALL = ("institutional", "whale", "liquidity", "macro", "market_structure")
SCOPES = ("BTC", "ETH", "SOL", "XRP")


def _entry(domain: str, code: str, *, strength: str = "Moderate") -> dict[str, Any]:
    base = code[0]
    mark = code[1:]
    unavailable = base == "U"
    flags = ["stale"] if mark == "~" else ["partial"] if mark == "*" else []
    freshness = (
        "no_data"
        if unavailable
        else "stale"
        if mark == "~"
        else "not_assessed"
        if mark == "?"
        else "fresh"
    )
    return {
        "domain": domain,
        "component": f"{domain}.score",
        "role": "Directional",
        "independent_vote": True,
        "status": "insufficient_data" if unavailable else "ok",
        "freshness": freshness,
        "evidence_state": "insufficient_data" if unavailable else "available",
        "insufficient_data": unavailable,
        "quality_flags": flags,
        "direction": base,
        "strength": "Missing" if unavailable else strength,
        "band": None,
        "source_ids": [f"get_{domain}"],
        "field_ids": [f"get_{domain}.score.band"],
        "freshness_records": [{"path": f"p.{domain}", "status": freshness}],
    }


def _context(domain: str, role: str, direction: str | None) -> dict[str, Any]:
    entry = _entry(domain, "N")
    entry.update(role=role, independent_vote=False, direction=direction, component=f"{domain}.x")
    return entry


def _unified(codes: dict[str, str] | None = None, **strength: str) -> dict[str, Any]:
    """A minimal ``unified_snapshot.v0``. ``codes`` maps domain -> code (default ``N``)."""
    codes = codes or {}

    def code(domain: str) -> str:
        return codes.get(domain, "N")

    def make(domain: str) -> dict[str, Any]:
        return _entry(domain, code(domain), strength=strength.get(domain, "Moderate"))

    assets: dict[str, Any] = {}
    for scope in SCOPES:
        tracked = [d for d in ASSET_DOMAINS if d in SCOPE_DOMAINS[scope]]
        assets[scope] = {
            "domains": [
                *(make(d) for d in tracked),
                _context("derivatives", "Risk", "S"),
            ],
            "not_tracked_domains": [d for d in ASSET_DOMAINS if d not in tracked],
        }
    return {
        "contract_version": "unified_snapshot.v0",
        "snapshot": {"row_id": 9, "as_of": "2026-10-05T00:00:00+00:00", "snapshot_version": "t"},
        "global_domains": [
            *(make(d) for d in GLOBAL_DOMAINS),
            _context("regime", "Context", None),
            _context("anomaly", "Risk", "S"),
        ],
        "assets": assets,
        "coverage": {},
        "data_quality": {"platform_limits": ["mid-cap assets"], "look_ahead_violations": []},
    }


def _agreement(codes: dict[str, str], scope: str = "BTC", **strength: str) -> str:
    out = build_confirmation(_unified(codes, **strength))
    return str(out["assets"][scope]["agreement"])


def _member(out: dict[str, Any], scope: str, domain: str) -> dict[str, Any]:
    return next(m for m in out["assets"][scope]["members"] if m["domain"] == domain)


# ------------------------------------------------------------------------------ the rules
def test_two_families_with_a_key_layer_confirmer_confirm() -> None:
    out = build_confirmation(_unified({"institutional": "S", "liquidity": "S"}))
    btc = out["assets"]["BTC"]
    assert btc["agreement"] == "confirmed_supportive"
    assert btc["reasons"] == ["CF-CONFIRMED"]
    assert btc["supportive_families"] == ["institutional_flows", "stablecoin_liquidity"]
    assert btc["key_layer"]["supportive"] is True
    assert _agreement({"institutional": "A", "whale": "A"}) == "confirmed_adverse"


def test_two_families_without_a_key_layer_confirmer_do_not_confirm() -> None:
    out = build_confirmation(_unified({"liquidity": "S", "macro": "S", "market_structure": "S"}))
    btc = out["assets"]["BTC"]
    assert btc["agreement"] == "unconfirmed"
    assert btc["reasons"] == ["CF-NO-KEY-LAYER"]
    assert btc["key_layer"]["supportive"] is False


def test_a_single_family_or_only_neutral_evidence_is_unconfirmed() -> None:
    one = build_confirmation(_unified({"institutional": "S"}))["assets"]["BTC"]
    assert one["agreement"] == "unconfirmed"
    assert one["reasons"] == ["CF-TOO-FEW-FAMILIES"]
    none = build_confirmation(_unified())["assets"]["BTC"]
    assert none["agreement"] == "unconfirmed"
    assert none["reasons"] == ["CF-NO-DIRECTIONAL-EVIDENCE"]


def test_opposing_eligible_evidence_is_mixed_and_blocks_confirmation() -> None:
    codes = {"institutional": "S", "whale": "S", "liquidity": "S", "macro": "A"}
    btc = build_confirmation(_unified(codes))["assets"]["BTC"]
    assert btc["agreement"] == "mixed"
    assert btc["reasons"][0] == "CF-MIXED"


def test_mixed_is_not_hidden_by_the_coverage_floor() -> None:
    codes = {
        "institutional": "S",
        "liquidity": "A",
        "whale": "U",
        "macro": "U",
        "market_structure": "U",
    }
    btc = build_confirmation(_unified(codes))["assets"]["BTC"]
    assert btc["coverage"] == {"eligible": 2, "expected": 5, "floor": [1, 2], "met": False}
    assert btc["agreement"] == "mixed"
    assert btc["reasons"] == ["CF-MIXED", "CF-MIXED-LOW-COVERAGE"]


def test_low_coverage_without_opposition_is_insufficient_evidence() -> None:
    codes = {
        "institutional": "S",
        "whale": "U",
        "liquidity": "U",
        "macro": "U",
        "market_structure": "U",
    }
    btc = build_confirmation(_unified(codes))["assets"]["BTC"]
    assert btc["agreement"] == "insufficient_evidence"
    assert btc["reasons"] == ["CF-LOW-COVERAGE"]


@pytest.mark.parametrize(
    ("scope", "eligible", "met"),
    [("BTC", 3, True), ("BTC", 2, False), ("SOL", 2, True), ("SOL", 1, False)],
)
def test_the_coverage_floor_boundary(scope: str, eligible: int, met: bool) -> None:
    domains = SCOPE_DOMAINS[scope]
    codes = {d: ("N" if i < eligible else "U") for i, d in enumerate(domains)}
    cov = build_confirmation(_unified(codes))["assets"][scope]["coverage"]
    assert cov["eligible"] == eligible
    assert cov["expected"] == len(domains)
    assert cov["met"] is met


def test_the_decision_conflict_definition_is_reported_when_met() -> None:
    codes = {"institutional": "S", "whale": "S", "liquidity": "A", "macro": "A"}
    assert (
        "CF-DECISION-CONFLICT-DEFINITION-MET"
        in (build_confirmation(_unified(codes))["assets"]["BTC"]["reasons"])
    )
    one_each = {"institutional": "S", "liquidity": "A"}
    strong = build_confirmation(_unified(one_each, institutional="Strong", liquidity="Strong"))
    assert "CF-DECISION-CONFLICT-DEFINITION-MET" in strong["assets"]["BTC"]["reasons"]
    weak = build_confirmation(_unified(one_each))["assets"]["BTC"]["reasons"]
    assert "CF-DECISION-CONFLICT-DEFINITION-MET" not in weak


# ------------------------------------------------------------ verified freshness (audit)
def _with_records(domain: str, code: str, records: Any) -> dict[str, Any]:
    """A unified snapshot whose ``domain`` entry carries the given freshness records, with the
    top-level freshness still labelled ``fresh`` (as the engine labels a market-wide domain)."""
    unified = _unified({"institutional": "S", "liquidity": code})
    target = next(e for e in unified["global_domains"] if e["domain"] == domain)
    if records is _MISSING:
        target.pop("freshness_records")
    else:
        target["freshness_records"] = records
    return unified


_MISSING = object()


def test_explicitly_fresh_records_remain_eligible() -> None:
    out = build_confirmation(_with_records("liquidity", "S", [{"path": "p", "status": "fresh"}]))
    assert _member(out, "BTC", "liquidity")["eligible"] is True
    assert out["assets"]["BTC"]["agreement"] == "confirmed_supportive"


@pytest.mark.parametrize(
    "records",
    [
        [{"path": "p", "status": "no_data"}],
        [{"path": "p", "status": "weird"}],
        [{"path": "p", "status": None}],
        [{"path": "p"}],
        [None],
        ["fresh"],
        [{"path": "a", "status": "fresh"}, {"path": "b", "status": "no_data"}],
        [],
        None,
        _MISSING,
    ],
    ids=[
        "no_data",
        "unknown",
        "status_none",
        "status_missing",
        "record_none",
        "record_not_a_mapping",
        "one_unverified_of_two",
        "empty_list",
        "records_none",
        "records_missing",
    ],
)
def test_unverified_freshness_cannot_vote(records: Any) -> None:
    out = build_confirmation(_with_records("liquidity", "S", records))
    member = _member(out, "BTC", "liquidity")
    assert member["state"] == "not_assessed"
    assert member["eligible"] is False
    assert member["exclusion_reason"] == "freshness_unverified"
    assert member["freshness"] == "fresh"  # the engine's label is preserved, not relabelled
    assert member["direction"] == "S"
    assert "stablecoin_liquidity" not in out["assets"]["BTC"]["supportive_families"]
    # With the second family gone, a would-be confirmation is not manufactured.
    assert out["assets"]["BTC"]["agreement"] == "unconfirmed"


def test_unverified_records_are_preserved_unchanged_in_the_output() -> None:
    records = [{"path": "p", "status": "no_data", "latest": None}]
    out = build_confirmation(_with_records("liquidity", "S", copy.deepcopy(records)))
    assert _member(out, "BTC", "liquidity")["freshness_records"] == records


@pytest.mark.parametrize("side", ["S", "A"])
def test_unverified_market_wide_evidence_cannot_confirm_either_side(side: str) -> None:
    unified = _unified({"liquidity": side, "macro": side, "market_structure": side})
    for entry in unified["global_domains"][:3]:
        entry["freshness_records"] = [{"path": "p", "status": "no_data"}]
    unified["assets"]["BTC"]["domains"][0].update(
        direction=side, freshness_records=[{"path": "q", "status": "fresh"}]
    )
    btc = build_confirmation(unified)["assets"]["BTC"]
    assert not btc["agreement"].startswith("confirmed_")
    assert btc["agreement"] == "insufficient_evidence"  # only institutional + whale(N) are eligible
    assert btc["supportive_families"] + btc["adverse_families"] == ["institutional_flows"]


def test_genuine_opposition_is_mixed_below_coverage_even_with_unverified_neighbours() -> None:
    codes = {"institutional": "S", "liquidity": "A", "whale": "U"}
    unified = _unified(codes)
    for entry in unified["global_domains"][1:3]:  # macro, market_structure: unverified
        entry["freshness_records"] = []
    btc = build_confirmation(unified)["assets"]["BTC"]
    assert btc["coverage"]["met"] is False
    assert btc["agreement"] == "mixed"
    assert btc["reasons"][:2] == ["CF-MIXED", "CF-MIXED-LOW-COVERAGE"]


def test_asset_specific_member_without_records_cannot_be_the_key_layer() -> None:
    unified = _unified({"institutional": "S", "liquidity": "S"})
    unified["assets"]["BTC"]["domains"][0]["freshness_records"] = []
    btc = build_confirmation(unified)["assets"]["BTC"]
    assert btc["key_layer"]["supportive"] is False
    assert btc["agreement"] != "confirmed_supportive"


# ------------------------------------------------------------------- ineligible evidence
@pytest.mark.parametrize(
    ("code", "state"),
    [("S~", "stale"), ("S*", "partial"), ("S?", "not_assessed"), ("U", "unavailable")],
)
def test_ineligible_readings_never_vote_and_keep_their_state(code: str, state: str) -> None:
    base = {"institutional": "S", "liquidity": "S"}
    assert _agreement(base) == "confirmed_supportive"
    out = build_confirmation(_unified({**base, "liquidity": code}))
    btc = out["assets"]["BTC"]
    member = _member(out, "BTC", "liquidity")
    assert member["state"] == state
    assert member["eligible"] is False
    assert member["exclusion_reason"]
    assert btc["agreement"] != "confirmed_supportive"
    assert "stablecoin_liquidity" not in btc["supportive_families"]
    assert btc["counts_by_state"].get(state) == 1


@pytest.mark.parametrize("code", ["A~", "A*", "A?", "U"])
def test_ineligible_opposition_cannot_create_a_contradiction(code: str) -> None:
    out = build_confirmation(_unified({"institutional": "S", "whale": "S", "macro": code}))
    assert out["assets"]["BTC"]["agreement"] == "confirmed_supportive"
    assert out["assets"]["BTC"]["adverse_families"] == []


def test_partial_is_visible_with_flags_provenance_and_the_reason() -> None:
    out = build_confirmation(_unified({"liquidity": "S*"}))
    member = _member(out, "BTC", "liquidity")
    assert member["state"] == "partial"
    assert member["quality_flags"] == ["partial"]
    assert member["exclusion_reason"] == "quality_flag:partial"
    assert member["direction"] == "S"
    assert member["strength"] == "Moderate"
    assert member["source_ids"] == ["get_liquidity"]
    assert member["field_ids"] == ["get_liquidity.score.band"]
    assert member["freshness_records"]


def test_stale_with_the_stale_flag_only_is_still_stale() -> None:
    entry = _entry("liquidity", "S")
    entry["quality_flags"] = ["stale"]
    unified = _unified()
    unified["global_domains"][0] = entry
    assert _member(build_confirmation(unified), "BTC", "liquidity")["state"] == "stale"


def test_unavailable_is_never_neutral() -> None:
    out = build_confirmation(_unified({d: "U" for d in ALL}))
    for scope in SCOPES:
        block = out["assets"][scope]
        assert block["counts_by_state"].get("neutral") is None
        assert block["agreement"] == "insufficient_evidence"
        assert block["coverage"]["eligible"] == 0


def test_not_tracked_whale_is_shown_but_not_expected_or_counted() -> None:
    out = build_confirmation(_unified({"institutional": "S", "liquidity": "S"}))
    sol = out["assets"]["SOL"]
    assert sol["coverage"]["expected"] == 4
    whale = _member(out, "SOL", "whale")
    assert whale["state"] == "not_tracked"
    assert whale["eligible"] is False
    assert whale["exclusion_reason"] == "not_tracked_for_scope"
    assert sol["agreement"] == "confirmed_supportive"


# ------------------------------------------------------------- independence safeguards
def test_regime_risk_and_context_never_vote_and_are_listed_as_excluded() -> None:
    plain = build_confirmation(_unified({"institutional": "S"}))
    unified = _unified({"institutional": "S"})
    for entry in (*unified["global_domains"][3:], *unified["assets"]["BTC"]["domains"][-1:]):
        entry["direction"] = "S"  # even a supportive-looking non-vote changes nothing
    assert build_confirmation(unified)["assets"] == plain["assets"]
    domains = {(e["scope"], e["domain"]) for e in plain["excluded"]}
    assert ("global", "regime") in domains
    assert ("global", "anomaly") in domains
    assert ("BTC", "derivatives") in domains
    assert all(e["reason"] == "not_a_directional_vote" for e in plain["excluded"])
    voters = {m["domain"] for a in plain["assets"].values() for m in a["members"]}
    assert voters <= set(ALL)


def test_global_readings_are_shared_not_asset_observations() -> None:
    out = build_confirmation(_unified({"liquidity": "S"}))
    for scope in SCOPES:
        for domain in GLOBAL_DOMAINS:
            m = _member(out, scope, domain)
            assert m["shared_across_assets"] is True
            assert m["scope_basis"] == "market_wide"
        assert _member(out, scope, "institutional")["shared_across_assets"] is False
    assert sum(e["domain"] == "regime" for e in out["excluded"]) == 1  # listed once


def test_every_directional_domain_has_an_evidence_family() -> None:
    directional = {d for domains in SCOPE_DOMAINS.values() for d in domains}
    assert directional <= set(EVIDENCE_FAMILIES)
    ids = [f.family_id for f in EVIDENCE_FAMILIES.values()]
    assert len(ids) == len(set(ids))  # v0: lineage keeps every domain in its own family


def test_domains_in_one_family_count_once(monkeypatch: pytest.MonkeyPatch) -> None:
    shared = EvidenceFamily("one_family", "test lineage")
    families = {**EVIDENCE_FAMILIES, "institutional": shared, "whale": shared}
    monkeypatch.setattr(confirmation_module, "EVIDENCE_FAMILIES", families)
    btc = build_confirmation(_unified({"institutional": "S", "whale": "S"}))["assets"]["BTC"]
    assert btc["supportive_families"] == ["one_family"]
    assert btc["agreement"] == "unconfirmed"
    assert btc["reasons"] == ["CF-TOO-FEW-FAMILIES"]


def test_a_domain_without_a_family_fails_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    families = {k: v for k, v in EVIDENCE_FAMILIES.items() if k != "macro"}
    monkeypatch.setattr(confirmation_module, "EVIDENCE_FAMILIES", families)
    out = build_confirmation(_unified({"institutional": "S", "macro": "S"}))
    member = _member(out, "BTC", "macro")
    assert member["state"] == "unmapped"
    assert member["eligible"] is False
    assert member["exclusion_reason"] == "no_family_mapping"
    assert out["assets"]["BTC"]["supportive_families"] == ["institutional_flows"]


def test_strength_is_preserved_but_never_weights_the_result() -> None:
    codes = {"institutional": "S", "liquidity": "S"}
    strong = build_confirmation(_unified(codes, institutional="Strong", liquidity="Strong"))
    weak = build_confirmation(_unified(codes, institutional="Weak", liquidity="Weak"))
    assert strong["assets"]["BTC"]["agreement"] == weak["assets"]["BTC"]["agreement"]
    assert _member(strong, "BTC", "institutional")["strength"] == "Strong"
    assert _member(weak, "BTC", "institutional")["strength"] == "Weak"


# ---------------------------------------------------------------------------- properties
STATES = ("S", "A", "N", "S~", "U")


def test_exhaustive_mixed_is_never_hidden_and_removal_never_manufactures_agreement() -> None:
    domains = SCOPE_DOMAINS["BTC"]
    for combo in itertools.product(STATES, repeat=len(domains)):
        codes = dict(zip(domains, combo, strict=True))
        result = _agreement(codes)
        if "S" in combo and "A" in combo:
            assert result == "mixed", codes
        for domain in domains:
            removed = codes[domain]
            after = _agreement({**codes, domain: "U"})
            if after.startswith("confirmed_") and after != result:
                # Only removing the *opposing* side can create a confirmation.
                opposite = "A" if after.endswith("supportive") else "S"
                assert removed == opposite, (codes, domain)
            if result == "insufficient_evidence":
                assert after in ("insufficient_evidence",), (codes, domain)


# ------------------------------------------------------------------ provenance, purity
def test_identity_data_quality_and_limitations_are_preserved() -> None:
    unified = _unified({"institutional": "S"})
    out = build_confirmation(unified)
    assert out["contract_version"] == "cross_domain_confirmation.v0"
    assert out["source_contract"] == "unified_snapshot.v0"
    assert out["snapshot"] == unified["snapshot"]
    assert out["data_quality"] == unified["data_quality"]
    assert out["parameters"] == {
        "version": "confirmation_params.v0",
        "min_families": 2,
        "require_key_layer": True,
        "coverage_floor": [1, 2],
        "families_version": "evidence_families.v0",
    }
    ids = {item["id"] for item in out["limitations"]}
    assert {"independence_by_lineage_only", "experimental_parameters"} <= ids


def test_deterministic_pure_and_does_not_mutate_the_input() -> None:
    unified = _unified({"institutional": "S", "liquidity": "A~"})
    before = copy.deepcopy(unified)
    first = build_confirmation(unified)
    assert first == build_confirmation(unified)
    assert unified == before
    json.dumps(first)


def test_the_output_carries_no_stance_score_or_recommendation() -> None:
    text = json.dumps(build_confirmation(_unified({"institutional": "S", "liquidity": "S"})))
    for word in ("stance", "posture", "recommend", "buy", "sell", "bullish", "bearish", "score"):
        assert word not in text.lower().replace("component", "").replace(".score", "")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda u: u.update(contract_version="unified_snapshot.v9"),
        lambda u: u.pop("assets"),
        lambda u: u.update(global_domains={}),
        lambda u: u["assets"].pop("SOL"),
        lambda u: u["assets"]["BTC"].pop("not_tracked_domains"),
        lambda u: u["global_domains"].append("not a mapping"),
        lambda u: u["global_domains"][0].pop("freshness"),
        lambda u: u.update(snapshot=None),
    ],
)
def test_malformed_input_is_refused_explicitly(mutate: Any) -> None:
    unified = _unified()
    mutate(unified)
    with pytest.raises(ConfirmationInputError):
        build_confirmation(unified)
    with pytest.raises(ConfirmationInputError):
        build_confirmation("nope")  # type: ignore[arg-type]


# ----------------------------------------------------------------------- the real chain
def _real(codes: list[str]) -> dict[str, Any]:
    payload = make_payload(codes)
    payload["snapshot_version"] = "analyst_snapshot.v1"
    return build_confirmation(build_unified_snapshot(payload))


def test_real_chain_fresh_evidence_confirms() -> None:
    out = _real(["S2", "S1", "S1", "S1", "S2"])
    btc = out["assets"]["BTC"]
    assert btc["agreement"] == "confirmed_supportive"
    assert len(btc["supportive_families"]) == 5
    assert all(m["eligible"] for m in btc["members"])
    assert out["assets"]["BTC"]["members"][0]["freshness_records"]  # provenance carried through


def test_real_chain_stale_key_layer_is_not_a_confirmer() -> None:
    out = _real(["S2~", "S1~", "S1", "S1", "S2"])
    btc = out["assets"]["BTC"]
    states = {m["domain"]: m["state"] for m in btc["members"]}
    assert states["institutional"] == "stale"
    assert states["whale"] == "stale"
    assert btc["agreement"] == "unconfirmed"
    assert btc["reasons"] == ["CF-NO-KEY-LAYER"]


def test_real_chain_opposition_is_mixed_even_with_low_coverage() -> None:
    out = _real(["S2", "U", "A1", "U", "U"])
    btc = out["assets"]["BTC"]
    assert btc["agreement"] == "mixed"
    assert btc["reasons"][:2] == ["CF-MIXED", "CF-MIXED-LOW-COVERAGE"]


def test_real_chain_live_state_is_insufficient_and_keeps_identity() -> None:
    unified = build_unified_snapshot(live_state_payload())
    out = build_confirmation(unified)
    assert out["snapshot"] == unified["snapshot"]
    assert out["data_quality"] == unified["data_quality"]
    for scope in SCOPES:
        assert out["assets"][scope]["agreement"] == "insufficient_evidence"
        block = out["assets"][scope]
        # Only a reading that really is eligible can appear; the unavailable domains cannot.
        eligible = {m["family"] for m in block["members"] if m["eligible"]}
        assert set(block["supportive_families"]) | set(block["adverse_families"]) <= eligible
        for member in block["members"]:
            if member["state"] == "unavailable":
                assert member["exclusion_reason"].startswith("status:")
