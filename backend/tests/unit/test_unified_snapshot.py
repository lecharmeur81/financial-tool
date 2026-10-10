"""Unified Intelligence Snapshot (Phase 44): a stored payload -> ``unified_snapshot.v0``.

Pure: no database, network, clock or model. The builder only arranges the Decision Context's own
readings, so these tests pin the arrangement (every domain once, nothing duplicated across
assets, unavailable never neutral, regime never a vote) and that the existing view is untouched."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from cfi.decision.context import InvalidSnapshotError
from cfi.decision.identity import SnapshotRef, producer_payload_hash
from cfi.decision.read_service import build_decision_view
from cfi.intelligence import CONTRACT_VERSION, build_unified_snapshot
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload

BULLISH = ["S2", "S1", "N", "S1", "S2"]
GLOBAL = {
    "liquidity",
    "macro",
    "market_structure",
    "regime",
    "anomaly",
    "retail",
    "similarity",
    "divergence",
    "rotation",
    "market_data",
}


def _stored(codes: list[str], **kwargs: Any) -> dict[str, Any]:
    payload = make_payload(codes, **kwargs)
    payload["snapshot_version"] = "analyst_snapshot.v1"
    return payload


def _g(snap: dict[str, Any], component: str) -> dict[str, Any]:
    return next(e for e in snap["global_domains"] if e["component"] == component)


def _a(snap: dict[str, Any], asset: str, domain: str) -> dict[str, Any]:
    return next(e for e in snap["assets"][asset]["domains"] if e["domain"] == domain)


def test_contract_shape_and_every_domain_is_explicit() -> None:
    snap = build_unified_snapshot(_stored(BULLISH))
    assert snap["contract_version"] == CONTRACT_VERSION == "unified_snapshot.v0"
    assert {e["domain"] for e in snap["global_domains"]} == GLOBAL
    assert set(snap["assets"]) == {"BTC", "ETH", "SOL", "XRP"}
    for asset in ("BTC", "ETH"):
        assert {e["domain"] for e in snap["assets"][asset]["domains"]} == {
            "institutional",
            "whale",
            "derivatives",
        }
        assert snap["assets"][asset]["not_tracked_domains"] == []
    for asset in ("SOL", "XRP"):
        assert {e["domain"] for e in snap["assets"][asset]["domains"]} == {
            "institutional",
            "derivatives",
        }
        assert snap["assets"][asset]["not_tracked_domains"] == ["whale"]


def test_global_evidence_appears_once_and_is_not_duplicated_per_asset() -> None:
    snap = build_unified_snapshot(_stored(BULLISH))
    for asset in snap["assets"].values():
        assert not {e["domain"] for e in asset["domains"]} & GLOBAL
    components = [e["component"] for e in snap["global_domains"]]
    assert len(components) == len(set(components))


def test_global_entries_do_not_depend_on_the_scope_they_were_read_from() -> None:
    # The builder reads global evidence from the BTC assessment; pin that the other scopes agree.
    from cfi.decision.context import build_decision_context

    payload = _stored(BULLISH)
    btc = build_unified_snapshot(payload)["global_domains"]
    for scope in ("ETH", "SOL", "XRP"):
        ctx = build_decision_context(payload, scope)
        other = [
            (r.domain, r.component, r.status, r.freshness.value, r.band)
            for r in ctx.assessment.readings
            if r.domain in GLOBAL
        ]
        mine = [(e["domain"], e["component"], e["status"], e["freshness"], e["band"]) for e in btc]
        assert sorted(other) == sorted(mine)


def test_regime_and_other_non_directional_readings_are_never_votes() -> None:
    snap = build_unified_snapshot(_stored(BULLISH))
    regime = _g(snap, "regime.regime_id")
    assert regime["role"] == "Context"
    assert regime["independent_vote"] is False
    assert regime["direction"] is None
    for entry in snap["global_domains"]:
        assert entry["independent_vote"] is (entry["role"] == "Directional")
    assert _g(snap, "liquidity.score")["independent_vote"] is True
    assert _g(snap, "anomaly.volatility")["independent_vote"] is False


def test_unavailable_stays_unavailable_and_is_never_neutral() -> None:
    snap = build_unified_snapshot(_stored(["U", "U", "U", "U", "U"], regime=None, derivatives=None))
    for entry in (
        _g(snap, "liquidity.score"),
        _g(snap, "macro.score"),
        _g(snap, "regime.regime_id"),
        _a(snap, "BTC", "institutional"),
        _a(snap, "BTC", "whale"),
        _a(snap, "BTC", "derivatives"),
    ):
        assert entry["insufficient_data"] is True
        assert entry["evidence_state"] != "available"
        assert entry["direction"] in (None, "U")
        assert entry["direction"] != "N"
    assert snap["coverage"]["insufficient"] > 0
    assert (
        snap["coverage"]["available"] + snap["coverage"]["insufficient"]
        == (snap["coverage"]["entries"])
    )


def test_stale_and_partial_are_distinct_states() -> None:
    snap = build_unified_snapshot(_stored(["S1~", "N", "S1*", "N", "S1"]))
    inst = _a(snap, "BTC", "institutional")
    assert inst["evidence_state"] == "stale"
    assert "stale" in inst["quality_flags"]
    assert inst["insufficient_data"] is False
    liq = _g(snap, "liquidity.score")
    assert "partial" in liq["quality_flags"]
    assert liq["evidence_state"] != "stale"


def test_derivatives_without_a_freshness_node_is_not_assessed_not_stale() -> None:
    entry = _a(build_unified_snapshot(_stored(BULLISH)), "BTC", "derivatives")
    assert entry["freshness"] == "not_assessed"
    assert entry["evidence_state"] == "available_freshness_not_assessed"
    assert entry["freshness_records"] == []


def test_live_state_reports_insufficient_data_explicitly() -> None:
    snap = build_unified_snapshot(live_state_payload())
    for component in ("liquidity.score", "macro.score", "market_structure.score"):
        entry = _g(snap, component)
        assert entry["status"] == "insufficient_data"
        assert entry["freshness"] == "no_data"
        assert entry["insufficient_data"] is True
        assert entry["direction"] == "U"
    assert _a(snap, "BTC", "institutional")["insufficient_data"] is True
    assert snap["coverage"]["by_evidence_state"].get("insufficient_data", 0) >= 4


def test_freshness_records_are_copied_from_the_decision_context() -> None:
    payload = live_state_payload()
    snap = build_unified_snapshot(payload)
    view = build_decision_view(payload, "BTC")
    for row in view["domains"]:
        if row["domain"] != "institutional":
            continue
        mine = _a(snap, "BTC", "institutional")
        assert mine["status"] == row["status"]
        assert mine["freshness"] == row["freshness"]
        assert mine["quality_flags"] == row["quality_flags"]


def test_identity_provenance_and_platform_limits_are_preserved() -> None:
    payload = _stored(BULLISH)
    payload["snapshot_version"] = "analyst_snapshot.v1"
    stored_hash = producer_payload_hash(payload)
    from datetime import UTC, datetime

    ref = SnapshotRef(
        row_id=7,
        uuid="00000000-0000-0000-0000-000000000007",
        payload_hash=stored_hash,
        created_at=datetime(2026, 10, 5, tzinfo=UTC),
    )
    snap = build_unified_snapshot(payload, snapshot_ref=ref)["snapshot"]
    assert snap["row_id"] == 7
    assert snap["uuid"] == "00000000-0000-0000-0000-000000000007"
    assert snap["producer_payload_hash"] == stored_hash
    assert snap["producer_hash_check"] == "verified"
    assert snap["as_of"] == payload["as_of"]
    assert snap["knowledge_time"] == payload["knowledge_time"]
    assert snap["snapshot_version"] == "analyst_snapshot.v1"
    assert snap["snapshot_data_quality_state"] == "ok"
    built = build_unified_snapshot(payload)
    assert built["data_quality"]["platform_limits"] == ["mid-cap assets"]
    assert built["snapshot"]["producer_hash_check"] == "unverified"


def test_a_hash_mismatch_is_reported_not_repaired() -> None:
    payload = _stored(BULLISH)
    ref = SnapshotRef(payload_hash="0" * 64)
    assert (
        build_unified_snapshot(payload, snapshot_ref=ref)["snapshot"]["producer_hash_check"]
        == "mismatch"
    )


def test_look_ahead_violations_are_surfaced() -> None:
    payload = _stored(BULLISH)
    payload["as_of"] = "2026-10-06T00:00:00+00:00"  # later than knowledge_time
    assert "as_of" in build_unified_snapshot(payload)["data_quality"]["look_ahead_violations"]
    assert build_unified_snapshot(_stored(BULLISH))["data_quality"]["look_ahead_violations"] == []


def test_tool_quality_lists_are_carried_from_the_payload() -> None:
    snap = build_unified_snapshot(live_state_payload())
    dq = snap["data_quality"]
    assert isinstance(dq["unavailable_tools"], list)
    assert isinstance(dq["degraded_tools"], list)
    assert isinstance(dq["conflicting_tools"], list)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(snapshot_version="analyst_snapshot.v0"),
        lambda p: p.update(tool_results=[]),
        lambda p: p.update(as_of="not a time"),
        lambda p: p.pop("knowledge_time"),
    ],
)
def test_unsupported_or_malformed_payloads_are_refused_explicitly(mutate: Any) -> None:
    payload = _stored(BULLISH)
    mutate(payload)
    with pytest.raises(InvalidSnapshotError):
        build_unified_snapshot(payload)
    with pytest.raises(InvalidSnapshotError):
        build_unified_snapshot("nope")  # type: ignore[arg-type]


def test_deterministic_pure_and_does_not_mutate_the_payload() -> None:
    payload = _stored(BULLISH)
    before = copy.deepcopy(payload)
    first = build_unified_snapshot(payload)
    second = build_unified_snapshot(payload)
    assert first == second
    assert payload == before
    json.dumps(first)  # plain JSON data


def test_the_contract_carries_no_stance_score_or_recommendation() -> None:
    text = json.dumps(build_unified_snapshot(_stored(BULLISH))).lower()
    for word in (
        "stance",
        "posture",
        "confidence",
        "recommend",
        "buy",
        "sell",
        "bullish",
        "bearish",
    ):
        assert word not in text


def test_the_decision_view_is_unchanged_by_building_the_snapshot() -> None:
    payload = _stored(BULLISH)
    before = build_decision_view(copy.deepcopy(payload), "BTC")
    build_unified_snapshot(payload)
    assert build_decision_view(payload, "BTC") == before
