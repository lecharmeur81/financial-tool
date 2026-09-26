"""Binance futures, OKX derivatives and Deribit adapters: requests, pagination, parsing and
normalisation (no network).

OKX and Deribit are tested against real responses captured on 2026-09-25/26
(``tests/fixtures/derivatives``); Binance against its documented response shape (no live
response could be captured from the development environment — README there).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from cfi.core.errors import (
    NotYetFinalError,
    ProviderNotConfiguredError,
    ProviderPermanentError,
    SchemaMismatchError,
)
from cfi.derivatives.records import ms
from cfi.derivatives.universe import dataset
from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import CanonicalObservation, CanonicalQuote
from cfi.providers.base import (
    FetchWindow,
    NormaliseContext,
    ProviderAdapter,
    RawResponse,
    RequestSpec,
)
from cfi.providers.binance_futures import BinanceFutures
from cfi.providers.deribit import Deribit, expiry_of
from cfi.providers.okx_derivatives import OkxDerivatives

FIXTURES = Path(__file__).parent.parent / "fixtures" / "derivatives"
UTC0 = datetime(1970, 1, 1, tzinfo=UTC)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def raw(spec: RequestSpec, body: object | bytes, provider: str, at: datetime) -> RawResponse:
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    return RawResponse(provider, spec.path, dict(spec.params), at, 200, "application/json", content)


def ctx(metric: str, asset: str, at: datetime) -> NormaliseContext:
    return NormaliseContext(dataset=dataset(metric, asset), ingested_at=at, raw_ref=7)


def records(
    adapter: ProviderAdapter, spec: RequestSpec, response: RawResponse, metric: str, asset: str
) -> list[Any]:
    parsed = adapter.parse_page(spec, response)
    return [adapter.normalise(r, ctx(metric, asset, response.received_at)) for r in parsed]


def t(ms_value: int) -> datetime:
    return UTC0 + timedelta(milliseconds=ms_value)


# =========================================================================== OKX

OKX = OkxDerivatives()


def okx_spec(metric: str, start: datetime, end: datetime, asset: str = "BTC") -> RequestSpec:
    return OKX.first_request(dataset(metric, asset).dataset_id, FetchWindow(start, end, asset))


def test_okx_open_interest_real_response_is_read_in_coins() -> None:
    end = datetime(2026, 9, 23, 3, tzinfo=UTC)
    spec = okx_spec("open_interest", end - timedelta(hours=6), end)
    assert spec.path == "/api/v5/rubik/stat/contracts/open-interest-history"
    assert spec.params == {
        "instId": "BTC-USDT-SWAP",
        "period": "1H",
        "limit": "100",
        "end": "1790132400000",  # exclusive: records earlier than the window end
    }
    response = raw(spec, fixture("okx_open_interest_BTC.json"), "okx_derivatives", end)
    out = records(OKX, spec, response, "open_interest", "BTC")
    assert len(out) == 6
    first = out[0]
    assert isinstance(first, CanonicalObservation)
    assert first.event_time == datetime(2026, 9, 23, 2, tzinfo=UTC)
    assert first.value == Decimal("30205.5580000001167")  # oiCcy (coins), exactly as sent
    assert (first.subject_ref, first.venue, first.unit) == ("PERP:BTC-USDT", "okx", "btc")
    # snapshot estimated knowable 5 minutes after the hour
    assert first.available_at == datetime(2026, 9, 23, 2, 5, tzinfo=UTC)
    assert first.available_at_estimated is True
    assert first.pit_reliability is PitReliability.NATIVE
    assert OKX.next_request(spec, response, []) is None  # fewer rows than the page limit


def test_okx_open_interest_pages_back_with_end() -> None:
    end = datetime(2026, 9, 23, 3, tzinfo=UTC)
    spec = okx_spec("open_interest", end - timedelta(days=10), end)
    rows = [[ms(end - timedelta(hours=i + 1)), "1", "2", "3"] for i in range(100)]
    response = raw(spec, {"code": "0", "msg": "", "data": rows}, "okx_derivatives", end)
    nxt = OKX.next_request(spec, response, [])
    assert nxt is not None
    assert nxt.params["end"] == ms(end - timedelta(hours=100))
    # a page reaching the window start ends the load
    short = okx_spec("open_interest", end - timedelta(hours=50), end)
    assert OKX.next_request(short, raw(short, {"code": "0", "data": rows}, "x", end), []) is None


def test_okx_funding_real_response() -> None:
    end = datetime(2026, 9, 26, 8, tzinfo=UTC)
    spec = okx_spec("funding_rate", end - timedelta(days=3), end)
    assert spec.params == {"instId": "BTC-USDT-SWAP", "limit": "100", "after": "1790409600000"}
    response = raw(spec, fixture("okx_funding_BTC.json"), "okx_derivatives", end)
    out = records(OKX, spec, response, "funding_rate", "BTC")
    assert [o.event_time for o in out][:2] == [
        datetime(2026, 9, 26, 0, tzinfo=UTC),
        datetime(2026, 9, 25, 16, tzinfo=UTC),
    ]
    assert out[0].value == Decimal("0.0000170028374203")
    assert out[3].value == Decimal("-0.0000037995722708")
    assert {o.dataset_id for o in out} == {"deriv.funding_rate"}
    assert out[0].available_at == datetime(2026, 9, 26, 0, 1, tzinfo=UTC)


def test_okx_account_ratio_real_response_counts_contract_holders() -> None:
    start, end = datetime(2026, 9, 25, 10, tzinfo=UTC), datetime(2026, 9, 25, 14, tzinfo=UTC)
    spec = okx_spec("long_short_account_ratio", start, end)
    assert spec.params == {
        "ccy": "BTC",
        "period": "1H",
        "begin": "1790330400000",
        "end": "1790344799999",  # both ends inclusive
    }
    response = raw(spec, fixture("okx_long_short_BTC.json"), "okx_derivatives", end)
    out = records(OKX, spec, response, "long_short_account_ratio", "BTC")
    assert [(o.event_time.hour, o.value) for o in out] == [
        (13, Decimal("1.28")),
        (12, Decimal("1.27")),
        (11, Decimal("1.23")),
        (10, Decimal("1.21")),
    ]
    assert out[0].subject_ref == "CONTRACTS:BTC"
    nxt = OKX.next_request(spec, response, [])
    assert nxt is None  # oldest row reached the window start


def test_okx_error_code_is_a_provider_error() -> None:
    end = datetime(2026, 9, 23, 3, tzinfo=UTC)
    spec = okx_spec("open_interest", end - timedelta(hours=6), end)
    bad = raw(spec, {"code": "50011", "msg": "Too Many Requests", "data": []}, "okx", end)
    with pytest.raises(ProviderPermanentError, match="50011"):
        OKX.parse_page(spec, bad)
    with pytest.raises(SchemaMismatchError):
        OKX.parse_page(spec, raw(spec, {"data": "x"}, "okx", end))


def test_okx_unconfigured_asset_is_refused() -> None:
    window = FetchWindow(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC), "DOGE")
    with pytest.raises(ProviderNotConfiguredError):
        OKX.first_request("deriv.open_interest.btc.1h", window)


# --------------------------------------------------------------------------- OKX liquidations

LIQ_START = datetime(2026, 9, 25, 13, tzinfo=UTC)
LIQ_END = datetime(2026, 9, 25, 15, tzinfo=UTC)
RECEIVED = datetime(2026, 9, 25, 15, 5, tzinfo=UTC)


def liquidation_pages(pages: list[object]) -> list[CanonicalObservation]:
    """Run the instruments request and the given liquidation pages through the adapter."""
    spec = okx_spec("liquidations", LIQ_START, LIQ_END)
    assert spec.path == "/api/v5/public/instruments"
    instrument = raw(spec, fixture("okx_instrument_BTC-USDT-SWAP.json"), "okx", RECEIVED)
    assert OKX.parse_page(spec, instrument) == []
    spec_or_none = OKX.next_request(spec, instrument, [])
    out: list[CanonicalObservation] = []
    for page in pages:
        assert spec_or_none is not None
        spec = spec_or_none
        body = page if isinstance(page, bytes) else json.dumps(page).encode()
        response = raw(spec, body, "okx", RECEIVED)
        out.extend(records(OKX, spec, response, "liquidations", "BTC"))
        spec_or_none = OKX.next_request(spec, response, [])
    assert spec_or_none is None, "pagination should have ended"
    return out


def test_okx_liquidations_real_excerpt_become_hourly_totals_in_coins() -> None:
    out = liquidation_pages([fixture("okx_liquidations_BTC_excerpt.json")])
    by = {(o.event_time.hour, o.subject_ref): o for o in out}
    assert len(out) == 4  # hours 13:00 and 14:00, long and short
    # 14 long liquidations 14:04-14:05 UTC: sum of sz = 85.20 contracts x ctVal 0.01 BTC
    assert by[(14, "PERP:BTC-USDT:long")].value == Decimal("0.8520")
    assert by[(14, "PERP:BTC-USDT:short")].value == 0
    assert by[(13, "PERP:BTC-USDT:long")].value == 0  # complete hour without liquidations
    first = by[(14, "PERP:BTC-USDT:long")]
    assert first.available_at == datetime(2026, 9, 25, 15, 2, tzinfo=UTC)  # hour end + 2 min
    assert "ctVal 0.01" in first.transformations[0]
    assert first.quality_status is QualityStatus.OK


def detail(ts: datetime, size: str, pos: str = "long", side: str = "sell") -> dict[str, str]:
    stamp = ms(ts)
    return {"bkPx": "80000", "posSide": pos, "side": side, "sz": size, "ts": stamp}


def page(details: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "code": "0",
        "msg": "",
        "data": [{"instId": "BTC-USDT-SWAP", "uly": "BTC-USDT", "details": details}],
    }


def test_okx_liquidations_count_orders_sharing_the_page_boundary_once() -> None:
    boundary = datetime(2026, 9, 25, 14, 30, tzinfo=UTC)
    first = [detail(boundary + timedelta(seconds=100 - i), "1") for i in range(98)]
    first += [detail(boundary, "2"), detail(boundary, "3")]  # 100 details: the page is full
    # the next page (after = boundary + 1 ms) repeats both orders at the boundary, then older ones
    second = [detail(boundary, "2"), detail(boundary, "3"), detail(boundary, "5")]
    second += [detail(datetime(2026, 9, 25, 13, 10, tzinfo=UTC), "7", "short", "buy")]
    second += [detail(datetime(2026, 9, 25, 12, 59, tzinfo=UTC), "100")]  # before the window
    out = liquidation_pages([page(first), page(second)])
    by = {(o.event_time.hour, o.subject_ref.rsplit(":", 1)[1]): o.value for o in out}
    # 98 x 1 + 2 + 3 + 5 (the new order at the boundary) = 108 contracts x 0.01
    assert by[(14, "long")] == Decimal("1.08")
    assert by[(13, "short")] == Decimal("0.07")
    assert by[(13, "long")] == 0  # the order at 12:59 is outside the window


def test_okx_liquidations_flag_inconsistent_sides() -> None:
    hour = datetime(2026, 9, 25, 14, 10, tzinfo=UTC)
    out = liquidation_pages(
        [page([detail(hour, "4", "net", "buy"), detail(hour, "1", "long", "buy")])]
    )
    by = {(o.event_time.hour, o.subject_ref.rsplit(":", 1)[1]): o for o in out}
    assert by[(14, "short")].value == Decimal("0.04")  # one-way mode: a buy closes a short
    assert by[(14, "long")].value == 0
    assert by[(14, "long")].quality_status is QualityStatus.SUSPECT
    assert "0.01 BTC" in (by[(14, "long")].quality_note or "")


def test_okx_liquidation_hours_beyond_retention_are_not_emitted() -> None:
    spec = okx_spec("liquidations", LIQ_END - timedelta(hours=30), LIQ_END)
    instrument = raw(spec, fixture("okx_instrument_BTC-USDT-SWAP.json"), "okx", RECEIVED)
    liq = OKX.next_request(spec, instrument, [])
    assert liq is not None
    response = raw(liq, page([]), "okx", RECEIVED)
    hours = {r.payload["time"] for r in OKX.parse_page(liq, response)}
    # only hours starting within 18 h of receipt (from 21:05 the day before): 22:00 … 14:00
    assert len(hours) == 17
    assert min(hours) == ms(datetime(2026, 9, 24, 22, tzinfo=UTC))


def test_okx_instrument_must_be_linear_in_the_asset() -> None:
    spec = okx_spec("liquidations", LIQ_START, LIQ_END)
    body = json.loads(fixture("okx_instrument_BTC-USDT-SWAP.json"))
    body["data"][0]["ctValCcy"] = "USD"
    with pytest.raises(SchemaMismatchError, match="linear"):
        OKX.next_request(spec, raw(spec, body, "okx", RECEIVED), [])


# =========================================================================== Binance

BINANCE = BinanceFutures()


def binance_spec(metric: str, start: datetime, end: datetime, asset: str = "BTC") -> RequestSpec:
    return BINANCE.first_request(dataset(metric, asset).dataset_id, FetchWindow(start, end, asset))


def test_binance_requests_use_documented_parameters() -> None:
    end = datetime(2026, 9, 20, 12, tzinfo=UTC)
    oi = binance_spec("open_interest", end - timedelta(hours=6), end, "ETH")
    assert oi.path == "/futures/data/openInterestHist"
    assert oi.params == {
        "symbol": "ETHUSDT",
        "limit": "500",
        "period": "1h",
        "startTime": ms(end - timedelta(hours=6)),
        "endTime": str(int(ms(end)) - 1),
    }
    funding = binance_spec("funding_rate", end - timedelta(days=3), end)
    assert funding.path == "/fapi/v1/fundingRate"
    assert "period" not in funding.params
    assert funding.params["limit"] == "1000"
    ratio = binance_spec("long_short_account_ratio", end - timedelta(hours=6), end, "XRP")
    assert (ratio.path, ratio.params["symbol"]) == (
        "/futures/data/globalLongShortAccountRatio",
        "XRPUSDT",
    )


def test_binance_documented_shapes_are_normalised() -> None:
    end = datetime(2026, 9, 20, 12, tzinfo=UTC)
    oi = binance_spec("open_interest", end - timedelta(hours=2), end)
    hour = int(ms(datetime(2026, 9, 20, 10, tzinfo=UTC)))
    body = [
        {
            "symbol": "BTCUSDT",
            "sumOpenInterest": "81234.567",
            "sumOpenInterestValue": "6801234567.89",
            "timestamp": hour,
        },
        {
            "symbol": "BTCUSDT",
            "sumOpenInterest": "81300.1",
            "sumOpenInterestValue": "1",
            "timestamp": str(hour + 3_600_000),
        },
    ]
    out = records(BINANCE, oi, raw(oi, body, "binance_futures", end), "open_interest", "BTC")
    assert [(o.event_time.hour, o.value) for o in out] == [
        (10, Decimal("81234.567")),
        (11, Decimal("81300.1")),
    ]
    assert (out[0].subject_ref, out[0].venue) == ("PERP:BTC-USDT", "binance")
    funding = binance_spec("funding_rate", end - timedelta(days=1), end)
    body_f = [
        {"symbol": "BTCUSDT", "fundingRate": "0.00010000", "fundingTime": hour + 7, "markPrice": ""}
    ]
    out_f = records(BINANCE, funding, raw(funding, body_f, "b", end), "funding_rate", "BTC")
    assert out_f[0].value == Decimal("0.00010000")
    assert out_f[0].event_time == t(hour + 7)  # settlement times are kept to the millisecond


def test_binance_snapshot_off_the_hour_is_rejected() -> None:
    from cfi.core.errors import DataValidationError

    end = datetime(2026, 9, 20, 12, tzinfo=UTC)
    oi = binance_spec("open_interest", end - timedelta(hours=2), end)
    body = [{"symbol": "BTCUSDT", "sumOpenInterest": "1", "timestamp": int(ms(end)) - 60_000}]
    (record,) = BINANCE.parse_page(oi, raw(oi, body, "b", end))
    with pytest.raises(DataValidationError, match="not on the hour"):
        BINANCE.normalise(record, ctx("open_interest", "BTC", end))


def test_binance_pages_continue_after_the_last_time() -> None:
    end = datetime(2026, 9, 20, 12, tzinfo=UTC)
    spec = binance_spec("open_interest", end - timedelta(days=29), end)
    first = datetime(2026, 8, 22, 12, tzinfo=UTC)
    body = [
        {
            "symbol": "BTCUSDT",
            "sumOpenInterest": "1",
            "timestamp": int(ms(first + i * timedelta(hours=1))),
        }
        for i in range(500)
    ]
    nxt = BINANCE.next_request(spec, raw(spec, body, "b", end), [])
    assert nxt is not None
    assert nxt.params["startTime"] == str(int(ms(first + 499 * timedelta(hours=1))) + 1)
    assert BINANCE.next_request(spec, raw(spec, body[:10], "b", end), []) is None
    with pytest.raises(SchemaMismatchError):
        BINANCE.parse_page(spec, raw(spec, {"code": -1130}, "b", end))
    wrong = [{"symbol": "ETHUSDT", "sumOpenInterest": "1", "timestamp": 1}]
    with pytest.raises(SchemaMismatchError, match="ETHUSDT"):
        BINANCE.parse_page(spec, raw(spec, wrong, "b", end))


# =========================================================================== Deribit

DERIBIT = Deribit()
SNAPSHOT = datetime(2026, 9, 26, 7, 8, 17, 5971, tzinfo=UTC)  # usOut of the futures fixture


def deribit_spec(metric: str, asset: str = "BTC", end: datetime = SNAPSHOT) -> RequestSpec:
    window = FetchWindow(end - timedelta(hours=6), end, asset)
    return DERIBIT.first_request(dataset(metric, asset).dataset_id, window)


def test_deribit_expiry_codes() -> None:
    assert expiry_of("30OCT26") == datetime(2026, 10, 30, 8, tzinfo=UTC)
    assert expiry_of("9OCT26") == datetime(2026, 10, 9, 8, tzinfo=UTC)
    from cfi.core.errors import DataValidationError

    with pytest.raises(DataValidationError):
        expiry_of("31FEB27")


def test_deribit_futures_curve_real_response() -> None:
    spec = deribit_spec("futures_curve")
    assert spec.params == {"currency": "BTC", "kind": "future"}
    received = SNAPSHOT + timedelta(milliseconds=300)
    response = raw(spec, fixture("deribit_future_BTC.json"), "deribit", received)
    out = records(DERIBIT, spec, response, "futures_curve", "BTC")
    assert len(out) == 14
    by = {q.instrument: q for q in out}
    dec = by["BTC-25DEC26"]
    assert isinstance(dec, CanonicalQuote)
    assert (dec.instrument_kind, dec.expiry) == ("future", datetime(2026, 12, 25, 8, tzinfo=UTC))
    assert (dec.mark_price, dec.index_price) == (Decimal("85024.53"), Decimal("83996.18"))
    assert dec.open_interest_usd == Decimal(302679010)  # inverse futures: USD
    assert dec.volume_native == Decimal("98.38040597")
    assert dec.event_time == SNAPSHOT
    assert dec.available_at == SNAPSHOT
    assert dec.available_at_estimated is False
    assert dec.subject_ref == "DERIBIT:BTC-25DEC26"
    perp = by["BTC-PERPETUAL"]
    assert (perp.instrument_kind, perp.expiry) == ("perpetual", None)
    assert by["BTC-28SEP26"].bid_price == Decimal("8.4E+4")  # exponent notation read exactly


def test_deribit_clock_ahead_of_ours_is_dated_by_receipt() -> None:
    spec = deribit_spec("futures_curve")
    early = SNAPSHOT - timedelta(seconds=2)
    response = raw(spec, fixture("deribit_future_BTC.json"), "deribit", early)
    out = records(DERIBIT, spec, response, "futures_curve", "BTC")
    assert out[0].available_at == early
    assert out[0].event_time == SNAPSHOT
    assert any("receipt" in x for x in out[0].transformations)


def test_deribit_option_excerpt_real_rows() -> None:
    spec = deribit_spec("option_chain")
    assert spec.params == {"currency": "BTC", "kind": "option"}
    received = datetime(2026, 9, 25, 14, 28, 43, tzinfo=UTC)
    response = raw(spec, fixture("deribit_option_BTC_30OCT26_excerpt.json"), "deribit", received)
    out = records(DERIBIT, spec, response, "option_chain", "BTC")
    assert len(out) == 23
    put = next(q for q in out if q.instrument == "BTC-30OCT26-76000-P")
    assert (put.instrument_kind, put.option_type, put.strike) == ("option", "put", Decimal(76000))
    assert put.mark_iv == Decimal("0.3661")  # 36.61 % → ratio
    assert put.mark_price == Decimal("0.01106193")  # in BTC
    assert put.open_interest_native == Decimal("778.1")
    assert put.underlying_price == Decimal("83992.59")
    assert put.unit == "btc"
    assert any("percent -> ratio" in x for x in put.transformations)


def test_deribit_rejects_foreign_instruments() -> None:
    from cfi.core.errors import DataValidationError

    spec = deribit_spec("futures_curve")
    body = {
        "jsonrpc": "2.0",
        "result": [
            {
                "instrument_name": "BTC_USDC-PERPETUAL",
                "base_currency": "BTC",
                "quote_currency": "USDC",
                "mark_price": 1,
            }
        ],
        "usOut": 1790406497005971,
    }
    (record,) = DERIBIT.parse_page(spec, raw(spec, body, "deribit", SNAPSHOT))
    with pytest.raises(DataValidationError, match="inverse future"):
        DERIBIT.normalise(record, ctx("futures_curve", "BTC", SNAPSHOT))
    error = {"jsonrpc": "2.0", "error": {"code": 10028, "message": "too_many_requests"}}
    with pytest.raises(ProviderPermanentError, match="10028"):
        DERIBIT.parse_page(spec, raw(spec, error, "deribit", SNAPSHOT))


def test_deribit_dvol_real_response() -> None:
    end = datetime(2026, 9, 26, 7, tzinfo=UTC)
    spec = deribit_spec("volatility_index", end=end)
    assert spec.path == "/public/get_volatility_index_data"
    assert spec.params["resolution"] == "3600"
    assert spec.params["end_timestamp"] == str(int(ms(end)) - 1)
    received = datetime(2026, 9, 26, 7, 18, 46, tzinfo=UTC)
    response = raw(spec, fixture("deribit_dvol_BTC.json"), "deribit", received)
    parsed = DERIBIT.parse_page(spec, response)
    assert len(parsed) == 7
    out = [DERIBIT.normalise(r, ctx("volatility_index", "BTC", received)) for r in parsed]
    last = out[-1]
    assert isinstance(last, CanonicalObservation)
    assert last.event_time == datetime(2026, 9, 26, 6, tzinfo=UTC)
    assert last.value == Decimal("0.3462")  # close 34.62 → ratio
    assert last.available_at == datetime(2026, 9, 26, 7, 2, tzinfo=UTC)
    assert last.subject_ref == "DVOL:BTC"
    assert DERIBIT.next_request(spec, response, []) is None  # continuation null
    # the current, unfinished hour is skipped
    early = datetime(2026, 9, 26, 7, 1, tzinfo=UTC)
    with pytest.raises(NotYetFinalError):
        DERIBIT.normalise(parsed[-1], ctx("volatility_index", "BTC", early))


def test_deribit_dvol_follows_continuation() -> None:
    end = datetime(2026, 9, 26, 7, tzinfo=UTC)
    spec = deribit_spec("volatility_index", end=end)
    body = {"jsonrpc": "2.0", "result": {"data": [], "continuation": int(ms(end)) - 3_600_000}}
    nxt = DERIBIT.next_request(spec, raw(spec, body, "deribit", end), [])
    assert nxt is not None
    assert nxt.params["end_timestamp"] == str(int(ms(end)) - 3_600_000)
