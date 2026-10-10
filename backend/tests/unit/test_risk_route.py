"""``GET /api/v1/intelligence/risk-invalidation`` without a database (Phase 48): the storage
dependency is an in-memory source, so the 200 / 404 / 503 contract is covered where the integration
services are not configured. The PostgreSQL round trip is in
``tests/integration/test_risk_api.py``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cfi.analyst.repository import SnapshotRow
from cfi.api.app import create_app
from cfi.api.routes import intelligence_risk as risk_route
from cfi.api.routes.decision import get_snapshot_source
from cfi.core.config import Settings
from cfi.decision.identity import producer_payload_hash
from cfi.intelligence import RiskInputError
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload

PATH = "/api/v1/intelligence/risk-invalidation"


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


def test_a_stored_snapshot_is_served_with_risk_findings_and_its_identity() -> None:
    status, body = _get(_row(_payload()))
    assert status == 200
    assert body["contract_version"] == "risk_invalidation.v0"
    assert body["parameters"]["version"] == "risk_params.v0"
    assert body["checks"]["version"] == "risk_checks.v0"
    assert body["source_contracts"]["ranking"] == "opportunity_ranking.v0"
    assert body["source_contracts"]["risk_view"] == "risk_view.v0"
    assert body["snapshot"]["row_id"] == 4
    assert body["snapshot"]["producer_hash_check"] == "verified"
    assert list(body["assets"]) == ["BTC", "ETH", "SOL", "XRP"]
    assert body["assessment"]["performed"] is True
    btc = body["assets"]["BTC"]
    assert btc["assessment"] == "assessed"
    assert btc["findings"]
    assert btc["invalidation"]["conditions"][-1]["condition_id"] == "INV-06"
    assert btc["invalidation"]["conditions"][-1]["result"] != "triggered"
    assert {f["result"] for f in btc["findings"]} <= {
        "passed",
        "detected",
        "unverified",
        "unavailable",
        "not_applicable",
    }
    assert body["evidence_dependence"]["independent_confirmation"] is False
    assert body["notice"]["id"] == "risk_findings_not_a_safety_rating"
    assert body["unavailable_checks"]
    assert body["limitations"]


def test_the_live_state_snapshot_assesses_no_asset() -> None:
    status, body = _get(_row(live_state_payload()))
    assert status == 200
    assert all(a["assessment"] == "not_applicable" for a in body["assets"].values())
    assert "passed" not in {f["result"] for f in body["market_risks"]["findings"]}


def test_no_stored_snapshot_is_a_404() -> None:
    status, body = _get(None)
    assert status == 404
    assert body["error_code"] == "not_found"


def test_an_unsupported_payload_is_a_503_with_the_reason_and_no_assessment() -> None:
    payload = _payload()
    payload["snapshot_version"] = "analyst_snapshot.v0"
    status, body = _get(_row(payload))
    assert status == 503
    assert "assets" not in body
    assert "risk and invalidation" in str(body)


def test_inconsistent_inputs_are_a_503_not_a_partial_assessment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_: Any, **__: Any) -> dict[str, Any]:
        raise RiskInputError("the risk view and the opportunities describe different snapshots")

    monkeypatch.setattr(risk_route, "build_risk_view", refuse)
    status, body = _get(_row(_payload()))
    assert status == 503
    assert "different snapshots" in str(body)
    assert "assets" not in body
