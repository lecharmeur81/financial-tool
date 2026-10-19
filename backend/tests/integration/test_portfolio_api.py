"""``GET /api/v1/portfolio/exposure`` against real PostgreSQL (Phase 54 step 1): simulated open
paper trades stored with the platform's own repository, and a stored snapshot stored with
``insert_snapshot``, are read back through the real queries and served. Runs only on the isolated
``<configured name>_test`` database (see ``conftest.py``). Asserts the contract, the arithmetic on
the stored rows and consistency with the Advisor Brief endpoint, not any market view: the stance and
the price availability depend on the stored data and are not assumed. Skipped unless the
integration services are configured."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.analyst.repository import AnalystRepository
from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.decision.identity import producer_payload_hash
from cfi.paper.repository import PaperTradeRepository
from cfi.paper.universe import DEFAULT_COST_MODEL_VERSION
from cfi.portfolio import NOT_CLAIMED
from tests.decision_live_payload import live_state_payload
from tests.decision_snapshots import stored_form
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

PATH = "/api/v1/portfolio/exposure"
BRIEF_PATH = "/api/v1/advisor/brief"

TOP_LEVEL_FIELDS = {
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


def _get(settings: Settings, path: str = PATH, **params: str) -> tuple[int, dict[str, object]]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params=params)
    return response.status_code, response.json()


async def _store_snapshot(db: AsyncEngine) -> int:
    stored = stored_form(live_state_payload())
    now = datetime.now(UTC)
    row_id, _ = await AnalystRepository(db).insert_snapshot(
        created_at=now,
        as_of=now,
        knowledge_time=now,
        snapshot_version="analyst_snapshot.v1",
        payload=stored,
        payload_hash=producer_payload_hash(stored),
    )
    return row_id


async def _store_trade(
    db: AsyncEngine, asset: str, direction: str, notional: str, leverage: str
) -> str:
    now = datetime.now(UTC)
    n, lev = Decimal(notional), Decimal(leverage)
    _, trade_uuid = await PaperTradeRepository(db).insert_trade(
        now=now,
        asset=asset,
        direction=direction,
        entry_time=now,
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal(100),
        entry_price_source="integration test fixture",
        notional=n,
        leverage=lev,
        margin=n / lev,
        stop_loss=None,
        take_profit=None,
        cost_model_version=DEFAULT_COST_MODEL_VERSION,
        strategy_tag=None,
        notes=None,
        decision_snapshot_id=None,
        market_brief_id=None,
        relevant_alert_ids=[],
    )
    return str(trade_uuid)


async def _counts(db: AsyncEngine) -> tuple[int, int]:
    """(stored snapshots, paper trades): the two tables this endpoint reads."""
    sql = text("select (select count(*) from ai.snapshot), (select count(*) from usr.paper_trade)")
    async with db.connect() as conn:
        snapshots, trades = (await conn.execute(sql)).one()
    return int(snapshots), int(trades)


async def test_an_empty_portfolio_is_a_200_with_no_ratios(
    db: AsyncEngine, test_settings: Settings
) -> None:
    status, body = _get(test_settings)
    assert status == 200
    assert set(body) == TOP_LEVEL_FIELDS
    assert body["contract_version"] == "portfolio_exposure.v0"
    summary = body["summary"]
    assert isinstance(summary, dict)
    assert summary["status"] == "empty"
    assert summary["largest_asset_share"] is None
    assert body["not_claimed"] == [dict(n) for n in NOT_CLAIMED]


async def test_stored_paper_trades_are_summarised_from_the_database(
    db: AsyncEngine, test_settings: Settings
) -> None:
    await _store_snapshot(db)
    ids = {
        await _store_trade(db, "BTC", "long", "1000", "2"),
        await _store_trade(db, "BTC", "short", "250", "5"),
        await _store_trade(db, "ETH", "long", "750", "1"),
    }

    status, body = _get(test_settings)

    assert status == 200
    assert set(body) == TOP_LEVEL_FIELDS
    source = body["source"]
    assert isinstance(source, dict)
    assert source["kind"] == "simulated_paper_trades"
    assert source["positions_received"] == 3
    assert source["positions_valid"] == 3

    summary = body["summary"]
    assert isinstance(summary, dict)
    assert Decimal(summary["gross_notional"]) == Decimal(2000)
    assert Decimal(summary["long_notional"]) == Decimal(1750)
    assert Decimal(summary["short_notional"]) == Decimal(250)
    assert Decimal(summary["net_notional"]) == Decimal(1500)
    assert Decimal(summary["total_margin"]) == Decimal(500) + Decimal(50) + Decimal(750)
    assert summary["largest_asset"] == "BTC"
    assert Decimal(summary["largest_asset_share"]) == Decimal("0.625")

    positions = body["positions"]
    assert isinstance(positions, list)
    assert {p["trade_id"] for p in positions} == ids
    assert body["invalid_positions"] == []

    # Price availability depends on stored market data; the report must agree with itself.
    quality = body["data_quality"]
    assert isinstance(quality, dict)
    assert quality["positions_missing_price"] == sum(
        1 for p in positions if p["price_status"] == "missing"
    )


async def test_the_brief_shown_is_the_advisor_briefs_own_for_the_same_snapshot(
    db: AsyncEngine, test_settings: Settings
) -> None:
    row_id = await _store_snapshot(db)
    await _store_trade(db, "BTC", "long", "1000", "1")
    await _store_trade(db, "ETH", "short", "500", "1")

    status, body = _get(test_settings)
    assert status == 200
    assets = body["assets"]
    assert isinstance(assets, list)
    for entry in assets:
        asset = str(entry["asset"])
        b_status, brief = _get(test_settings, BRIEF_PATH, asset=asset)
        assert b_status == 200
        shown = entry["brief"]
        assert shown["status"] == "assessed"
        assert shown["snapshot_row_id"] == row_id
        assert shown["stance"] == brief["assessment"]["stance"]["final"]  # type: ignore[index]
        assert shown["confidence"] == brief["assessment"]["stance"]["confidence"]  # type: ignore[index]
        assert (
            shown["decision_state"]
            == (
                brief["assessment"]["investment_state"]["decision_state"]  # type: ignore[index]
            )
        )


async def test_positions_without_a_stored_snapshot_are_not_assessed(
    db: AsyncEngine, test_settings: Settings
) -> None:
    await _store_trade(db, "SOL", "long", "300", "3")
    status, body = _get(test_settings)
    assert status == 200
    assets = body["assets"]
    assert isinstance(assets, list)
    assert assets[0]["brief"]["status"] == "not_assessed"
    assert assets[0]["brief_relation"] == "not_assessed"
    assert assets[0]["disagreement"] is None


async def test_the_read_path_does_not_write(db: AsyncEngine, test_settings: Settings) -> None:
    await _store_snapshot(db)
    await _store_trade(db, "BTC", "long", "1000", "2")
    before = await _counts(db)
    for _ in range(3):
        status, _ = _get(test_settings)
        assert status == 200
    after = await _counts(db)
    assert before == after == (1, 1)
