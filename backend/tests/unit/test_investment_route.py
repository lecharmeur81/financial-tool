"""``GET /api/v1/intelligence/investment-decision`` without a database (Phase 49): the storage
dependency is an in-memory source, so the 200 / 404 / 503 contract is covered where the integration
services are not configured. The PostgreSQL round trip is in
``tests/integration/test_investment_api.py``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cfi.analyst.repository import SnapshotRow
from cfi.api.app import create_app
from cfi.api.routes import intelligence_investment as route
from cfi.api.routes.decision import get_snapshot_source
from cfi.core.config import Settings
from cfi.decision.identity import producer_payload_hash
from cfi.intelligence import InvestmentInputError
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload

PATH = "/api/v1/intelligence/investment-decision"
STATES = {
    "withheld_integrity_gate",
    "candidate_invalidation_triggered",
    "contradicted_evidence",
    "insufficient_evidence",
    "no_opportunity",
    "candidate_risk_findings_detected",
    "candidate_unresolved",
    "candidate_no_findings_detected",
}


class _Source:
    def __init__(self, row: SnapshotRow | None) -> None:
        self.row = row

    async def latest_snapshot_row(self) -> SnapshotRow | None:
        return self.row


def _get(row: SnapshotRow | None) -> tuple[int, dict[str, Any]]:
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://u:not-a-real-password@db:5432/x"),
        redis_url=SecretStr("redis://:not-a-real-password@redis:6379/0"),
    )
    app = create_app(settings, health_checks={})  # no engine / Redis is created
    app.dependency_overrides[get_snapshot_source] = lambda: _Source(row)
    with TestClient(app) as client:
        response = client.get(PATH)
    return response.status_code, response.json()


def _payload() -> dict[str, Any]:
    payload = make_payload(["S2", "S1", "N", "S1", "S2"])
    payload["snapshot_version"] = "analyst_snapshot.v1"
    return payload


def _row(payload: dict[str, Any]) -> SnapshotRow:
    return SnapshotRow(
        row_id=4,
        uuid="00000000-0000-0000-0000-000000000004",
        payload_hash=producer_payload_hash(payload),
        created_at=datetime(2026, 10, 5, tzinfo=UTC),
        payload=payload,
    )


def test_a_stored_snapshot_is_served_with_decision_states_and_its_identity() -> None:
    status, body = _get(_row(_payload()))
    assert status == 200
    assert body["contract_version"] == "investment_decision.v0"
    assert body["parameters"]["version"] == "investment_params.v0"
    assert body["parameters"]["states_version"] == "investment_states.v0"
    assert body["source_contracts"]["risk"] == "risk_invalidation.v0"
    assert body["snapshot"]["row_id"] == 4
    assert body["snapshot"]["producer_hash_check"] == "verified"
    assert list(body["assets"]) == ["BTC", "ETH", "SOL", "XRP"]
    assert {s["id"] for s in body["states"]} == STATES
    btc = body["assets"]["BTC"]
    assert btc["decision_state"] in STATES
    assert btc["status"] == "candidate"
    assert btc["decision_state"] == "candidate_unresolved"
    assert btc["why_not_conclusive"]
    assert btc["risk_assessment"]["state"] == "assessed"
    assert btc["risk_assessment"]["reasons"] == ["RI-ASSESSED"]
    assert btc["risk_findings"]["unverified"]
    assert btc["invalidation"]["conditions"][-1]["condition_id"] == "INV-06"
    assert btc["ranking_context"]["used_for_decision"] is False
    assert btc["evidence"]["supporting"]
    assert body["evidence_dependence"]["independent_confirmation"] is False
    assert body["notice"]["id"] == "research_state_not_a_recommendation"
    assert body["declared_unavailable"]
    assert body["limitations"]
    assert sum(body["counts"].values()) == 4


def test_the_live_state_snapshot_has_no_candidate_and_nothing_favourable() -> None:
    status, body = _get(_row(live_state_payload()))
    assert status == 200
    states = {a["decision_state"] for a in body["assets"].values()}
    assert states <= {"insufficient_evidence", "no_opportunity"}
    assert all(a["risk_findings"] is None for a in body["assets"].values())
    for asset in body["assets"].values():
        assert asset["risk_assessment"]["state"] == "not_applicable"
        assert {w["reason_id"] for w in asset["why_not_conclusive"]} >= {"DI-NO-RISK-ASSESSMENT"}


def test_no_stored_snapshot_is_a_404() -> None:
    status, body = _get(None)
    assert status == 404
    assert body["error_code"] == "not_found"


def test_an_unsupported_payload_is_a_503_with_the_reason_and_no_result() -> None:
    payload = _payload()
    payload["snapshot_version"] = "analyst_snapshot.v0"
    status, body = _get(_row(payload))
    assert status == 503
    assert "assets" not in body
    assert "investment decision" in str(body)


def test_inconsistent_inputs_are_a_503_not_a_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_: Any, **__: Any) -> dict[str, Any]:
        raise InvestmentInputError("the risk output was not derived from these inputs")

    monkeypatch.setattr(route, "build_investment_decision", refuse)
    status, body = _get(_row(_payload()))
    assert status == 503
    assert "not derived" in str(body)
    assert "assets" not in body


def test_a_producer_hash_mismatch_is_served_withheld_with_truthful_nulls() -> None:
    row = _row(_payload())
    row = SnapshotRow(
        row_id=row.row_id,
        uuid=row.uuid,
        payload_hash="0" * 64,  # does not match the payload: the producer-hash gate triggers
        created_at=row.created_at,
        payload=row.payload,
    )
    status, body = _get(row)
    assert status == 200
    assert body["assessment"] == {"performed": False, "gate_reasons": ["DI-GATE-INTEGRITY"]}
    for asset in body["assets"].values():
        assert asset["decision_state"] == "withheld_integrity_gate"
        # a blocked candidate is withheld; a non-candidate keeps Phase 48's not_applicable
        assert asset["risk_assessment"]["state"] in ("withheld", "not_applicable")
        assert asset["risk_findings"] is None
        assert asset["invalidation"] is None
        assert {"reason_id": "DI-GATE-WITHHELD", "ref": "DI-GATE-INTEGRITY"} in asset[
            "why_not_conclusive"
        ]
    assert body["assets"]["BTC"]["risk_assessment"]["state"] == "withheld"
    assert {f["result"] for f in body["market_risks"]} == {"withheld"}
