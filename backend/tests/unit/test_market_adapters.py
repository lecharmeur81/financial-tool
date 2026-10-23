"""Coinbase, Binance and CoinGecko adapters: requests, parsing and normalisation (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from cfi.core.errors import (
    DataValidationError,
    NotYetFinalError,
    ProviderPermanentError,
    ProviderTransientError,
    SchemaMismatchError,
)
from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import CanonicalBar, CanonicalObservation
from cfi.market.universe import (
    MARKET_CAP_USD,
    MARKET_CAP_USD_1D,
    SPOT_PRICE_USD,
    ohlcv_dataset,
)
from cfi.providers.base import FetchWindow, NormaliseContext, RawResponse, RequestSpec
from cfi.providers.binance import BinanceSpot
from cfi.providers.bybit import BybitSpot
from cfi.providers.coinbase import CoinbaseExchange
from cfi.providers.coingecko import CoinGecko
from cfi.providers.kraken import KrakenSpot
from cfi.providers.okx import OkxSpot
from tests.market_fakes import dumps_exact, synthetic_bar

FIXTURES = Path(__file__).parent.parent / "fixtures"
H = timedelta(hours=1)


def raw(provider: str, spec: RequestSpec, body: bytes, received: datetime) -> RawResponse:
    return RawResponse(
        provider, spec.path, dict(spec.params), received, 200, "application/json", body
    )


# --------------------------------------------------------------------------- Coinbase


def test_coinbase_reads_the_captured_real_response_exactly() -> None:
    """The fixture is a real Coinbase response: [time, low, high, open, close, volume], newest
    first. Values must be stored exactly as sent, in the right fields."""
    adapter = CoinbaseExchange()
    dataset = ohlcv_dataset("usd", "1h")
    t0 = datetime(2026, 9, 22, tzinfo=UTC)
    spec = adapter.first_request(dataset.dataset_id, FetchWindow(t0, t0 + 4 * H, "BTC"))
    assert spec.params == {
        "granularity": "3600",
        "start": "2026-09-22T00:00:00+00:00",
        "end": "2026-09-22T03:00:00+00:00",  # inclusive end = last bucket that starts in window
    }
    body = (FIXTURES / "coinbase_candles_BTC-USD_3600.json").read_bytes()
    ingested = datetime(2026, 9, 23, 2, tzinfo=UTC)
    records = adapter.parse(raw("coinbase", spec, body, ingested))
    assert len(records) == 4
    ctx = NormaliseContext(dataset, ingested, raw_ref=7)
    bars = sorted(
        (b for b in (adapter.normalise(r, ctx) for r in records) if isinstance(b, CanonicalBar)),
        key=lambda b: b.event_time,
    )
    assert len(bars) == 4
    first = bars[0]
    assert first.event_time == t0
    assert (first.open, first.high, first.low, first.close) == (
        Decimal("86594.94"),
        Decimal("86610.96"),
        Decimal("85832.35"),
        Decimal("85876.06"),
    )
    assert first.volume_base == Decimal("443.58855359")
    assert first.volume_quote is None  # Coinbase does not report it — never estimated
    assert first.trade_count is None
    assert first.unit == "usd"
    assert first.asset == "BTC"
    assert first.subject_ref == "coinbase:spot:BTC-USD"
    assert first.venue == "coinbase"
    assert first.raw_ref == 7
    assert first.available_at == t0 + H + timedelta(seconds=60)
    assert first.available_at_estimated is True
    assert first.pit_reliability is PitReliability.BACKFILLED_LATEST  # ingested a day later
    assert first.transformed
    assert first.consistency_problems() == []
    # consecutive bars chain: each open equals the previous close in this real sample
    assert [b.open for b in bars[1:]] == [b.close for b in bars[:-1]]


def test_coinbase_paginates_in_300_candle_chunks() -> None:
    adapter = CoinbaseExchange()
    dataset = ohlcv_dataset("usd", "1m")
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    window = FetchWindow(t0, t0 + timedelta(minutes=700), "ETH")
    spec: RequestSpec | None = adapter.first_request(dataset.dataset_id, window)
    chunks = []
    while spec is not None:
        chunks.append((spec.params["start"], spec.params["end"]))
        dummy = raw("coinbase", spec, b"[]", t0)
        spec = adapter.next_request(spec, dummy, [])
    assert chunks == [
        ("2026-09-01T00:00:00+00:00", "2026-09-01T04:59:00+00:00"),
        ("2026-09-01T05:00:00+00:00", "2026-09-01T09:59:00+00:00"),
        ("2026-09-01T10:00:00+00:00", "2026-09-01T11:39:00+00:00"),
    ]


def test_coinbase_current_bar_is_not_final() -> None:
    adapter = CoinbaseExchange()
    dataset = ohlcv_dataset("usd", "1m")
    t = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    spec = adapter.first_request(
        dataset.dataset_id, FetchWindow(t, t + timedelta(minutes=1), "SOL")
    )
    bar = synthetic_bar("SOL", t, timedelta(minutes=1))
    body = dumps_exact([[int(t.timestamp()), bar.low, bar.high, bar.open, bar.close, bar.volume]])
    (record,) = adapter.parse(raw("coinbase", spec, body, t))
    with pytest.raises(NotYetFinalError):  # bar closes 12:01, final from 12:02
        adapter.normalise(record, NormaliseContext(dataset, t + timedelta(seconds=90), None))
    final = adapter.normalise(record, NormaliseContext(dataset, t + timedelta(minutes=2), None))
    assert isinstance(final, CanonicalBar)
    assert final.pit_reliability is PitReliability.NATIVE


@pytest.mark.parametrize(
    "body",
    [b'{"message": "error"}', b"[[1, 2, 3]]", b"not json"],
    ids=["object", "wrong arity", "not json"],
)
def test_coinbase_schema_changes_are_detected(body: bytes) -> None:
    adapter = CoinbaseExchange()
    dataset = ohlcv_dataset("usd", "5m")
    t = datetime(2026, 9, 1, tzinfo=UTC)
    spec = adapter.first_request(dataset.dataset_id, FetchWindow(t, t + H, "BTC"))
    with pytest.raises(SchemaMismatchError):
        adapter.parse(raw("coinbase", spec, body, t))


def test_coinbase_ticker_keeps_exact_price_and_notes_truncation() -> None:
    adapter = CoinbaseExchange()
    t = datetime(2026, 9, 23, 1, 51, tzinfo=UTC)
    spec = adapter.first_request(SPOT_PRICE_USD.dataset_id, FetchWindow(t - H, t, "XRP"))
    assert spec.path == "/products/XRP-USD/ticker"
    body = b'{"price":"1.585","time":"2026-09-23T01:51:21.100019781Z","size":"515.5"}'
    (record,) = adapter.parse(raw("coinbase", spec, body, t))
    obs = adapter.normalise(record, NormaliseContext(SPOT_PRICE_USD, t, None))
    assert isinstance(obs, CanonicalObservation)
    assert obs.value == Decimal("1.585")
    assert obs.event_time == datetime(2026, 9, 23, 1, 51, 21, 100019, tzinfo=UTC)
    assert obs.available_at == obs.event_time
    assert obs.available_at_estimated is False
    assert "time: sub-microsecond digits truncated to microseconds" in obs.transformations


def test_coinbase_requires_a_known_subject() -> None:
    adapter = CoinbaseExchange()
    t = datetime(2026, 9, 1, tzinfo=UTC)
    with pytest.raises(Exception, match="subject"):
        adapter.first_request(ohlcv_dataset("usd", "1h").dataset_id, FetchWindow(t, t + H))


# --------------------------------------------------------------------------- Binance


def test_binance_requests_half_open_windows_in_1000_bar_chunks() -> None:
    adapter = BinanceSpot()
    dataset = ohlcv_dataset("usdt", "1m")
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    spec = adapter.first_request(
        dataset.dataset_id, FetchWindow(t0, t0 + timedelta(minutes=1500), "SOL")
    )
    ms = int(t0.timestamp() * 1000)
    assert spec.params == {
        "symbol": "SOLUSDT",
        "interval": "1m",
        "startTime": str(ms),
        "endTime": str(ms + 1000 * 60_000 - 1),
        "limit": "1000",
    }
    nxt = adapter.next_request(spec, raw("binance", spec, b"[]", t0), [])
    assert nxt is not None
    assert nxt.params["startTime"] == str(ms + 1000 * 60_000)
    assert nxt.params["endTime"] == str(ms + 1500 * 60_000 - 1)
    assert adapter.next_request(nxt, raw("binance", nxt, b"[]", t0), []) is None


def test_binance_normalises_usdt_bars_with_quote_volume_and_trades() -> None:
    adapter = BinanceSpot()
    dataset = ohlcv_dataset("usdt", "4h")
    t = datetime(2026, 9, 1, 4, tzinfo=UTC)
    spec = adapter.first_request(dataset.dataset_id, FetchWindow(t, t + 4 * H, "BTC"))
    ms = int(t.timestamp() * 1000)
    body = json.dumps(
        [
            [
                ms,
                "60000.10",
                "60500.00",
                "59800.00",
                "60200.55",
                "12.5",
                ms + 4 * 3600_000 - 1,
                "752506.87",
                4210,
                "6",
                "300000",
                "0",
            ]
        ]
    ).encode()
    (record,) = adapter.parse(raw("binance", spec, body, t))
    bar = adapter.normalise(record, NormaliseContext(dataset, t + 5 * H, 3))
    assert bar.unit == "usdt"  # never presented as USD
    assert bar.subject_ref == "binance:spot:BTC-USDT"
    assert bar.close == Decimal("60200.55")
    assert bar.volume_quote == Decimal("752506.87")
    assert bar.trade_count == 4210


def test_binance_rejects_a_kline_whose_close_time_does_not_fit_the_interval() -> None:
    adapter = BinanceSpot()
    dataset = ohlcv_dataset("usdt", "1h")
    t = datetime(2026, 9, 1, tzinfo=UTC)
    spec = adapter.first_request(dataset.dataset_id, FetchWindow(t, t + H, "ETH"))
    ms = int(t.timestamp() * 1000)
    body = json.dumps([[ms, "1", "2", "0.5", "1.5", "3", ms + 60_000 - 1, "4", 5, "0", "0", "0"]])
    (record,) = adapter.parse(raw("binance", spec, body.encode(), t))
    with pytest.raises(DataValidationError, match="close time"):
        adapter.normalise(record, NormaliseContext(dataset, t + 2 * H, None))


# --------------------------------------------------------------------------- CoinGecko


def test_coingecko_latest_market_caps_for_all_assets_in_one_request() -> None:
    adapter = CoinGecko()
    t = datetime(2026, 9, 23, 10, tzinfo=UTC)
    spec = adapter.first_request(MARKET_CAP_USD.dataset_id, FetchWindow(t - H, t))
    assert spec.params["ids"] == "bitcoin,ethereum,solana,ripple"
    updated = int((t - timedelta(seconds=40)).timestamp())
    body = (
        b'{"bitcoin":{"usd":85000.1,"usd_market_cap":1691500000000.5,"last_updated_at":'
        + str(updated).encode()
        + b'},"ripple":{"usd":1.58,"last_updated_at":'
        + str(updated).encode()
        + b"}}"
    )
    records = adapter.parse(raw("coingecko", spec, body, t))
    ctx = NormaliseContext(MARKET_CAP_USD, t, None)
    btc, xrp = (adapter.normalise(r, ctx) for r in records)
    assert isinstance(btc, CanonicalObservation)
    assert isinstance(xrp, CanonicalObservation)
    assert btc.value == Decimal("1691500000000.5")
    assert btc.subject_ref == "BTC"
    assert btc.available_at_estimated is False
    assert xrp.value is None  # provider gave no market cap → explicit missing, never zero
    assert xrp.quality_status is QualityStatus.MISSING


def test_coingecko_daily_history_skips_the_running_value() -> None:
    adapter = CoinGecko()
    now = datetime(2026, 9, 23, 10, 30, tzinfo=UTC)
    spec = adapter.first_request(
        MARKET_CAP_USD_1D.dataset_id, FetchWindow(now - 3 * 24 * H, now, "ETH")
    )
    assert spec.path == "/coins/ethereum/market_chart"
    assert spec.params["days"] == "3"
    assert spec.params["interval"] == "daily"
    midnight = datetime(2026, 9, 23, tzinfo=UTC)
    body = json.dumps(
        {
            "market_caps": [
                [int((midnight - 24 * H).timestamp() * 1000), 3.5e11],
                [int(midnight.timestamp() * 1000) + 90_000, 3.6e11],  # 90 s after midnight
                [int(now.timestamp() * 1000), 3.7e11],  # running value
            ]
        }
    ).encode()
    records = adapter.parse(raw("coingecko", spec, body, now))
    ctx = NormaliseContext(MARKET_CAP_USD_1D, now, None)
    day1 = adapter.normalise(records[0], ctx)
    assert day1.event_time == midnight - 24 * H
    day2 = adapter.normalise(records[1], ctx)
    assert day2.event_time == midnight
    assert any("aligned to the 00:00 UTC daily grid" in t for t in day2.transformations)
    with pytest.raises(NotYetFinalError, match="running value"):
        adapter.normalise(records[2], ctx)


def test_coingecko_rejects_non_positive_market_cap() -> None:
    adapter = CoinGecko()
    t = datetime(2026, 9, 23, tzinfo=UTC)
    spec = adapter.first_request(MARKET_CAP_USD.dataset_id, FetchWindow(t - H, t, "SOL"))
    body = b'{"solana":{"usd":150,"usd_market_cap":0,"last_updated_at":1790121600}}'
    (record,) = adapter.parse(raw("coingecko", spec, body, t))
    with pytest.raises(DataValidationError, match="non-positive"):
        adapter.normalise(record, NormaliseContext(MARKET_CAP_USD, t, None))


# --------------------------------------------------------------------------- OKX, Bybit, Kraken


def test_okx_sends_only_bar_values_okx_accepts_for_every_timeframe() -> None:
    # OKX rejects "4Hutc" with code 51000 "Parameter bar error" (it has no UTC variant below 6H);
    # a Hong Kong 4H bar opens on a multiple of four hours, so plain "4H" is already UTC-aligned.
    adapter = OkxSpot()
    t = datetime(2026, 9, 1, tzinfo=UTC)
    sent = {
        tf: adapter.first_request(
            ohlcv_dataset("usdt", tf).dataset_id, FetchWindow(t - 24 * H, t, "XRP")
        ).params["bar"]
        for tf in ("1m", "5m", "15m", "1h", "4h", "1d")
    }
    assert sent == {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1Dutc"}
    assert "4Hutc" not in sent.values()


def test_okx_uses_utc_daily_bars_and_respects_the_confirm_flag() -> None:
    adapter = OkxSpot()
    dataset = ohlcv_dataset("usdt", "1d")
    t = datetime(2026, 9, 1, tzinfo=UTC)
    spec = adapter.first_request(dataset.dataset_id, FetchWindow(t - 3 * 24 * H, t, "XRP"))
    assert spec.params["bar"] == "1Dutc"  # not the Hong Kong-time 1D bar
    assert spec.params["instId"] == "XRP-USDT"
    ms = str(int((t - 24 * H).timestamp() * 1000))
    body = json.dumps(
        {"code": "0", "msg": "", "data": [[ms, "2", "2.1", "1.9", "2.05", "10", "20", "20.5", "0"]]}
    ).encode()
    (record,) = adapter.parse(raw("okx", spec, body, t + H))
    with pytest.raises(NotYetFinalError, match="unfinished"):
        adapter.normalise(record, NormaliseContext(dataset, t + H, None))


def test_provider_error_payloads_fail_the_request_visibly() -> None:
    t = datetime(2026, 9, 1, tzinfo=UTC)
    okx = OkxSpot()
    spec = okx.first_request(ohlcv_dataset("usdt", "1h").dataset_id, FetchWindow(t - H, t, "BTC"))
    with pytest.raises(ProviderPermanentError, match="OKX error 51001"):
        okx.parse(
            raw("okx", spec, b'{"code":"51001","msg":"Instrument ID does not exist","data":[]}', t)
        )
    bybit = BybitSpot()
    spec = bybit.first_request(ohlcv_dataset("usdt", "1h").dataset_id, FetchWindow(t - H, t, "BTC"))
    assert spec.params["category"] == "spot"
    assert spec.params["interval"] == "60"
    with pytest.raises(ProviderPermanentError, match="Bybit error 10001"):
        bybit.parse(raw("bybit", spec, b'{"retCode":10001,"retMsg":"params error"}', t))
    kraken = KrakenSpot()
    spec = kraken.first_request(ohlcv_dataset("usd", "1h").dataset_id, FetchWindow(t - H, t, "BTC"))
    assert spec.params["pair"] == "XBTUSD"
    with pytest.raises(ProviderTransientError, match="Rate limit"):
        kraken.parse(raw("kraken", spec, b'{"error":["EAPI:Rate limit exceeded"]}', t))
    with pytest.raises(ProviderPermanentError, match="Unknown asset pair"):
        kraken.parse(raw("kraken", spec, b'{"error":["EQuery:Unknown asset pair"]}', t))


def test_kraken_reads_its_own_pair_key_and_trade_count() -> None:
    adapter = KrakenSpot()
    dataset = ohlcv_dataset("usd", "4h")
    t = datetime(2026, 9, 1, 4, tzinfo=UTC)
    spec = adapter.first_request(dataset.dataset_id, FetchWindow(t, t + 4 * H, "XRP"))
    assert spec.params["interval"] == "240"
    body = json.dumps(
        {
            "error": [],
            "result": {
                "XXRPZUSD": [
                    [int(t.timestamp()), "2.01", "2.2", "1.95", "2.1", "2.07", "150.5", 42]
                ],
                "last": int(t.timestamp()),
            },
        }
    ).encode()
    (record,) = adapter.parse(raw("kraken", spec, body, t + 5 * H))
    bar = adapter.normalise(record, NormaliseContext(dataset, t + 5 * H, None))
    assert (bar.unit, bar.subject_ref, bar.trade_count) == ("usd", "kraken:spot:XRP-USD", 42)
    assert bar.volume_quote is None  # Kraken's vwap is never used to estimate quote volume
