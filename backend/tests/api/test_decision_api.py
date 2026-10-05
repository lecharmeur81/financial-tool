"""``GET /api/v1/decision/current`` (Phase 39) without a database: the storage dependency is
replaced by a fake that can only return one stored row, so these tests also prove the route reads a
stored snapshot and never builds one. The real-PostgreSQL round trip is in
``tests/integration/test_decision_api.py``."""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.analyst.repository import SnapshotRow
from cfi.api.app import create_app
from cfi.api.routes.decision import get_snapshot_source
from cfi.core.config import Settings
from cfi.core.health import HealthCheck
from cfi.decision.identity import producer_payload_hash
from tests.decision_live_payload import live_state_payload

PATH = "/api/v1/decision/current"
CREATED = datetime(2026, 10, 5, 23, 10, tzinfo=UTC)


async def _ok() -> Mapping[str, str]:
    return {"note": "fake"}


class FakeSource:
    """Only ``latest_snapshot_row`` exists: any other storage call raises ``AttributeError``."""

    def __init__(self, row: SnapshotRow | None) -> None:
        self.row = row
        self.calls = 0

    async def latest_snapshot_row(self) -> SnapshotRow | None:
        self.calls += 1
        return self.row


def _row(payload: dict[str, Any] | None = None) -> SnapshotRow:
    payload = payload or live_state_payload()
    return SnapshotRow(
        row_id=461,
        uuid="4c79f753-0ef7-4766-b131-406452df8ffd",
        payload_hash=producer_payload_hash(payload),
        created_at=CREATED,
        payload=payload,
    )


def _client(settings: Settings, source: FakeSource) -> Iterator[TestClient]:
    checks: dict[str, HealthCheck] = {"database": _ok, "redis": _ok}
    app = create_app(settings, health_checks=checks)
    app.dependency_overrides[get_snapshot_source] = lambda: source
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def source() -> FakeSource:
    return FakeSource(_row())


@pytest.fixture
def client(settings: Settings, source: FakeSource) -> Iterator[TestClient]:
    yield from _client(settings, source)


@pytest.fixture(autouse=True)
def _no_snapshot_building(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route must never build a snapshot (that is the slow regime/similarity path)."""

    async def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("the decision read path must not build a snapshot")

    monkeypatch.setattr("cfi.analyst.snapshot.build_snapshot", boom)


def test_latest_snapshot_is_read_and_btc_is_the_default(
    client: TestClient, source: FakeSource
) -> None:
    response = client.get(PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["asset"] == "BTC"
    assert body["stance"]["final"] == "Insufficient Evidence"
    assert body["stance"]["posture"] == "INVESTIGATE FURTHER"
    assert source.calls == 1


@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "sol"])
def test_every_supported_asset_returns_a_view(settings: Settings, asset: str) -> None:
    source = FakeSource(_row(live_state_payload(scope=asset.upper())))
    for client in _client(settings, source):
        response = client.get(PATH, params={"asset": asset})
        assert response.status_code == 200
        assert response.json()["asset"] == asset.upper()


def test_snapshot_identity_is_returned_and_the_hashes_stay_distinct(client: TestClient) -> None:
    snap = client.get(PATH).json()["snapshot"]
    assert snap["row_id"] == 461
    assert snap["uuid"] == "4c79f753-0ef7-4766-b131-406452df8ffd"
    assert snap["producer_hash_check"] == "verified"
    assert snap["producer_payload_hash"] != snap["decision_input_hash"]
    assert snap["as_of"] == "2026-10-05T23:09:52.212066+00:00"
    assert snap["knowledge_time"] == snap["as_of"]
    assert snap["row_created_at"] == CREATED.isoformat()


def test_missing_domains_come_with_their_explicit_reasons(client: TestClient) -> None:
    body = client.get(PATH).json()
    assert body["coverage"]["missing"] == [
        "institutional",
        "liquidity",
        "macro",
        "market_structure",
    ]
    macro = next(d for d in body["domains"] if d["domain"] == "macro")
    assert macro["evidence_state"] == "insufficient_data"
    assert any("no VIX value" in r["text"] for r in macro["reasons"])


def test_the_response_is_deterministic(settings: Settings) -> None:
    payload = live_state_payload()
    bodies = []
    for _ in range(2):
        for client in _client(settings, FakeSource(_row(copy.deepcopy(payload)))):
            bodies.append(client.get(PATH).text)
    assert bodies[0] == bodies[1]


def test_no_stored_snapshot_is_a_404_not_found(settings: Settings) -> None:
    for client in _client(settings, FakeSource(None)):
        response = client.get(PATH)
        assert response.status_code == 404
        assert response.json()["error_code"] == "not_found"


def test_an_unsupported_asset_is_a_422(client: TestClient, source: FakeSource) -> None:
    response = client.get(PATH, params={"asset": "DOGE"})
    assert response.status_code == 422
    assert response.json()["error_code"] == "data_validation_error"
    assert source.calls == 1


def test_an_invalid_stored_payload_is_a_503_with_the_reason(settings: Settings) -> None:
    payload = live_state_payload()
    payload["snapshot_version"] = "analyst_snapshot.v999"
    for client in _client(settings, FakeSource(_row(payload))):
        response = client.get(PATH)
        assert response.status_code == 503
        assert response.json()["error_code"] == "service_unavailable"
        assert "snapshot_version" in response.json()["detail"]


def test_without_a_database_the_route_fails_explicitly(settings: Settings) -> None:
    checks: dict[str, HealthCheck] = {"database": _ok, "redis": _ok}
    with TestClient(create_app(settings, health_checks=checks), raise_server_exceptions=False) as c:
        response = c.get(PATH)
    assert response.status_code == 503
    assert response.json()["error_code"] == "service_unavailable"


def test_the_route_is_read_only_and_needs_no_api_key(client: TestClient) -> None:
    assert client.get(PATH).status_code == 200  # no X-API-Key header
    assert client.post(PATH).status_code == 405
    assert client.delete(PATH).status_code == 405


def test_the_stored_row_is_not_modified(client: TestClient, source: FakeSource) -> None:
    before = copy.deepcopy(source.row)
    client.get(PATH)
    client.get(PATH, params={"asset": "ETH"})
    assert source.row == before


def test_no_secret_or_connection_detail_is_exposed(client: TestClient) -> None:
    text = client.get(PATH).text.lower()
    for needle in ("password", "postgresql://", "api_key", "secret", "redis://"):
        assert needle not in text
