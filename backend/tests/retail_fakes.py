"""In-process fakes of the CoinGecko trending endpoint and the Blockchair small-output-count
aggregation — FOR TESTS ONLY.

Both serve **synthetic** data through ``httpx2.MockTransport``, to the real adapters and the real
HTTP client, in each endpoint's documented shape (see ``cfi/providers/coingecko.py`` and
``cfi/providers/blockchair.py``). Every value is a simple deterministic function of a poll count or
a calendar day, so the expected percentile/score figures can be computed on paper (see
``tests/integration/retail_support.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from urllib.parse import unquote

import httpx2

from tests.market_fakes import dumps_exact

# ---------------------------------------------------------------------------- CoinGecko trending

# A repeating pattern of how many curated meme coins are "trending" on each successive poll (a
# controlled, computable history — not real search data).
MEME_COUNT_PATTERN: tuple[int, ...] = (0, 1, 2, 3, 2, 1, 0, 1, 2, 1)
MEME_SYMBOLS_IN_ORDER: tuple[str, ...] = ("DOGE", "SHIB", "PEPE", "WIF", "BONK", "FLOKI")
FILLER_COIN = {"id": "bitcoin", "symbol": "btc"}  # always present, never a meme coin


def meme_count_at(poll_index: int) -> int:
    return MEME_COUNT_PATTERN[poll_index % len(MEME_COUNT_PATTERN)]


@dataclass
class CoinGeckoTrendingFake:
    poll_count: int = 0
    requests: list[httpx2.Request] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path != "/api/v3/search/trending":
            return httpx2.Response(
                404,
                content=dumps_exact({"error": "unknown path"}),
                headers={"content-type": "application/json"},
            )
        n = meme_count_at(self.poll_count)
        self.poll_count += 1
        coins = [
            {
                "item": {
                    "id": sym.lower(),
                    "symbol": sym.lower(),
                    "name": sym,
                    "market_cap_rank": 100 + rank,
                    "score": rank,
                }
            }
            for rank, sym in enumerate(MEME_SYMBOLS_IN_ORDER[:n])
        ]
        coins.append(
            {
                "item": {
                    "id": FILLER_COIN["id"],
                    "symbol": FILLER_COIN["symbol"],
                    "name": "Bitcoin",
                    "market_cap_rank": 1,
                    "score": n,
                }
            }
        )
        return httpx2.Response(
            200,
            content=dumps_exact({"coins": coins, "nfts": [], "categories": []}),
            headers={"content-type": "application/json"},
        )


# ---------------------------------------------------------------------------- Blockchair small-tx

FIRST_DAY = date(2026, 7, 1)
LAST_DAY = date(2026, 9, 25)  # newest complete UTC day at the fixture's NOW
NOW = datetime(2026, 9, 26, 9, tzinfo=UTC)


def day_index(day: date) -> int:
    return (day - FIRST_DAY).days


def small_output_count(day: date) -> int:
    """A sawtooth: 1000 rising by 20/day, wrapping every 30 days — deterministic and easy to
    check percentile math against by hand."""
    return 1000 + 20 * (day_index(day) % 30)


def all_days() -> list[date]:
    out, d = [], FIRST_DAY
    while d <= LAST_DAY:
        out.append(d)
        d += timedelta(days=1)
    return out


@dataclass
class BlockchairSmallOutputFake:
    requests: list[httpx2.Request] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path, q = request.url.path, request.url.params
        if path != "/bitcoin/outputs" or "a" not in q:
            return httpx2.Response(
                404,
                content=dumps_exact({"error": "unexpected request"}),
                headers={"content-type": "application/json"},
            )
        filt = unquote(q.get("q", ""))
        time_range = next((part for part in filt.split(",") if part.startswith("time(")), None)
        if time_range is None:
            return httpx2.Response(
                400,
                content=dumps_exact({"error": "missing time range"}),
                headers={"content-type": "application/json"},
            )
        bounds = time_range[len("time(") : -1]
        first_s, last_s = bounds.split("..")
        first, last = date.fromisoformat(first_s), date.fromisoformat(last_s)
        group, key = q["a"].split(",")
        rows = [
            {group: d.isoformat(), key: small_output_count(d)}
            for d in all_days()
            if first <= d <= last
        ]
        return httpx2.Response(
            200,
            content=dumps_exact(
                {
                    "data": rows,
                    "context": {
                        "code": 200,
                        "limit": None,
                        "offset": None,
                        "rows": len(rows),
                        "total_rows": len(rows),
                        "state": 900_000,
                        "request_cost": 1,
                    },
                }
            ),
            headers={"content-type": "application/json"},
        )
