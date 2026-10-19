"""``GET /api/v1/portfolio/exposure`` without a database (Phase 54 step 1): both storage
dependencies are in-memory sources, so the HTTP contract is covered where the integration services
are not configured. The route writes nothing, reads at most one stored snapshot, and calls no
provider or Claude."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cfi.advisor import AdvisorInputError, build_advisor_brief
from cfi.analyst.repository import SnapshotRow
from cfi.api.app import create_app
from cfi.api.routes import portfolio as route
from cfi.api.routes.decision import get_snapshot_source
from cfi.api.routes.portfolio import get_position_source
from cfi.core.config import Settings
from cfi.decision.identity import producer_payload_hash
from cfi.paper.service import OpenPosition
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload

PATH = "/api/v1/portfolio/exposure"


class _Snapshots:
    def __init__(self, row: SnapshotRow | None) -> None:
        self.row = row
        self.reads = 0

    async def latest_snapshot_row(self) -> SnapshotRow | None:
        self.reads += 1
        return self.row


class _Positions:
    def __init__(self, positions: list[OpenPosition]) -> None:
        self.positions = positions
        self.reads = 0

    async def open_positions(self) -> list[OpenPosition]:
        self.reads += 1
        return self.positions


def _trade(
    asset: str = "BTC",
    direction: str = "long",
    notional: str = "1000",
    leverage: str = "2",
    missing_price: bool = False,
) -> OpenPosition:
    n, lev = Decimal(notional), Decimal(leverage)
    return OpenPosition(
        trade={
            "uuid": uuid.uuid4(),
            "asset": asset,
            "direction": direction,
            "notional": n,
            "leverage": lev,
            "margin": n / lev,
        },
        current_price_observed=None if missing_price else Decimal(100),
        unrealized_pnl=None,
        data_quality_state="missing" if missing_price else "ok",
    )


def _payload(codes: list[str] | None = None) -> dict[str, Any]:
    payload = make_payload(codes or ["S2", "S1", "N", "S1", "S2"])
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


def _get(
    positions: list[OpenPosition], row: SnapshotRow | None
) -> tuple[int, dict[str, Any], _Positions, _Snapshots]:
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://u:not-a-real-password@db:5432/x"),
        redis_url=SecretStr("redis://:not-a-real-password@redis:6379/0"),
    )
    pos, snap = _Positions(positions), _Snapshots(row)
    app = create_app(settings, health_checks={})  # no engine / Redis is created
    app.dependency_overrides[get_position_source] = lambda: pos
    app.dependency_overrides[get_snapshot_source] = lambda: snap
    with TestClient(app) as client:
        response = client.get(PATH)
    return response.status_code, response.json(), pos, snap


TOP_LEVEL = {
    "contract_version",
    "source",
    "conventions",
    "summary",
    "assets",
    "positions",
    "invalid_positions",
    "data_quality",
    "unavailable",
    "not_claimed",
}


def test_an_empty_portfolio_is_200_and_needs_no_snapshot() -> None:
    status, body, pos, snap = _get([], None)
    assert status == 200
    assert set(body) == TOP_LEVEL
    assert body["summary"]["status"] == "empty"
    assert body["source"]["kind"] == "simulated_paper_trades"
    assert (pos.reads, snap.reads) == (1, 0)


def test_positions_are_summarised_and_compared_with_the_stored_brief() -> None:
    positions = [
        _trade("BTC", "long", "1000"),
        _trade("BTC", "short", "200"),
        _trade("ETH", "short", "800"),
    ]
    status, body, _, snap = _get(positions, _row(_payload()))  # strongly bullish for every asset
    assert status == 200
    assert snap.reads == 1  # one snapshot read for all assets
    assert body["summary"]["gross_notional"] == "2000"
    assert body["summary"]["net_notional"] == "0"
    by_asset = {a["asset"]: a for a in body["assets"]}
    assert by_asset["BTC"]["brief"]["status"] == "assessed"
    assert by_asset["BTC"]["brief"]["stance"] == "Strongly Bullish"
    assert by_asset["BTC"]["brief_relation"] == "same_direction"  # net long, bullish stance
    assert by_asset["ETH"]["brief_relation"] == "opposite_direction"  # net short, bullish stance
    assert by_asset["ETH"]["disagreement"] is True
    assert body["data_quality"]["assets_without_assessed_brief"] == []
    assert {n["id"] for n in body["not_claimed"]} >= {"PF-NOT-REAL-HOLDINGS", "PF-NO-TRADING"}
    assert {u["id"] for u in body["unavailable"]} >= {"PF-UNV-HOLDINGS", "PF-UNV-CORRELATION"}


def test_the_live_state_snapshot_gives_no_directional_view_not_agreement() -> None:
    status, body, _, _ = _get([_trade("BTC", "long")], _row(live_state_payload()))
    assert status == 200
    asset = body["assets"][0]
    assert asset["brief"]["stance"] == "Insufficient Evidence"
    assert asset["brief_relation"] == "no_directional_view"
    assert asset["disagreement"] is None


def test_no_stored_snapshot_is_not_assessed_not_an_error() -> None:
    status, body, _, snap = _get([_trade()], None)
    assert status == 200
    assert snap.reads == 1
    asset = body["assets"][0]
    assert asset["brief"] == {"status": "not_assessed", "reason": "No stored snapshot exists yet."}
    assert asset["brief_relation"] == "not_assessed"
    assert body["data_quality"]["has_gaps"] is True


def test_an_unusable_snapshot_is_not_assessed_but_the_exposure_is_still_served() -> None:
    payload = _payload()
    payload["snapshot_version"] = "analyst_snapshot.v0"
    status, body, _, _ = _get([_trade("BTC"), _trade("ETH", "short")], _row(payload))
    assert status == 200
    assert body["summary"]["gross_notional"] == "2000"
    for asset in body["assets"]:
        assert asset["brief"]["status"] == "not_assessed"
        assert "cannot be used for an advisor brief" in asset["brief"]["reason"]
        assert asset["disagreement"] is None


def test_a_brief_refused_for_one_asset_does_not_hide_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = build_advisor_brief

    def refuse_eth(view: dict[str, Any], investment: dict[str, Any], asset: str) -> dict[str, Any]:
        if asset == "ETH":
            raise AdvisorInputError("inconsistent for ETH")
        return real(view, investment, asset)

    monkeypatch.setattr(route, "build_advisor_brief", refuse_eth)
    status, body, _, _ = _get([_trade("BTC"), _trade("ETH")], _row(_payload()))
    assert status == 200
    by_asset = {a["asset"]: a for a in body["assets"]}
    assert by_asset["BTC"]["brief"]["status"] == "assessed"
    assert by_asset["ETH"]["brief"]["status"] == "not_assessed"
    assert "inconsistent for ETH" in by_asset["ETH"]["brief"]["reason"]


def test_a_missing_price_and_an_invalid_position_are_reported() -> None:
    bad = _trade("BTC", "long", "0")
    status, body, _, _ = _get([_trade("ETH", missing_price=True), bad], None)
    assert status == 200
    assert body["data_quality"]["positions_missing_price"] == 1
    assert len(body["invalid_positions"]) == 1
    assert body["invalid_positions"][0]["reasons"] == ["invalid_notional"]
    assert body["summary"]["gross_notional"] == "1000"


def test_without_a_database_connection_the_endpoint_is_503() -> None:
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://u:not-a-real-password@db:5432/x"),
        redis_url=SecretStr("redis://:not-a-real-password@redis:6379/0"),
    )
    app = create_app(settings, health_checks={})
    with TestClient(app) as client:
        response = client.get(PATH)
    assert response.status_code == 503


def test_the_endpoint_offers_only_get() -> None:
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://u:not-a-real-password@db:5432/x"),
        redis_url=SecretStr("redis://:not-a-real-password@redis:6379/0"),
    )
    app = create_app(settings, health_checks={})
    assert set(app.openapi()["paths"][PATH]) == {"get"}
