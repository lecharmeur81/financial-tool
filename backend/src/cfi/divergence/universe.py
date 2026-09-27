"""Divergence Engine parameters and scope declarations (Phase 13).

This module has **no ingestion of its own** — every comparison is computed live from data already
ingested and already calculated by Phases 5-12 (market bars, institutional ETF flows, whale
exchange flows, retail proxies, stablecoin supply, derivatives open interest / funding / long-short
ratio, and macro FRED series). All values below are **judgment parameters chosen by design** (not
fitted to data), published here exactly like every other phase's ``PARAMETERS``/``ParameterSet``
(R13: never hard-code a value to force a particular test result — these are the one place such
constants live, and every comparison cites them by name).
"""

from __future__ import annotations

from decimal import Decimal

# The trailing window used to classify a series as "up"/"down"/"flat" for the quadrant matrix.
WINDOW_DAYS_DEFAULT = 30
WINDOW_DAYS_MIN = 3
WINDOW_DAYS_MAX = 180

# How much history is loaded per comparison to compute the historical percentile, the duration of
# the current quadrant, and past historical examples of it. Matches the LOAD_SPAN reasoning used
# by macro/market_structure (deep enough for a full duration lookback plus the window itself, plus
# a safety margin).
LOAD_SPAN_DAYS = 400

# Below this many historical rolling-window readings, a percentile rank is not considered
# statistically meaningful (mirrors ``cfi.retail.metrics.MIN_PERCENTILE_SAMPLE`` exactly).
MIN_PERCENTILE_SAMPLE = 20

# A magnitude percentile at or above this counts as a "notable" historical episode when scanning
# for past examples of the current quadrant.
EPISODE_PERCENTILE_THRESHOLD = Decimal(70)

# How far back (in days) the duration/episode scan walks before giving up (never an unbounded
# scan — always reported as a cap, never silently truncated, R3).
MAX_DURATION_LOOKBACK_DAYS = 180

# At most this many past episodes of the current quadrant are reported (most recent first).
MAX_HISTORICAL_EXAMPLES = 3

# The default asset used for every asset-specific comparison when the caller does not specify one.
DEFAULT_ASSET = "BTC"

# What this engine explicitly does NOT (yet) cover — declared once, referenced from every
# response's ``not_tracked`` field, never silently narrowed (R3, matching the precedent set by
# every prior phase's ``NOT_TRACKED`` tuple).
NOT_TRACKED = (
    "Mid-cap assets: no tracked mid-cap asset universe (this platform tracks BTC/ETH/SOL/XRP "
    "only — see cfi.market.universe.ASSET_SYMBOLS).",
    "DeFi-sector assets: no tracked DeFi-token universe.",
    "AI-related assets: no tracked AI-token universe.",
    "Meme-asset CAPITAL FLOW: no price or flow data is ingested for meme coins. The 'Meme assets' "
    "Capital Flow Map node uses retail's meme-coin trending-mention count as a retail-ATTENTION "
    "proxy only — never presented as an observed flow.",
    "Full-market institutional/whale flow: limited to each domain's own tracked assets "
    "(institutional: BTC/ETH/SOL/XRP US spot ETFs; whales: BTC/ETH on-chain exchange flow).",
    "The Market Structure Score and BTC dominance have no ranged history in this platform yet "
    "(Phase 12 gap) — the 'macro vs crypto market structure' comparison uses TOTAL crypto market "
    "capitalization instead, which does have ranged history.",
)
