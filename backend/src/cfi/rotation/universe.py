"""Capital Rotation Engine parameters and node registry (Phase 20).

This module has **no ingestion of its own** — every node reads data already ingested and already
calculated by Phases 5-13 (market bars and per-asset market caps, institutional ETF flows, whale
exchange flows, stablecoin supply, retail attention proxies), read through
``cfi.divergence.adapters.Adapters`` (reused unchanged, plus one new method,
``asset_market_cap`` — see that module). All parameters below are **judgment parameters chosen by
design** (not fitted to data), versioned and published exactly like every other phase's
``PARAMETERS``/``ParameterSet`` (R13).

**Node/edge reuse (R13: do not create unnecessary abstractions).** ``NodeDef``, ``RotationEdge``
and ``classify_edge`` are Phase 13's own Capital Flow Map types
(``cfi.divergence.capital_flow_map``), reused unchanged here for Phase 20's own node list: the
exact same hedge discipline the user is asking for — "never claim capital moved from A to B solely
because B increased while A decreased" — was already built, tested, and is Phase 13's whole reason
for existing. ``classify_edge`` only ever returns ``"possible_rotation"`` (never a bare "rotation
happened" claim) with ``evidence_class = "inferred"`` and hedged wording; this phase's own
contribution is a directly comparable pairwise MARKET-SHARE metric across the requested 10
categories, and a check of whether OBSERVED FLOW data corroborates or contradicts each inferred
rotation (``cfi.rotation.metrics.flow_corroboration``).
"""

from __future__ import annotations

from dataclasses import dataclass

from cfi.divergence.capital_flow_map import NodeDef
from cfi.liquidity.universe import STABLECOINS, TOTAL_SUBJECT
from cfi.market.universe import ASSET_SYMBOLS

# The trailing window used to classify a node's market-share reading as "up"/"down"/"flat".
WINDOW_DAYS_DEFAULT = 30
WINDOW_DAYS_MIN = 3
WINDOW_DAYS_MAX = 180

# How much history is loaded per node to compute its window reading (mirrors
# ``cfi.divergence.universe.LOAD_SPAN_DAYS``'s reasoning).
LOAD_SPAN_DAYS = 400

# The four assets this platform tracks individually make up the "large_caps" aggregate node.
LARGE_CAP_ASSETS: tuple[str, ...] = ASSET_SYMBOLS


@dataclass(frozen=True, slots=True)
class RotationParameters:
    version: str
    window_days_default: int
    description: str


ROTATION_PARAMETERS_V1 = RotationParameters(
    version="rotation_v1",
    window_days_default=WINDOW_DAYS_DEFAULT,
    description=(
        "Direction (up/down/flat) is the sign of the change in a node's own market-share (or, for "
        "the stablecoin aggregate, its own supply) over the trailing window_days — no smoothing, "
        "no arbitrary dead zone, the same transparent rule as cfi.divergence.metrics.direction_of."
    ),
)

# -------------------------------------------------------------------------- nodes

# fetch_key dispatch (interpreted by cfi.rotation.service, not by cfi.divergence — reusing NodeDef's
# shape only): "asset_share" (one asset's market cap / the genuine global CoinGecko TOTAL crypto
# market cap — cfi.divergence.adapters.Adapters.total_market_cap, the same global denominator
# Phase 12's own BTC/ETH dominance figures already use), "large_caps_share" (sum of the 4 tracked
# assets' market caps / that same global TOTAL — deliberately NOT the sum of the 4 tracked assets
# used as its own denominator, which would make this share a circular, always-100% figure),
# "stablecoin_growth" (TOTAL tracked stablecoin supply's own trailing growth), "stablecoin_share"
# (one issuer's supply / TOTAL tracked stablecoin supply), "retail_meme_trending" (attention proxy,
# informational only — never part of the pairwise rotation matrix), or None (no tracked data at
# all).
NODES: tuple[NodeDef, ...] = (
    NodeDef(
        "btc",
        "BTC",
        "asset_share",
        "BTC",
        "observed",
        "BTC market cap ÷ genuine global crypto TOTAL market cap × 100 (CoinGecko's global figure, "
        "the same denominator Phase 12's own BTC/ETH dominance already uses) — now available as "
        "ranged daily history via CoinGecko's per-asset market-cap chart (MARKET_CAP_USD_1D).",
    ),
    NodeDef(
        "eth",
        "ETH",
        "asset_share",
        "ETH",
        "observed",
        "ETH market cap ÷ genuine global crypto TOTAL market cap × 100.",
    ),
    NodeDef(
        "sol",
        "SOL",
        "asset_share",
        "SOL",
        "observed",
        "SOL market cap ÷ genuine global crypto TOTAL market cap × 100.",
    ),
    NodeDef(
        "xrp",
        "XRP",
        "asset_share",
        "XRP",
        "observed",
        "XRP market cap ÷ genuine global crypto TOTAL market cap × 100.",
    ),
    NodeDef(
        "large_caps",
        "Large Caps",
        "large_caps_share",
        "ALL",
        "observed",
        "Combined (BTC+ETH+SOL+XRP) market cap ÷ genuine global crypto TOTAL market cap × 100 — "
        "this platform's full tracked-asset universe, not a broad large-cap index (see "
        "NOT_TRACKED). Never compared against BTC/ETH/SOL/XRP individually: it is their own sum, "
        "not an independent bucket, so that pair would be a definitional identity, not a rotation "
        "signal.",
    ),
    NodeDef(
        "mid_caps", "Mid Caps", None, None, "unavailable", "No tracked mid-cap asset universe."
    ),
    NodeDef("defi", "DeFi", None, None, "unavailable", "No tracked DeFi-token universe."),
    NodeDef(
        "ai_related",
        "AI-related assets",
        None,
        None,
        "unavailable",
        "No tracked AI-token universe.",
    ),
    NodeDef(
        "meme_assets",
        "Meme assets",
        "retail_meme_trending",
        None,
        "proxy",
        "Retail ATTENTION proxy (trending-mention count across tracked meme coins) — NOT an "
        "observed capital flow or market share; excluded from the pairwise rotation matrix, "
        "reported for information only (see NOT_TRACKED).",
    ),
    NodeDef(
        "stablecoins_total",
        "Stablecoins (total)",
        "stablecoin_growth",
        TOTAL_SUBJECT,
        "observed",
        "TOTAL tracked stablecoin circulating supply's own trailing growth (net minting vs. "
        "redemption, cfi.liquidity's established proxy for stablecoin flow) — a genuine OBSERVED "
        "FLOW reading, not a market-share ratio, so 'up' here means net supply growth, not gained "
        "share of some denominator.",
    ),
    *(
        NodeDef(
            f"stablecoin_{symbol.lower()}",
            symbol,
            "stablecoin_share",
            symbol,
            "observed",
            f"{symbol} circulating supply ÷ TOTAL tracked stablecoin circulating supply × 100 — "
            "cfi.liquidity's own established market-share metric, reused unchanged.",
        )
        for symbol in STABLECOINS
    ),
)

