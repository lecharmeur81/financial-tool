"""Institutional ingestion end to end: real adapters, HTTP client, engine and PostgreSQL, with fake
provider servers serving the synthetic historical fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.institutional.universe import (
    ETF_FLOW_US_SPOT,
    ETF_FUND_FLOW_US_SPOT,
    TREASURY_HOLDINGS_COMPANIES,
    TREASURY_PURCHASE_BTC,
)
from tests.integration.conftest import requires_services
from tests.integration.institutional_support import FLOWS_SQL, NOW, InstitutionalHarness

pytestmark = [pytest.mark.integration, requires_services]

M = Decimal(1_000_000)


async def test_etf_totals_are_stored_with_provenance_and_point_in_time_dates(
    inst: InstitutionalHarness,
) -> None:
    del inst.soso.files["sosovalue_etf_summary_XRP.json"]  # the provider rejects XRP this time
    results = await inst.run("sosovalue", ETF_FLOW_US_SPOT.dataset_id)
    by_subject = {r.subject: r for r in results}
    assert set(by_subject) == {"BTC", "ETH", "SOL", "XRP"}
    btc = by_subject["BTC"]
    assert btc.status == "succeeded"
    assert (btc.pages, btc.records_received, btc.inserted, btc.skipped) == (1, 26, 25, 1)
    assert (by_subject["SOL"].status, by_subject["SOL"].inserted) == ("succeeded", 12)
    # a provider error is a visible failed run for that asset only; nothing is invented
    assert by_subject["XRP"].status == "failed"
    assert by_subject["XRP"].error_code == "provider_permanent_error"

    rows = [
        r for r in await inst.rows(FLOWS_SQL, d=ETF_FLOW_US_SPOT.dataset_id) if r["asset"] == "BTC"
    ]
    assert len(rows) == 25
    last = rows[-1]
    assert last["event_time"] == datetime(2026, 9, 4, tzinfo=UTC)
    assert last["flow_usd"] == 200 * M
    assert last["holdings_usd"] == 100_000 * M
    assert last["subject_ref"] == "US-SPOT-ETF:BTC"
    assert (last["entity_type"], last["evidence_class"]) == ("etf_group", "direct")
    # Labor Day: Friday's flow counts as public on Tuesday 18:00 New York = 22:00 UTC
    assert last["available_at"] == datetime(2026, 9, 8, 22, tzinfo=UTC)
    assert last["available_at_estimated"] is True
    assert last["pit_reliability"] == "native"  # stored 14 h after it became public
    first = rows[0]
    assert first["event_time"] == datetime(2026, 8, 3, tzinfo=UTC)
    assert first["pit_reliability"] == "backfilled_latest"  # loaded a month later
    assert first["raw_ref"] is not None
    request = inst.soso.requests[0]
    assert request.headers["x-soso-api-key"] == "test-key"
    logged = await inst.rows(
        "SELECT endpoint FROM ops.provider_request WHERE provider_id = 'sosovalue'"
    )
    assert "test-key" not in str(logged)


async def test_rerun_is_idempotent_and_a_changed_value_becomes_a_revision(
    inst: InstitutionalHarness,
) -> None:
    await inst.run("sosovalue", ETF_FLOW_US_SPOT.dataset_id)
    inst.wall.advance(timedelta(hours=2))
    again = {r.subject: r for r in await inst.run("sosovalue", ETF_FLOW_US_SPOT.dataset_id)}
    assert (again["BTC"].inserted, again["BTC"].duplicates) == (0, 25)

    row = next(
        r for r in inst.soso.data("sosovalue_etf_summary_BTC.json") if r["date"] == "2026-09-03"
    )
    row["total_net_inflow"] = 450 * 1_000_000  # the provider corrects Thursday's flow
    inst.wall.advance(timedelta(hours=2))
    third = {r.subject: r for r in await inst.run("sosovalue", ETF_FLOW_US_SPOT.dataset_id)}
    assert (third["BTC"].inserted, third["BTC"].revisions) == (1, 1)
    revised = await inst.rows(
        FLOWS_SQL.replace("ORDER BY", "AND f.event_time = '2026-09-03' ORDER BY"),
        d=ETF_FLOW_US_SPOT.dataset_id,
    )
    btc = [r for r in revised if r["asset"] == "BTC"]
    assert [(r["revision"], r["flow_usd"]) for r in btc] == [(0, 400 * M), (1, 450 * M)]
    findings = await inst.rows(
        "SELECT status FROM ops.quality_check_result WHERE check_name = 'revision'"
    )
    assert findings == [{"status": "expected"}]  # ETF flows are declared revisable


async def test_fund_listing_and_histories_run_as_one_job(inst: InstitutionalHarness) -> None:
    results = {r.subject: r for r in await inst.run("sosovalue", ETF_FUND_FLOW_US_SPOT.dataset_id)}
    btc = results["BTC"]
    assert btc.status == "succeeded"
    assert btc.pages == 3  # listing + two fund histories
    assert (btc.inserted, btc.skipped) == (50, 2)
    rows = await inst.rows(FLOWS_SQL, d=ETF_FUND_FLOW_US_SPOT.dataset_id)
    names = {r["subject_ref"]: r["entity_name"] for r in rows}
    assert names == {
        "ETF:TSTF": "Test Fund Bitcoin Trust F",
        "ETF:TSTG": "Test Fund Bitcoin Trust G",
    }
    sep4 = {r["subject_ref"]: r["flow_usd"] for r in rows if r["event_time"].day == 4}
    assert sep4 == {"ETF:TSTF": 120 * M, "ETF:TSTG": 80 * M}
    assert {r["premium_discount"] for r in rows} == {Decimal("0.0005")}
    payloads = await inst.rows("SELECT endpoint FROM raw.payload ORDER BY payload_id")
    assert [p["endpoint"] for p in payloads][:3] == [
        "/etfs",
        "/etfs/TSTF/history",
        "/etfs/TSTG/history",
    ]


async def test_treasury_purchases_are_attributed_signed_and_not_freshness_checked(
    inst: InstitutionalHarness,
) -> None:
    (result,) = await inst.run("sosovalue", TREASURY_PURCHASE_BTC.dataset_id)
    assert result.status == "succeeded"
    assert (result.pages, result.inserted) == (4, 6)
    assert result.stale is None  # sporadic events: no freshness verdict on the newest event
    rows = await inst.rows(FLOWS_SQL, d=TREASURY_PURCHASE_BTC.dataset_id)
    sale = next(r for r in rows if r["subject_ref"] == "COMPANY:TSTC" and r["flow_native"] < 0)
    assert (sale["flow_native"], sale["flow_usd"]) == (Decimal(-300), Decimal(-33_000_000))
    assert sale["evidence_class"] == "attributed"
    assert sale["available_at"] == datetime(2026, 9, 8, tzinfo=UTC)  # date + 7 days
    assert sale["pit_reliability"] == "native"
    old = next(r for r in rows if r["event_time"] == datetime(2026, 4, 1, tzinfo=UTC))
    assert old["pit_reliability"] == "backfilled_latest"
    freshness = await inst.rows(
        "SELECT count(*) AS n FROM ops.quality_check_result WHERE check_name = 'freshness'"
    )
    assert freshness == [{"n": 0}]


async def test_inconsistent_purchase_is_kept_but_flagged_suspect(
    inst: InstitutionalHarness,
) -> None:
    rows = inst.soso.data("sosovalue_purchase_history_TSTB.json")
    rows[0]["avg_btc_cost"] = 90_000  # 55 M USD / 500 BTC = 110,000, not 90,000
    (result,) = await inst.run("sosovalue", TREASURY_PURCHASE_BTC.dataset_id)
    assert result.suspect == 1
    stored = await inst.rows(
        FLOWS_SQL.replace("ORDER BY", "AND f.quality_status = 'suspect' ORDER BY"),
        d=TREASURY_PURCHASE_BTC.dataset_id,
    )
    assert len(stored) == 1
    assert stored[0]["unit_cost_usd"] == Decimal(90_000)  # never repaired
    assert "unit cost" in stored[0]["quality_note"]


async def test_coingecko_holdings_snapshot(inst: InstitutionalHarness) -> None:
    results = await inst.run("coingecko", TREASURY_HOLDINGS_COMPANIES.dataset_id)
    assert {r.subject for r in results} == {"BTC", "ETH", "SOL"}
    assert all(r.status == "succeeded" for r in results)
    rows = await inst.rows(FLOWS_SQL, d=TREASURY_HOLDINGS_COMPANIES.dataset_id)
    btc = next(r for r in rows if r["asset"] == "BTC")
    assert btc["event_time"] == NOW
    assert btc["holdings_native"] == Decimal(100_000)
    assert btc["entity_type"] == "public_company_group"


async def test_invalid_key_is_an_auth_failure_recorded_on_the_run(
    inst: InstitutionalHarness,
) -> None:
    inst.ctx.clients["sosovalue"]._environ = {"CFI_PROVIDER_SOSOVALUE_API_KEY": "wrong"}
    results = {r.subject: r for r in await inst.run("sosovalue", ETF_FLOW_US_SPOT.dataset_id)}
    assert results["BTC"].status == "failed"
    requests = await inst.rows(
        "SELECT outcome, http_status FROM ops.provider_request WHERE provider_id = 'sosovalue'"
    )
    assert {"outcome": "auth_failed", "http_status": 401} in requests
