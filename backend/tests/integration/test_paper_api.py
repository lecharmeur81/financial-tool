"""Paper trading API endpoints against real PostgreSQL (Phase 24 "API"), same
``TestClient``/fake-provider harness convention as ``test_anomaly_api.py``. Runs wherever a real
test database is reachable (none anywhere this phase has been built — see PROGRESS.md)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.market.jobs import backfill_step
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import ohlcv_dataset
from tests.integration.conftest import requires_services
from tests.integration.market_support import MarketHarness

pytestmark = [pytest.mark.integration, requires_services]

DAILY = ohlcv_dataset("usd", "1d")


def post(settings: Settings, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.post(path, json=body or {})
    return response.status_code, response.json()


def get(settings: Settings, path: str) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path)
    return response.status_code, response.json()


async def _seed_btc(market: MarketHarness) -> None:
    await backfill_step(market.ctx, MARKET_ADAPTERS["coinbase"], DAILY, "BTC", depth_days=280)


async def test_create_list_get_close_round_trip(
    market: MarketHarness, test_settings: Settings
) -> None:
    await _seed_btc(market)

    status, created = post(
        test_settings,
        "/api/v1/paper/trades",
        {"asset": "BTC", "direction": "long", "notional": "10000"},
    )
    assert status == 200
    assert created["status"] == "open"
    trade_id = created["trade_id"]

    status, listed = get(test_settings, "/api/v1/paper/trades")
    assert status == 200
    assert any(t["trade_id"] == trade_id for t in listed)

    status, fetched = get(test_settings, f"/api/v1/paper/trades/{trade_id}")
    assert status == 200
    assert fetched["trade_id"] == trade_id

    status, positions = get(test_settings, "/api/v1/paper/positions")
    assert status == 200
    assert any(p["trade"]["trade_id"] == trade_id for p in positions)

    status, closed = post(test_settings, f"/api/v1/paper/trades/{trade_id}/close")
    assert status == 200
    assert closed["status"] == "closed"
    assert closed["realized_pnl"] is not None

    status, perf = get(test_settings, "/api/v1/paper/performance")
    assert status == 200
    assert perf["closed_trades"] >= 1
    assert "disclaimer" in perf


async def test_create_trade_with_invalid_direction_is_rejected(test_settings: Settings) -> None:
    status, _ = post(
        test_settings,
        "/api/v1/paper/trades",
        {"asset": "BTC", "direction": "sideways", "notional": "1000"},
    )
    assert status == 422  # DataValidationError


async def test_create_trade_with_nonpositive_notional_is_rejected(test_settings: Settings) -> None:
    status, _ = post(
        test_settings,
        "/api/v1/paper/trades",
        {"asset": "BTC", "direction": "long", "notional": "0"},
    )
    assert status == 422  # pydantic Field(gt=0)


async def test_get_unknown_trade_is_not_found(test_settings: Settings) -> None:
    import uuid

    status, _ = get(test_settings, f"/api/v1/paper/trades/{uuid.uuid4()}")
    assert status == 404


async def test_cancel_round_trip(market: MarketHarness, test_settings: Settings) -> None:
    await _seed_btc(market)
    status, created = post(
        test_settings,
        "/api/v1/paper/trades",
        {"asset": "BTC", "direction": "short", "notional": "5000", "leverage": "2"},
    )
    assert status == 200
    trade_id = created["trade_id"]

    status, cancelled = post(test_settings, f"/api/v1/paper/trades/{trade_id}/cancel")
    assert status == 200
    assert cancelled["status"] == "cancelled"

    # Cancelling again is an invalid transition.
    status, _ = post(test_settings, f"/api/v1/paper/trades/{trade_id}/cancel")
    assert status == 422
