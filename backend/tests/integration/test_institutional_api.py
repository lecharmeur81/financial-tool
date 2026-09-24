"""Institutional API against real PostgreSQL + TimescaleDB, fed through the real ingestion pipeline
from the synthetic historical fixtures (expected values: tests/fixtures/institutional/README.md)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.institutional.universe import ETF_FLOW_US_SPOT
from tests.integration.conftest import requires_services
from tests.integration.institutional_support import NOW, InstitutionalHarness

pytestmark = [pytest.mark.integration, requires_services]

PIT = {"as_of": NOW.isoformat(), "knowledge_time": NOW.isoformat()}
METRIC_KEYS = {"source", "timestamp", "unit", "calculation", "freshness", "quality"}


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


def assert_metric(metric: dict[str, Any]) -> None:
    """Every metric displays source, timestamp, unit, calculation, freshness and data quality."""
    assert set(metric) >= METRIC_KEYS
    assert metric["source"]["provider_id"]
    assert metric["unit"]
    assert metric["calculation"]
    assert metric["freshness"]["status"] in ("fresh", "stale", "no_data")
    assert metric["quality"]["status"]
    assert metric["evidence_category"] in ("observed", "metric")


async def test_daily_flows_with_reconciliation_and_freshness(
    inst: InstitutionalHarness, test_settings: Settings
) -> None:
    await inst.run_all()
    status, body = get(
        test_settings,
        "/api/v1/institutional/etf-flows",
        asset="btc",
        interval="1d",
        start="2026-08-03",
        end="2026-09-10",
        **PIT,
    )
    assert status == 200
    assert body["evidence_category"] == "observed"
    assert body["evidence_class"] == "direct"
    assert body["source"]["provider_id"] == "sosovalue"
    assert body["source"]["attribution"]["text"] == "Data: SoSoValue"
    days = {b["start"]: b for b in body["buckets"]}
    assert len(days) == 27  # 25 reported trading days + 8 and 9 September (not due yet)
    sep4 = days["2026-09-04"]
    assert Decimal(sep4["net_flow_usd"]) == Decimal(200_000_000)
    assert sep4["status"] == "complete"
    assert sep4["reconciliation"]["reconciles"] is True
    assert Decimal(sep4["reconciliation"]["difference_usd"]) == 0
    assert days["2026-09-08"]["status"] == "not_due"
    assert body["freshness"]["status"] == "fresh"
    assert body["freshness"]["expected_latest"] == "2026-09-04"
    assert body["coverage_start"] == "2026-08-03"


async def test_weekly_and_monthly_aggregation(
    inst: InstitutionalHarness, test_settings: Settings
) -> None:
    await inst.run_all()
    _, weekly = get(
        test_settings,
        "/api/v1/institutional/etf-flows",
        asset="BTC",
        interval="1w",
        start="2026-08-03",
        end="2026-09-10",
        **PIT,
    )
    assert weekly["evidence_category"] == "metric"
    totals = [(b["start"], b["net_flow_usd"], b["status"]) for b in weekly["buckets"]]
    assert totals == [
        ("2026-08-03", "-400000000", "complete"),
        ("2026-08-10", "100000000", "complete"),
        ("2026-08-17", "100000000", "complete"),
        ("2026-08-24", "300000000", "complete"),
        ("2026-08-31", "1000000000", "complete"),
        ("2026-09-07", None, "not_due"),
    ]
    _, monthly = get(
        test_settings,
        "/api/v1/institutional/etf-flows",
        asset="BTC",
        interval="1mo",
        start="2026-07-01",
        end="2026-09-10",
        **PIT,
    )
    months = {b["start"]: b for b in monthly["buckets"]}
    assert months["2026-07-01"]["status"] == "not_loaded"
    assert (
        months["2026-07-01"]["quality"]["not_loaded"] == 22
    )  # 23 weekdays minus the 3 July holiday
    assert Decimal(months["2026-08-01"]["net_flow_usd"]) == 300 * Decimal(1_000_000)
    assert months["2026-09-01"]["status"] == "in_progress"
    assert any("most recent month" in w for w in monthly["warnings"])


async def test_score_exposes_every_component_and_matches_the_fixture(
    inst: InstitutionalHarness, test_settings: Settings
) -> None:
    await inst.run_all()
    status, body = get(test_settings, "/api/v1/institutional/score", asset="BTC", **PIT)
    assert status == 200
    assert body["status"] == "ok"
    assert body["value"] == "69.5"
    assert body["band"] == "strong net inflow"
    assert body["evidence_category"] == "metric"
    assert body["etf_due_until"] == "2026-09-04"
    comps = {c["component_id"]: c for c in body["components"]}
    assert set(comps) == {
        "etf_flow_5d",
        "etf_flow_20d",
        "etf_flow_breadth_10d",
        "treasury_net_acq_30d",
    }
    for c in comps.values():
        assert_metric(c["metric"])
        assert c["weight"]
        assert c["definition"]
    assert comps["etf_flow_5d"]["sub_score"] == "1.0000"
    assert comps["etf_flow_20d"]["metric"]["value"] == "1.5000"
    assert comps["treasury_net_acq_30d"]["metric"]["evidence_class"] == "attributed"
    assert comps["treasury_net_acq_30d"]["metric"]["value"] == "1.2000"
    assert sum(Decimal(c["contribution"]) for c in comps.values()) == Decimal("69.50")
    assert any("not" in limit and "advice" in limit for limit in body["interpretation_limits"])

    _, eth = get(test_settings, "/api/v1/institutional/score", asset="ETH", **PIT)
    assert eth["value"] == "71.9"
    eth_treasury = next(c for c in eth["components"] if c["component_id"].startswith("treasury"))
    assert eth_treasury["status"] == "unavailable"
    assert eth_treasury["metric"]["value"] is None
    assert eth_treasury["metric"]["quality"]["status"] == "missing"


async def test_score_is_point_in_time_future_rows_never_leak(
    inst: InstitutionalHarness, test_settings: Settings
) -> None:
    await inst.run_all()
    _, before = get(test_settings, "/api/v1/institutional/score", asset="BTC", **PIT)
    # Poison: a huge outflow for a day inside the window, published only after as_of, and a
    # revision stored after knowledge_time. Neither may change the result.
    series = await inst.rows(
        "SELECT series_id FROM obs.series"
        " WHERE dataset_id = :d AND subject_ref = 'US-SPOT-ETF:BTC'",
        d=ETF_FLOW_US_SPOT.dataset_id,
    )
    sid = series[0]["series_id"]
    async with inst.db.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO obs.institutional_flow
                  (series_id, event_time, available_at, available_at_estimated, ingested_at,
                   entity_type, evidence_class, flow_usd, holdings_usd, source_provider,
                   original_source, revision, pit_reliability, quality_status, transformations)
                VALUES
                  (:sid, '2026-09-03', :late, true, :early, 'etf_group', 'direct',
                   -99000000000, 100000000000, 'sosovalue', 'sosovalue', 5, 'native', 'ok', '{}'),
                  (:sid, '2026-09-02', :early, true, :late, 'etf_group', 'direct',
                   -99000000000, 100000000000, 'sosovalue', 'sosovalue', 6, 'native', 'ok', '{}')
                """
            ),
            {"sid": sid, "late": NOW + timedelta(hours=1), "early": NOW - timedelta(days=1)},
        )
    _, after = get(test_settings, "/api/v1/institutional/score", asset="BTC", **PIT)
    assert after["value"] == before["value"] == "69.5"
    # With as_of/knowledge_time later, the poisoned rows are visible — proving they were real.
    later = (NOW + timedelta(hours=2)).isoformat()
    _, visible = get(
        test_settings,
        "/api/v1/institutional/score",
        asset="BTC",
        as_of=later,
        knowledge_time=later,
    )
    assert visible["value"] != "69.5"


