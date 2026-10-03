"""The 14 analyst tools (Phase 21 spec, Section 7): a controlled, read-only, uniform calling
convention over the platform's existing, already-tested domain services. This module invents no
new data access — every function below is a thin call into a service Phases 5-20 already built and
tested, exactly as ``cfi.divergence.adapters.Adapters`` already does for the Divergence Engine
(R13: reuse before reinventing).

Claude never calls these directly (ARCHITECTURE.md 5.17: "No action tools" — Claude gets a
pre-built, immutable snapshot, never live database access). ``cfi.analyst.snapshot`` calls every
tool once per analysis, before Claude is ever invoked, and folds the results into that snapshot.

A tool result is always ``{"tool_id", "status", "data", "error"}``: ``status`` is ``"ok"`` when the
service call returned normally (its own internal fields may still say ``missing``/``insufficient``
for individual metrics — that is R3's first-class missing state, not a tool failure), or
``"unavailable"`` when the service itself raised one of the platform's own well-understood
``CFIError`` conditions (no data at all, not yet computable, etc — ``error`` carries the exact
``error_code``/``detail``, never hidden, R3). Any *other* exception is a real bug and is left to
propagate — swallowing an unexpected error here would hide it, which R3 explicitly forbids.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cfi.anomaly.service import AnomalyService
from cfi.core.config import Settings
from cfi.core.errors import CFIError
from cfi.derivatives.queries import DerivativesQueries
from cfi.derivatives.service import DerivativesService
from cfi.divergence.adapters import Adapters
from cfi.divergence.metrics import window_reading
from cfi.divergence.service import DivergenceService
from cfi.divergence.universe import WINDOW_DAYS_DEFAULT as DIVERGENCE_WINDOW_DAYS_DEFAULT
from cfi.institutional.queries import InstitutionalQueries
from cfi.institutional.service import InstitutionalService
from cfi.liquidity.queries import LiquidityQueries
from cfi.liquidity.service import LiquidityService
from cfi.macro.queries import MacroQueries
from cfi.macro.service import MacroService
from cfi.market.universe import ASSET_SYMBOLS
from cfi.market_structure.queries import MarketStructureQueries
from cfi.market_structure.service import MarketStructureService
from cfi.regime.service import RegimeService
from cfi.retail.queries import RetailQueries
from cfi.retail.service import RetailService
from cfi.rotation.service import RotationService
from cfi.rotation.universe import WINDOW_DAYS_DEFAULT as ROTATION_WINDOW_DAYS_DEFAULT
from cfi.similarity.service import SimilarityService
from cfi.whales.queries import WhaleQueries
from cfi.whales.service import WhaleService

ToolResult = dict[str, Any]


async def _run(tool_id: str, call: Any) -> ToolResult:
    """Await ``call`` and wrap it in the uniform tool-result envelope. Only the platform's own
    typed ``CFIError`` family is treated as "this tool has no reading right now" (R3: an explicit,
    visible ``unavailable`` state) — anything else is an unanticipated bug and is left to raise."""
    try:
        data = await call
    except CFIError as exc:
        return {
            "tool_id": tool_id,
            "status": "unavailable",
            "data": None,
            "error": {"error_code": exc.error_code, "detail": exc.detail},
        }
    return {"tool_id": tool_id, "status": "ok", "data": data, "error": None}


# --------------------------------------------------------------------------- market data


async def get_market_data(engine: Any, *, as_of: datetime, knowledge_time: datetime) -> ToolResult:
    """Latest close, 24h/7d change and direction, daily volume, and realized volatility for every
    tracked asset (BTC/ETH/SOL/XRP) — the platform's own 4-asset universe (Phase 5/12)."""

    async def build() -> dict[str, Any]:
        adapters = Adapters(engine)
        assets: dict[str, Any] = {}
        for asset in ASSET_SYMBOLS:
            price = await adapters.price_close(asset, as_of)
            volume = await adapters.daily_volume(asset, as_of)
            vol = await adapters.realized_volatility(asset, as_of)
            r24 = window_reading(price, as_of, 1)
            r7d = window_reading(price, as_of, 7)
            assets[asset] = {
                "price_close": {
                    "value": None if r24.last_value is None else str(r24.last_value),
                    "unit": "usd",
                    "timestamp": r24.last_time.isoformat() if r24.last_time else None,
                    "source": "coinbase",
                    "evidence_category": "observed_data",
                },
                "change_24h_pct": {
                    "value": None if r24.change_pct is None else str(round(r24.change_pct, 2)),
                    "unit": "pct",
                    "direction": r24.direction,
                    "evidence_category": "calculated_metric",
                },
                "change_7d_pct": {
                    "value": None if r7d.change_pct is None else str(round(r7d.change_pct, 2)),
                    "unit": "pct",
                    "direction": r7d.direction,
                    "evidence_category": "calculated_metric",
                },
                "volume_24h": {
                    "value": None if not volume else str(volume[-1].value),
                    "unit": "native",
                    "timestamp": volume[-1].time.isoformat() if volume else None,
                    "evidence_category": "observed_data",
                },
                "realized_volatility_30d": {
                    "value": None
                    if not vol
                    else str(round(vol[-1].value, 4))
                    if vol[-1].value is not None
                    else None,
                    "unit": "annualized_ratio",
                    "evidence_category": "calculated_metric",
                },
            }
        return {"as_of": as_of.isoformat(), "assets": assets}

    return await _run("get_market_data", build())


