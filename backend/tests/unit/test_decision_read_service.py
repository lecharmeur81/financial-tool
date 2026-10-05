"""Decision read service (Phase 39): a stored payload -> the Decision Center view.

Pure: no database, no network, no clock. The live-state payload reproduces what the real
``ai.snapshot`` check showed (four domains ``insufficient_data`` with explicit reasons, producer
flag ``ok``)."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from cfi.decision.context import InvalidSnapshotError, UnsupportedScopeError
from cfi.decision.identity import SnapshotRef, producer_payload_hash
from cfi.decision.read_service import (
    CONTRACT_VERSION,
    SUPPORTED_ASSETS,
    build_decision_view,
    normalise_asset,
)
from tests.decision_builders import make_payload
from tests.decision_live_payload import (
    BREADTH_REASON,
    ETH_BTC_REASON,
    GENERIC_NOTE,
    INSTITUTIONAL_NOTE,
    SCORE_REASON,
    USDT_REASON,
    VIX_REASON,
    live_state_payload,
)

MISSING_FOUR = ["institutional", "liquidity", "macro", "market_structure"]
BULLISH = ["S2", "S1", "N", "S1", "S2"]


def _domain(view: dict[str, Any], name: str) -> dict[str, Any]:
    return next(d for d in view["domains"] if d["domain"] == name)


def _stored(codes: list[str], **kwargs: Any) -> dict[str, Any]:
    payload = make_payload(codes, **kwargs)
    payload["snapshot_version"] = "analyst_snapshot.v1"
    return payload


# ------------------------------------------------------------------ the live data state


def test_live_state_is_insufficient_evidence_with_the_engines_own_labels() -> None:
    view = build_decision_view(live_state_payload(), "BTC")
    assert view["contract_version"] == CONTRACT_VERSION
    assert view["stance"]["final"] == "Insufficient Evidence"
    assert view["stance"]["raw"] == "Insufficient Evidence"
    assert view["stance"]["confidence"] == "Insufficient Evidence"
    assert view["stance"]["posture"] == "INVESTIGATE FURTHER"
    assert view["stance"]["differs_from_raw"] is False
    assert view["stance"]["cap_u_applied"] is False
    assert view["coverage"]["missing"] == MISSING_FOUR
    assert view["coverage"]["available"] < view["coverage"]["expected"]


@pytest.mark.parametrize("domain", MISSING_FOUR)
def test_each_missing_domain_is_insufficient_data_with_no_data_freshness(domain: str) -> None:
    row = _domain(build_decision_view(live_state_payload(), "BTC"), domain)
    assert row["evidence_state"] == "insufficient_data"
    assert row["status"] == "insufficient_data"
    assert row["freshness"] == "no_data"
    assert row["direction"] == "U"
    assert "no_data" in row["freshness_info"]["status_counts"]


def test_explicit_reason_strings_are_copied_verbatim_from_fixed_paths() -> None:
    view = build_decision_view(live_state_payload(), "BTC")
    by_domain = {
        d: {(r["kind"], r["text"]) for r in _domain(view, d)["reasons"]} for d in MISSING_FOUR
    }
    assert ("score_reason", SCORE_REASON) in by_domain["institutional"]
    assert ("freshness_note", INSTITUTIONAL_NOTE) in by_domain["institutional"]
    assert ("score_reason", SCORE_REASON) in by_domain["liquidity"]
    assert ("component_reason", USDT_REASON) in by_domain["liquidity"]
    assert ("component_reason", VIX_REASON) in by_domain["macro"]
    assert ("component_reason", ETH_BTC_REASON) in by_domain["market_structure"]
    assert ("component_reason", BREADTH_REASON) in by_domain["market_structure"]


def test_every_reason_is_traceable_to_the_payload_and_none_is_invented() -> None:
    """The service may not state a cause the snapshot does not: every reason text is a string
    that exists in the payload at the path given, and no causal claim appears anywhere."""
    payload = live_state_payload()
    view = build_decision_view(payload, "BTC")
    reasons = [r for d in view["domains"] for r in d["reasons"]]
    assert reasons
    for reason in reasons:
        node: Any = payload
        for part in reason["path"].replace("]", "").replace("[", ".").split("."):
            node = node[int(part)] if isinstance(node, list) else node[part]
        assert node == reason["text"]
    blob = json.dumps(view).lower()
    for claim in ("api key", "provider down", "ingestion failed", "disconnected", "not configured"):
        assert claim not in blob


def test_the_generic_producer_note_and_flags_are_not_surfaced() -> None:
    view = build_decision_view(live_state_payload(), "BTC")
    blob = json.dumps(view)
    assert GENERIC_NOTE not in blob
    assert "data_quality_state" not in blob
    assert "has_conflicts" not in blob
    # the producer says "ok"; the view still reports four missing domains
    assert view["coverage"]["missing"] == MISSING_FOUR
    assert view["data_quality"]["unavailable_components"]


def test_a_reading_with_no_recorded_reason_gets_no_invented_one() -> None:
    row = _domain(build_decision_view(live_state_payload(), "BTC"), "regime")
    assert row["evidence_state"] != "available"
    assert row["reasons"] == []


def test_empty_display_fields_are_not_treated_as_evidence() -> None:
    payload = live_state_payload()
    payload["fields"]["get_liquidity.supply.USDT"] = {
        "display": "",
        "quality_status": "unavailable",
        "evidence_category": None,
        "unit": None,
        "source": "get_liquidity",
    }
    view = build_decision_view(payload, "BTC")
    technical = view["technical"]
    assert all(f["display"].strip() for f in technical["fields"])
    assert isinstance(technical["fields_without_display"], int)


# ------------------------------------------------------------------ scopes and labels


@pytest.mark.parametrize("asset", SUPPORTED_ASSETS)
def test_every_supported_scope_builds(asset: str) -> None:
    view = build_decision_view(live_state_payload(scope=asset), asset)
    assert view["asset"] == asset
    assert view["stance"]["final"] == "Insufficient Evidence"


def test_default_asset_is_btc_and_symbols_are_normalised() -> None:
    payload = live_state_payload()
    assert build_decision_view(payload)["asset"] == "BTC"
    assert build_decision_view(payload, " eth ")["asset"] == "ETH"
    assert normalise_asset(None) == "BTC"


@pytest.mark.parametrize("asset", ["DOGE", "", "BTC-USD", "bitcoin"])
def test_unsupported_asset_is_refused(asset: str) -> None:
    with pytest.raises(UnsupportedScopeError):
        build_decision_view(live_state_payload(), asset)


def test_scope_labels_distinguish_asset_specific_from_market_wide() -> None:
    view = build_decision_view(live_state_payload(), "BTC")
    label = {d["domain"]: (d["scope_label"] or {}).get("code") for d in view["domains"]}
    assert label["institutional"] == "asset_specific"
    assert label["whale"] == "asset_specific"
    assert label["derivatives"] == "asset_specific"
    assert label["liquidity"] == "market_wide"
    assert label["macro"] == "market_wide"
    assert label["market_structure"] == "market_wide_btc_benchmarked"
    assert label["regime"] == "market_wide_btc_benchmarked"
    assert label["anomaly"] == "btc_only"


def test_scope_notes_say_other_assets_are_not_independent_analyses() -> None:
    assert build_decision_view(live_state_payload(), "BTC")["scope_notes"] == []
    eth_notes = build_decision_view(live_state_payload(scope="ETH"), "ETH")["scope_notes"]
    assert any("not independent" in n for n in eth_notes)
    assert not any("Whale" in n for n in eth_notes)
    sol_notes = build_decision_view(live_state_payload(scope="SOL"), "SOL")["scope_notes"]
    assert any("Whale activity is only tracked for BTC and ETH" in n for n in sol_notes)
    assert any("not independent" in n for n in sol_notes)


def test_btc_data_is_never_silently_used_for_another_assets_domain() -> None:
    """SOL has no whale domain: it is reported as out of scope, never read from BTC."""
    view = build_decision_view(live_state_payload(scope="SOL"), "SOL")
    assert "whale" not in {d["domain"] for d in view["domains"]}
    assert "whale" not in view["coverage"]["missing"]


# ------------------------------------------------------------------ CAP-U / conflict / evidence


def test_cap_u_shows_raw_versus_final_stance() -> None:
    view = build_decision_view(_stored(BULLISH, regime=None), "BTC")
    assert view["stance"]["differs_from_raw"] is True
    assert view["stance"]["cap_u_applied"] is True
    assert view["stance"]["raw"] != view["stance"]["final"]
    cap = view["cap_u"][0]
    assert cap["rule_id"].startswith("CU-")
    assert cap["raw_stance"] == view["stance"]["raw"]
    assert cap["final_stance"] == view["stance"]["final"]
    assert cap["text"]  # the engine's own sentence, resolved from its template id


def test_no_cap_u_when_the_evidence_is_complete() -> None:
    view = build_decision_view(_stored(BULLISH), "BTC")
    assert view["cap_u"] == []
    assert view["stance"]["differs_from_raw"] is False


def test_supporting_and_adverse_evidence_carry_engine_text_and_scope() -> None:
    view = build_decision_view(_stored(["S2", "A1", "S1", "A2", "N"]), "BTC")
    assert view["evidence"]["supportive"]
    assert view["evidence"]["adverse"]
    for item in view["evidence"]["supportive"] + view["evidence"]["adverse"]:
        assert item["text"]
        assert item["scope_label"] is not None
    assert {i["side"] for i in view["evidence"]["supportive"]} == {"supportive"}


def test_sources_conflict_is_distinct_from_insufficient_data() -> None:
    conflicted = build_decision_view(_stored(["S2", "A2", "S2", "A2", "N"]), "BTC")
    insufficient = build_decision_view(live_state_payload(), "BTC")
    assert conflicted["conflict"]["directional"] is True
    assert conflicted["coverage"]["missing"] == []
    assert insufficient["conflict"]["directional"] is False
    assert insufficient["coverage"]["missing"] == MISSING_FOUR


def test_missing_evidence_is_never_reported_as_zero_or_bearish() -> None:
    view = build_decision_view(live_state_payload(), "BTC")
    evidence = view["evidence"]
    assert evidence["adverse"] == []
    assert {i["domain"] for i in evidence["supportive"]} == {"whale"}  # only what has data
    assert all(d["direction"] == "U" for d in view["domains"] if d["domain"] in MISSING_FOUR)


# ------------------------------------------------------------------ identity, determinism, purity


def test_producer_hash_identity_is_preserved_and_kept_distinct() -> None:
    payload = live_state_payload()
    stored = producer_payload_hash(payload)
    ref = SnapshotRef(row_id=7, uuid="u-1", payload_hash=stored)
    snap = build_decision_view(payload, "BTC", snapshot_ref=ref)["snapshot"]
    assert snap["row_id"] == 7
    assert snap["uuid"] == "u-1"
    assert snap["producer_payload_hash"] == stored
    assert snap["producer_hash_check"] == "verified"
    assert snap["decision_input_hash"] != stored  # two different hashes, never equated


def test_a_tampered_producer_hash_is_reported_as_a_mismatch_not_repaired() -> None:
    payload = live_state_payload()
    ref = SnapshotRef(row_id=1, uuid="u", payload_hash="0" * 64)
    snap = build_decision_view(payload, "BTC", snapshot_ref=ref)["snapshot"]
    assert snap["producer_hash_check"] == "mismatch"
    assert snap["producer_payload_hash"] == "0" * 64


def test_without_a_row_the_hash_is_unverified() -> None:
    snap = build_decision_view(live_state_payload(), "BTC")["snapshot"]
    assert snap["producer_hash_check"] == "unverified"
    assert snap["row_id"] is None


def test_the_view_is_deterministic_and_json_serialisable() -> None:
    payload = live_state_payload()
    first = json.dumps(build_decision_view(payload, "BTC"), sort_keys=True)
    second = json.dumps(build_decision_view(copy.deepcopy(payload), "BTC"), sort_keys=True)
    assert first == second
    assert "generated_at" not in first


def test_building_a_view_does_not_mutate_the_payload() -> None:
    payload = live_state_payload()
    before = copy.deepcopy(payload)
    build_decision_view(payload, "BTC")
    assert payload == before


def test_every_assessment_text_is_resolved_or_explicitly_none() -> None:
    view = build_decision_view(_stored(BULLISH), "BTC")
    assert view["stance"]["headline"]
    for item in view["why"]["directional"]:
        assert item["id"]


# ------------------------------------------------------------------ invalid input


def test_an_unsupported_snapshot_version_is_refused() -> None:
    payload = live_state_payload()
    payload["snapshot_version"] = "analyst_snapshot.v999"
    with pytest.raises(InvalidSnapshotError):
        build_decision_view(payload, "BTC")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("as_of"),
        lambda p: p.update(as_of="not-a-time"),
        lambda p: p.update(tool_results=[]),
    ],
)
def test_a_malformed_payload_is_refused(mutate: Any) -> None:
    payload = live_state_payload()
    mutate(payload)
    with pytest.raises(InvalidSnapshotError):
        build_decision_view(payload, "BTC")


def test_malformed_tool_results_do_not_break_reason_extraction() -> None:
    payload = live_state_payload()
    payload["tool_results"]["get_liquidity"] = {"status": "ok", "data": "oops"}
    payload["tool_results"]["get_macro"]["data"]["vix"] = "oops"
    payload["tool_results"]["get_institutional_flows"]["data"]["assets"] = "oops"
    view = build_decision_view(payload, "BTC")
    assert view["stance"]["final"] == "Insufficient Evidence"
