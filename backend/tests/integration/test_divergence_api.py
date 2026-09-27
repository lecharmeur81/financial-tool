"""Capital Flow Divergence Engine API against real PostgreSQL, fed through the real Coinbase (price)
and FRED (macro) ingestion pipelines already exercised by ``test_market_structure_api.py`` and
``test_macro_ingestion.py``.

Scope (documented, not silently narrowed — see PROGRESS.md's Phase 13 known limitations): this
suite seeds price bars, TOTAL market cap and macro FRED series (the lightest harnesses already
proven in Phases 11/12), which is enough to exercise the full pipeline end to end (a fully "ok"
comparison, the partial-availability path, and the empty-database path). It does not additionally
seed institutional/whale/retail/liquidity/derivatives data — those domains' own harnesses are
already covered by their own phases' integration suites, and every divergence adapter that reads
them is unit-tested against synthetic series in ``test_divergence_metrics.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.macro.universe import FED_BALANCE_SHEET, REVERSE_REPO, TREASURY_GENERAL_ACCOUNT
from cfi.market.jobs import backfill_step
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import ASSET_SYMBOLS, ohlcv_dataset
from cfi.market_structure.universe import TOTAL_MARKET_CAP_USD
from tests.integration.conftest import requires_services
from tests.integration.macro_support import MacroHarness
from tests.integration.market_structure_support import MarketStructureHarness
from tests.integration.market_support import MarketHarness

pytestmark = [pytest.mark.integration, requires_services]

DAILY = ohlcv_dataset("usd", "1d")
AS_OF = datetime(2026, 10, 5, tzinfo=UTC)  # after every harness's own fixed "NOW"


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


async def _seed_bars(market: MarketHarness) -> None:
    for asset in ASSET_SYMBOLS:
        await backfill_step(market.ctx, MARKET_ADAPTERS["coinbase"], DAILY, asset, depth_days=280)


async def _seed_macro(macro: MacroHarness) -> None:
    for dataset in (FED_BALANCE_SHEET, TREASURY_GENERAL_ACCOUNT, REVERSE_REPO):
        await macro.load(dataset.dataset_id, history_runs=2)


async def test_catalog_lists_all_ten_comparisons_and_twelve_map_nodes(
    test_settings: Settings,
) -> None:
    status, body = get(test_settings, "/api/v1/divergence/catalog")
    assert status == 200
    assert len(body["comparisons"]) == 10
    assert {c["number"] for c in body["comparisons"]} == set(range(1, 11))
    assert len(body["capital_flow_map_nodes"]) == 12
    assert body["capital_flow_map_nodes"][0]["node_id"] == "institutions"
    assert body["capital_flow_map_nodes"][-1]["node_id"] == "retail"


async def test_pair_is_insufficient_data_when_nothing_is_loaded(test_settings: Settings) -> None:
    status, body = get(
        test_settings,
        "/api/v1/divergence/pair",
        comparison_id="open_interest_vs_price",
        asset="BTC",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert body["metric_a"]["status"] == "insufficient_data"
    assert body["metric_b"]["status"] == "insufficient_data"
    assert body["is_divergent"] is None
    assert body["observed_quadrant"] is None


async def test_capital_flow_map_reports_unavailable_nodes_when_nothing_loaded(
    test_settings: Settings,
) -> None:
    status, body = get(
        test_settings,
        "/api/v1/divergence/capital-flow-map",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert body["observed_flow"]["mid_caps"]["status"] == "unavailable"
    assert body["observed_flow"]["defi"]["status"] == "unavailable"
    assert body["observed_flow"]["ai_related"]["status"] == "unavailable"
    assert body["observed_flow"]["btc"]["status"] == "insufficient_data"
    for edge in body["inferred_rotation"]:
        assert edge["status"] == "unavailable"
        assert edge["hypothesis"] is None


async def test_price_only_pair_has_ok_price_leg_and_insufficient_institutional_leg(
    market: MarketHarness, test_settings: Settings
) -> None:
    await _seed_bars(market)
    status, body = get(
        test_settings,
        "/api/v1/divergence/pair",
        comparison_id="institutional_vs_price",
        asset="BTC",
        window_days=30,
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert body["metric_a"]["status"] == "insufficient_data"  # no ETF data ingested
    assert body["metric_b"]["status"] == "ok"  # price is loaded
    assert body["metric_b"]["direction"] in ("up", "down", "flat")


async def test_capital_flow_map_populates_btc_eth_sol_once_bars_are_loaded(
    market: MarketHarness, test_settings: Settings
) -> None:
    await _seed_bars(market)
    status, body = get(
        test_settings,
        "/api/v1/divergence/capital-flow-map",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    for node_id in ("btc", "eth", "sol", "large_caps"):
        assert body["observed_flow"][node_id]["status"] == "ok"
        assert body["observed_flow"][node_id]["direction"] in ("up", "down", "flat")
    # an edge between two "ok" nodes is always resolved (never left 'unavailable')
    btc_eth_edge = next(
        e for e in body["inferred_rotation"] if e["from"] == "btc" and e["to"] == "eth"
    )
    assert btc_eth_edge["status"] in ("possible_rotation", "no_rotation_signal")


async def test_macro_vs_market_structure_pair_is_ok_once_both_legs_are_loaded(
    market: MarketHarness,
    market_structure: MarketStructureHarness,
    macro: MacroHarness,
    test_settings: Settings,
) -> None:
    await _seed_bars(market)
    await market_structure.load(TOTAL_MARKET_CAP_USD.dataset_id)
    await _seed_macro(macro)
    status, body = get(
        test_settings,
        "/api/v1/divergence/pair",
        comparison_id="macro_vs_market_structure",
        window_days=30,
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert body["metric_a"]["status"] == "ok"
    assert body["metric_b"]["status"] == "ok"
    assert body["observed_quadrant"] is not None
    assert body["is_divergent"] in (True, False)


async def test_matrix_returns_all_ten_comparisons(
    market: MarketHarness, test_settings: Settings
) -> None:
    await _seed_bars(market)
    status, body = get(
        test_settings,
        "/api/v1/divergence/matrix",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert len(body["comparisons"]) == 10
    ids = {c["comparison_id"] for c in body["comparisons"]}
    assert ids == {
        "institutional_vs_retail",
        "institutional_vs_price",
        "whale_vs_retail",
        "whale_vs_price",
        "liquidity_vs_price",
        "open_interest_vs_price",
        "funding_vs_price",
        "stablecoin_supply_vs_price",
        "leverage_vs_price",
        "macro_vs_market_structure",
    }
