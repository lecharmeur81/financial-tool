"""The 10 standardized comparisons of the Capital Flow Divergence Engine (Phase 13's explicit
list) and the quadrant-matrix labeling shared by all of them.

Each comparison names two "legs" (metric A, metric B) and which asset the ``asset`` query
parameter applies to (``asset_scope``): the caller never has to know which underlying dataset a
comparison reads — only its ``comparison_id`` and, where relevant, an asset.
"""

from __future__ import annotations

from dataclasses import dataclass

from cfi.derivatives.universe import PERP_ASSETS
from cfi.institutional.universe import ETF_ASSETS
from cfi.liquidity.universe import STABLECOINS  # noqa: F401 (documents USDT/USDC choice below)
from cfi.market.universe import ASSET_SYMBOLS
from cfi.whales.universe import WHALE_ASSETS

Direction = str  # "up" / "down" / "flat" / "unavailable"

ARROWS = {"up": "↑", "down": "↓", "flat": "→", "unavailable": "?"}


@dataclass(frozen=True, slots=True)
class Leg:
    key: str  # dispatch key into cfi.divergence.service._fetch
    label: str
    short_label: str
    unit: str


@dataclass(frozen=True, slots=True)
class ComparisonDef:
    comparison_id: str
    number: int  # position 1-10 in the user's own numbered list, for traceability
    title: str
    leg_a: Leg
    leg_b: Leg
    asset_scope: str  # none / shared / leg_a_only / leg_b_only
    allowed_assets: tuple[str, ...] | None
    notes: str


def quadrant_label(short_a: str, short_b: str, dir_a: Direction, dir_b: Direction) -> str:
    return f"{short_a} {ARROWS.get(dir_a, '?')} / {short_b} {ARROWS.get(dir_b, '?')}"


def standard_matrix(short_a: str, short_b: str) -> list[str]:
    """The 4-cell standardized matrix (Phase 13's explicit list): every up/down combination of
    the two legs, always in this fixed order."""
    return [
        quadrant_label(short_a, short_b, da, db) for da in ("up", "down") for db in ("up", "down")
    ]


def is_divergent(dir_a: Direction, dir_b: Direction) -> bool:
    """True only for a genuine opposite-direction pair — never for 'flat' or 'unavailable', which
    are their own distinct states, not a form of divergence."""
    return {dir_a, dir_b} == {"up", "down"}


