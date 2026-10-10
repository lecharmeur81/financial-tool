"""``risk_view.v0`` (Phase 48; ADR-0085): the decision engine's risk results, copied unchanged."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from cfi.decision.context import InvalidSnapshotError, build_decision_context
from cfi.decision.universe import SCOPE_DOMAINS
from cfi.intelligence import build_risk_view, build_unified_snapshot
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload

SCOPES = tuple(SCOPE_DOMAINS)


def _payload() -> dict[str, Any]:
    payload = make_payload(["S2", "S1", "N", "S1", "S2"])
    payload["snapshot_version"] = "analyst_snapshot.v1"
    return payload


def test_the_view_has_a_fixed_shape() -> None:
    view = build_risk_view(_payload())
    assert view["contract_version"] == "risk_view.v0"
    assert view["source"] == "decision_engine"
    assert set(view["decision"]) == {"methodology_version", "parameter_version"}
    assert list(view["scopes"]) == list(SCOPES)
    for scope_view in view["scopes"].values():
        assert set(scope_view) == {
            "caps_evaluated",
            "risks",
            "max_risk",
            "observed_caps",
            "cap_u",
            "source_status",
        }
        assert [r["dimension"] for r in scope_view["risks"]] == [
            "market",
            "liquidity",
            "leverage",
            "volatility",
            "narrative",
            "data_quality",
        ]
        assert set(scope_view["source_status"]) == {"regime", "derivatives", "anomaly"}


def test_levels_caps_and_versions_are_the_decision_engines_own_values() -> None:
    payload = _payload()
    view = build_risk_view(payload)
    for scope in SCOPES:
        a = build_decision_context(payload, scope).assessment
        sv = view["scopes"][scope]
        assert view["decision"]["methodology_version"] == a.methodology_version
        assert view["decision"]["parameter_version"] == a.parameter_version
        assert [(r["dimension"], r["level"]) for r in sv["risks"]] == [
            (r.dimension.value, r.level.value) for r in a.risks
        ]
        assert [r["reason_ids"] for r in sv["risks"]] == [list(r.reason_ids) for r in a.risks]
        assert [r["field_ids"] for r in sv["risks"]] == [list(r.field_ids) for r in a.risks]
        assert sv["max_risk"] == a.max_risk.value
        assert [(c["rule_id"], c["binding"]) for c in sv["observed_caps"]] == [
            (c.rule_id, c.binding) for c in a.observed_caps
        ]
        assert [c["rule_id"] for c in sv["cap_u"]] == [c.rule_id for c in a.cap_u]


def test_caps_are_evaluated_only_for_a_bullish_family_raw_stance() -> None:
    view = build_risk_view(_payload())
    flags = {s: v["caps_evaluated"] for s, v in view["scopes"].items()}
    assert flags["BTC"] is True
    assert flags["SOL"] is False  # a neutral raw stance: caps were not evaluated, not absent


def test_the_raw_stance_is_not_exposed() -> None:
    text = json.dumps(build_risk_view(_payload())).lower()
    assert "stance" not in text
    assert "recommend" not in text


def test_the_identity_equals_the_unified_snapshot_identity() -> None:
    payload = _payload()
    view = build_risk_view(payload)
    snapshot = build_unified_snapshot(payload)["snapshot"]
    for key, value in view["identity"].items():
        assert snapshot[key] == value, key
    assert set(view["identity"]) == {
        "row_id",
        "uuid",
        "row_created_at",
        "as_of",
        "knowledge_time",
        "snapshot_version",
        "producer_payload_hash",
        "producer_hash_check",
        "decision_input_hash",
    }


def test_the_view_is_deterministic_json_and_does_not_mutate_the_payload() -> None:
    payload = _payload()
    before = copy.deepcopy(payload)
    first = build_risk_view(payload)
    assert first == build_risk_view(payload)
    assert payload == before
    assert json.loads(json.dumps(first)) == first


def test_the_live_state_view_reports_unassessed_dimensions_without_raising() -> None:
    view = build_risk_view(live_state_payload())
    for sv in view["scopes"].values():
        levels = {r["dimension"]: r["level"] for r in sv["risks"]}
        assert levels["market"] == "Not assessed"  # missing evidence is explicit, not Low
        assert sv["caps_evaluated"] is False


def test_an_unsupported_payload_is_refused() -> None:
    payload = _payload()
    payload["snapshot_version"] = "analyst_snapshot.v0"
    with pytest.raises(InvalidSnapshotError):
        build_risk_view(payload)