async def test_knowledge_time_before_ingestion_shows_insufficient_data(
    inst: InstitutionalHarness, test_settings: Settings
) -> None:
    await inst.run_all()
    earlier = (NOW - timedelta(minutes=1)).isoformat()
    _, body = get(
        test_settings,
        "/api/v1/institutional/score",
        asset="BTC",
        as_of=NOW.isoformat(),
        knowledge_time=earlier,
    )
    assert body["status"] == "insufficient_data"
    assert body["value"] is None
    assert "Insufficient data" in body["reason"]


async def test_missing_day_is_reported_not_filled(
    inst: InstitutionalHarness, test_settings: Settings
) -> None:
    summary = inst.soso.files["sosovalue_etf_summary_BTC.json"]
    summary["data"] = [r for r in summary["data"] if r["date"] != "2026-09-02"]
    await inst.run_all()
    _, score = get(test_settings, "/api/v1/institutional/score", asset="BTC", **PIT)
    assert score["value"] == "58.5"
    five = next(c for c in score["components"] if c["component_id"] == "etf_flow_5d")
    assert five["status"] == "unavailable"
    assert "2026-09-02" in five["reason"]
    _, flows = get(
        test_settings,
        "/api/v1/institutional/etf-flows",
        asset="BTC",
        interval="1w",
        start="2026-08-31",
        end="2026-09-07",
        **PIT,
    )
    (week,) = flows["buckets"]
    assert week["status"] == "partial"
    assert week["quality"]["missing_days"] == ["2026-09-02"]
    assert any("no reported flow" in w for w in flows["warnings"])