COMPARISONS: dict[str, ComparisonDef] = {
    c.comparison_id: c
    for c in (
        ComparisonDef(
            "institutional_vs_retail",
            1,
            "Institutional flow vs retail activity",
            Leg(
                "institutional_net_flow",
                "Institutional US spot ETF net flow",
                "Institutional",
                "usd",
            ),
            Leg("retail_small_tx", "Retail small-tx count (BTC, proxy)", "Retail", "count"),
            "leg_a_only",
            ETF_ASSETS,
            "Retail leg is always BTC small-tx count (a proxy, not retail-exclusive data).",
        ),
        ComparisonDef(
            "institutional_vs_price",
            2,
            "Institutional flow vs price",
            Leg(
                "institutional_net_flow",
                "Institutional US spot ETF net flow",
                "Institutional",
                "usd",
            ),
            Leg("price", "Daily close price (Coinbase)", "Price", "usd"),
            "shared",
            tuple(a for a in ETF_ASSETS if a in ASSET_SYMBOLS),
            "Both legs use the same asset.",
        ),
        ComparisonDef(
            "whale_vs_retail",
            3,
            "Whale flow vs retail activity",
            Leg("whale_net_flow", "Whale exchange net flow (inflow − outflow)", "Whale", "coin"),
            Leg("retail_small_tx", "Retail small-tx count (BTC, proxy)", "Retail", "count"),
            "leg_a_only",
            WHALE_ASSETS,
            "Retail leg is always BTC small-transaction count. Includes the two explicitly "
            "requested cross-divergence cells (Whale ↑ / Retail ↓, Whale ↓ / Retail ↑).",
        ),
        ComparisonDef(
            "whale_vs_price",
            4,
            "Whale flow vs price",
            Leg("whale_net_flow", "Whale exchange net flow (inflow − outflow)", "Whale", "coin"),
            Leg("price", "Daily close price (Coinbase)", "Price", "usd"),
            "shared",
            WHALE_ASSETS,
            "Both legs use the same asset.",
        ),
        ComparisonDef(
            "liquidity_vs_price",
            5,
            "Liquidity vs price",
            Leg(
                "stablecoin_supply_total",
                "Combined stablecoin supply (USDT+USDC, TOTAL)",
                "Liquidity",
                "usd",
            ),
            Leg("price", "Daily close price (Coinbase)", "Price", "usd"),
            "leg_b_only",
            ASSET_SYMBOLS,
            "Liquidity leg is the combined TOTAL stablecoin supply (Phase 9's liquidity layer); "
            "the price leg's asset defaults to BTC. See 'stablecoin_supply_vs_price' for the "
            "single-issuer (USDT) view.",
        ),
        ComparisonDef(
            "open_interest_vs_price",
            6,
            "Open interest vs price",
            Leg("open_interest", "Aggregate perpetual open interest", "Open Interest", "coin"),
            Leg("price", "Daily close price (Coinbase)", "Price", "usd"),
            "shared",
            PERP_ASSETS,
            "Open interest is only aggregated across venues for hours where every tracked venue "
            "reported (Phase 8's own convention, never a partial mixed sum).",
        ),
        ComparisonDef(
            "funding_vs_price",
            7,
            "Funding vs price",
            Leg(
                "funding_rate",
                "Mean perpetual funding rate across reporting venues",
                "Funding",
                "ratio",
            ),
            Leg("price", "Daily close price (Coinbase)", "Price", "usd"),
            "shared",
            PERP_ASSETS,
            "A simple mean across whichever venues report that day (no minimum-venue-count gate, "
            "unlike open interest's stricter all-venues aggregate).",
        ),
        ComparisonDef(
            "stablecoin_supply_vs_price",
            8,
            "Stablecoin supply vs price",
            Leg(
                "stablecoin_supply_usdt",
                "USDT stablecoin supply (single issuer)",
                "Stablecoin Supply",
                "usd",
            ),
            Leg("price", "Daily close price (Coinbase)", "Price", "usd"),
            "leg_b_only",
            ASSET_SYMBOLS,
            "USDT alone (the platform's largest tracked stablecoin by supply) — the single-issuer "
            "view, distinct from #5's combined TOTAL view.",
        ),
        ComparisonDef(
            "leverage_vs_price",
            9,
            "Derivatives leverage vs price",
            Leg(
                "leverage_skew",
                "Mean |long/short account ratio − 1| across venues",
                "Leverage Skew",
                "ratio",
            ),
            Leg("price", "Daily close price (Coinbase)", "Price", "usd"),
            "shared",
            PERP_ASSETS,
            "A directional-crowding proxy for implied leverage (distance of the long/short account "
            "ratio from 1.0), distinct from #6's raw open-interest level.",
        ),
        ComparisonDef(
            "macro_vs_market_structure",
            10,
            "Macro conditions vs crypto market structure",
            Leg(
                "macro_net_liquidity",
                "US net liquidity proxy (Fed balance sheet − TGA − reverse repo)",
                "Macro",
                "usd_b",
            ),
            Leg("total_market_cap", "TOTAL crypto market cap", "Market Structure", "usd"),
            "none",
            None,
            "Uses TOTAL crypto market capitalization, not the Market Structure Score itself — the "
            "Score has no ranged history in this platform yet (a Phase 12 gap, not silently "
            "narrowed here — see NOT_TRACKED).",
        ),
    )
}
