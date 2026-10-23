"""In-process fakes of the Coinbase, Binance and CoinGecko endpoints — FOR TESTS ONLY.

They answer in each provider's documented format (see the adapter module docstrings) with
**synthetic** values from :func:`synthetic_bar`, so tests can compute the expected result. They are
served through ``httpx2.MockTransport`` to the real adapters and the real HTTP client.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

import httpx2

BASE_PRICE = {"BTC": Decimal(60000), "ETH": Decimal(3000), "SOL": Decimal(150), "XRP": Decimal(2)}
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class SynthBar:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trades: int


def synthetic_bar(asset: str, t: datetime, period: timedelta) -> SynthBar:
    """Deterministic, internally consistent synthetic bar (test data, not market data)."""
    base = BASE_PRICE[asset]
    step = base / 1000
    i = int(t.timestamp() // 60) % 97 + int(period.total_seconds() // 60) % 5
    open_ = base + step * i
    close = open_ + step * ((i % 7) - 3)
    high = max(open_, close) + step
    low = min(open_, close) - step
    volume = Decimal("1.5") + i
    return SynthBar(open_, high, low, close, volume, (volume * close).quantize(Decimal("0.01")), i)


def dumps_exact(obj: object) -> bytes:
    """JSON with Decimals written as exact number literals (as providers send them)."""

    def enc(o: object) -> str:
        if isinstance(o, Decimal):
            return format(o, "f")
        if isinstance(o, dict):
            return "{" + ",".join(f"{json.dumps(k)}:{enc(v)}" for k, v in o.items()) + "}"
        if isinstance(o, list | tuple):
            return "[" + ",".join(enc(v) for v in o) + "]"
        return json.dumps(o)

    return enc(obj).encode()


def _json(obj: object) -> httpx2.Response:
    return httpx2.Response(
        200, content=dumps_exact(obj), headers={"content-type": "application/json"}
    )


@dataclass
class FakeProvider:
    clock: Clock
    listed_from: dict[str, datetime] = field(default_factory=dict)  # asset -> first bar
    omitted: set[tuple[str, int, datetime]] = field(default_factory=set)  # no bar published
    overrides: dict[tuple[str, int, datetime], SynthBar] = field(default_factory=dict)
    script: deque[httpx2.Response | Exception] = field(default_factory=deque)
    requests: list[httpx2.Request] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def then(self, *items: httpx2.Response | Exception) -> FakeProvider:
        self.script.extend(items)
        return self

    async def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.script:
            item = self.script.popleft()
            if isinstance(item, Exception):
                raise item
            return item
        return self.serve(request)

    def serve(self, request: httpx2.Request) -> httpx2.Response:
        raise NotImplementedError

    def bars(
        self, asset: str, seconds: int, first: datetime, last: datetime
    ) -> list[tuple[datetime, SynthBar]]:
        """Bars with open time in [first, last] that have started by now (includes the current,
        unfinished bar — as real venues do)."""
        period = timedelta(seconds=seconds)
        now = self.clock()
        start = self.listed_from.get(asset, datetime(2000, 1, 1, tzinfo=UTC))
        out = []
        t = first
        while t <= last:
            if t <= now and t >= start and (asset, seconds, t) not in self.omitted:
                out.append(
                    (t, self.overrides.get((asset, seconds, t), synthetic_bar(asset, t, period)))
                )
            t += period
        return out


class CoinbaseFake(FakeProvider):
    PRODUCT = re.compile(r"^/products/(?P<asset>[A-Z]+)-USD/(?P<kind>candles|ticker)$")

    def serve(self, request: httpx2.Request) -> httpx2.Response:
        match = self.PRODUCT.match(request.url.path)
        if match is None:
            return httpx2.Response(404, json={"message": "NotFound"})
        asset = match["asset"]
        if match["kind"] == "ticker":
            bar = synthetic_bar(asset, self.clock(), timedelta(minutes=1))
            trade_time = self.clock() - timedelta(seconds=3)
            return httpx2.Response(
                200,
                json={
                    "ask": str(bar.close),
                    "bid": str(bar.close),
                    "volume": "1000",
                    "trade_id": 1,
                    "price": str(bar.close),
                    "size": "0.1",
                    # nanosecond precision, like the real API
                    "time": trade_time.strftime("%Y-%m-%dT%H:%M:%S.%f") + "123Z",
                },
            )
        q = request.url.params
        seconds = int(q["granularity"])
        start = datetime.fromisoformat(q["start"])
        end = datetime.fromisoformat(q["end"])  # inclusive, like the real API
        if (end - start) / timedelta(seconds=seconds) + 1 > 300:
            return httpx2.Response(400, json={"message": "exceeds 300 candles"})
        rows = self.bars(asset, seconds, start, end)
        body = [
            [int(t.timestamp()), b.low, b.high, b.open, b.close, b.volume]
            for t, b in reversed(rows)  # newest first
        ]
        return _json(body)


class BinanceFake(FakeProvider):
    def serve(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path != "/api/v3/klines":
            return httpx2.Response(404, json={"code": -1, "msg": "not found"})
        q = request.url.params
        asset = q["symbol"].removesuffix("USDT")
        seconds = int(parse_interval(q["interval"]).total_seconds())
        start = datetime.fromtimestamp(int(q["startTime"]) / 1000, tz=UTC)
        end = datetime.fromtimestamp(int(q["endTime"]) / 1000, tz=UTC)
        rows = self.bars(asset, seconds, start, end)[: int(q.get("limit", "500"))]
        body = [
            [
                int(t.timestamp() * 1000),
                str(b.open),
                str(b.high),
                str(b.low),
                str(b.close),
                str(b.volume),
                int(t.timestamp() * 1000) + seconds * 1000 - 1,
                str(b.quote_volume),
                b.trades,
                "0",
                "0",
                "0",
            ]
            for t, b in rows
        ]
        return httpx2.Response(200, json=body)


def parse_interval(value: str) -> timedelta:
    units = {"m": "minutes", "h": "hours", "d": "days"}
    return timedelta(**{units[value[-1]]: int(value[:-1])})


COIN_ASSET = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "ripple": "XRP"}
SUPPLY = {
    "BTC": Decimal(19_900_000),
    "ETH": Decimal(120_000_000),
    "SOL": Decimal(500_000_000),
    "XRP": Decimal(59_000_000_000),
}


def synthetic_market_cap(asset: str, t: datetime) -> Decimal:
    return synthetic_bar(asset, t, timedelta(days=1)).close * SUPPLY[asset]


class CoinGeckoFake(FakeProvider):
    CHART = re.compile(r"^/api/v3/coins/(?P<coin>[a-z]+)/market_chart$")

    def serve(self, request: httpx2.Request) -> httpx2.Response:
        now = self.clock()
        if request.url.path == "/api/v3/simple/price":
            updated = now - timedelta(seconds=30)
            body = {
                coin: {
                    "usd": synthetic_bar(COIN_ASSET[coin], updated, timedelta(days=1)).close,
                    "usd_market_cap": synthetic_market_cap(COIN_ASSET[coin], updated),
                    "last_updated_at": int(updated.timestamp()),
                }
                for coin in request.url.params["ids"].split(",")
            }
            return _json(body)
        match = self.CHART.match(request.url.path)
        if match is None:
            return httpx2.Response(404, json={"error": "not found"})
        asset = COIN_ASSET[match["coin"]]
        days = int(request.url.params["days"])
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        points = [midnight - timedelta(days=d) for d in range(days, -1, -1)]
        caps = [[int(t.timestamp() * 1000), synthetic_market_cap(asset, t)] for t in points]
        caps.append([int(now.timestamp() * 1000), synthetic_market_cap(asset, now)])  # running
        return _json({"prices": [], "market_caps": caps, "total_volumes": []})


class OkxFake(FakeProvider):
    """``after`` = records strictly earlier than the timestamp; newest first; ``confirm`` flag."""

    BARS: ClassVar[dict[str, int]] = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1H": 3600,
        "4H": 14400,
        "1Dutc": 86400,
    }

    def serve(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path not in ("/api/v5/market/candles", "/api/v5/market/history-candles"):
            return httpx2.Response(404, json={"code": "50000", "msg": "not found"})
        q = request.url.params
        asset = q["instId"].removesuffix("-USDT")
        seconds = self.BARS[q["bar"]]
        before_ms = int(q["after"])
        limit = int(q.get("limit", "100"))
        last = datetime.fromtimestamp(before_ms / 1000, tz=UTC) - timedelta(seconds=seconds)
        first = last - timedelta(seconds=seconds) * (limit - 1)
        rows = self.bars(asset, seconds, first, last)
        now = self.clock()
        body = [
            [
                str(int(t.timestamp() * 1000)),
                str(b.open),
                str(b.high),
                str(b.low),
                str(b.close),
                str(b.volume),
                str(b.volume),
                str(b.quote_volume),
                "1" if t + timedelta(seconds=seconds) <= now else "0",
            ]
            for t, b in reversed(rows)
        ]
        return httpx2.Response(200, json={"code": "0", "msg": "", "data": body})


class BybitFake(FakeProvider):
    INTERVALS: ClassVar[dict[str, int]] = {
        "1": 60,
        "5": 300,
        "15": 900,
        "60": 3600,
        "240": 14400,
        "D": 86400,
    }

    def serve(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path != "/v5/market/kline":
            return httpx2.Response(404)
        q = request.url.params
        asset = q["symbol"].removesuffix("USDT")
        seconds = self.INTERVALS[q["interval"]]
        start = datetime.fromtimestamp(int(q["start"]) / 1000, tz=UTC)
        end = datetime.fromtimestamp(int(q["end"]) / 1000, tz=UTC)
        rows = self.bars(asset, seconds, start, end)[-int(q.get("limit", "200")) :]
        body = [
            [
                str(int(t.timestamp() * 1000)),
                str(b.open),
                str(b.high),
                str(b.low),
                str(b.close),
                str(b.volume),
                str(b.quote_volume),
            ]
            for t, b in reversed(rows)
        ]
        return httpx2.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {"category": "spot", "symbol": q["symbol"], "list": body},
                "retExtInfo": {},
                "time": int(self.clock().timestamp() * 1000),
            },
        )


class KrakenFake(FakeProvider):
    """Only the 720 most recent entries exist, whatever ``since`` asks for; the last entry is the
    current, uncommitted candle. Responses are keyed by Kraken's own pair names."""

    NAMES: ClassVar[dict[str, str]] = {
        "XBTUSD": "XXBTZUSD",
        "ETHUSD": "XETHZUSD",
        "SOLUSD": "SOLUSD",
        "XRPUSD": "XXRPZUSD",
    }
    ASSETS: ClassVar[dict[str, str]] = {
        "XBTUSD": "BTC",
        "ETHUSD": "ETH",
        "SOLUSD": "SOL",
        "XRPUSD": "XRP",
    }

    def serve(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path != "/0/public/OHLC":
            return httpx2.Response(404)
        q = request.url.params
        seconds = int(q["interval"]) * 60
        period = timedelta(seconds=seconds)
        now = self.clock()
        current = datetime.fromtimestamp(now.timestamp() // seconds * seconds, tz=UTC)
        oldest = current - period * 719
        since = datetime.fromtimestamp(int(q.get("since", "0")), tz=UTC)
        rows = self.bars(self.ASSETS[q["pair"]], seconds, max(oldest, since + period), current)
        entries = [
            [
                int(t.timestamp()),
                str(b.open),
                str(b.high),
                str(b.low),
                str(b.close),
                "0",
                str(b.volume),
                b.trades,
            ]
            for t, b in rows
        ]
        return httpx2.Response(
            200,
            json={
                "error": [],
                "result": {self.NAMES[q["pair"]]: entries, "last": int(current.timestamp())},
            },
        )
