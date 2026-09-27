"""In-process fake of the CoinGecko ``/global`` endpoint (TOTAL market capitalisation) —
FOR TESTS ONLY.

Serves synthetic data through ``httpx2.MockTransport``, to the real adapter and the real HTTP
client, in the endpoint's documented shape (see ``cfi/providers/coingecko.py``). The total is a
simple deterministic function of the clock, so the expected stored value can be computed on paper.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

import httpx2

from tests.market_fakes import dumps_exact

Clock = Callable[[], datetime]

BASE_TOTAL_USD = Decimal("2500000000000")  # 2.5T, a plausible round-number total


def total_market_cap_at(t: datetime) -> Decimal:
    """Deterministic, monotonically-varying total: base + a small function of the minute."""
    return BASE_TOTAL_USD + Decimal(t.minute) * Decimal("1000000000")


@dataclass
class CoinGeckoGlobalFake:
    clock: Clock
    requests: list[httpx2.Request] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path != "/api/v3/global":
            return httpx2.Response(
                404,
                content=dumps_exact({"error": "unknown path"}),
                headers={"content-type": "application/json"},
            )
        now = self.clock()
        body = {
            "data": {
                "active_cryptocurrencies": 10000,
                "total_market_cap": {"usd": total_market_cap_at(now)},
                "market_cap_percentage": {"btc": 55.0, "eth": 12.0},
                "updated_at": int(now.timestamp()),
            }
        }
        return httpx2.Response(
            200, content=dumps_exact(body), headers={"content-type": "application/json"}
        )
