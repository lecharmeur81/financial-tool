"""``GET /api/v1/intelligence/opportunities`` without a database (Phase 46): the storage dependency
is an in-memory source, so the 200 / 404 / 503 contract is covered where the integration services
are not configured. The PostgreSQL round trip is in
``tests/integration/test_ranking_api.py``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cfi.analyst.repository import SnapshotRow
from cfi.api.app import create_app
from cfi.api.routes import intelligence_ranking as ranking_route
from cfi.api.routes.decision import get_snapshot_source
from cfi.core.config import Settings
from cfi.decision.identity import producer_payload_hash
from cfi.intelligence import build_opportunities
from tests.decision_builders import make_payload

PATH = "/api/v1/intelligence/opportunity-ranking"


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


def test_a_stored_snapshot_is_served_ranked_with_its_identity() -> None:
    status, body = _get(_row(_payload()))
    assert status == 200
    assert body["contract_version"] == "opportunity_ranking.v0"
    assert body["parameters"]["version"] == "ranking_params.v0"
    assert body["components"]["version"] == "ranking_components.v0"
    assert body["source_contracts"]["opportunity"] == "opportunity_discovery.v0"
    assert body["snapshot"]["row_id"] == 4
    assert body["snapshot"]["producer_hash_check"] == "verified"
    assert list(body["assets"]) == ["BTC", "ETH", "SOL", "XRP"]
    btc = body["assets"]["BTC"]
    assert btc["scored"] is True
    assert isinstance(btc["evidence_depth"], int)
    assert 1 <= btc["evidence_depth"] <= 4
    assert btc["components"]["market_wide"]["points"] == 0
    assert body["notice"]["id"] == "evidence_depth_not_a_forecast"
    assert body["limitations"]
    assert [g["group_id"] for g in body["groups"]] == ["BTC+ETH", "SOL+XRP"]


def test_no_stored_snapshot_is_a_404_not_a_server_error() -> None:
    status, body = _get(None)
    assert status == 404
    assert body["error_code"] == "not_found"


def test_an_unsupported_stored_payload_is_a_503_with_the_reason() -> None:
    payload = _payload()
    payload["snapshot_version"] = "analyst_snapshot.v0"
    status, body = _get(_row(payload))
    assert status == 503
    assert "unsupported snapshot_version" in body["detail"]


def test_an_inconsistent_opportunity_input_is_a_503_and_never_a_partial_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def tampered(unified: dict[str, Any], confirmation: dict[str, Any]) -> dict[str, Any]:
        out = build_opportunities(unified, confirmation)
        out["assets"]["BTC"]["basis"]["asset_specific_supporting_families"] = []
        return out

    monkeypatch.setattr(ranking_route, "build_opportunities", tampered)
    status, body = _get(_row(_payload()))
    assert status == 503
    assert "opportunity ranking" in body["detail"]
    assert "assets" not in body
