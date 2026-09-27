"""Whale API against real PostgreSQL + TimescaleDB, fed through the real ingestion pipeline from
the synthetic history (expected values: tests/fixtures/whales/README.md)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.providers import coinmetrics
from cfi.whales.sources import source
from cfi.whales.universe import dataset
from tests.integration.conftest import requires_services
from tests.integration.whale_support import (
    BINANCE,
    NOW,
    SMALL,
    UK_GOV,
    UNKNOWN,
    WhaleHarness,
)
from tests.whale_fakes import LAST_DAY

pytestmark = [pytest.mark.integration, requires_services]

PIT = {"as_of": NOW.isoformat(), "knowledge_time": NOW.isoformat()}
EARLIER = datetime(2026, 9, 6, 12, tzinfo=UTC)
METRIC_KEYS = {"source", "timestamp", "unit", "calculation", "freshness", "quality"}


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


def components(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["component_id"]: c for c in body["components"]}


def assert_classified(c: dict[str, Any]) -> None:
    """Every classification carries evidence, source and confidence (or says it has none)."""
    assert c["evidence"]
    assert c["rule"]
    if c["actor_class"] != "unlabelled":
        assert c["source"]
        assert c["confidence"] is not None
        assert c["evidence_class"] in ("direct", "attributed", "inferred")


async def test_score_matches_the_hand_computation(
    whales: WhaleHarness, test_settings: Settings
) -> None:
    await whales.load_everything()
    status, body = get(test_settings, "/api/v1/whales/score", asset="btc", **PIT)
    assert status == 200
    assert (body["status"], body["value"], body["band"]) == ("ok", "22.5", "accumulation")
    assert body["evidence_category"] == "metric"
    assert body["window_end"] == "2026-09-09"
    c = components(body)
    assert c["exchange_netflow_7d"]["sub_score"] == "0.2506"
    assert c["exchange_supply_30d"]["sub_score"] == "0.0833"
    assert c["large_holders_7d"]["sub_score"] == "1.0000"
    assert c["revived_1y_7d"]["sub_score"] == "-0.5000"
    for comp in c.values():
        assert set(comp["metric"]) >= METRIC_KEYS
        assert comp["metric"]["source"]["provider_id"] in ("coinmetrics", "blockchair")
        assert comp["metric"]["calculation"]
    assert c["exchange_netflow_7d"]["metric"]["evidence_class"] == "attributed"
    assert c["large_holders_7d"]["metric"]["evidence_class"] == "inferred"
    assert c["exchange_netflow_7d"]["metric"]["source"]["attribution"]["text"].startswith(
        "Source: Coin Metrics"
    )
    # 3 'flash' days in the net-flow window: estimated inputs are reported, not hidden
    assert c["exchange_netflow_7d"]["metric"]["quality"]["status"] == "ok"
    checks = {x["indicator_id"]: x["status"] for x in body["contradictions"]}
    assert checks == {
        "exchange_flows_vs_old_coins": "contradiction",
        "exchange_flows_vs_large_holders": "consistent",
        "whales_vs_etf": "insufficient_data",
        "exchange_balances_two_sources": "no_clear_direction",
    }
    detail = next(x for x in body["contradictions"] if "detail" in x)["detail"]
    assert detail["labelled_balance_then"] == "250000"
    assert detail["labelled_balance_now"] == "245000"
    assert body["miner_spending"]["value"] == "1.0000"
    assert body["miner_spending"]["numerator_btc"] == "3150"

    status, eth = get(test_settings, "/api/v1/whales/score", asset="ETH", **PIT)
    assert (eth["value"], eth["band"], eth["available_weight"]) == ("-37.2", "distribution", "0.50")
    assert eth["miner_spending"] is None


async def test_point_in_time_score_uses_only_data_and_labels_public_by_then(
    whales: WhaleHarness, test_settings: Settings
) -> None:
    await whales.load_everything()
    params = {"as_of": EARLIER.isoformat(), "knowledge_time": NOW.isoformat()}
    _, body = get(test_settings, "/api/v1/whales/score", asset="BTC", **params)
    c = components(body)
    assert c["exchange_netflow_7d"]["window"]["end"] == "2026-09-05"
    assert c["exchange_netflow_7d"]["sub_score"] == "0.1073"
    assert c["exchange_supply_30d"]["sub_score"] == "0.0357"
    assert c["large_holders_7d"]["status"] == "unavailable"
    assert c["revived_1y_7d"]["metric"]["value"] == "1.2143"
    assert (body["value"], body["band"]) == ("-1.4", "neutral")
    # the Binance label was published on 2026-09-08: before that it is only a large address
    _, holders = get(test_settings, "/api/v1/whales/holders", asset="BTC", **params)
    top = holders["holders"][0]["classification"]
    assert top["address"] == BINANCE
    assert top["actor_class"] == "unknown_large_holder"
    assert top["evidence_class"] == "inferred"
    assert holders["snapshot"].startswith("2026-09-03")


async def test_knowledge_time_hides_data_stored_later_and_revisions(
    whales: WhaleHarness, test_settings: Settings
) -> None:
    await whales.load_everything()
    before = NOW - timedelta(minutes=1)  # Coin Metrics data was stored at NOW
    _, body = get(
        test_settings,
        "/api/v1/whales/score",
        asset="BTC",
        as_of=NOW.isoformat(),
        knowledge_time=before.isoformat(),
    )
    assert body["status"] == "insufficient_data"
    assert body["reason"].startswith("Insufficient data")
    # a provider revision stored later changes the score only for later knowledge times
    whales.cm.overrides[("btc", "FlowInExNtv", LAST_DAY)] = Decimal(27_000)
    whales.wall.advance(timedelta(hours=1))
    item = source(coinmetrics.PROVIDER_ID, dataset("exchange_inflow", "BTC").dataset_id, "BTC")
    await whales.run_source(item)
    later = NOW + timedelta(hours=1)
    _, old = get(test_settings, "/api/v1/whales/score", asset="BTC", **PIT)
    _, new = get(
        test_settings,
        "/api/v1/whales/score",
        asset="BTC",
        as_of=later.isoformat(),
        knowledge_time=later.isoformat(),
    )
    assert components(old)["exchange_netflow_7d"]["sub_score"] == "0.2506"
    assert components(new)["exchange_netflow_7d"]["sub_score"] == "0.0000"  # net flow 0
    assert components(new)["exchange_netflow_7d"]["metric"]["quality"]["revised"] == 1


async def test_holders_are_classified_with_evidence_and_cohorts(
    whales: WhaleHarness, test_settings: Settings
) -> None:
    await whales.load_everything()
    status, body = get(test_settings, "/api/v1/whales/holders", asset="BTC", **PIT)
    assert status == 200
    assert body["compared_with"].startswith("2026-09-03T06:00")
    by_address = {h["classification"]["address"]: h for h in body["holders"]}
    assert len(by_address) == 13
    binance = by_address[BINANCE]
    assert binance["rank"] == 1
    assert binance["change_7d"] == "-5000"
    cls = binance["classification"]
    assert (cls["actor_class"], cls["entity_name"], cls["evidence_class"], cls["confidence"]) == (
        "exchange",
        "Binance",
        "attributed",
        "0.6",
    )
    assert cls["source"] == "Test labels"
    assert "Binance-coldwallet" in cls["evidence"]
    assert by_address[UK_GOV]["classification"]["actor_class"] == "government"
    unknown = by_address[UNKNOWN[0]]["classification"]
    assert (unknown["actor_class"], unknown["confidence"], unknown["source"]) == (
        "unknown_large_holder",
        "0.5",
        "size rule",
    )
    small = by_address[SMALL]
    assert small["classification"]["actor_class"] == "unlabelled"
    assert small["change_7d"] is None
    assert small["change_7d_note"] == "not in the top 100 seven days earlier"
    for h in body["holders"]:
        assert_classified(h["classification"])
        # no address is ever called an institution because of its size
        if h["classification"]["source"] == "size rule":
            assert h["classification"]["actor_class"] == "unknown_large_holder"
    cohorts = {c["actor_class"]: c for c in body["cohorts"]}
    assert cohorts["exchange"]["change_7d_pct"] == "-2.0000"
    assert cohorts["unknown_large_holder"]["addresses"] == 10
    assert cohorts["unknown_large_holder"]["change_7d"] == "1000"
    assert body["freshness"]["status"] == "fresh"
    assert body["label_sources"] == ["Test labels"]


async def test_transfers_are_listed_with_direction_and_classification(
    whales: WhaleHarness, test_settings: Settings
) -> None:
    await whales.load_everything()
    status, body = get(test_settings, "/api/v1/whales/transfers", asset="BTC", **PIT)
    assert status == 200
    assert body["summary"]["transfers"] == 3
    assert body["summary"]["total"] == "2600"
    by_dir = {d["direction"]: d for d in body["summary"]["by_direction"]}
    assert (by_dir["to_exchange"]["transfers"], by_dir["to_exchange"]["total"]) == (1, "1200")
    assert by_dir["other"]["transfers"] == 2
    assert "no sender" in body["summary"]["note"]
    newest = body["transfers"][0]
    assert newest["value"] == "600"
    assert newest["quality_status"] == "suspect"
    assert newest["recipient"] is None  # invalid address: never classified
    to_unknown = next(t for t in body["transfers"] if t["value"] == "800")
    # classified with the balance snapshot in effect AT THE TRANSFER'S OWN TIME (2026-09-03), not
    # the latest one (2026-09-09) — RED_TEAM_REPORT.md finding #13 / ADR-0064
    assert to_unknown["recipient"]["actor_class"] == "unknown_large_holder"
    assert "10,000.00 BTC" in to_unknown["recipient"]["evidence"]
    to_binance = next(t for t in body["transfers"] if t["value"] == "1200")
    assert to_binance["recipient"]["entity_name"] == "Binance"
    assert to_binance["sender"] is None
    status, eth = get(test_settings, "/api/v1/whales/transfers", asset="ETH", **PIT)
    assert eth["summary"]["transfers"] == 1  # 4,999.5 ETH is below the exact threshold
    [t] = eth["transfers"]
    assert t["sender"]["actor_class"] == "unlabelled"
    assert t["direction"] == "other"
    # point in time: nothing of 2026-09-08 … 09-10 was known on 09-06
    _, early = get(
        test_settings,
        "/api/v1/whales/transfers",
        asset="BTC",
        as_of=EARLIER.isoformat(),
        knowledge_time=NOW.isoformat(),
    )
    assert early["summary"]["transfers"] == 0


async def test_flows_return_daily_values_with_sources_and_quality(
    whales: WhaleHarness, test_settings: Settings
) -> None:
    await whales.load_everything()
    status, body = get(
        test_settings, "/api/v1/whales/flows", asset="BTC", start="2026-09-06", **PIT
    )
    assert status == 200
    assert [d["date"] for d in body["days"]] == [
        "2026-09-06",
        "2026-09-07",
        "2026-09-08",
        "2026-09-09",
    ]
    last = body["days"][-1]
    assert last["netflow"] == "-1000"
    assert last["values"]["exchange_inflow"]["quality_status"] == "estimated"
    assert last["values"]["revived_supply_1y"]["value"] == "1500"
    datasets = {d["metric"]: d for d in body["datasets"]}
    assert set(datasets) == {
        "exchange_inflow",
        "exchange_outflow",
        "exchange_supply",
        "supply",
        "issuance",
        "coin_days_destroyed",
        "revived_supply_1y",
        "lth_spent_155d",
        "miner_origin_spent",
    }
    assert datasets["exchange_inflow"]["freshness"]["status"] == "fresh"
    assert datasets["exchange_inflow"]["evidence_class"] == "attributed"
    assert datasets["coin_days_destroyed"]["source"]["provider_id"] == "blockchair"
    _, eth = get(test_settings, "/api/v1/whales/flows", asset="ETH", **PIT)
    assert "revived_supply_1y" not in {d["metric"] for d in eth["datasets"]}


async def test_address_entities_catalog_and_errors(
    whales: WhaleHarness, test_settings: Settings
) -> None:
    await whales.load_everything()
    status, body = get(test_settings, f"/api/v1/whales/addresses/bitcoin/{BINANCE}", **PIT)
    assert status == 200
    assert body["classification"]["actor_class"] == "exchange"
    assert body["balance"]["value"] == "245000"
    [label] = body["labels"]
    assert label["counts_now"] is True
    assert label["available_at"].startswith("2026-09-08T05:29:20")
    _, unknown = get(test_settings, f"/api/v1/whales/addresses/bitcoin/{UNKNOWN[1]}", **PIT)
    assert unknown["classification"]["actor_class"] == "unknown_large_holder"
    assert unknown["labels"] == []
    status, _ = get(test_settings, "/api/v1/whales/addresses/bitcoin/1BadAddress", **PIT)
    assert status == 404
    status, ents = get(test_settings, "/api/v1/whales/entities", **PIT)
    assert status == 200
    binance = next(e for e in ents["entities"] if e["entity_id"] == "binance")
    assert len(binance["addresses"]) == 1
    _, early = get(
        test_settings,
        "/api/v1/whales/entities",
        as_of=EARLIER.isoformat(),
        knowledge_time=NOW.isoformat(),
    )
    assert all(e["addresses"] == [] for e in early["entities"])
    status, catalog = get(test_settings, "/api/v1/whales/catalog")
    assert status == 200
    assert {c["actor_class"] for c in catalog["classes"]} >= {
        "exchange",
        "institution",
        "fund",
        "market_maker",
        "protocol",
        "unknown_large_holder",
    }
    assert catalog["score"]["score_id"] == "whale_flow_score"
    assert catalog["not_tracked"]
    for path, params in (
        ("/api/v1/whales/score", {"asset": "SOL"}),
        ("/api/v1/whales/score", {"asset": "DOGE"}),
        ("/api/v1/whales/flows", {"asset": "BTC", "start": "2026-09-06", "end": "2026-09-06"}),
    ):
        status, _ = get(test_settings, path, **params)
        assert status == 404
    status, _ = get(test_settings, "/api/v1/whales/score", asset="BTC", as_of="2026-09-06T12:00:00")
    assert status in (400, 422)  # naive time rejected, never assumed UTC


async def test_empty_database_says_insufficient_data(
    whales: WhaleHarness, test_settings: Settings
) -> None:
    _, body = get(test_settings, "/api/v1/whales/overview", **PIT)
    for asset in body["assets"]:
        assert asset["score"]["status"] == "insufficient_data"
        assert asset["freshness"]["status"] == "no_data"
    _, holders = get(test_settings, "/api/v1/whales/holders", asset="BTC", **PIT)
    assert holders["holders"] == []
    assert holders["freshness"]["status"] == "no_data"
