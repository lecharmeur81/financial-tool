"""SoSoValue and CoinGecko treasury adapters: requests, parsing, normalisation (no network)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.core.errors import (
    DataValidationError,
    NotYetFinalError,
    ProviderNotConfiguredError,
    ProviderPermanentError,
    SchemaMismatchError,
)
from cfi.domain.datasets import AvailabilityRule
from cfi.domain.enums import EvidenceClass, PitReliability, QualityStatus
from cfi.domain.observation import CanonicalFlow
from cfi.institutional.universe import (
    ETF_AVAILABILITY,
    ETF_FLOW_US_SPOT,
    ETF_FUND_FLOW_US_SPOT,
    TREASURY_HOLDINGS_COMPANIES,
    TREASURY_PURCHASE_BTC,
)
from cfi.providers.base import FetchWindow, NormaliseContext, RawResponse, RequestSpec
from cfi.providers.coingecko import CoinGecko
from cfi.providers.sosovalue import PURCHASE_PAGE_LIMIT, SoSoValue
from tests.institutional_fakes import fixture

NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)
WINDOW = FetchWindow(NOW - timedelta(days=31), NOW, "BTC")


def raw(spec: RequestSpec, body: object, provider: str = "sosovalue") -> RawResponse:
    return RawResponse(
        provider,
        spec.path,
        dict(spec.params),
        NOW,
        200,
        "application/json",
        json.dumps(body).encode(),
    )


def ctx(dataset: object, at: datetime = NOW) -> NormaliseContext:
    return NormaliseContext(dataset=dataset, ingested_at=at, raw_ref=7)  # type: ignore[arg-type]


def wrap(data: object) -> dict[str, object]:
    return {"code": 0, "message": "success", "data": data}


# --------------------------------------------------------------------------- documented examples


def test_summary_history_documented_example_is_read_exactly() -> None:
    """The example response printed in the SoSoValue documentation (2.1 ETF Summary History)."""
    adapter = SoSoValue()
    spec = adapter.first_request(ETF_FLOW_US_SPOT.dataset_id, WINDOW)
    assert spec.path == "/etfs/summary-history"
    assert spec.params == {"symbol": "BTC", "country_code": "US", "limit": "300"}
    body = (
        b'{"code":0,"message":"success","data":[{"date":"2024-04-12",'
        b'"total_net_inflow":-55066297.0000000000000000,'
        b'"total_value_traded":4706120449.0000000000000000,'
        b'"total_net_assets":56216535367.0000000000000000,'
        b'"cum_net_inflow":13534833596.0950000000000000}]}'
    )
    page = RawResponse("sosovalue", spec.path, dict(spec.params), NOW, 200, "json", body)
    (record,) = adapter.parse_page(spec, page)
    flow = adapter.normalise(record, ctx(ETF_FLOW_US_SPOT))
    assert isinstance(flow, CanonicalFlow)
    assert flow.flow_usd == Decimal("-55066297.0000000000000000")
    assert flow.holdings_usd == Decimal("56216535367.0000000000000000")
    assert flow.cum_flow_usd == Decimal("13534833596.0950000000000000")
    assert flow.value_traded_usd == Decimal("4706120449.0000000000000000")
    assert flow.subject_ref == "US-SPOT-ETF:BTC"
    assert flow.entity_type == "etf_group"
    assert flow.evidence_class is EvidenceClass.DIRECT
    assert flow.event_time == datetime(2024, 4, 12, tzinfo=UTC)
    # Friday 2024-04-12 → next trading day Monday 2024-04-15, 18:00 New York (EDT) = 22:00 UTC
    assert flow.available_at == datetime(2024, 4, 15, 22, tzinfo=UTC)
    assert flow.available_at_estimated is True
    assert flow.pit_reliability is PitReliability.BACKFILLED_LATEST
    assert flow.transformations == ("event_time: date 2024-04-12 -> 00:00 UTC label",)


def test_fund_history_documented_example_and_known_volume_issue() -> None:
    adapter = SoSoValue()
    spec = RequestSpec(
        "/etfs/IBIT/history",
        state={"asset": "BTC", "ticker": "IBIT", "directory": '{"IBIT": "iShares Bitcoin Trust"}'},
    )
    example = {
        "date": "2024-04-12",
        "ticker": "IBIT",
        "net_inflow": 3000000,
        "cum_inflow": 400000000,
        "net_assets": 5000000,
        "currency_share": 0.005,
        "prem_dsc": -0.0001,
        "value_traded": 4441000000,
        "volume": "4441000000",
    }
    (record,) = adapter.parse_page(spec, raw(spec, wrap([example])))
    flow = adapter.normalise(record, ctx(ETF_FUND_FLOW_US_SPOT))
    assert isinstance(flow, CanonicalFlow)
    assert flow.subject_ref == "ETF:IBIT"
    assert flow.entity_name == "iShares Bitcoin Trust"
    assert flow.entity_type == "etf_fund"
    assert (flow.flow_usd, flow.holdings_usd, flow.cum_flow_usd) == (
        Decimal(3000000),
        Decimal(5000000),
        Decimal(400000000),
    )
    assert flow.premium_discount == Decimal("-0.0001")
    # documented known issue: 'volume' repeats value_traded, so no share volume is stored
    assert flow.value_traded_usd == Decimal(4441000000)
    assert not hasattr(flow, "volume")


# --------------------------------------------------------------------------- settlement / missing


def test_current_day_without_settled_figures_is_not_final() -> None:
    adapter = SoSoValue()
    spec = adapter.first_request(ETF_FLOW_US_SPOT.dataset_id, WINDOW)
    row = {
        "date": "2026-09-08",
        "total_net_inflow": None,
        "total_value_traded": 5,
        "total_net_assets": None,
        "cum_net_inflow": None,
    }
    (record,) = adapter.parse_page(spec, raw(spec, wrap([row])))
    with pytest.raises(NotYetFinalError):
        adapter.normalise(record, ctx(ETF_FLOW_US_SPOT))


def test_older_day_without_figures_is_an_explicit_missing_row() -> None:
    adapter = SoSoValue()
    spec = adapter.first_request(ETF_FLOW_US_SPOT.dataset_id, WINDOW)
    row = {
        "date": "2026-09-01",
        "total_net_inflow": None,
        "total_value_traded": 5,
        "total_net_assets": None,
        "cum_net_inflow": None,
    }
    (record,) = adapter.parse_page(spec, raw(spec, wrap([row])))
    flow = adapter.normalise(record, ctx(ETF_FLOW_US_SPOT))
    assert flow.is_missing
    assert flow.quality_status is QualityStatus.MISSING
    assert flow.value_traded_usd is None  # a missing row carries no values at all


def test_api_level_error_code_fails_loudly() -> None:
    adapter = SoSoValue()
    spec = adapter.first_request(ETF_FLOW_US_SPOT.dataset_id, WINDOW)
    body = {"code": 400003, "message": "Invalid parameter value", "data": None}
    with pytest.raises(ProviderPermanentError, match="400003"):
        adapter.parse_page(spec, raw(spec, body))


def test_unexpected_shapes_are_schema_errors() -> None:
    adapter = SoSoValue()
    spec = adapter.first_request(ETF_FLOW_US_SPOT.dataset_id, WINDOW)
    with pytest.raises(SchemaMismatchError):
        adapter.parse_page(spec, raw(spec, {"data": []}))  # no wrapper code
    with pytest.raises(SchemaMismatchError):
        adapter.parse_page(spec, raw(spec, wrap({"date": "2026-09-01"})))  # not a list
    listing = adapter.first_request(ETF_FUND_FLOW_US_SPOT.dataset_id, WINDOW)
    with pytest.raises(SchemaMismatchError, match="ticker"):
        adapter.parse_page(listing, raw(listing, wrap([{"ticker": "../etc", "name": "x"}])))


def test_bad_dates_are_rejected_per_record() -> None:
    adapter = SoSoValue()
    spec = adapter.first_request(ETF_FLOW_US_SPOT.dataset_id, WINDOW)
    (record,) = adapter.parse_page(spec, raw(spec, wrap([{"date": "12/04/2024"}])))
    with pytest.raises(DataValidationError, match="yyyy-MM-dd"):
        adapter.normalise(record, ctx(ETF_FLOW_US_SPOT))


def test_unsupported_subjects_are_refused() -> None:
    adapter = SoSoValue()
    with pytest.raises(ProviderNotConfiguredError):
        adapter.first_request(
            ETF_FLOW_US_SPOT.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "DOGE")
        )
    with pytest.raises(ProviderNotConfiguredError):
        adapter.first_request(
            TREASURY_PURCHASE_BTC.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "ETH")
        )


# --------------------------------------------------------------------------- listing chains


def test_fund_listing_chains_into_one_history_request_per_fund() -> None:
    adapter = SoSoValue()
    listing = adapter.first_request(ETF_FUND_FLOW_US_SPOT.dataset_id, WINDOW)
    assert (listing.path, listing.params) == ("/etfs", {"symbol": "BTC", "country_code": "US"})
    page = raw(listing, fixture("sosovalue_etf_list_BTC.json"))
    assert adapter.parse_page(listing, page) == []  # listings produce no flow records
    first = adapter.next_request(listing, page, [])
    assert first is not None
    assert first.path == "/etfs/TSTF/history"
    assert first.state["ticker"] == "TSTF"
    history = raw(first, fixture("sosovalue_etf_history_TSTF.json"))
    records = adapter.parse_page(first, history)
    assert records[0].payload["entity_name"] == "Test Fund Bitcoin Trust F"
    second = adapter.next_request(first, history, records)
    assert second is not None
    assert second.path == "/etfs/TSTG/history"
    assert adapter.next_request(second, raw(second, wrap([])), []) is None


def test_history_page_for_another_ticker_is_a_schema_error() -> None:
    adapter = SoSoValue()
    spec = RequestSpec("/etfs/TSTF/history", state={"asset": "BTC", "ticker": "TSTF"})
    with pytest.raises(SchemaMismatchError, match="TSTG"):
        adapter.parse_page(spec, raw(spec, wrap([{"date": "2026-09-01", "ticker": "TSTG"}])))


def test_full_purchase_page_asks_for_older_purchases_and_stops_without_progress() -> None:
    adapter = SoSoValue()
    spec = RequestSpec(
        "/btc-treasuries/TSTA/purchase-history",
        params={"limit": str(PURCHASE_PAGE_LIMIT)},
        state={"asset": "BTC", "ticker": "TSTA", "queue": "TSTB", "kind": "company"},
    )
    day0 = date(2026, 9, 1)
    rows = [
        {
            "date": (day0 - timedelta(days=i)).isoformat(),
            "ticker": "TSTA",
            "btc_holding": 1,
            "btc_acq": 1,
            "acq_cost": 1,
            "avg_btc_cost": 1,
        }
        for i in range(PURCHASE_PAGE_LIMIT)
    ]
    page = raw(spec, wrap(rows))
    records = adapter.parse_page(spec, page)
    older = adapter.next_request(spec, page, records)
    assert older is not None
    oldest = day0 - timedelta(days=PURCHASE_PAGE_LIMIT - 1)
    assert older.path == spec.path
    assert older.params["end_date"] == (oldest - timedelta(days=1)).isoformat()
    # the provider ignores end_date and repeats the same page: no loop, move to the next company
    again = adapter.next_request(older, raw(older, wrap(rows)), records)
    assert again is not None
    assert again.path == "/btc-treasuries/TSTB/purchase-history"
    assert "cursor" not in again.state


# --------------------------------------------------------------------------- purchases


def purchase(row: dict[str, object], at: datetime = NOW) -> CanonicalFlow:
    adapter = SoSoValue()
    spec = RequestSpec(
        "/btc-treasuries/TSTC/purchase-history",
        state={"asset": "BTC", "ticker": "TSTC", "directory": '{"TSTC": "Test Treasury Co C"}'},
    )
    (record,) = adapter.parse_page(spec, raw(spec, wrap([row])))
    flow = adapter.normalise(record, ctx(TREASURY_PURCHASE_BTC, at))
    assert isinstance(flow, CanonicalFlow)
    return flow


def test_purchase_is_attributed_and_dated_conservatively() -> None:
    flow = purchase(
        {
            "date": "2026-08-20",
            "ticker": "TSTC",
            "btc_holding": 30000,
            "btc_acq": 500,
            "acq_cost": 55000000,
            "avg_btc_cost": 110000,
        }
    )
    assert flow.evidence_class is EvidenceClass.ATTRIBUTED
    assert flow.entity_type == "public_company"
    assert flow.entity_name == "Test Treasury Co C"
    assert (flow.flow_native, flow.flow_usd, flow.holdings_native) == (
        Decimal(500),
        Decimal(55000000),
        Decimal(30000),
    )
    assert flow.unit_cost_usd is None  # avg_btc_cost is not a USD price (real data, 2026-09-24)
    assert flow.available_at == datetime(2026, 8, 27, tzinfo=UTC)  # date + 7 days
    assert flow.consistency_problems() == []


def test_purchase_received_before_the_estimate_is_dated_by_receipt() -> None:
    received = datetime(2026, 9, 2, 9, tzinfo=UTC)
    flow = purchase(
        {
            "date": "2026-09-01",
            "ticker": "TSTC",
            "btc_holding": 10,
            "btc_acq": 1,
            "acq_cost": 110000,
            "avg_btc_cost": 110000,
        },
        at=received,
    )
    assert flow.available_at == received
    assert flow.available_at_estimated is True
    assert flow.pit_reliability is PitReliability.NATIVE


def test_sale_cost_is_signed_like_the_coins_and_recorded() -> None:
    flow = purchase(
        {
            "date": "2026-09-01",
            "ticker": "TSTC",
            "btc_holding": 10000,
            "btc_acq": -300,
            "acq_cost": 33000000,
            "avg_btc_cost": 110000,
        }
    )
    assert flow.flow_native == Decimal(-300)
    assert flow.flow_usd == Decimal(-33000000)
    assert any("sale" in t for t in flow.transformations)
    assert flow.consistency_problems() == []


def test_real_avg_btc_cost_shape_is_not_taken_as_a_price() -> None:
    """Shape of a real row seen on 2026-09-24: 950 BTC for 75.7 M USD, avg_btc_cost 0.09."""
    flow = purchase(
        {
            "date": "2026-09-21",
            "ticker": "TSTC",
            "btc_holding": 846000,
            "btc_acq": 950,
            "acq_cost": 75700000,
            "avg_btc_cost": 0.09,
        }
    )
    assert flow.unit_cost_usd is None
    assert "avg_btc_cost not stored" in " ".join(flow.transformations)
    assert flow.consistency_problems() == []  # 75.7 M ÷ 950 ≈ 79,684 USD per BTC: plausible


def test_implausible_implied_price_is_suspect_not_repaired() -> None:
    """Shape of a real row seen on 2026-09-24: 2 BTC for 111.84 M (probably not USD)."""
    flow = purchase(
        {
            "date": "2026-09-04",
            "ticker": "TSTC",
            "btc_holding": 1506,
            "btc_acq": 2,
            "acq_cost": 111840000,
            "avg_btc_cost": 49.3,
        }
    )
    problems = flow.consistency_problems()
    assert len(problems) == 1
    assert "implied price 55,920,000.00 USD per BTC" in problems[0]
    assert flow.flow_usd == Decimal(111840000)  # kept exactly as reported


# --------------------------------------------------------------------------- CoinGecko


def test_coingecko_treasury_totals_are_a_received_snapshot() -> None:
    adapter = CoinGecko()
    spec = adapter.first_request(TREASURY_HOLDINGS_COMPANIES.dataset_id, WINDOW)
    assert spec.path == "/companies/public_treasury/bitcoin"
    page = raw(spec, fixture("coingecko_public_treasury_bitcoin.json"), "coingecko")
    (record,) = adapter.parse(page)
    flow = adapter.normalise(record, ctx(TREASURY_HOLDINGS_COMPANIES))
    assert isinstance(flow, CanonicalFlow)
    assert flow.subject_ref == "PUBLIC-COMPANIES:BTC"
    assert (flow.holdings_native, flow.holdings_usd) == (Decimal(100000), Decimal(11000000000))
    assert flow.event_time == NOW
    assert flow.evidence_class is EvidenceClass.ATTRIBUTED
    with pytest.raises(SchemaMismatchError):
        adapter.parse(raw(spec, {"total_holdings": 1}, "coingecko"))
    with pytest.raises(ProviderNotConfiguredError):
        adapter.first_request(
            TREASURY_HOLDINGS_COMPANIES.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "XRP")
        )


# --------------------------------------------------------------------------- availability rules


def test_next_trading_day_rule_skips_holidays() -> None:
    labor_day_friday = datetime(2026, 9, 4, tzinfo=UTC)
    available, estimated = ETF_FLOW_US_SPOT.available_at(labor_day_friday, None, NOW)
    assert available == datetime(2026, 9, 8, 22, tzinfo=UTC)  # Tuesday 18:00 EDT
    assert estimated is True


def test_known_when_received_uses_receipt_time_instead_of_skipping() -> None:
    early = datetime(2026, 9, 5, 1, tzinfo=UTC)  # before the Tuesday estimate
    available, _ = ETF_FLOW_US_SPOT.available_at(datetime(2026, 9, 4, tzinfo=UTC), None, early)
    assert available == early
    assert ETF_AVAILABILITY.known_when_received
    with pytest.raises(ValueError, match="estimated availability"):
        AvailabilityRule("period_end_plus", known_when_received=True)
