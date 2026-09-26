"""In-process fakes of the Binance futures, OKX and Deribit endpoints — FOR TESTS ONLY.

They serve the **synthetic** derivatives history designed in
``tests/fixtures/derivatives/README.md`` (every value chosen so the expected results can be
computed on paper) in each provider's response shape (verified against real OKX and Deribit
responses; Binance as documented), through ``httpx2.MockTransport``, to the real adapters and the
real HTTP client. They are not market data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx2

from tests.market_fakes import dumps_exact

H = timedelta(hours=1)
NOW = datetime(2026, 9, 10, 12, 5, tzinfo=UTC)
LATEST = datetime(2026, 9, 10, 11, tzinfo=UTC)  # newest complete hourly snapshot at NOW
FIRST = NOW - timedelta(days=10)  # the fakes know nothing earlier
SPIKE = datetime(2026, 9, 10, 5, tzinfo=UTC)  # liquidation cascade hour
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
Clock = Callable[[], datetime]


def ms(t: datetime) -> int:
    return (t - EPOCH) // timedelta(milliseconds=1)


def from_ms(value: str | int) -> datetime:
    return EPOCH + timedelta(milliseconds=int(value))


def hours(start: datetime, end: datetime) -> list[datetime]:
    """Hourly times in [start, end] within the fake's history, oldest first."""
    t = max(start, FIRST).replace(minute=0, second=0, microsecond=0)
    if t < start:
        t += H
    out = []
    while t <= end:
        out.append(t)
        t += H
    return out


def settlements(start: datetime, end: datetime) -> list[datetime]:
    """Funding settlements (00:00, 08:00, 16:00 UTC) in [start, end]."""
    return [t for t in hours(start, end) if t.hour % 8 == 0]


# --------------------------------------------------------------------------- synthetic values


def binance_oi(asset: str, t: datetime) -> Decimal | None:
    if asset == "SOL":
        return Decimal(1_000_000)
    if asset != "BTC":
        return None
    if t >= LATEST:
        return Decimal(110_000)
    return Decimal(95_000) if t >= LATEST - timedelta(days=1) else Decimal(90_000)


def okx_oi(asset: str, t: datetime) -> Decimal | None:
    return Decimal(30_000) if asset == "BTC" else None


FUNDING = {("binance", "BTC"): "0.0001", ("binance", "SOL"): "0.0001", ("okx", "BTC"): "0.0003"}
RATIO = {("binance", "BTC"): "1.5", ("okx", "BTC"): "1.2"}


def liquidation_orders(start: datetime, end: datetime) -> list[dict[str, str]]:
    """OKX BTC-USDT-SWAP liquidations in [start, end): each hour one long (60 contracts) and one
    short (40 contracts) liquidation at :30; the spike hour 1,800 long and 200 short."""
    out = []
    for h in hours(start - H, end):
        long, short = ("1800", "200") if h == SPIKE else ("60", "40")
        t = h + timedelta(minutes=30)
        if start <= t < end:
            out.append({"posSide": "long", "side": "sell", "sz": long, "ts": str(ms(t))})
            out.append({"posSide": "short", "side": "buy", "sz": short, "ts": str(ms(t) + 1)})
    return sorted(out, key=lambda d: int(d["ts"]), reverse=True)


FUTURES = {  # instrument → mark (USD); index 60,000
    "BTC-PERPETUAL": Decimal(60_030),
    "BTC-11SEP26": Decimal(60_010),
    "BTC-18SEP26": Decimal(60_100),
    "BTC-25SEP26": Decimal(60_200),
    "BTC-30OCT26": Decimal(60_900),
    "BTC-25DEC26": Decimal(62_100),
    "BTC-26MAR27": Decimal(63_500),
}
OPTIONS = [  # instrument, mark (BTC), mark IV (percent), forward, open interest, 24 h volume
    ("BTC-9OCT26-54000-P", Decimal("0.004"), Decimal(55), Decimal(60_300), 1500, 200),
    ("BTC-9OCT26-60000-C", Decimal("0.03"), Decimal(45), Decimal(60_300), 1000, 100),
    ("BTC-9OCT26-60000-P", Decimal("0.026"), Decimal(45), Decimal(60_300), 500, 100),
    ("BTC-9OCT26-66000-C", Decimal("0.006"), Decimal(47), Decimal(60_300), 2000, 300),
    ("BTC-25SEP26-60000-C", Decimal("0.02"), Decimal(44), Decimal(60_150), 100, 10),
]
INDEX = Decimal(60_000)
DVOL = Decimal(45)


# --------------------------------------------------------------------------- servers


def _json(body: object, status: int = 200) -> httpx2.Response:
    return httpx2.Response(
        status, content=dumps_exact(body), headers={"content-type": "application/json"}
    )


