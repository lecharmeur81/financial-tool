"""The market-structure universe: the one directly-ingested dataset (global TOTAL market
capitalisation) plus which already-tracked assets this module's technical calculations cover
(Phase 12).

Everything else this phase calculates — moving averages, RSI, ATR, volatility, volume trend, VWAP,
relative strength, support/resistance, market breadth, BTC/ETH dominance, TOTAL2, TOTAL3 and the
ETH/BTC ratio — is a **Calculated Metric** (R2) derived at read time from data this platform already
ingests: daily OHLCV bars (Phase 5, ``cfi.market.universe``) and per-asset market capitalisation
(Phase 5/6, ``cfi.market.universe.MARKET_CAP_USD``). Nothing new is ingested for those; see
``cfi.market_structure.metrics`` for the formulas.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from cfi.domain.datasets import AvailabilityRule, DatasetSpec
from cfi.market.universe import ASSET_SYMBOLS

#: The one canonical "no per-asset subject" sentinel for a global, market-wide reading — same
#: pattern as ``cfi.retail.universe.TRENDING_SUBJECT`` and ``cfi.liquidity.universe.TOTAL_SUBJECT``.
GLOBAL_SUBJECT = "GLOBAL"

#: The assets this module computes a per-asset technical readout for — the same universe Phase 5
#: already tracks OHLCV bars for. Reused, not redefined (a second, drifting asset list would be a
#: bug waiting to happen).
STRUCTURE_ASSETS: tuple[str, ...] = ASSET_SYMBOLS

#: Relative strength, ETH/BTC and dominance are always measured against BTC (the market's largest,
#: most liquid, longest-history asset) — a judgment call recorded here, not assumed silently.
BENCHMARK_ASSET = "BTC"
SECONDARY_ASSET = "ETH"  # for the ETH/BTC ratio and ETH dominance specifically

TOTAL_MARKET_CAP_USD = DatasetSpec(
    dataset_id="market_structure.total_market_cap.usd",
    metric="total_market_cap",
    unit="usd",
    period="event",
    availability=AvailabilityRule("provider"),
    freshness_limit=timedelta(hours=6),
    conflict_tolerance=Decimal("0.02"),
    revisable=True,
    description=(
        "Total market capitalisation across every cryptocurrency CoinGecko tracks, in USD "
        "(event_time = provider's last update time). This is TOTAL; TOTAL2 (TOTAL minus BTC's "
        "market cap) and TOTAL3 (TOTAL2 minus ETH's market cap) are Calculated Metrics derived "
        "from this value and the per-asset market caps already tracked by Phase 5/6 "
        "(cfi.market.universe.MARKET_CAP_USD) — never separately ingested."
    ),
)

#: Sourcing gaps and scope decisions for the user's review (restated in TODO.md), not silent
#: shortcuts.
NOT_TRACKED: tuple[dict[str, str], ...] = (
    {
        "item": "Full-market breadth (advance/decline across the entire crypto market)",
        "reason": (
            "No free source publishes an advance/decline line across the whole crypto market "
            "(thousands of listed assets). Market breadth here is a proxy limited to the four "
            "assets this platform already tracks (BTC, ETH, SOL, XRP) — the fraction of them "
            "trading above their own 50-day moving average — never presented as full-market "
            "breadth."
        ),
    },
    {
        "item": "Full market-cap-weighted TOTAL/TOTAL2/TOTAL3 constituent breakdown",
        "reason": (
            "TOTAL2 and TOTAL3 are calculated as TOTAL minus BTC's (and BTC+ETH's) market cap, "
            "matching the common charting convention (e.g. TradingView's CRYPTOCAP:TOTAL2/TOTAL3). "
            "This is a Calculated Metric (R2), never a directly observed value from any provider."
        ),
    },
)


def all_datasets() -> list[DatasetSpec]:
    return [TOTAL_MARKET_CAP_USD]


def dataset_by_id(dataset_id: str) -> DatasetSpec:
    for spec in all_datasets():
        if spec.dataset_id == dataset_id:
            return spec
    raise KeyError(dataset_id)