async def test_funds_treasury_overview_and_catalog(
    inst: InstitutionalHarness, test_settings: Settings
) -> None:
    await inst.run_all()
    _, funds = get(test_settings, "/api/v1/institutional/etf-funds", asset="BTC", **PIT)
    assert [f["ticker"] for f in funds["funds"]] == ["TSTF", "TSTG"]  # by net assets
    assert funds["funds"][0]["share_of_net_assets_pct"] == "60.0000"

    _, treasury = get(
        test_settings,
        "/api/v1/institutional/treasury",
        asset="BTC",
        interval="1w",
        start="2026-08-17",
        end="2026-09-10",
        **PIT,
    )
    purchases = treasury["purchases"]
    weeks = {b["start"]: b for b in purchases["buckets"]}
    assert weeks["2026-08-17"]["btc_acquired"] == "500"
    assert weeks["2026-08-31"]["btc_acquired"] == "700"  # +1,000 and -300 (sale)
    assert weeks["2026-08-31"]["events"] == 2
    assert purchases["recent"][0]["ticker"] == "TSTC"
    assert purchases["top_holders"][0]["holdings_btc"] == "60000"
    assert_metric(purchases["reported_holdings"])
    assert purchases["reported_holdings"]["value"] == "100000"
    holdings = treasury["holdings_totals"]
    assert_metric(holdings["holdings"])
    assert holdings["holdings"]["value"] == "100000"
    assert holdings["changes"][0]["note"] is not None  # no week-old snapshot stored yet

    _, eth = get(test_settings, "/api/v1/institutional/treasury", asset="ETH", **PIT)
    assert eth["purchases"] is None
    assert any("not tracked for ETH" in w for w in eth["warnings"])

    _, overview = get(test_settings, "/api/v1/institutional/overview", **PIT)
    assets = {a["asset"]: a for a in overview["assets"]}
    assert assets["BTC"]["score"]["value"] == "69.5"
    assert set(assets) == {"BTC", "ETH", "SOL", "XRP"}
    assert assets["XRP"]["score"]["value"] == "71.9"
    assert assets["SOL"]["score"]["value"] == "85.0"  # 20-day component excluded (README)
    _, sol = get(test_settings, "/api/v1/institutional/score", asset="SOL", **PIT)
    sol_20d = next(c for c in sol["components"] if c["component_id"] == "etf_flow_20d")
    assert sol_20d["status"] == "unavailable"
    assert "12 of 20" in sol_20d["reason"]
    assert sol["available_weight"] == "0.50"
    _, sol_flows = get(
        test_settings,
        "/api/v1/institutional/etf-flows",
        asset="SOL",
        interval="1w",
        start="2026-08-17",
        end="2026-09-07",
        **PIT,
    )
    assert sol_flows["coverage_start"] == "2026-08-20"
    assert [b["net_flow_usd"] for b in sol_flows["buckets"]] == ["-1000000", "3000000", "10000000"]

    _, catalog = get(test_settings, "/api/v1/institutional/catalog")
    assert sum(Decimal(c["weight"]) for c in catalog["score"]["components"]) == 1
    assert {p["provider_id"] for p in catalog["providers"]} == {"sosovalue", "coingecko"}
    assert catalog["not_tracked"]


async def test_bad_requests(inst: InstitutionalHarness, test_settings: Settings) -> None:
    status, _ = get(test_settings, "/api/v1/institutional/score", asset="DOGE")
    assert status == 404
    status, _ = get(test_settings, "/api/v1/institutional/etf-flows", asset="BTC", interval="2h")
    assert status == 404
    status, body = get(
        test_settings, "/api/v1/institutional/score", asset="BTC", as_of="2026-09-09T12:00:00"
    )
    assert status == 422
    assert "time zone" in body["detail"]


async def test_no_data_yet_is_explained(
    inst: InstitutionalHarness, test_settings: Settings
) -> None:
    _, body = get(test_settings, "/api/v1/institutional/etf-flows", asset="BTC", **PIT)
    assert body["freshness"]["status"] == "no_data"
    assert any("CFI_PROVIDER_SOSOVALUE_API_KEY" in w for w in body["warnings"])


async def test_daily_range_ends_on_the_new_york_date(
    inst: InstitutionalHarness, test_settings: Settings
) -> None:
    await inst.run_all()
    # 02:00 UTC on 10 September is still 9 September (22:00) in New York
    late = "2026-09-10T02:00:00+00:00"
    _, body = get(
        test_settings,
        "/api/v1/institutional/etf-flows",
        asset="BTC",
        interval="1d",
        as_of=late,
        knowledge_time=late,
    )
    assert body["range"]["end"] == "2026-09-10"
    assert body["buckets"][-1]["start"] == "2026-09-09"
