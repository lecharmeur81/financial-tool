"""In-process fake of the DefiLlama stablecoins endpoint — FOR TESTS ONLY.

Serves **synthetic** circulating-supply history in DefiLlama's documented shape (see
``cfi/providers/defillama.py``'s module docstring) through ``httpx2.MockTransport``, to the real
adapter and the real HTTP client. Every value is a simple linear function of the calendar day, so
the expected growth/market-share/acceleration figures can be computed on paper (see
``tests/integration/liquidity_support.py``). It is not market data.

The fake always returns its **entire** stored history in one response, exactly like the real
endpoint (there is no date-range parameter to filter by — see ``providers/defillama.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx2

from tests.market_fakes import dumps_exact

EPOCH_DATE = date(1970, 1, 1)

# The fake's synthetic history: one row per day, oldest first.
FIRST_DAY = date(2026, 8, 1)
LATEST_DAY = date(2026, 9, 25)  # the newest day the fake ever reports as final
# Close enough to LATEST_DAY's UTC midnight to stay inside metrics.LATEST_TOLERANCE (36 h) — a
# separate margin from the availability rule's own 36 h estimate (which ``known_when_received``
# satisfies regardless, by falling back to the ingestion time).
NOW = datetime(2026, 9, 26, 9, tzinfo=UTC)

USDT_BASE, USDT_STEP = Decimal(100_000_000), Decimal(500_000)
USDC_BASE, USDC_STEP = Decimal(50_000_000), Decimal(100_000)
TOTAL_BASE, TOTAL_STEP = Decimal(300_000_000), Decimal(1_000_000)


def day_index(day: date) -> int:
    return (day - FIRST_DAY).days


def usdt_supply(day: date) -> Decimal:
    return USDT_BASE + USDT_STEP * day_index(day)


def usdc_supply(day: date) -> Decimal:
    return USDC_BASE + USDC_STEP * day_index(day)


def total_supply(day: date) -> Decimal:
    return TOTAL_BASE + TOTAL_STEP * day_index(day)


def all_days() -> list[date]:
    out = []
    d = FIRST_DAY
    while d <= LATEST_DAY:
        out.append(d)
        d += timedelta(days=1)
    return out


def epoch_seconds(day: date) -> int:
    return int((day - EPOCH_DATE).days) * 86400


@dataclass
class DefiLlamaFake:
    requests: list[httpx2.Request] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path != "/stablecoincharts/all":
            return httpx2.Response(
                404,
                content=dumps_exact({"error": "unknown path"}),
                headers={"content-type": "application/json"},
            )
        stablecoin = request.url.params.get("stablecoin")
        if stablecoin == "1":
            supply = usdt_supply
        elif stablecoin == "2":
            supply = usdc_supply
        else:
            supply = total_supply
        rows = [
            {
                "date": str(epoch_seconds(d)),
                "totalCirculating": {"peggedUSD": supply(d)},
                "totalCirculatingUSD": {"peggedUSD": supply(d)},
                "totalUnreleased": {"peggedUSD": Decimal(0)},
            }
            for d in all_days()
        ]
        return httpx2.Response(
            200, content=dumps_exact(rows), headers={"content-type": "application/json"}
        )
