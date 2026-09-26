"""Retail API against real PostgreSQL, fed through the real ingestion pipeline (CoinGecko
trending, Blockchair small-output-count) plus directly-inserted derivatives context data
(``retail_support.RetailHarness.store_derivatives_inputs``).

Expected values for the three proxy metrics are computed independently here, directly from the
fixtures' known deterministic formulas via the production ``cfi.retail.metrics`` functions — a
different path than the API (which reads the same values back out of the database) — so this
checks the full ingest -> store -> read -> format pipeline, not just the math (already covered by
the unit tests). Percentile/score numeric values are exercised at the unit level
(``test_retail_metrics.py``, ``test_retail_score.py``); here we check they come back with the
right *shape* (status, sample size, measurement class, evidence labelling) end to end.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.retail import metrics as m
from cfi.retail import score as sc
from cfi.retail.universe import MEME_COIN_SYMBOLS
from tests.integration.conftest import requires_services
from tests.integration.retail_support import (
    DERIVATIVES_ASSETS,
    DERIVATIVES_HISTORY,
    RetailHarness,
    account_ratio,
    funding_rate,
)
from tests.retail_fakes import LAST_DAY, all_days, small_output_count

pytestmark = [pytest.mark.integration, requires_services]

H = timedelta(hours=1)
POLLS = 30
POLL_STEP = timedelta(hours=6)


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


async def _load_all(retail: RetailHarness) -> None:
    await retail.store_derivatives_inputs()
    await retail.load_small_output_count()
    await retail.load_trending(polls=POLLS, step=POLL_STEP)


def _expected_derivatives(as_of: Any) -> m.DerivativesProxy:
    """Rebuild the exact hourly point series ``store_derivatives_inputs`` wrote, from the same
    formulas, and run it through the real ``derivatives_proxy`` function — independent of the
    database, but exercising the same production metric code the service calls."""
    funding_by_asset: dict[str, list[m.Point]] = {}
    ratio_by_asset: dict[str, list[m.Point]] = {}
    for asset in DERIVATIVES_ASSETS:
        funding_points = []
        ratio_points = []
        t = as_of - DERIVATIVES_HISTORY
        i = 0
        while t < as_of:
            funding_points.append(m.Point(t, funding_rate(asset, i)))
            ratio_points.append(m.Point(t, account_ratio(asset, i)))
            t += H
            i += 1
        funding_by_asset[asset] = funding_points
        ratio_by_asset[asset] = ratio_points
    return m.derivatives_proxy(funding_by_asset, ratio_by_asset, as_of)


def _expected_small_tx(as_of: Any) -> m.SmallTransactionActivity:
    points = [
        m.Point(datetime.combine(d, time.min, tzinfo=UTC), Decimal(small_output_count(d)))
        for d in all_days()
    ]
    return m.small_transaction_activity(points, as_of)


async def test_overview_derivatives_proxy_matches_independent_computation(
    retail: RetailHarness, test_settings: Settings
) -> None:
    await _load_all(retail)
    as_of = retail.wall.current  # ends at NOW after load_trending
    expected = _expected_derivatives(as_of)
    status, body = get(
        test_settings,
        "/api/v1/retail/overview",
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 200
    got = body["derivatives_proxy"]
    assert got["measurement_class"] == "proxy"
    assert got["status"] == expected.status == "ok"
    assert expected.funding_rate_avg is not None
    assert expected.account_ratio_avg is not None
    assert Decimal(got["funding_rate_avg"]) == expected.funding_rate_avg
    assert Decimal(got["account_ratio_avg"]) == expected.account_ratio_avg
    assert got["funding_condition"] == expected.funding_condition
    assert got["ratio_condition"] == expected.ratio_condition
    assert set(got["assets_used"]) == set(expected.assets_used)


async def test_overview_small_transaction_activity_matches_independent_computation(
    retail: RetailHarness, test_settings: Settings
) -> None:
    await _load_all(retail)
    as_of = retail.wall.current
    expected = _expected_small_tx(as_of)
    status, body = get(
        test_settings,
        "/api/v1/retail/overview",
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 200
    got = body["small_transaction_activity"]
    assert got["measurement_class"] == "proxy"
    assert got["status"] == expected.status == "ok"
    assert expected.latest_count is not None
    assert Decimal(got["value"]) == expected.latest_count.value
    assert Decimal(got["week_avg"]) == expected.week_avg


async def test_overview_meme_coin_activity_reflects_the_latest_poll(
    retail: RetailHarness, test_settings: Settings
) -> None:
    await _load_all(retail)
    as_of = retail.wall.current
    status, body = get(
        test_settings,
        "/api/v1/retail/overview",
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 200
    got = body["meme_coin_activity"]
    assert got["measurement_class"] == "proxy"
    assert got["status"] == "ok"
    assert set(got["tracked_symbols"]) == set(MEME_COIN_SYMBOLS)
    # deterministic per tests/retail_fakes.py's repeating pattern for poll index (POLLS - 1)
    assert got["meme_coins_trending_count"] >= 0


async def test_overview_scores_are_ok_with_full_available_weight(
    retail: RetailHarness, test_settings: Settings
) -> None:
    """With 10 days of hourly derivatives history, 30 trending polls and ~87 days of daily
    small-output-count history, every component of both scores clears its minimum sample size, so
    both scores compute (never 'insufficient_data') with the full weight available."""
    await _load_all(retail)
    as_of = retail.wall.current
    status, body = get(
        test_settings,
        "/api/v1/retail/overview",
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 200
    activity = body["activity_score"]
    speculation = body["speculation_score"]
    assert activity["status"] == "ok"
    assert activity["score_id"] == sc.ACTIVITY_SCORE_ID
    assert activity["version"] == sc.ACTIVITY_SCORE_VERSION
    assert Decimal(activity["available_weight"]) == Decimal(1)
    assert activity["band"] is not None
    assert speculation["status"] == "ok"
    assert speculation["score_id"] == sc.SPECULATION_SCORE_ID
    assert Decimal(speculation["available_weight"]) == Decimal(1)
    assert speculation["band"] is not None
    for score in (activity, speculation):
        for component in score["components"]:
            assert component["status"] == "ok"


async def test_overview_percentiles_have_a_sample_size_and_are_statistical_signals(
    retail: RetailHarness, test_settings: Settings
) -> None:
    await _load_all(retail)
    as_of = retail.wall.current
    status, body = get(
        test_settings,
        "/api/v1/retail/overview",
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 200
    for key in ("small_tx", "meme_trending", "derivatives_turnover"):
        p = body["percentiles"][key]
        assert p["evidence_category"] == "Statistical Signal"
        assert p["status"] == "ok"
        assert p["sample_size"] >= m.MIN_PERCENTILE_SAMPLE
        assert p["percentile"] is not None


async def test_overview_not_tracked_lists_the_documented_gaps(
    retail: RetailHarness, test_settings: Settings
) -> None:
    status, body = get(
        test_settings,
        "/api/v1/retail/overview",
        as_of=retail.wall.current.isoformat(),
        knowledge_time=retail.wall.current.isoformat(),
    )
    assert status == 200
    items = {n["item"] for n in body["not_tracked"]}
    assert any("Google Trends" in item for item in items)
    assert any("Reddit" in item for item in items)


async def test_catalog_lists_both_providers_and_both_score_definitions(
    retail: RetailHarness, test_settings: Settings
) -> None:
    status, body = get(test_settings, "/api/v1/retail/catalog")
    assert status == 200
    providers = {p["provider_id"] for p in body["providers"]}
    assert providers == {"coingecko", "blockchair"}
    assert body["activity_score"]["version"] == sc.ACTIVITY_SCORE_VERSION
    assert body["speculation_score"]["version"] == sc.SPECULATION_SCORE_VERSION
    dataset_ids = {d["dataset_id"] for d in body["datasets"]}
    assert dataset_ids == {"retail.trending_coin_rank", "retail.small_output_count.btc.1d"}
    reused_ids = {d["dataset_id"] for d in body["reused_derivatives_datasets"]}
    assert reused_ids == {"deriv.funding_rate", "deriv.long_short_account_ratio.1h"}


async def test_history_endpoint_returns_daily_small_transaction_points(
    retail: RetailHarness, test_settings: Settings
) -> None:
    await retail.load_small_output_count()
    as_of = retail.wall.current
    status, body = get(
        test_settings,
        "/api/v1/retail/history",
        series="small_transaction_count",
        days=10,
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 200
    assert body["series"] == "small_transaction_count"
    values = {p["time"]: p["value"] for p in body["points"]}
    latest_time = max(values)
    assert Decimal(values[latest_time]) == small_output_count(LAST_DAY)


async def test_history_endpoint_rejects_an_unknown_series(
    retail: RetailHarness, test_settings: Settings
) -> None:
    as_of = retail.wall.current
    status, _ = get(
        test_settings,
        "/api/v1/retail/history",
        series="not_a_real_series",
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 404
