"""Market Anomaly Engine parameters and metric registry (Phase 19).

This module has **no ingestion of its own** — every feed is data already ingested and already
calculated by Phases 5-13 (market bars, institutional ETF flows and treasury purchases, whale
exchange flows, derivatives funding/open interest/liquidations, liquidity stablecoin supply, retail
activity/attention proxies, and market structure). All thresholds below are **judgment parameters
chosen by design** (not fitted to data), versioned and published exactly like every other phase's
``PARAMETERS``/``ParameterSet`` (R13). Nothing here labels anything "bullish" or "bearish" — the
user's explicit Phase 19 instruction — and ``POSSIBLE_INTERPRETATIONS`` below is a fixed, neutral,
non-AI-generated registry (L3 Statistical Signal territory, R2): Phase 20's Claude AI Analyst is
the only place an L5 AI Interpretation is produced — anticipating it here is not this module's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

# --------------------------------------------------------------------------- shared parameters

# Matches ``cfi.retail.metrics.MIN_PERCENTILE_SAMPLE`` / ``cfi.divergence.universe`` exactly — below
# this many historical readings, a percentile rank is not considered statistically meaningful.
MIN_PERCENTILE_SAMPLE = 20

# How much history is loaded per metric to compute the historical percentile, the magnitude, and
# the duration of the current band (mirrors ``cfi.divergence.universe.LOAD_SPAN_DAYS``).
LOAD_SPAN_DAYS = 400

# How far back (in days) the duration scan walks before giving up (never an unbounded scan —
# always reported as a cap, never silently truncated, R3).
MAX_DURATION_LOOKBACK_DAYS = 180

# The default asset used for every asset-specific metric when the caller does not specify one.
DEFAULT_ASSET = "BTC"

Band = Literal[
    "extreme_high", "notable_high", "normal", "notable_low", "extreme_low", "unavailable"
]


@dataclass(frozen=True, slots=True)
class AnomalyBandParameters:
    """A versioned, disclosed set of percentile-band cut-points (R13: never a silently hard-coded
    threshold). Bands are symmetric around the median by design, not fitted to any metric's own
    distribution — every metric is judged by the same bands, and the bands themselves are the one
    place this choice is recorded."""

    version: str
    extreme_high: Decimal
    notable_high: Decimal
    notable_low: Decimal
    extreme_low: Decimal
    description: str


ANOMALY_BANDS_V1 = AnomalyBandParameters(
    version="anomaly_bands_v1",
    extreme_high=Decimal("97.5"),
    notable_high=Decimal(90),
    notable_low=Decimal(10),
    extreme_low=Decimal("2.5"),
    description=(
        "extreme_high >= 97.5th percentile, notable_high >= 90th, notable_low <= 10th, "
        "extreme_low <= 2.5th percentile of the metric's own trailing history; normal otherwise. "
        "Symmetric two-tailed cut-points chosen by design (not fitted to any metric's data), "
        "identical for every metric in this registry."
    ),
)


def classify_band(
    percentile: Decimal | None, params: AnomalyBandParameters = ANOMALY_BANDS_V1
) -> Band:
    """Where the current reading's percentile falls among ``params``'s cut-points. ``None``
    (percentile not computable — insufficient history) is always ``"unavailable"``, never silently
    treated as ``"normal"`` (R3)."""
    if percentile is None:
        return "unavailable"
    if percentile >= params.extreme_high:
        return "extreme_high"
    if percentile >= params.notable_high:
        return "notable_high"
    if percentile <= params.extreme_low:
        return "extreme_low"
    if percentile <= params.notable_low:
        return "notable_low"
    return "normal"


# --------------------------------------------------------------------------- metric registry


@dataclass(frozen=True, slots=True)
class AnomalyMetricDef:
    """One of the 13 user-requested anomaly categories. ``adapter`` is the ``Adapters`` method
    name this metric reads (``cfi.divergence.adapters.Adapters``, reused unchanged — Phase 19
    adds no parallel read layer); ``asset_specific`` says whether ``adapter`` takes ``asset``."""

    metric_id: str
    category: str
    label: str
    unit: str
    source: str
    adapter: str
    asset_specific: bool
    evidence_class: Literal["direct", "attributed", "inferred"]
    proxy_caveat: str | None
    counterparts: tuple[str, ...]
    interpretations: dict[Band, tuple[str, ...]]


def _hedged(*lines: str) -> tuple[str, ...]:
    return lines


# Every entry's ``interpretations`` is hedged, mechanism-level, and non-directional in the
# bullish/bearish/buy/sell sense (Phase 19's explicit instruction) — a fixed candidate-reading
# registry, not an AI-generated explanation (R2/R6: this is L3, never L5).
ANOMALY_METRICS: tuple[AnomalyMetricDef, ...] = (
    AnomalyMetricDef(
        metric_id="etf_flows",
        category="ETF flows",
        label="Institutional US spot ETF net flow",
        unit="usd/day",
        source="cfi.institutional (SoSoValue/provider ETF flow filings)",
        adapter="institutional_net_flow",
        asset_specific=True,
        evidence_class="direct",
        proxy_caveat=None,
        counterparts=("institutional_flows", "whale_flows"),
        interpretations={
            "extreme_high": _hedged(
                "Daily ETF net creations are unusually large relative to their own history; "
                "this can reflect a concentrated inflow event, a rebalancing, or a reporting "
                "correction.",
            ),
            "notable_high": _hedged(
                "ETF net creations are elevated relative to their own recent history.",
            ),
            "notable_low": _hedged(
                "ETF net redemptions are elevated relative to their own recent history.",
            ),
            "extreme_low": _hedged(
                "Daily ETF net redemptions are unusually large relative to their own history; "
                "this can reflect a concentrated outflow event, a rebalancing, or a reporting "
                "correction.",
            ),
            "normal": _hedged("ETF net flow is within its ordinary historical range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="institutional_flows",
        category="institutional flows",
        label="Listed-company BTC treasury purchases",
        unit="usd/day",
        source="cfi.institutional (SoSoValue treasury purchase filings, self-disclosed)",
        adapter="treasury_net_acquisitions",
        asset_specific=True,
        evidence_class="attributed",
        proxy_caveat=(
            "Self-disclosed by listed companies and compiled by the provider — attributed "
            "evidence, never a direct on-chain observation of the purchase itself."
        ),
        counterparts=("etf_flows", "whale_flows"),
        interpretations={
            "extreme_high": _hedged(
                "Disclosed treasury purchase spend is unusually large relative to its own "
                "history; this can reflect one or more large concentrated purchases.",
            ),
            "notable_high": _hedged(
                "Disclosed treasury purchase spend is elevated relative to its own recent history.",
            ),
            "notable_low": _hedged(
                "Disclosed treasury purchase spend is unusually quiet relative to its own recent "
                "history; this metric only ever accumulates, so 'low' means little disclosed "
                "acquisition activity (treasury disposals are not tracked, see NOT_TRACKED).",
            ),
            "extreme_low": _hedged(
                "Disclosed treasury purchase spend is unusually quiet relative to its own history.",
            ),
            "normal": _hedged("Treasury purchase spend is within its ordinary historical range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="whale_flows",
        category="whale flows",
        label="Whale-to-exchange net flow",
        unit="native units/day",
        source="cfi.whales (on-chain exchange inflow/outflow, BTC/ETH)",
        adapter="whale_net_flow",
        asset_specific=True,
        evidence_class="direct",
        proxy_caveat=(
            "This platform measures whale activity as net flow to/from known exchange wallets — "
            "the same underlying quantity reported for 'exchange flows' below, not two "
            "independently observed feeds (see NOT_TRACKED)."
        ),
        counterparts=("exchange_flows", "etf_flows", "institutional_flows"),
        interpretations={
            "extreme_high": _hedged(
                "Net flow of large holdings onto exchanges is unusually large relative to its own "
                "history; exchange deposits are commonly associated with preparing to trade or to "
                "post collateral, but custody transfers and cold-storage moves are not "
                "distinguishable from this data alone.",
            ),
            "notable_high": _hedged(
                "Net flow of large holdings onto exchanges is elevated relative to its own recent "
                "history.",
            ),
            "notable_low": _hedged(
                "Net flow of large holdings off exchanges is elevated relative to its own recent "
                "history; exchange withdrawals are commonly associated with moving into "
                "self-custody, but this cannot be confirmed from flow data alone.",
            ),
            "extreme_low": _hedged(
                "Net flow of large holdings off exchanges is unusually large relative to its own "
                "history.",
            ),
            "normal": _hedged(
                "Whale-to-exchange net flow is within its ordinary historical range."
            ),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="exchange_flows",
        category="exchange flows",
        label="Whale-to-exchange net flow",
        unit="native units/day",
        source="cfi.whales (on-chain exchange inflow/outflow, BTC/ETH)",
        adapter="whale_net_flow",
        asset_specific=True,
        evidence_class="direct",
        proxy_caveat=(
            "Same underlying series as 'whale flows' above — this platform does not separately "
            "track aggregate exchange-wallet flow independent of the whale on-chain dataset "
            "(see NOT_TRACKED)."
        ),
        counterparts=("whale_flows",),
        interpretations={
            "extreme_high": _hedged(
                "Net inflow to exchange wallets is unusually large relative to its own history.",
            ),
            "notable_high": _hedged("Net inflow to exchange wallets is elevated."),
            "notable_low": _hedged("Net outflow from exchange wallets is elevated."),
            "extreme_low": _hedged(
                "Net outflow from exchange wallets is unusually large relative to its own history.",
            ),
            "normal": _hedged("Exchange net flow is within its ordinary historical range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="funding",
        category="funding",
        label="Perpetual futures funding rate",
        unit="ratio per interval",
        source="cfi.derivatives (perpetual futures funding rate, multi-venue)",
        adapter="funding_rate",
        asset_specific=True,
        evidence_class="direct",
        proxy_caveat=None,
        counterparts=("oi", "liquidations"),
        interpretations={
            "extreme_high": _hedged(
                "Funding paid by longs to shorts is unusually high relative to its own history — "
                "commonly associated with crowded leveraged-long positioning, though funding "
                "alone does not identify who is paying it.",
            ),
            "notable_high": _hedged("Funding is elevated relative to its own recent history."),
            "notable_low": _hedged(
                "Funding paid by shorts to longs is elevated relative to its own recent history.",
            ),
            "extreme_low": _hedged(
                "Funding paid by shorts to longs is unusually high (funding unusually negative) "
                "relative to its own history — commonly associated with crowded leveraged-short "
                "positioning, though funding alone does not identify who is paying it.",
            ),
            "normal": _hedged("Funding is within its ordinary historical range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="oi",
        category="OI",
        label="Aggregate perpetual futures open interest",
        unit="native units",
        source="cfi.derivatives (open interest, multi-venue aggregate)",
        adapter="open_interest",
        asset_specific=True,
        evidence_class="direct",
        proxy_caveat=None,
        counterparts=("funding", "liquidations"),
        interpretations={
            "extreme_high": _hedged(
                "Open interest is unusually large relative to its own history — commonly "
                "associated with elevated aggregate leverage in the market, without identifying "
                "which side holds it.",
            ),
            "notable_high": _hedged(
                "Open interest is elevated relative to its own recent history."
            ),
            "notable_low": _hedged(
                "Open interest is unusually quiet relative to its own recent history."
            ),
            "extreme_low": _hedged(
                "Open interest is unusually small relative to its own history — commonly "
                "associated with deleveraging or reduced derivatives participation.",
            ),
            "normal": _hedged("Open interest is within its ordinary historical range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="liquidations",
        category="liquidations",
        label="Total forced liquidations (long + short)",
        unit="native units/day",
        source="cfi.derivatives (OKX liquidations, the only tracked venue)",
        adapter="liquidations_total",
        asset_specific=True,
        evidence_class="direct",
        proxy_caveat="Single-venue (OKX) — not a whole-market liquidation total.",
        counterparts=("oi", "funding"),
        interpretations={
            "extreme_high": _hedged(
                "Total forced liquidations are unusually large relative to their own history — "
                "commonly associated with a sharp price move forcing out over-leveraged "
                "positions on one or both sides.",
            ),
            "notable_high": _hedged(
                "Forced liquidations are elevated relative to their own recent history."
            ),
            "notable_low": _hedged("Forced liquidations are unusually quiet."),
            "extreme_low": _hedged(
                "Forced liquidations are unusually quiet relative to their own history."
            ),
            "normal": _hedged("Forced liquidations are within their ordinary historical range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="stablecoin_supply",
        category="stablecoin supply",
        label="Aggregate tracked stablecoin supply",
        unit="usd",
        source="cfi.liquidity (stablecoin issuer supply)",
        adapter="stablecoin_supply",
        asset_specific=False,
        evidence_class="direct",
        proxy_caveat=None,
        counterparts=("retail_activity",),
        interpretations={
            "extreme_high": _hedged(
                "Stablecoin supply growth is unusually fast relative to its own history — "
                "commonly associated with capital entering exchange-accessible form, though this "
                "does not confirm that capital is deployed into crypto assets.",
            ),
            "notable_high": _hedged(
                "Stablecoin supply is growing faster than its own recent history."
            ),
            "notable_low": _hedged(
                "Stablecoin supply growth has slowed relative to its own recent history."
            ),
            "extreme_low": _hedged(
                "Stablecoin supply is contracting unusually fast relative to its own history — "
                "commonly associated with redemptions back to fiat.",
            ),
            "normal": _hedged("Stablecoin supply is within its ordinary historical growth range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="retail_activity",
        category="retail activity",
        label="Small-output on-chain transaction count",
        unit="count/day",
        source="cfi.retail (BTC small-output transaction count)",
        adapter="retail_small_tx_count",
        asset_specific=False,
        evidence_class="direct",
        proxy_caveat=(
            "A retail-activity PROXY (small-output transaction count), never retail-exclusive data."
        ),
        counterparts=("social_activity", "stablecoin_supply"),
        interpretations={
            "extreme_high": _hedged(
                "Small-output transaction activity is unusually high relative to its own history "
                "— a retail-activity proxy, not a direct measure of retail capital flow.",
            ),
            "notable_high": _hedged("Small-output transaction activity is elevated."),
            "notable_low": _hedged("Small-output transaction activity is unusually quiet."),
            "extreme_low": _hedged(
                "Small-output transaction activity is unusually low relative to its own history.",
            ),
            "normal": _hedged("Small-output transaction activity is within its ordinary range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="social_activity",
        category="social activity",
        label="Trending meme-coin count",
        unit="count",
        source="cfi.retail (tracked meme-coin trending-mention count)",
        adapter="retail_meme_trending_count",
        asset_specific=False,
        evidence_class="direct",
        proxy_caveat=(
            "A retail-ATTENTION proxy only — never presented as an observed capital flow "
            "(see NOT_TRACKED)."
        ),
        counterparts=("retail_activity",),
        interpretations={
            "extreme_high": _hedged(
                "The count of trending meme coins is unusually high relative to its own history — "
                "an attention proxy, not a capital-flow measure.",
            ),
            "notable_high": _hedged("Meme-coin trending attention is elevated."),
            "notable_low": _hedged("Meme-coin trending attention is unusually quiet."),
            "extreme_low": _hedged(
                "Meme-coin trending attention is unusually low relative to its own history."
            ),
            "normal": _hedged("Meme-coin trending attention is within its ordinary range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="volume",
        category="volume",
        label="Daily traded volume",
        unit="native units/day",
        source="cfi.market (Coinbase daily bars, base-asset volume)",
        adapter="daily_volume",
        asset_specific=True,
        evidence_class="direct",
        proxy_caveat="Single-venue (Coinbase) — not a whole-market volume total.",
        counterparts=("volatility",),
        interpretations={
            "extreme_high": _hedged(
                "Traded volume is unusually large relative to its own history — commonly "
                "associated with a period of unusually high participation or a large repricing "
                "event, without identifying who is trading.",
            ),
            "notable_high": _hedged(
                "Traded volume is elevated relative to its own recent history."
            ),
            "notable_low": _hedged(
                "Traded volume is unusually quiet relative to its own recent history."
            ),
            "extreme_low": _hedged("Traded volume is unusually quiet relative to its own history."),
            "normal": _hedged("Traded volume is within its ordinary historical range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="volatility",
        category="volatility",
        label="30-day realized volatility",
        unit="annualized ratio",
        source="cfi.market_structure (30-day rolling realized volatility of Coinbase daily bars)",
        adapter="realized_volatility",
        asset_specific=True,
        evidence_class="direct",
        proxy_caveat=None,
        counterparts=("volume", "market_structure"),
        interpretations={
            "extreme_high": _hedged(
                "Realized volatility is unusually high relative to its own history — commonly "
                "associated with a period of large, fast price moves in either direction.",
            ),
            "notable_high": _hedged(
                "Realized volatility is elevated relative to its own recent history."
            ),
            "notable_low": _hedged(
                "Realized volatility is unusually low relative to its own recent history — "
                "commonly associated with a compressed, range-bound market.",
            ),
            "extreme_low": _hedged(
                "Realized volatility is unusually low relative to its own history."
            ),
            "normal": _hedged("Realized volatility is within its ordinary historical range."),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
    AnomalyMetricDef(
        metric_id="market_structure",
        category="market structure",
        label="Total crypto market capitalization",
        unit="usd",
        source="cfi.market_structure (TOTAL crypto market cap)",
        adapter="total_market_cap",
        asset_specific=False,
        evidence_class="direct",
        proxy_caveat=None,
        counterparts=("volatility",),
        interpretations={
            "extreme_high": _hedged(
                "Total crypto market capitalization's daily change is unusually large relative to "
                "its own history.",
            ),
            "notable_high": _hedged("Total crypto market capitalization change is elevated."),
            "notable_low": _hedged("Total crypto market capitalization change is unusually quiet."),
            "extreme_low": _hedged(
                "Total crypto market capitalization's daily change is unusually large (in the "
                "negative direction) relative to its own history.",
            ),
            "normal": _hedged(
                "Total crypto market capitalization change is within its ordinary range."
            ),
            "unavailable": _hedged("Not enough historical readings to rank this metric yet."),
        },
    ),
)

METRICS_BY_ID: dict[str, AnomalyMetricDef] = {m.metric_id: m for m in ANOMALY_METRICS}

# What this engine explicitly does NOT (yet) cover — declared once, referenced from every
# response's ``not_tracked`` field, never silently narrowed (R3, matching the precedent set by
# every prior phase's ``NOT_TRACKED`` tuple).
NOT_TRACKED = (
    "Whale flows and exchange flows are the SAME underlying measured quantity in this platform "
    "(whale-to-exchange on-chain net flow) — not two independently observed feeds.",
    "Institutional treasury purchases only cover BTC (no verified free source publishes dated "
    "purchases for other assets — see cfi.institutional.universe.TREASURY_PURCHASE_ASSETS) and "
    "only accumulation events; treasury disposals are not tracked.",
    "Liquidations are single-venue (OKX) — not a whole-market liquidation total.",
    "Volume is single-venue (Coinbase) — not a whole-market volume total.",
    "Social activity is a retail-ATTENTION proxy (trending meme-coin count), never a capital-flow "
    "measure. Retail activity is a small-output-transaction PROXY, never retail-exclusive data.",
    "Market structure here is TOTAL crypto market capitalization only (Phase 12 gap: no ranged "
    "history yet for the Market Structure Score or BTC dominance).",
    "Mid-cap, DeFi-sector, AI-related and meme assets have no tracked anomaly feed (this "
    "platform's tracked universe is BTC/ETH/SOL/XRP; whale/exchange flows are BTC/ETH only).",
)
