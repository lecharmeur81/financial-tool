"""Coin Metrics and Blockchair adapters: requests, parsing, normalisation (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from cfi.core.errors import (
    DataValidationError,
    NotYetFinalError,
    ProviderNotConfiguredError,
    SchemaMismatchError,
)
from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import CanonicalObservation, CanonicalTransfer
from cfi.providers.base import FetchWindow, NormaliseContext, RawResponse, RequestSpec
from cfi.providers.blockchair import Blockchair
from cfi.providers.coinmetrics import CoinMetrics, parse_time
from cfi.whales.universe import dataset
from tests.whale_fakes import btc_address, btc_output, eth_address, eth_tx

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def raw(spec: RequestSpec, body: object | bytes, provider: str) -> RawResponse:
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    return RawResponse(
        provider, spec.path, dict(spec.params), NOW, 200, "application/json", content
    )


def ctx(metric: str, asset: str, at: datetime = NOW) -> NormaliseContext:
    return NormaliseContext(dataset=dataset(metric, asset), ingested_at=at, raw_ref=3)


# =========================================================================== Coin Metrics

CM = CoinMetrics()
# Real response row, fetched 2026-09-24 (BTC, 2026-09-20; Coin Metrics Community, CC BY-NC 4.0).
REAL_ROW = (
    b'{"data":[{"asset":"btc","time":"2026-09-20T00:00:00.000000000Z",'
    b'"FlowInExNtv":"12118.44914273","FlowInExNtv-status":"flash",'
    b'"FlowInExNtv-status-time":"2026-09-21T02:30:30.281487000Z"}],'
    b'"next_page_token":"0.MjAyNi0wOS0yMFQwMDowMDowMFo","next_page_url":"https://x"}'
)


def cm_spec(metric: str = "exchange_inflow", asset: str = "BTC") -> RequestSpec:
    window = FetchWindow(NOW - timedelta(days=35), datetime(2026, 9, 24, tzinfo=UTC), asset)
    return CM.first_request(dataset(metric, asset).dataset_id, window)


def test_coinmetrics_request_uses_documented_parameters() -> None:
    spec = cm_spec()
    assert spec.path == "/timeseries/asset-metrics"
    assert spec.params == {
        "assets": "btc",
        "metrics": "FlowInExNtv",
        "frequency": "1d",
        "start_time": "2026-08-20T12:00:00Z",
        "end_time": "2026-09-23T23:59:59Z",  # inclusive end, one second before the window end
        "paging_from": "start",
        "page_size": "1000",
    }
    assert cm_spec("issuance", "ETH").params["metrics"] == "IssTotNtv"


def test_coinmetrics_refuses_unconfigured_asset() -> None:
    window = FetchWindow(NOW - timedelta(days=2), NOW, "SOL")
    with pytest.raises(ProviderNotConfiguredError):
        CM.first_request(dataset("exchange_inflow", "BTC").dataset_id, window)


def test_coinmetrics_real_row_is_read_exactly() -> None:
    spec = cm_spec()
    response = raw(spec, REAL_ROW, "coinmetrics")
    [record] = CM.parse(response)
    obs = CM.normalise(record, ctx("exchange_inflow", "BTC"))
    assert isinstance(obs, CanonicalObservation)
    assert obs.value == Decimal("12118.44914273")
    assert obs.unit == "btc"
    assert obs.subject_ref == "EXCHANGES:BTC"
    assert obs.event_time == datetime(2026, 9, 20, tzinfo=UTC)
    # the status time is the publication time; "flash" = preliminary → estimated
    assert obs.available_at == datetime(2026, 9, 21, 2, 30, 30, 281487, tzinfo=UTC)
    assert obs.available_at_estimated is False
    assert obs.quality_status is QualityStatus.ESTIMATED
    assert obs.quality_note is not None
    assert "flash" in obs.quality_note
    # stored 3 days 9.5 h after publication (freshness limit 3 days): history, not live
    assert obs.pit_reliability is PitReliability.BACKFILLED_LATEST
    assert "status time truncated to microseconds" not in " ".join(obs.transformations)
    nxt = CM.next_request(spec, response, [record])
    assert nxt is not None
    assert nxt.params["next_page_token"] == "0.MjAyNi0wOS0yMFQwMDowMDowMFo"
    assert nxt.params["metrics"] == "FlowInExNtv"


def row(**kw: Any) -> dict[str, Any]:
    return {"asset": "btc", "time": "2026-09-22T00:00:00.000000000Z"} | kw


def test_coinmetrics_reviewed_missing_and_network_values() -> None:
    spec = cm_spec()
    body = {
        "data": [
            row(
                FlowInExNtv="5",
                **{
                    "FlowInExNtv-status": "reviewed",
                    "FlowInExNtv-status-time": "2026-09-23T02:00:00.123456789Z",
                },
            ),
            row(time="2026-09-21T00:00:00.000000000Z"),  # a row without the metric
        ]
    }
    reviewed, empty = (
        CM.normalise(r, ctx("exchange_inflow", "BTC")) for r in CM.parse(raw(spec, body, "cm"))
    )
    assert reviewed.quality_status is QualityStatus.OK
    assert "status time truncated to microseconds" in " ".join(reviewed.transformations)
    assert empty.value is None
    assert empty.quality_status is QualityStatus.MISSING
    # network supply has no status time: availability estimated (30 h after the day starts)
    net_spec = cm_spec("supply")
    [rec] = CM.parse(raw(net_spec, {"data": [row(SplyCur="20000000")]}, "cm"))
    obs = CM.normalise(rec, ctx("supply", "BTC"))
    assert obs.subject_ref == "NETWORK:BTC"
    assert obs.available_at == datetime(2026, 9, 23, 6, tzinfo=UTC)
    assert obs.available_at_estimated is True


def test_coinmetrics_unfinished_day_is_skipped_and_bad_rows_rejected() -> None:
    spec = cm_spec()
    [today] = CM.parse(
        raw(spec, {"data": [row(time="2026-09-24T00:00:00Z", FlowInExNtv="1")]}, "cm")
    )
    with pytest.raises(NotYetFinalError):
        CM.normalise(today, ctx("exchange_inflow", "BTC"))
    [noon] = CM.parse(
        raw(spec, {"data": [row(time="2026-09-20T12:00:00Z", FlowInExNtv="1")]}, "cm")
    )
    with pytest.raises(DataValidationError, match="00:00"):
        CM.normalise(noon, ctx("exchange_inflow", "BTC"))
    [odd] = CM.parse(
        raw(spec, {"data": [row(FlowInExNtv="1", **{"FlowInExNtv-status": "guess"})]}, "cm")
    )
    with pytest.raises(DataValidationError, match="status"):
        CM.normalise(odd, ctx("exchange_inflow", "BTC"))
    [nan] = CM.parse(raw(spec, {"data": [row(FlowInExNtv="abc")]}, "cm"))
    with pytest.raises(DataValidationError):
        CM.normalise(nan, ctx("exchange_inflow", "BTC"))


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"type": "bad_parameter", "message": "x"}},
        {"data": {"not": "a list"}},
        {"data": [{"asset": "btc"}]},
        {"data": [{"asset": "eth", "time": "2026-09-22T00:00:00Z"}]},
        [],
    ],
)
def test_coinmetrics_schema_changes_are_detected(body: object) -> None:
    with pytest.raises(SchemaMismatchError):
        CM.parse(raw(cm_spec(), body, "coinmetrics"))


def test_coinmetrics_time_parser() -> None:
    assert parse_time("2026-09-20T00:00:00Z", "t") == (datetime(2026, 9, 20, tzinfo=UTC), False)
    assert parse_time("2026-09-20T00:00:00.5Z", "t")[0].microsecond == 500_000
    with pytest.raises(DataValidationError):
        parse_time("2026-09-20 00:00:00", "t")


# =========================================================================== Blockchair

BC = Blockchair()
END = datetime(2026, 9, 24, tzinfo=UTC)


def bc_spec(metric: str, asset: str = "BTC", start: datetime | None = None) -> RequestSpec:
    window = FetchWindow(start or END - timedelta(days=10), END, asset)
    return BC.first_request(dataset(metric, asset).dataset_id, window)


def bc_obs(record: Any, metric: str, asset: str = "BTC") -> CanonicalObservation:
    out = BC.normalise(record, ctx(metric, asset))
    assert isinstance(out, CanonicalObservation)
    return out


def bc_transfer(record: Any, asset: str = "BTC") -> CanonicalTransfer:
    out = BC.normalise(record, ctx("large_transfer", asset))
    assert isinstance(out, CanonicalTransfer)
    return out


def context(rows: int, total: int, **kw: Any) -> dict[str, Any]:
    return {"code": 200, "rows": rows, "total_rows": total, "limit": 100, "offset": 0} | kw


def test_blockchair_requests_follow_the_documented_query_language() -> None:
    assert bc_spec("address_balance").path == "/bitcoin/addresses"
    assert bc_spec("address_balance").params == {"s": "balance(desc)", "limit": "100"}
    assert bc_spec("address_balance", "ETH").params["q"] == "is_contract(false)"
    btc = bc_spec("large_transfer", start=END - timedelta(hours=6))
    assert btc.path == "/bitcoin/outputs"
    assert btc.params == {
        "q": "value(50000000000..),time(2026-09-23 18:00:00..2026-09-23 23:59:59)",
        "s": "time(asc)",
        "limit": "100",
        "offset": "0",
    }
    eth = bc_spec("large_transfer", "ETH", start=END - timedelta(hours=6))
    assert eth.path == "/ethereum/transactions"
    assert eth.params["q"] == (
        "value(5000000000000000000000..),time(2026-09-23 18:00:00..2026-09-23 23:59:59),"
        "failed(false)"
    )
    assert bc_spec("coin_days_destroyed").params == {
        "a": "date,sum(cdd_total)",
        "q": "time(2026-09-14..2026-09-23)",
    }
    assert bc_spec("revived_supply_1y").params == {
        "a": "spending_date,sum(value)",
        "q": "spending_time(2026-09-14..2026-09-23),lifespan(31536000..)",
    }
    assert bc_spec("lth_spent_155d").params["q"].endswith("lifespan(13392000..)")
    assert bc_spec("miner_origin_spent").params["q"].endswith("is_from_coinbase(true)")


def test_blockchair_refuses_unconfigured_combinations() -> None:
    window = FetchWindow(END - timedelta(days=1), END, "ETH")
    with pytest.raises(ProviderNotConfiguredError):
        BC.first_request(dataset("coin_days_destroyed", "BTC").dataset_id, window)
    with pytest.raises(ProviderNotConfiguredError):
        BC.first_request(
            "whale.exchange_inflow.btc.1d", FetchWindow(END - timedelta(1), END, "BTC")
        )


def test_documented_rich_list_example_is_read() -> None:
    """First row of the documented example (`GET /bitcoin/addresses`)."""
    spec = bc_spec("address_balance")
    body = {
        "data": [{"address": "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo", "balance": 16625913046297}],
        "context": context(1, 27908261),
    }
    [record] = BC.parse_page(spec, raw(spec, body, "blockchair"))
    obs = bc_obs(record, "address_balance")
    assert isinstance(obs, CanonicalObservation)
    assert obs.value == Decimal("166259.13046297")
    assert obs.subject_ref == "bitcoin:34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo"
    assert obs.event_time == NOW  # the list has no timestamp: dated by receipt
    assert obs.available_at_estimated is True
    assert "rank 1 of 100 by balance at the snapshot" in obs.transformations


def test_ethereum_rich_list_balance_in_wei_and_invalid_address_rejected() -> None:
    spec = bc_spec("address_balance", "ETH")
    addr = eth_address(7).upper().replace("0X", "0x")
    body = {
        "data": [
            {"address": addr, "balance": "2296896558056344842665984", "is_contract": False},
            {"address": "0x123", "balance": "1", "is_contract": False},
        ],
        "context": context(2, 2),
    }
    good, bad = BC.parse_page(spec, raw(spec, body, "blockchair"))
    obs = bc_obs(good, "address_balance", "ETH")
    assert obs.value == Decimal("2296896.558056344842665984")
    assert obs.subject_ref == f"ethereum:{addr.lower()}"
    assert "address: canonical form (lower case)" in obs.transformations
    with pytest.raises(DataValidationError, match="0x123"):
        BC.normalise(bad, ctx("address_balance", "ETH"))


def test_bitcoin_output_becomes_a_transfer_without_sender() -> None:
    spec = bc_spec("large_transfer", start=END - timedelta(days=1))
    when = datetime(2026, 9, 23, 10, tzinfo=UTC)
    recipient = btc_address(4)
    body = {
        "data": [btc_output(1, 2, when, Decimal(750), recipient, Decimal("8e7"))],
        "context": context(1, 1),
    }
    [record] = BC.parse_page(spec, raw(spec, body, "blockchair"))
    t = bc_transfer(record)
    assert isinstance(t, CanonicalTransfer)
    assert (t.chain, t.output_index, t.sender, t.recipient) == ("bitcoin", 2, None, recipient)
    assert t.value_native == Decimal(750)
    assert t.value_usd == Decimal("80000000.0")
    assert t.subject_ref == f"bitcoin:{t.tx_hash}:2"
    assert t.event_time == when
    assert t.available_at == when + timedelta(minutes=10)
    assert t.consistency_problems() == []


def test_ethereum_transaction_becomes_a_transfer_with_both_sides() -> None:
    spec = bc_spec("large_transfer", "ETH", start=END - timedelta(days=1))
    when = datetime(2026, 9, 23, 7, tzinfo=UTC)
    body = {
        "data": [eth_tx(1, when, Decimal(6_000), eth_address(1), eth_address(2))],
        "context": context(1, 1),
    }
    [record] = BC.parse_page(spec, raw(spec, body, "blockchair"))
    t = bc_transfer(record, "ETH")
    assert (t.sender, t.recipient, t.output_index) == (eth_address(1), eth_address(2), None)
    assert t.value_native == Decimal(6_000)
    assert "value_native: wei / 10^18 -> ETH" in t.transformations


def test_invalid_recipient_is_kept_and_flagged_not_corrected() -> None:
    spec = bc_spec("large_transfer", start=END - timedelta(days=1))
    body = {
        "data": [btc_output(1, 0, datetime(2026, 9, 23, tzinfo=UTC), Decimal(600), "d-deadbeef")],
        "context": context(1, 1),
    }
    [record] = BC.parse_page(spec, raw(spec, body, "blockchair"))
    t = bc_transfer(record)
    assert t.recipient == "d-deadbeef"
    assert t.consistency_problems() == ["recipient 'd-deadbeef' is not a valid bitcoin address"]


def test_transfer_pagination_uses_offset_until_all_rows_are_read() -> None:
    spec = bc_spec("large_transfer", start=END - timedelta(days=1))
    full = raw(spec, {"data": [], "context": context(100, 250)}, "blockchair")
    page2 = BC.next_request(spec, full, [])
    assert page2 is not None
    assert page2.params["offset"] == "100"
    assert page2.params["q"] == spec.params["q"]
    last = raw(page2, {"data": [], "context": context(50, 250, offset=200)}, "blockchair")
    page3 = BC.next_request(page2, raw(page2, {"data": [], "context": context(100, 250)}, "b"), [])
    assert page3 is not None
    assert page3.params["offset"] == "200"
    assert BC.next_request(page3, last, []) is None
    # aggregations and rich lists are single requests
    agg = bc_spec("revived_supply_1y")
    assert BC.next_request(agg, raw(agg, {"data": [], "context": context(0, 0)}, "b"), []) is None


def test_daily_aggregation_rows_are_complete_days_in_btc() -> None:
    spec = bc_spec("revived_supply_1y")
    body = {
        "data": [
            {"spending_date": "2026-09-22", "sum(value)": 150_000_000_000},
            {"spending_date": "2026-09-24", "sum(value)": 1},  # today: not over yet
        ],
        "context": context(2, 2),
    }
    done, today = BC.parse_page(spec, raw(spec, body, "blockchair"))
    obs = bc_obs(done, "revived_supply_1y")
    assert obs.value == Decimal(1_500)
    assert obs.event_time == datetime(2026, 9, 22, tzinfo=UTC)
    assert obs.available_at == datetime(2026, 9, 23, 2, tzinfo=UTC)  # day close + 2 h
    assert "value: satoshi / 100,000,000 -> BTC" in obs.transformations
    with pytest.raises(NotYetFinalError):
        BC.normalise(today, ctx("revived_supply_1y", "BTC"))
    cdd = bc_spec("coin_days_destroyed")
    [c] = BC.parse_page(
        cdd,
        raw(
            cdd,
            b'{"data":[{"date":"2026-09-22","sum(cdd_total)":5000000.5}],"context":{"code":200}}',
            "b",
        ),
    )
    assert bc_obs(c, "coin_days_destroyed").value == Decimal("5000000.5")


@pytest.mark.parametrize(
    "body",
    [
        {"data": []},  # no context
        {"data": [], "context": {"code": 402}},
        {"data": [{"address": "x"}], "context": {"code": 200}},  # balance missing
        {"data": "nope", "context": {"code": 200}},
        [],
    ],
)
def test_blockchair_schema_changes_and_errors_are_detected(body: object) -> None:
    spec = bc_spec("address_balance")
    with pytest.raises(SchemaMismatchError):
        BC.parse_page(spec, raw(spec, body, "blockchair"))


def test_blockchair_null_data_is_an_empty_page() -> None:
    spec = bc_spec("address_balance")
    assert BC.parse_page(spec, raw(spec, {"data": None, "context": {"code": 200}}, "b")) == []


def test_malformed_transfer_fields_are_rejected() -> None:
    spec = bc_spec("large_transfer", start=END - timedelta(days=1))
    base = btc_output(1, 0, datetime(2026, 9, 23, tzinfo=UTC), Decimal(600), btc_address(1))
    for change in ({"index": -1}, {"transaction_hash": "xyz"}, {"time": "2026-09-23"}):
        [record] = BC.parse_page(
            spec, raw(spec, {"data": [base | change], "context": context(1, 1)}, "b")
        )
        with pytest.raises(DataValidationError):
            BC.normalise(record, ctx("large_transfer", "BTC"))
