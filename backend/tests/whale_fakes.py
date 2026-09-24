"""In-process fakes of the Coin Metrics Community and Blockchair endpoints — FOR TESTS ONLY.

They serve the synthetic whale history designed in ``tests/fixtures/whales/README.md`` (every
value hand-designed so the expected results can be computed on paper) in the documented response
shapes, through ``httpx2.MockTransport``, to the real adapters and the real HTTP client.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

import httpx2

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
LAST_DAY = date(2026, 9, 9)  # last complete day at NOW (2026-09-10 12:00 UTC)
FIRST_DAY = LAST_DAY - timedelta(days=145)  # 2026-04-17: 146 days of history
WEEK_BEFORE = LAST_DAY - timedelta(days=7)  # 2026-09-02
RECENT = [LAST_DAY - timedelta(days=i) for i in range(7)]  # 2026-09-03 … 2026-09-09


def btc_address(n: int, version: int = 0x00) -> str:
    """A valid Base58Check address built from a counter (synthetic, owned by nobody known)."""
    payload = bytes([version]) + hashlib.sha256(f"cfi-test-{n}".encode()).digest()[:20]
    raw = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    number = int.from_bytes(raw, "big")
    out = ""
    while number:
        number, rem = divmod(number, 58)
        out = B58[rem] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def eth_address(n: int) -> str:
    return "0x" + hashlib.sha256(f"cfi-eth-{n}".encode()).hexdigest()[:40]


def days() -> list[date]:
    out, d = [], FIRST_DAY
    while d <= LAST_DAY:
        out.append(d)
        d += timedelta(days=1)
    return out


def _btc(day: date) -> dict[str, Decimal]:
    recent = day in RECENT
    k = (day - WEEK_BEFORE).days if recent else 0  # 1 … 7 in the last week
    return {
        "FlowInExNtv": Decimal(20_000),
        "FlowOutExNtv": Decimal(21_000 if recent else 20_000),
        "SplyExNtv": Decimal(2_800_000 - 1_000 * k),
        "SplyCur": Decimal(20_000_000) + Decimal(450) * (day - FIRST_DAY).days,
        "IssTotNtv": Decimal(450),
    }


def _eth(day: date) -> dict[str, Decimal]:
    recent = day in RECENT
    k = (day - WEEK_BEFORE).days if recent else 0
    return {
        "FlowInExNtv": Decimal(200_000),
        "FlowOutExNtv": Decimal(190_000 if recent else 200_000),
        "SplyExNtv": Decimal(15_000_000 + 10_000 * k),
        "SplyCur": Decimal(122_000_000),
        "IssTotNtv": Decimal(2_700),
    }


COINMETRICS: dict[str, Callable[[date], dict[str, Decimal]]] = {"btc": _btc, "eth": _eth}


def coinmetrics_status(day: date) -> tuple[str, datetime]:
    """Recent days are 'flash', older 'reviewed'; published 02:00 UTC the next day."""
    published = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1, hours=2)
    return ("flash" if day >= LAST_DAY - timedelta(days=2) else "reviewed"), published


def btc_daily(metric: str, day: date) -> Decimal:
    """Blockchair aggregations (satoshi for BTC sums, coin days for CDD)."""
    recent = day in RECENT
    btc = {
        "revived_supply_1y": Decimal(1_500 if recent else 1_000),
        "lth_spent_155d": Decimal(3_000),
        "miner_origin_spent": Decimal(450),
    }
    if metric == "coin_days_destroyed":
        return Decimal(5_000_000)
    return btc[metric] * 100_000_000


def _json(obj: object, status: int = 200) -> httpx2.Response:
    return httpx2.Response(
        status,
        content=json.dumps(obj, default=str).encode(),
        headers={"content-type": "application/json"},
    )


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond:06d}000Z"


@dataclass
class CoinMetricsFake:
    page_limit: int = 100  # serves smaller pages than asked, to exercise pagination
    requests: list[httpx2.Request] = field(default_factory=list)
    overrides: dict[tuple[str, str, date], Decimal | None] = field(default_factory=dict)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    async def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path != "/v4/timeseries/asset-metrics":
            return _json({"error": {"type": "not_found", "message": "unknown path"}}, 404)
        q = request.url.params
        asset, metric = q["assets"], q["metrics"]
        start = datetime.fromisoformat(q["start_time"].replace("Z", "+00:00")).date()
        end = datetime.fromisoformat(q["end_time"].replace("Z", "+00:00"))
        rows = []
        for day in days():
            moment = datetime(day.year, day.month, day.day, tzinfo=UTC)
            if day < start or moment > end:
                continue
            value = self.overrides.get((asset, metric, day), COINMETRICS[asset](day)[metric])
            row: dict[str, Any] = {"asset": asset, "time": _iso(moment)}
            if value is not None:
                row[metric] = str(value)
            if metric.endswith("ExNtv"):
                status, published = coinmetrics_status(day)
                row[f"{metric}-status"] = status
                row[f"{metric}-status-time"] = _iso(published)
            rows.append(row)
        offset = int(q.get("next_page_token", "0"))
        page = rows[offset : offset + self.page_limit]
        body: dict[str, Any] = {"data": page}
        if offset + self.page_limit < len(rows):
            body["next_page_token"] = str(offset + self.page_limit)
            body["next_page_url"] = "https://example.invalid/next"
        return _json(body)


_RANGE = re.compile(r"(?P<col>\w+)\((?P<a>[^.)]*)\.\.(?P<b>[^)]*)\)")


@dataclass
class BlockchairFake:
    btc_snapshot: dict[str, Decimal] = field(default_factory=dict)  # address → BTC
    eth_snapshot: dict[str, Decimal] = field(default_factory=dict)
    btc_transfers: list[dict[str, Any]] = field(default_factory=list)
    eth_transfers: list[dict[str, Any]] = field(default_factory=list)
    requests: list[httpx2.Request] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    @staticmethod
    def _ctx(rows: int, total: int, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        return {
            "code": 200,
            "limit": limit,
            "offset": offset,
            "rows": rows,
            "total_rows": total,
            "state": 900_000,
            "request_cost": 1,
        }

    def _ranges(self, q: str) -> dict[str, tuple[str, str]]:
        return {m["col"]: (m["a"], m["b"]) for m in _RANGE.finditer(unquote(q))}

    async def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path, q = request.url.path, request.url.params
        if path.endswith("/addresses"):
            chain = path.split("/")[1]
            snap = self.btc_snapshot if chain == "bitcoin" else self.eth_snapshot
            scale = Decimal(100_000_000) if chain == "bitcoin" else Decimal(10) ** 18
            ordered = sorted(snap.items(), key=lambda kv: kv[1], reverse=True)[:100]
            data = [
                {
                    "address": a,
                    "balance": int(b * scale) if chain == "bitcoin" else str(int(b * scale)),
                }
                | ({"nonce": 1, "is_contract": False} if chain == "ethereum" else {})
                for a, b in ordered
            ]
            return _json({"data": data, "context": self._ctx(len(data), len(snap))})
        if "a" in q:
            ranges = self._ranges(q.get("q", ""))
            col = "time" if path == "/bitcoin/blocks" else "spending_time"
            first, last = (date.fromisoformat(x) for x in ranges[col])
            filt = unquote(q.get("q", ""))
            metric = (
                "coin_days_destroyed"
                if path == "/bitcoin/blocks"
                else "miner_origin_spent"
                if "is_from_coinbase(true)" in filt
                else "revived_supply_1y"
                if "lifespan(31536000..)" in filt
                else "lth_spent_155d"
            )
            group, key = q["a"].split(",")
            rows_out: list[dict[str, object]] = [
                {group: d.isoformat(), key: int(btc_daily(metric, d))}
                if metric != "coin_days_destroyed"
                else {group: d.isoformat(), key: float(btc_daily(metric, d))}
                for d in days()
                if first <= d <= last
            ]
            return _json(
                {"data": rows_out, "context": self._ctx(len(rows_out), len(rows_out), limit=10000)}
            )
        rows = self.btc_transfers if path == "/bitcoin/outputs" else self.eth_transfers
        a, b = self._ranges(q["q"])["time"]
        lo = datetime.strptime(a, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        hi = datetime.strptime(b, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        hits = sorted(
            (
                r
                for r in rows
                if lo <= datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC) <= hi
            ),
            key=lambda r: r["time"],
        )
        offset, limit = int(q.get("offset", "0")), int(q.get("limit", "10"))
        page = hits[offset : offset + limit]
        return _json({"data": page, "context": self._ctx(len(page), len(hits), offset, limit)})


def btc_output(
    tx: int, index: int, when: datetime, btc: Decimal, recipient: str, usd: Decimal | None = None
) -> dict[str, Any]:
    return {
        "block_id": 900_000 + tx,
        "transaction_id": 1_000 + tx,
        "index": index,
        "transaction_hash": hashlib.sha256(f"tx{tx}".encode()).hexdigest(),
        "date": when.date().isoformat(),
        "time": when.strftime("%Y-%m-%d %H:%M:%S"),
        "value": int(btc * 100_000_000),
        "value_usd": float(usd) if usd is not None else None,
        "recipient": recipient,
        "type": "scripthash",
        "is_from_coinbase": False,
    }


def eth_tx(tx: int, when: datetime, eth: Decimal, sender: str, recipient: str) -> dict[str, Any]:
    return {
        "block_id": 20_000_000 + tx,
        "id": 5_000 + tx,
        "hash": "0x" + hashlib.sha256(f"eth{tx}".encode()).hexdigest(),
        "date": when.date().isoformat(),
        "time": when.strftime("%Y-%m-%d %H:%M:%S"),
        "failed": False,
        "type": "call",
        "sender": sender,
        "recipient": recipient,
        "value": str(int(eth * 10**18)),
        "value_usd": 4000.0 * float(eth),
    }
