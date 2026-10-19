"""``GET /api/v1/advisor/brief`` without a database (Phase 53): the storage dependency is an
in-memory source, so the 200 / 404 / 422 / 503 contract is covered where the integration services
are not configured. The route writes nothing and calls no provider or Claude."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cfi.advisor import AdvisorInputError
from cfi.analyst.repository import SnapshotRow
from cfi.api.app import create_app
from cfi.api.routes import advisor as route
from cfi.api.routes.decision import get_snapshot_source
from cfi.core.config import Settings
from cfi.decision.identity import producer_payload_hash
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload

PATH = "/api/v1/advisor/brief"


class _Source:
    def __init__(self, row: SnapshotRow | None) -> None:
        self.row = row
        self.reads = 0

    async def latest_snapshot_row(self) -> SnapshotRow | None:
        self.reads += 1
        return self.row


def _get(row: SnapshotRow | None, query: str = "") -> tuple[int, dict[str, Any], _Source]:
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://u:not-a-real-password@db:5432/x"),
        redis_url=SecretStr("redis://:not-a-real-password@redis:6379/0"),
    )
    source = _Source(row)
    app = create_app(settings, health_checks={})  # no engine / Redis is created
    app.dependency_overrides[get_snapshot_source] = lambda: source
    with TestClient(app) as client:
        response = client.get(PATH + query)
    return response.status_code, response.json(), source


def _payload() -> dict[str, Any]:
    payload = make_payload(["S2", "S1", "N", "S1", "S2"])
    payload["snapshot_version"] = "analyst_snapshot.v1"
    return payload


def _row(payload: dict[str, Any]) -> SnapshotRow:
    return SnapshotRow(
        row_id=9,
        uuid="00000000-0000-0000-0000-000000000009",
        payload_hash=producer_payload_hash(payload),
        created_at=datetime(2026, 10, 5, tzinfo=UTC),
        payload=payload,
    )


def test_a_stored_snapshot_is_briefed_with_identity_layers_and_boundaries() -> None:
    status, body, source = _get(_row(_payload()))
    assert status == 200
    assert source.reads == 1  # one read, nothing else
    assert body["contract_version"] == "advisor_brief.v0"
    assert body["asset"] == "BTC"
    assert body["snapshot"]["row_id"] == 9
    assert body["snapshot"]["producer_hash_check"] == "verified"
    assert body["assessment"]["stance"]["final"] == "Strongly Bullish"
    assert body["assessment"]["investment_state"]["decision_state"] == "candidate_unresolved"
    assert body["signals"]
    assert body["readings"]
    assert body["invalidation"]["conditions"]
    assert {n["id"] for n in body["not_claimed"]} >= {"ADV-NOT-ADVICE", "ADV-NO-TRADING"}


def test_the_live_state_snapshot_is_a_brief_of_gaps_not_of_opinions() -> None:
    status, body, _ = _get(_row(live_state_payload()))
    assert status == 200
    assert body["assessment"]["stance"]["final"] == "Insufficient Evidence"
    assert body["data_gaps"]["has_gaps"] is True
    assert body["invalidation"] is None


def test_asset_query_is_case_insensitive_and_selects_that_asset() -> None:
    status, body, _ = _get(_row(_payload()), "?asset=eth")
    assert status == 200
    assert body["asset"] == "ETH"


def test_an_unsupported_asset_is_422_with_no_brief() -> None:
    status, body, _ = _get(_row(_payload()), "?asset=DOGE")
    assert status == 422
    assert "contract_version" not in body


def test_no_stored_snapshot_is_a_404() -> None:
    status, body, _ = _get(None)
    assert status == 404
    assert body["error_code"] == "not_found"


def test_an_unsupported_payload_is_a_503_with_the_reason_and_no_brief() -> None:
    payload = _payload()
    payload["snapshot_version"] = "analyst_snapshot.v0"
    status, body, _ = _get(_row(payload))
    assert status == 503
    assert "advisor brief" in str(body)
    assert "assessment" not in body


def test_inconsistent_contracts_are_a_503_not_a_partial_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_: Any, **__: Any) -> dict[str, Any]:
        raise AdvisorInputError("the two contracts were built from different snapshots")

    monkeypatch.setattr(route, "build_advisor_brief", refuse)
    status, body, _ = _get(_row(_payload()))
    assert status == 503
    assert "different snapshots" in str(body)
    assert "assessment" not in body
