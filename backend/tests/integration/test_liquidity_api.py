"""Liquidity API against real PostgreSQL, fed through the real ingestion pipeline from the
synthetic DefiLlama history (``tests/liquidity_fakes.py``).

Expected values are computed independently here, directly from the fixture's known supply
formulas via the production metrics/score functions — a different path than the API (which reads
the same values back out of the database) — so this checks the full ingest → store → read →
format pipeline, not just the math (already covered by the unit tests).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.liquidity import metrics as m
from cfi.liquidity import score as sc
from cfi.liquidity.service import num, pct
from tests.integration.conftest import requires_services
from tests.integration.liquidity_support import LiquidityHarness
from tests.liquidity_fakes import (
    NOW,
    all_days,
    total_supply,
    usdc_supply,
    usdt_supply,
)

pytestmark = [pytest.mark.integration, requires_services]

PIT = {"as_of": NOW.isoformat(), "knowledge_time": NOW.isoformat()}


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


def _points(supply: Any) -> list[m.Point]:
    return [m.Point(datetime.combine(d, time.min, tzinfo=UTC), supply(d)) for d in all_days()]


def _expected() -> sc.ScoreResult:
    usdt_points, usdc_points, total_points = (
        _points(usdt_supply),
        _points(usdc_supply),
        _points(total_supply),
    )
    return sc.compute_score(
        as_of=NOW,
        calculated_at=NOW,
        usdt_growth=m.supply_growth("USDT", usdt_points, NOW),
        usdc_growth=m.supply_growth("USDC", usdc_points, NOW),
        total_growth=m.supply_growth("TOTAL", total_points, NOW),
        total_acceleration=m.growth_acceleration(total_points, NOW),
    )


async def test_overview_score_matches_the_independent_hand_computation(
    liquidity: LiquidityHarness, test_settings: Settings
) -> None:
    await liquidity.load_everything()
    expected = _expected()
    status, body = get(test_settings, "/api/v1/liquidity/overview", **PIT)
    assert status == 200
    score = body["score"]
    assert score["status"] == expected.status == "ok"
    assert score["score"] == num(expected.score)
    assert score["band"] == expected.band
    assert score["version"] == "liquidity_score_v1"
    assert score["semantic_note"] == sc.SEMANTIC_NOTE
    for exp_c in expected.components:
        got = next(
            c for c in score["components"] if c["component_id"] == exp_c.definition.component_id
        )
        assert got["status"] == exp_c.status == "ok"
        assert got["value"] == num(exp_c.value)
        assert got["sub_score"] == num(exp_c.sub_score)
        assert got["contribution"] == num(exp_c.contribution)


async def test_overview_supply_growth_matches_per_subject(
    liquidity: LiquidityHarness, test_settings: Settings
) -> None:
    await liquidity.load_everything()
    usdt_points, usdc_points, total_points = (
        _points(usdt_supply),
        _points(usdc_supply),
        _points(total_supply),
    )
    expected = {
        "USDT": m.supply_growth("USDT", usdt_points, NOW),
        "USDC": m.supply_growth("USDC", usdc_points, NOW),
        "TOTAL": m.supply_growth("TOTAL", total_points, NOW),
    }
    status, body = get(test_settings, "/api/v1/liquidity/overview", **PIT)
    assert status == 200
    for subject, g in expected.items():
        got = body["supply"][subject]
        assert got["status"] == g.status == "ok"
        assert got["change_24h_pct"] == pct(g.change_24h)
        assert got["change_7d_pct"] == pct(g.change_7d)
        assert got["change_30d_pct"] == pct(g.change_30d)
        assert got["condition"] == g.condition
    # the fixture's linear growth crosses the 30-day threshold for USDT and TOTAL but not the
    # 7-day or 24-hour ones, and USDC's slower growth never crosses any threshold
    assert expected["USDT"].condition == "growth"
    assert expected["USDC"].condition == "stable"
    assert expected["TOTAL"].condition == "growth"


async def test_overview_market_share_matches(
    liquidity: LiquidityHarness, test_settings: Settings
) -> None:
    await liquidity.load_everything()
    usdt_points, usdc_points, total_points = (
        _points(usdt_supply),
        _points(usdc_supply),
        _points(total_supply),
    )
    expected_usdt = m.market_share("USDT", usdt_points, total_points, NOW)
    expected_usdc = m.market_share("USDC", usdc_points, total_points, NOW)
    status, body = get(test_settings, "/api/v1/liquidity/overview", **PIT)
    assert status == 200
    assert body["market_share"]["USDT"]["share_pct"] == pct(expected_usdt.share, "0.01")
    assert body["market_share"]["USDC"]["share_pct"] == pct(expected_usdc.share, "0.01")


async def test_overview_growth_acceleration_matches(
    liquidity: LiquidityHarness, test_settings: Settings
) -> None:
    await liquidity.load_everything()
    total_points = _points(total_supply)
    expected = m.growth_acceleration(total_points, NOW)
    status, body = get(test_settings, "/api/v1/liquidity/overview", **PIT)
    assert status == 200
    got = body["growth_acceleration"]
    assert got["status"] == expected.status == "ok"
    assert got["change_pct_points"] == pct(expected.change)
    assert got["condition"] == expected.condition


async def test_overview_exchange_liquidity_change_is_always_unavailable(
    liquidity: LiquidityHarness, test_settings: Settings
) -> None:
    await liquidity.load_everything()
    status, body = get(test_settings, "/api/v1/liquidity/overview", **PIT)
    assert status == 200
    assert body["exchange_liquidity_change"]["status"] == "unavailable"
    assert body["exchange_liquidity_change"]["reason"]
    # never silently omitted, and never folded into the score as a component
    ids = {c["component_id"] for c in body["score"]["components"]}
    assert "exchange_liquidity_change" not in ids


async def test_overview_not_tracked_lists_the_documented_gaps(
    liquidity: LiquidityHarness, test_settings: Settings
) -> None:
    await liquidity.load_everything()
    status, body = get(test_settings, "/api/v1/liquidity/overview", **PIT)
    assert status == 200
    items = {n["item"] for n in body["not_tracked"]}
    assert "Exchange stablecoin balances" in items
    assert "Stablecoin exchange flows" in items


async def test_history_endpoint_returns_daily_points_for_one_subject(
    liquidity: LiquidityHarness, test_settings: Settings
) -> None:
    await liquidity.load_everything()
    status, body = get(test_settings, "/api/v1/liquidity/history", subject="TOTAL", days=10, **PIT)
    assert status == 200
    assert body["subject"] == "TOTAL"
    assert len(body["points"]) >= 9  # ~10 days of daily data, allowing for the boundary
    values = {p["time"]: p["value"] for p in body["points"]}
    latest_day = max(values)
    assert values[latest_day] == num(total_supply(NOW.date() - timedelta(days=1)))


async def test_catalog_lists_the_defillama_provider_and_score_definition(
    liquidity: LiquidityHarness, test_settings: Settings
) -> None:
    status, body = get(test_settings, "/api/v1/liquidity/catalog")
    assert status == 200
    providers = {p["provider_id"] for p in body["providers"]}
    assert providers == {"defillama"}
    assert body["score"]["version"] == "liquidity_score_v1"
    assert len(body["score"]["components"]) == 4