@dataclass
class BinanceFuturesFake:
    requests: list[httpx2.Request] = field(default_factory=list)
    drop: set[datetime] = field(default_factory=set)  # snapshot hours not published

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        q = request.url.params
        symbol = q["symbol"]
        asset = symbol.removesuffix("USDT")
        start, end = from_ms(q["startTime"]), from_ms(q["endTime"])
        limit = int(q["limit"])
        path = request.url.path
        rows: list[dict[str, Any]] = []
        if path == "/futures/data/openInterestHist":
            for t in hours(start, end):
                value = binance_oi(asset, t)
                if value is not None and t not in self.drop:
                    rows.append(
                        {
                            "symbol": symbol,
                            "sumOpenInterest": str(value),
                            "sumOpenInterestValue": str(value * 60_000),
                            "timestamp": ms(t),
                        }
                    )
        elif path == "/fapi/v1/fundingRate":
            rate = FUNDING.get(("binance", asset))
            if rate is not None:
                rows = [
                    {"symbol": symbol, "fundingRate": rate, "fundingTime": ms(t), "markPrice": ""}
                    for t in settlements(start, end)
                ]
        elif path == "/futures/data/globalLongShortAccountRatio":
            ratio = RATIO.get(("binance", asset))
            if ratio is not None:
                rows = [
                    {
                        "symbol": symbol,
                        "longShortRatio": ratio,
                        "longAccount": "0.6",
                        "shortAccount": "0.4",
                        "timestamp": str(ms(t)),
                    }
                    for t in hours(start, end)
                ]
        else:
            return _json({"code": -1, "msg": "unknown path"}, 404)
        return _json(rows[:limit])


@dataclass
class OkxDerivativesFake:
    requests: list[httpx2.Request] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        q = request.url.params
        path = request.url.path
        data: list[Any]
        if path == "/api/v5/rubik/stat/contracts/open-interest-history":
            asset = q["instId"].split("-")[0]
            end = from_ms(q["end"])
            data = [
                [str(ms(t)), str(v * 100), str(v), str(v * 60_000)]
                for t in reversed(hours(FIRST, end - H))
                if (v := okx_oi(asset, t)) is not None
            ][: int(q["limit"])]
        elif path == "/api/v5/public/funding-rate-history":
            asset = q["instId"].split("-")[0]
            rate = FUNDING.get(("okx", asset))
            before = from_ms(q["after"]) - timedelta(milliseconds=1)
            data = (
                []
                if rate is None
                else [
                    {
                        "fundingRate": rate,
                        "fundingTime": str(ms(t)),
                        "instId": q["instId"],
                        "instType": "SWAP",
                        "method": "current_period",
                        "realizedRate": rate,
                    }
                    for t in reversed(settlements(FIRST, before))
                ][: int(q["limit"])]
            )
        elif path == "/api/v5/rubik/stat/contracts/long-short-account-ratio":
            ratio = RATIO.get(("okx", q["ccy"]))
            span = hours(from_ms(q["begin"]), from_ms(q["end"]))
            data = [] if ratio is None else [[str(ms(t)), ratio] for t in reversed(span)][:500]
        elif path == "/api/v5/public/instruments":
            data = []
            if q["instId"] == "BTC-USDT-SWAP":
                data = [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "ctType": "linear",
                        "ctVal": "0.01",
                        "ctValCcy": "BTC",
                        "settleCcy": "USDT",
                    }
                ]
        elif path == "/api/v5/public/liquidation-orders":
            after = from_ms(q["after"])
            orders = [] if q["uly"] != "BTC-USDT" else liquidation_orders(FIRST, after)
            details = orders[: int(q["limit"])]
            data = [
                {
                    "details": details,
                    "instFamily": "BTC-USDT",
                    "instId": "BTC-USDT-SWAP",
                    "instType": "SWAP",
                    "totalLoss": "0",
                    "uly": "BTC-USDT",
                }
            ]
        else:
            return _json({"code": "51000", "msg": "unknown path", "data": []}, 404)
        return _json({"code": "0", "msg": "", "data": data})


@dataclass
class DeribitFake:
    clock: Clock
    requests: list[httpx2.Request] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        q = request.url.params
        path = request.url.path
        us = (self.clock() - EPOCH) // timedelta(microseconds=1)
        envelope: dict[str, Any] = {"jsonrpc": "2.0", "usIn": us, "usOut": us, "usDiff": 1}
        if path.endswith("/public/get_book_summary_by_currency"):
            rows: list[dict[str, Any]] = []
            if q["currency"] == "BTC" and q["kind"] == "future":
                rows = [
                    {
                        "instrument_name": name,
                        "mark_price": mark,
                        "bid_price": mark - 5,
                        "ask_price": mark + 5,
                        "estimated_delivery_price": INDEX,
                        "open_interest": 100_000_000,
                        "volume": Decimal("12.5"),
                        "volume_usd": 750_000,
                        "base_currency": "BTC",
                        "quote_currency": "USD",
                    }
                    for name, mark in FUTURES.items()
                ]
            elif q["currency"] == "BTC" and q["kind"] == "option":
                rows = [
                    {
                        "instrument_name": name,
                        "mark_price": mark,
                        "bid_price": mark,
                        "ask_price": mark + Decimal("0.0005"),
                        "mark_iv": iv,
                        "underlying_price": forward,
                        "estimated_delivery_price": INDEX,
                        "open_interest": oi,
                        "volume": vol,
                        "volume_usd": 0,
                        "base_currency": "BTC",
                        "quote_currency": "BTC",
                    }
                    for name, mark, iv, forward, oi, vol in OPTIONS
                ]
            return _json({**envelope, "result": rows})
        if path.endswith("/public/get_volatility_index_data"):
            start, end = from_ms(q["start_timestamp"]), from_ms(q["end_timestamp"])
            data = (
                [[ms(t), DVOL, DVOL, DVOL, DVOL] for t in hours(start, end)]
                if q["currency"] == "BTC"
                else []
            )
            return _json({**envelope, "result": {"data": data, "continuation": None}})
        return _json({**envelope, "error": {"code": 13020, "message": "not_found"}}, 400)
