"""Capital Rotation Engine API against real PostgreSQL, fed through the real CoinGecko ingestion
pipeline (per-asset market cap via ``tests/market_fakes.py``'s ``CoinGeckoFake`` /market_chart, and
the genuine global TOTAL crypto market cap via ``tests/market_structure_fakes.py``'s
``CoinGeckoGlobalFake`` /global — the same two fakes Phase 12/19 already exercise).

Scope (documented, not silently narrowed — mirrors Phase 19's own test-scope note): this suite
seeds only per-asset and TOTAL market-cap history, enough to exercise the 'asset_share' /
'large_caps_share' fetch keys end to end plus the empty-database and validation paths. It does not
additionally seed institutional/whale flow data for the flow_corroboration check — that check's
own classification logic is unit-tested against synthetic readings in ``test_rotation_metrics.py``,
and this suite confirms the 'no flow data tracked for either node' fallback wording appears instead
when a rotation IS detected without seeded flow data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.market.jobs import backfill_step
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import MARKET_CAP_USD_1D
from cfi.market_structure.universe import TOTAL_MARKET_CAP_USD
from tests.integration.conftest import requires_services
from tests.integration.market_structure_support import MarketStructureHarness
from tests.integration.market_support import MarketHarness

pytestmark = [pytest.mark.integration, requires_services]


# ``resolve_query_times`` (ADR-0060) clamps any as_of later than the real wall clock down to
# "now" — so, unlike the harnesses' own fake clocks (fully decoupled from real time), this value
# must stay safely in the real past no matter when the suite actually runs.
AS_OF = datetime(2026, 9, 20, tzinfo=UTC)
TOTAL_CAP_DEPTH_DAYS = 40


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


async def _seed_asset_market_caps(market: MarketHarness, assets: tuple[str, ...]) -> None:
    """Seeds ranged per-asset market-cap history (CoinGecko's /market_chart, one call serves the
    whole requested range)."""
    market.wall.current = AS_OF
    for asset in assets:
        await backfill_step(
            market.ctx, MARKET_ADAPTERS["coingecko"], MARKET_CAP_USD_1D, asset, depth_days=60
        )


async def _seed_total_market_cap(market_structure: MarketStructureHarness) -> None:
    """TOTAL_MARKET_CAP_USD is a single-instant snapshot per ingest call (the Phase 12 gap — see
    NOT_TRACKED), so ranged history is built by advancing the fake wall clock a day at a time and
    re-ingesting, ending exactly on AS_OF."""
    market_structure.wall.current = AS_OF - timedelta(days=TOTAL_CAP_DEPTH_DAYS)
    for _ in range(TOTAL_CAP_DEPTH_DAYS + 1):
        await market_structure.load(TOTAL_MARKET_CAP_USD.dataset_id)
        market_structure.wall.advance(timedelta(days=1))


async def test_catalog_lists_the_tracked_nodes_and_excluded_pairs(
    test_settings: Settings,
) -> None:
    status, body = get(test_settings, "/api/v1/rotation/catalog")
    assert status == 200
    node_ids = {n["node_id"] for n in body["nodes"]}
    assert node_ids == {
        "btc",
        "eth",
        "sol",
        "xrp",
        "large_caps",
        "mid_caps",
        "defi",
        "ai_related",
        "meme_assets",
        "stablecoins_total",
        "stablecoin_usdt",
        "stablecoin_usdc",
    }
    assert {"btc", "eth", "sol", "xrp", "large_caps"} <= set(body["matrix_eligible_nodes"])
    assert "meme_assets" not in body["matrix_eligible_nodes"]
    excluded = {(p["from"], p["to"]) for p in body["excluded_pairs"]}
    assert ("btc", "large_caps") in excluded
    assert body["not_tracked"]


async def test_pair_is_insufficient_data_when_nothing_is_loaded(test_settings: Settings) -> None:
    status, body = get(
        test_settings,
        "/api/v1/rotation/pair",
        from_node_id="btc",
        to_node_id="eth",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert body["from_node"]["status"] == "insufficient_data"
    assert body["to_node"]["status"] == "insufficient_data"
    assert body["inferred_capital_rotation"]["status"] == "unavailable"
    assert body["inferred_capital_rotation"]["evidence_class"] is None


async def test_pair_reports_unavailable_for_an_untracked_node(test_settings: Settings) -> None:
    status, body = get(
        test_settings,
        "/api/v1/rotation/pair",
        from_node_id="btc",
        to_node_id="mid_caps",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert body["to_node"]["status"] == "unavailable"
    assert body["to_node"]["reason"]
    assert body["inferred_capital_rotation"]["status"] == "unavailable"


async def test_pair_rejects_an_unknown_node(test_settings: Settings) -> None:
    status, _ = get(
        test_settings,
        "/api/v1/rotation/pair",
        from_node_id="btc",
        to_node_id="not_a_real_node",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 404


async def test_pair_rejects_the_same_node_twice(test_settings: Settings) -> None:
    status, _ = get(
        test_settings,
        "/api/v1/rotation/pair",
        from_node_id="btc",
        to_node_id="btc",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 404


async def test_pair_rejects_a_node_and_its_own_aggregate(test_settings: Settings) -> None:
    """large_caps IS the sum of btc/eth/sol/xrp — comparing it to one of its own components would
    manufacture a 'rotation' out of arithmetic identity, never an independent observation."""
    status, _ = get(
        test_settings,
        "/api/v1/rotation/pair",
        from_node_id="large_caps",
        to_node_id="btc",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 404


async def test_pair_computes_real_shares_once_market_caps_are_seeded(
    market: MarketHarness,
    market_structure: MarketStructureHarness,
    test_settings: Settings,
) -> None:
    await _seed_asset_market_caps(market, ("BTC", "ETH"))
    await _seed_total_market_cap(market_structure)
    status, body = get(
        test_settings,
        "/api/v1/rotation/pair",
        from_node_id="btc",
        to_node_id="eth",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert body["from_node"]["status"] == "ok"
    assert body["to_node"]["status"] == "ok"
    # a market-share percentage must be a plausible fraction of the genuine global TOTAL, never
    # ~100% (which would signal the degenerate same-4-assets-as-denominator bug this phase fixed)
    assert 0 < float(body["from_node"]["last_value"]) < 100
    assert 0 < float(body["to_node"]["last_value"]) < 100
    rotation = body["inferred_capital_rotation"]
    assert rotation["status"] in ("possible_rotation", "no_rotation_signal")
    if rotation["status"] == "possible_rotation":
        assert rotation["evidence_class"] == "inferred"
        assert "consistent with" in rotation["hypothesis"]
        assert "not proof of" in rotation["hypothesis"]
        # no institutional/whale flow data was seeded in this suite, so corroboration must say so
        checks = body["flow_corroboration"]
        assert checks["supporting_evidence"] == []
        assert any("no observed flow" in line.lower() for line in checks["contradicting_evidence"])
    else:
        assert rotation["evidence_class"] is None


async def test_large_caps_share_is_never_degenerately_100_percent(
    market: MarketHarness,
    market_structure: MarketStructureHarness,
    test_settings: Settings,
) -> None:
    """Regression test for the share-denominator design flaw caught before this phase's service
    layer was written: large_caps_share must be computed against the genuine global TOTAL crypto
    market cap, never against the sum of the platform's own 4 tracked assets (which would make it
    trivially always 100%)."""
    await _seed_asset_market_caps(market, ("BTC", "ETH", "SOL", "XRP"))
    await _seed_total_market_cap(market_structure)
    status, body = get(
        test_settings,
        "/api/v1/rotation/pair",
        from_node_id="stablecoins_total",
        to_node_id="large_caps",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    large_caps = body["to_node"]
    if large_caps["status"] == "ok":
        assert float(large_caps["last_value"]) != pytest.approx(100.0)


async def test_matrix_excludes_forbidden_pairs_and_meme_assets(
    market: MarketHarness,
    market_structure: MarketStructureHarness,
    test_settings: Settings,
) -> None:
    await _seed_asset_market_caps(market, ("BTC", "ETH", "SOL", "XRP"))
    await _seed_total_market_cap(market_structure)
    status, body = get(
        test_settings,
        "/api/v1/rotation/matrix",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    pairs = body["pairs"]
    assert len(pairs) > 0
    seen_node_ids = set()
    for p in pairs:
        seen_node_ids.add(p["from_node"]["node_id"])
        seen_node_ids.add(p["to_node"]["node_id"])
        assert (p["from_node"]["node_id"], p["to_node"]["node_id"]) != ("large_caps", "btc")
        assert (p["from_node"]["node_id"], p["to_node"]["node_id"]) != ("btc", "large_caps")
    assert "meme_assets" not in seen_node_ids
    assert body["not_tracked"]