NODES_BY_ID: dict[str, NodeDef] = {n.node_id: n for n in NODES}

# Node pairs excluded from the pairwise rotation matrix because one side is a strict aggregate of
# the other (a definitional identity, not an independent signal — comparing a whole to its own part
# would manufacture a "rotation" out of arithmetic, never a real observation, R1: never treat
# correlation as causation — here it would be worse, an identity).
_LARGE_CAP_OVERLAP: frozenset[tuple[str, str]] = frozenset(
    {("large_caps", a.lower()) for a in LARGE_CAP_ASSETS}
    | {(a.lower(), "large_caps") for a in LARGE_CAP_ASSETS}
)
_STABLECOIN_TOTAL_OVERLAP: frozenset[tuple[str, str]] = frozenset(
    {("stablecoins_total", f"stablecoin_{s.lower()}") for s in STABLECOINS}
    | {(f"stablecoin_{s.lower()}", "stablecoins_total") for s in STABLECOINS}
)
EXCLUDED_PAIRS: frozenset[tuple[str, str]] = _LARGE_CAP_OVERLAP | _STABLECOIN_TOTAL_OVERLAP

# Nodes excluded from the pairwise matrix entirely (informational only, never a rotation leg).
INFORMATIONAL_ONLY: frozenset[str] = frozenset({"meme_assets"})

# What this engine explicitly does NOT (yet) cover — declared once, referenced from every
# response's ``not_tracked`` field, never silently narrowed (R3, matching the precedent set by
# every prior phase's ``NOT_TRACKED`` tuple).
NOT_TRACKED = (
    "Mid-cap assets: no tracked mid-cap asset universe (this platform tracks BTC/ETH/SOL/XRP "
    "only — see cfi.market.universe.ASSET_SYMBOLS).",
    "DeFi-sector assets: no tracked DeFi-token universe.",
    "AI-related assets: no tracked AI-token universe.",
    "Meme assets: no price, market-cap or flow data is ingested for meme coins. The 'meme_assets' "
    "node uses retail's meme-coin trending-mention count as a retail-ATTENTION proxy only — never "
    "a capital-flow or market-share measure, and excluded from the pairwise rotation matrix.",
    "'Large Caps' here means only this platform's own 4-asset universe (BTC+ETH+SOL+XRP), not a "
    "broad market large-cap index — a scope decision, not a claim that no other large-cap assets "
    "exist.",
    "The residual share of the genuine global crypto TOTAL market cap not held by BTC/ETH/SOL/XRP "
    "(i.e. everything the global TOTAL includes but this platform does not individually track) "
    "cannot be decomposed into mid-cap / DeFi / AI / meme sub-shares with this platform's current "
    "data — it is reported once as an informational 'untracked_share_pct' figure, never split "
    "further.",
    "Stablecoin exchange balances and exchange flows are not tracked (cfi.liquidity.universe's "
    "own NOT_TRACKED) — only aggregate circulating supply.",
)

__all__ = [
    "EXCLUDED_PAIRS",
    "INFORMATIONAL_ONLY",
    "LARGE_CAP_ASSETS",
    "LOAD_SPAN_DAYS",
    "NODES",
    "NODES_BY_ID",
    "NOT_TRACKED",
    "ROTATION_PARAMETERS_V1",
    "WINDOW_DAYS_DEFAULT",
    "WINDOW_DAYS_MAX",
    "WINDOW_DAYS_MIN",
    "NodeDef",
    "RotationParameters",
]
