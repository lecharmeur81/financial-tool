"""Decision journal API endpoints against real PostgreSQL (Phase 25 "API"), same
``TestClient``/fake-provider harness convention as ``test_paper_api.py``. Runs wherever a real
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


def patch(settings: Settings, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.patch(path, json=body or {})
    return response.status_code, response.json()


def get(settings: Settings, path: str) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path)
    return response.status_code, response.json()


def delete(settings: Settings, path: str) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.delete(path)
    return response.status_code, response.json()


async def _seed_btc(market: MarketHarness) -> None:
    await backfill_step(market.ctx, MARKET_ADAPTERS["coinbase"], DAILY, "BTC", depth_days=280)


async def test_create_list_get_outcome_round_trip(
    market: MarketHarness, test_settings: Settings
) -> None:
    await _seed_btc(market)

    status, created = post(
        test_settings,
        "/api/v1/journal/decisions",
        {
            "asset": "BTC",
            "decision_type": "long_spot",
            "thesis": "ETF inflows diverging from retail funding.",
            "invalidation_condition": "BTC closes below 55000.",
        },
    )
    assert status == 200
    assert created["status"] == "open"
    decision_id = created["decision_id"]

    status, listed = get(test_settings, "/api/v1/journal/decisions")
    assert status == 200
    assert any(d["decision_id"] == decision_id for d in listed)

    status, fetched = get(test_settings, f"/api/v1/journal/decisions/{decision_id}")
    assert status == 200
    assert fetched["decision_id"] == decision_id

    status, noted = patch(
        test_settings,
        f"/api/v1/journal/decisions/{decision_id}/notes",
        {"notes": "revisiting next week"},
    )
    assert status == 200
    assert noted["notes"] == "revisiting next week"

    status, resolved = post(
        test_settings,
        f"/api/v1/journal/decisions/{decision_id}/outcome",
        {
            "status": "resolved",
            "outcome": "as_expected",
            "thesis_supported": True,
            "thesis_contradicted": False,
            "invalidation_occurred": False,
        },
    )
    assert status == 200
    assert resolved["status"] == "resolved"
    assert resolved["thesis"] == fetched["thesis"]  # hindsight protection: thesis unchanged

    status, stats = get(test_settings, "/api/v1/journal/stats")
    assert status == 200
    assert stats["total_decisions"] >= 1
    assert "disclaimer" in stats

    status, review = get(test_settings, "/api/v1/journal/review")
    assert status == 200
    assert "disclaimer" in review


async def test_create_decision_with_empty_thesis_is_rejected(test_settings: Settings) -> None:
    status, _ = post(
        test_settings,
        "/api/v1/journal/decisions",
        {"asset": "BTC", "decision_type": "long_spot", "thesis": ""},
    )
    assert status == 422  # DataValidationError


async def test_get_unknown_decision_is_not_found(test_settings: Settings) -> None:
    import uuid

    status, _ = get(test_settings, f"/api/v1/journal/decisions/{uuid.uuid4()}")
    assert status == 404


async def test_cancel_round_trip(test_settings: Settings) -> None:
    status, created = post(
        test_settings,
        "/api/v1/journal/decisions",
        {"asset": "ETH", "decision_type": "watch", "thesis": "Just watching."},
    )
    assert status == 200
    decision_id = created["decision_id"]

    status, cancelled = post(test_settings, f"/api/v1/journal/decisions/{decision_id}/cancel")
    assert status == 200
    assert cancelled["status"] == "cancelled"

    # Cancelling again is an invalid transition.
    status, _ = post(test_settings, f"/api/v1/journal/decisions/{decision_id}/cancel")
    assert status == 422


async def test_link_and_unlink_paper_trade_round_trip(
    market: MarketHarness, test_settings: Settings
) -> None:
    await _seed_btc(market)
    status, trade = post(
        test_settings,
        "/api/v1/paper/trades",
        {"asset": "BTC", "direction": "long", "notional": "10000"},
    )
    assert status == 200
    trade_id = trade["trade_id"]

    status, decision = post(
        test_settings,
        "/api/v1/journal/decisions",
        {"asset": "BTC", "decision_type": "long_spot", "thesis": "Thesis."},
    )
    assert status == 200
    decision_id = decision["decision_id"]

    status, linked = post(
        test_settings,
        f"/api/v1/journal/decisions/{decision_id}/paper-trade",
        {"paper_trade_id": trade_id},
    )
    assert status == 200
    assert linked["paper_trade_id"] is not None

    status, unlinked = delete(test_settings, f"/api/v1/journal/decisions/{decision_id}/paper-trade")
    assert status == 200
    assert unlinked["paper_trade_id"] is None


async def test_list_decisions_rejects_an_unknown_status_filter(test_settings: Settings) -> None:
    status, _ = get(test_settings, "/api/v1/journal/decisions?status=bogus")
    assert status == 404