# --------------------------------------------------------------------------- domain overviews


async def get_institutional_flows(
    engine: Any, settings: Settings, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """US spot ETF flows, treasury purchases, and the Institutional Flow Score (Phase 6)."""
    svc = InstitutionalService(InstitutionalQueries(engine), settings.institutional_provider_ids)
    return await _run(
        "get_institutional_flows", svc.overview(as_of=as_of, knowledge_time=knowledge_time)
    )


async def get_whale_activity(
    engine: Any, settings: Settings, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """Exchange flows, large transfers, top holders, and the Whale Flow Score (Phase 7)."""
    svc = WhaleService(
        WhaleQueries(engine),
        settings.whale_provider_ids,
        InstitutionalService(InstitutionalQueries(engine), settings.institutional_provider_ids),
    )
    return await _run(
        "get_whale_activity", svc.overview(as_of=as_of, knowledge_time=knowledge_time)
    )


async def get_retail_activity(
    engine: Any, settings: Settings, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """Retail Activity and Retail Speculation scores and their components (Phase 10)."""
    svc = RetailService(RetailQueries(engine), settings.retail_provider_ids)
    return await _run(
        "get_retail_activity", svc.overview(as_of=as_of, knowledge_time=knowledge_time)
    )


async def get_derivatives(
    engine: Any, settings: Settings, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """Funding, open interest, leverage, liquidations, options, and the Derivatives Health Score
    across every tracked perpetual asset (Phase 8)."""
    svc = DerivativesService(DerivativesQueries(engine), settings.derivative_provider_ids)
    return await _run("get_derivatives", svc.overview(as_of=as_of, knowledge_time=knowledge_time))


async def get_liquidity(
    engine: Any, settings: Settings, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """Stablecoin supply growth and the Liquidity Score (Phase 9)."""
    svc = LiquidityService(LiquidityQueries(engine), settings.liquidity_provider_ids)
    return await _run("get_liquidity", svc.overview(as_of=as_of, knowledge_time=knowledge_time))


async def get_macro(
    engine: Any, settings: Settings, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """Yield curve, real policy rate, VIX, US net liquidity, and the Macro Environment Score
    (Phase 11)."""
    svc = MacroService(MacroQueries(engine), settings.macro_provider_ids)
    return await _run("get_macro", svc.overview(as_of=as_of, knowledge_time=knowledge_time))


async def get_market_structure(
    engine: Any, settings: Settings, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """Trend, momentum, breadth, BTC/ETH dominance, TOTAL2/TOTAL3, and the Market Structure Score
    (Phase 12)."""
    svc = MarketStructureService(
        MarketStructureQueries(engine), settings.market_structure_provider_ids
    )
    return await _run(
        "get_market_structure", svc.overview(as_of=as_of, knowledge_time=knowledge_time)
    )


# --------------------------------------------------------------------------- cross-domain engines


async def calculate_divergence(
    engine: Any, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """The Phase 13 pairwise divergence matrix: 10 standardized comparisons (institutional vs.
    retail, whale vs. price, liquidity vs. price, and 7 more), each already distinguishing
    OBSERVED direction from a hedged, evidence-cited hypothesis."""
    svc = DivergenceService(engine)
    return await _run(
        "calculate_divergence",
        svc.matrix(
            window_days=DIVERGENCE_WINDOW_DAYS_DEFAULT, as_of=as_of, knowledge_time=knowledge_time
        ),
    )


async def get_market_regime(
    engine: Any, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """The current classified market regime, its confidence, and its contributing/contradicting
    metrics (Phase 14)."""
    svc = RegimeService(engine)
    return await _run("get_market_regime", svc.current(as_of=as_of, knowledge_time=knowledge_time))


async def find_historical_similar_periods(
    engine: Any, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """The most similar historical periods by feature distance, with their forward-return
    distributions across a broader analogue set — never a single predicted value (Phase 15)."""
    svc = SimilarityService(engine)
    return await _run(
        "find_historical_similar_periods", svc.current(as_of=as_of, knowledge_time=knowledge_time)
    )


async def get_anomalies(engine: Any, *, as_of: datetime, knowledge_time: datetime) -> ToolResult:
    """Every tracked metric's current percentile-band anomaly reading, for BTC (Phase 19's
    default asset) — magnitude, duration, possible interpretations, and contradicting evidence,
    never labelled bullish or bearish."""
    svc = AnomalyService(engine)
    return await _run(
        "get_anomalies", svc.scan(asset=None, as_of=as_of, knowledge_time=knowledge_time)
    )


async def get_capital_rotation(
    engine: Any, *, as_of: datetime, knowledge_time: datetime
) -> ToolResult:
    """The Phase 20 capital-rotation matrix: OBSERVED market-share moves across BTC/ETH/SOL/large
    caps/stablecoins, with INFERRED rotation hypotheses and flow corroboration — never a claim that
    capital moved from one asset to another."""
    svc = RotationService(engine)
    return await _run(
        "get_capital_rotation",
        svc.matrix(
            window_days=ROTATION_WINDOW_DAYS_DEFAULT, as_of=as_of, knowledge_time=knowledge_time
        ),
    )


def check_data_quality(tool_results: list[ToolResult]) -> ToolResult:
    """A cross-tool summary of missing, stale, unavailable and conflicting data across every other
    tool call in this snapshot — a pure function over already-gathered results, not a new database
    read (R13)."""
    unavailable = [r["tool_id"] for r in tool_results if r["status"] == "unavailable"]
    degraded: list[str] = []
    conflicting: list[str] = []
    for r in tool_results:
        if r["status"] != "ok" or not isinstance(r["data"], dict):
            continue
        quality = r["data"].get("data_quality") or r["data"].get("quality")
        statuses: set[str] = set()
        if isinstance(quality, dict):
            status = quality.get("status")
            if isinstance(status, str):
                statuses.add(status)
        if statuses & {"degraded", "partial", "stale"}:
            degraded.append(r["tool_id"])
        if statuses & {"conflicting"}:
            conflicting.append(r["tool_id"])
    if unavailable and len(unavailable) == len(tool_results):
        overall = "insufficient"
    elif unavailable or conflicting or degraded:
        overall = "degraded"
    else:
        overall = "ok"
    data = {
        "overall_status": overall,
        "unavailable_tools": unavailable,
        "degraded_tools": degraded,
        "conflicting_tools": conflicting,
    }
    return {"tool_id": "check_data_quality", "status": "ok", "data": data, "error": None}
