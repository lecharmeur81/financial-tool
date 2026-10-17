"""Market Structure read service (Phase 12): trend, moving averages, RSI, ATR, volatility, volume
trend, VWAP, relative strength, support/resistance and market breadth for each tracked asset (BTC,
ETH, SOL, XRP), BTC/ETH dominance, TOTAL/TOTAL2/TOTAL3, the ETH/BTC ratio, and the Market Structure
Score — all point-in-time.

Evidence categories (R2): stored OHLCV bars and market caps are **Observed Data** (read from
Phase 5/6, never re-ingested here except the one new TOTAL market-cap dataset); every moving
average, trend, RSI, ATR, volatility, volume-trend, VWAP, relative-strength, support/resistance,
breadth, dominance and TOTAL-family figure is a **Calculated Metric** with its formula and
parameters published (``cfi/market_structure/metrics.py``); the Market Structure Score is a
**Calculated Metric** built from them. Nothing here is a signal, forecast or recommendation, and
none of it is turned into an automatic trading recommendation (this phase's explicit instruction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.errors import NotFoundError
from cfi.core.time import utc_now
from cfi.market.service import freshness
from cfi.market.sources import VENUES
from cfi.market.universe import MARKET_CAP_USD, ohlcv_dataset_id
from cfi.market_structure import metrics as m
from cfi.market_structure import score as sc
from cfi.market_structure.queries import MarketStructureQueries
from cfi.market_structure.sources import ADAPTERS, ATTRIBUTION, SOURCES
from cfi.market_structure.universe import (
    BENCHMARK_ASSET,
    GLOBAL_SUBJECT,
    NOT_TRACKED,
    STRUCTURE_ASSETS,
    TOTAL_MARKET_CAP_USD,
    all_datasets,
)

# Deep enough for the longest window any component needs: a rolling volatility/ATR percentile
# ranks against its own trailing ~365-day history, itself built from 30/14-day windows of daily
# bars, plus a 200-day SMA for trend — all comfortably covered with a safety margin (matches
# ``cfi.macro.service.LOAD_SPAN``'s reasoning).
LOAD_SPAN = timedelta(days=430)
FLAGGED = ("suspect", "conflicting")
VENUE = VENUES["coinbase"]  # Phase 5's priority-10 default venue; native daily bars for all 4
OHLCV_DATASET_ID = ohlcv_dataset_id(VENUE.quote, "1d")
EVIDENCE_NOTE = (
    "Stored daily OHLCV bars and market caps are observed data (Phase 5/6, read here, never "
    "re-ingested except TOTAL market cap). Moving averages, trend, RSI, ATR, volatility, volume "
    "trend, VWAP, relative strength, support/resistance, market breadth, BTC/ETH dominance, "
    "TOTAL2, TOTAL3, the ETH/BTC ratio and the Market Structure Score are all calculated metrics "
    "with published formulas and parameters. Nothing here is a trading signal, forecast or "
    "automatic recommendation."
)


def num(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


@dataclass
class _AssetBundle:
    bars: list[m.Bar] = field(default_factory=list)
    moving_averages: m.MovingAverageReading | None = None
    trend: m.TrendReading | None = None
    rsi: m.RsiReading | None = None
    atr: m.AtrReading | None = None
    volatility: m.VolatilityReading | None = None
    volume_trend: m.VolumeTrendReading | None = None
    vwap: m.VwapReading | None = None
    support_resistance: dict[int, m.SupportResistanceReading] = field(default_factory=dict)
    relative_strength: m.RelativeStrengthReading | None = None


@dataclass
class _Bundle:
    as_of: datetime
    knowledge_time: datetime
    assets: dict[str, _AssetBundle] = field(default_factory=dict)
    total_cap_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MarketStructureService:
    queries: MarketStructureQueries
    enabled_providers: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers

    async def _asset_bars(self, asset: str, as_of: datetime) -> list[m.Bar]:
        instrument = VENUE.instruments[asset]
        series_id = await self.queries.series_id(OHLCV_DATASET_ID, instrument)
        if series_id is None:
            return []
        start, end = as_of - LOAD_SPAN, as_of + timedelta(seconds=1)
        rows = await self.queries.bars(series_id, VENUE.provider_id, start, end, as_of)
        return m.bars_from_rows(rows)

    async def _load(
        self, as_of: datetime, knowledge_time: datetime, *, include_total_cap: bool = True
    ) -> _Bundle:
        b = _Bundle(as_of, knowledge_time)
        for asset in STRUCTURE_ASSETS:
            bars = await self._asset_bars(asset, as_of)
            ab = _AssetBundle(bars=bars)
            ab.moving_averages = m.moving_averages(bars)
            ab.trend = m.trend(bars)
            ab.rsi = m.rsi(bars)
            ab.atr = m.atr(bars)
            ab.volatility = m.realized_volatility(bars)
            ab.volume_trend = m.volume_trend(bars)
            ab.vwap = m.rolling_vwap(bars)
            for lookback in m.SUPPORT_RESISTANCE_LOOKBACKS:
                ab.support_resistance[lookback] = m.support_resistance(bars, lookback)
            b.assets[asset] = ab
        benchmark_bars = b.assets[BENCHMARK_ASSET].bars
        for asset, ab in b.assets.items():
            if asset == BENCHMARK_ASSET:
                continue
            ab.relative_strength = m.relative_strength(ab.bars, benchmark_bars)

        if not include_total_cap:
            return b
        start, end = as_of - LOAD_SPAN, as_of + timedelta(seconds=1)
        b.total_cap_rows = await self.queries.observations(
            TOTAL_MARKET_CAP_USD.dataset_id,
            subject=GLOBAL_SUBJECT,
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        return b

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> dict[str, Any]:
        return {
            "tracked_assets": list(STRUCTURE_ASSETS),
            "benchmark_asset": BENCHMARK_ASSET,
            "venue": {"venue_id": VENUE.venue_id, "display_name": VENUE.display_name},
            "datasets": [
                {
                    "dataset_id": d.dataset_id,
                    "description": d.description,
                    "unit": d.unit,
                    "period": d.period,
                    "kind": d.kind,
                    "availability_rule": d.availability.as_dict(),
                    "providers": sorted({s.provider_id for s in SOURCES if s.dataset == d}),
                }
                for d in all_datasets()
            ],
            "reused_datasets": [
                {
                    "dataset_id": OHLCV_DATASET_ID,
                    "description": "Daily OHLCV bars, Coinbase Exchange — owning module: market "
                    "(Phase 5). Read here, not re-ingested.",
                    "owning_module": "market (Phase 5)",
                },
                {
                    "dataset_id": MARKET_CAP_USD.dataset_id,
                    "description": MARKET_CAP_USD.description,
                    "owning_module": "market (Phase 5/6). Read here, not re-ingested.",
                },
            ],
            "providers": [
                {
                    "provider_id": pid,
                    "display_name": a.capabilities.display_name,
                    "enabled": pid in self.enabled_providers,
                    "terms_verified": a.capabilities.terms_verified,
                    "notes": a.capabilities.notes,
                    "attribution": ATTRIBUTION.get(pid),
                }
                for pid, a in ADAPTERS.items()
            ],
            "schedule": [
                {
                    "provider_id": s.provider_id,
                    "dataset_id": s.dataset.dataset_id,
                    "subject": s.subject,
                    "every_hours": s.interval_seconds / 3600,
                }
                for s in SOURCES
            ],
            "parameters": m.PARAMETERS,
            "score": {
                "score_id": sc.SCORE_ID,
                "version": sc.SCORE_VERSION,
                "semantic_note": sc.SEMANTIC_NOTE,
                "components": [
                    {
                        "component_id": c.component_id,
                        "label": c.label,
                        "weight": num(c.weight),
                        "scale": num(c.scale),
                        "unit": c.unit,
                        "definition": c.definition,
                        "evidence": c.evidence,
                        "direction_note": c.direction_note,
                    }
                    for c in sc.COMPONENTS
                ],
            },
            "not_tracked": list(NOT_TRACKED),
            "evidence_note": EVIDENCE_NOTE,
        }

    # ------------------------------------------------------------------ overview

    async def overview(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        b = await self._load(as_of, knowledge_time)

        total_rows = [r for r in b.total_cap_rows if r["value"] is not None]
        latest_total = max(total_rows, key=lambda r: r["event_time"], default=None)
        caps = await self.queries.latest_scalars(
            MARKET_CAP_USD.dataset_id, [BENCHMARK_ASSET, "ETH"], as_of
        )
        btc_cap = caps.get(BENCHMARK_ASSET)
        eth_cap = caps.get("ETH")
        total_family = m.total_cap_family(
            None if latest_total is None else latest_total["value"],
            None if btc_cap is None else btc_cap["value"],
            None if eth_cap is None else eth_cap["value"],
            None if latest_total is None else latest_total["event_time"],
        )

        eth_btc = m.eth_btc_ratio(b.assets["ETH"].bars, b.assets[BENCHMARK_ASSET].bars)

        sections = self._overview_sections(b)
        return {
            **sections,
            "total_cap_family": self._total_family(total_family),
            "eth_btc": self._eth_btc(eth_btc),
            "data_quality": await self._quality(b),
            "not_tracked": list(NOT_TRACKED),
        }

    async def overview_score(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        """``overview`` without ``total_cap_family``, ``eth_btc`` and ``data_quality`` (and the
        total-market-cap, market-cap and per-source job queries behind them): every other key, in
        the same order, with the same values. For callers that read only the score, per-asset
        readings and breadth (the regime and similarity snapshot gatherers)."""
        b = await self._load(as_of, knowledge_time, include_total_cap=False)
        return {**self._overview_sections(b), "not_tracked": list(NOT_TRACKED)}

    def _overview_sections(self, b: _Bundle) -> dict[str, Any]:
        as_of, knowledge_time = b.as_of, b.knowledge_time
        calculated_at = utc_now()

        above_sma50 = {
            asset: (
                None
                if ab.moving_averages is None
                or ab.moving_averages.close is None
                or ab.moving_averages.sma50 is None
                else ab.moving_averages.close > ab.moving_averages.sma50
            )
            for asset, ab in b.assets.items()
        }
        breadth = m.market_breadth(above_sma50)

        btc = b.assets[BENCHMARK_ASSET]
        assert btc.moving_averages is not None  # noqa: S101
        assert btc.rsi is not None  # noqa: S101
        assert btc.volatility is not None  # noqa: S101
        altcoin_rs = [
            ab.relative_strength
            for asset, ab in b.assets.items()
            if asset != BENCHMARK_ASSET and ab.relative_strength is not None
        ]
        score = sc.compute_score(
            as_of=as_of,
            calculated_at=calculated_at,
            price_trend=btc.moving_averages,
            momentum=btc.rsi,
            breadth=breadth,
            altcoin_relative_strength=altcoin_rs,
            volatility_regime=btc.volatility,
        )

        return {
            "as_of": as_of.isoformat(),
            "knowledge_time": knowledge_time.isoformat(),
            "evidence_note": EVIDENCE_NOTE,
            "score": self._score(score),
            "assets": {asset: self._asset(ab) for asset, ab in b.assets.items()},
            "market_breadth": self._breadth(breadth),
        }

    # ------------------------------------------------------------------ sections

    @staticmethod
    def _score(s: sc.ScoreResult) -> dict[str, Any]:
        return {
            "score_id": sc.SCORE_ID,
            "version": s.parameter_version,
            "calculated_at": _iso(s.calculated_at),
            "evidence_category": "Calculated Metric",
            "status": s.status,
            "score": num(s.score),
            "band": s.band,
            "semantic_note": sc.SEMANTIC_NOTE,
            "available_weight": num(s.available_weight),
            "reason": s.reason,
            "components": [
                {
                    "component_id": c.definition.component_id,
                    "label": c.definition.label,
                    "weight": num(c.definition.weight),
                    "scale": num(c.definition.scale),
                    "unit": c.definition.unit,
                    "definition": c.definition.definition,
                    "evidence": c.definition.evidence,
                    "direction_note": c.definition.direction_note,
                    "status": c.status,
                    "reason": c.reason,
                    "value": num(c.value),
                    "sub_score": num(c.sub_score),
                    "effective_weight": num(c.effective_weight),
                    "contribution": num(c.contribution),
                    "calculation": c.calculation,
                }
                for c in s.components
            ],
        }

    @staticmethod
    def _asset(ab: _AssetBundle) -> dict[str, Any]:
        ma, tr, rsi, atr, vol, vt, vwap, rs = (
            ab.moving_averages,
            ab.trend,
            ab.rsi,
            ab.atr,
            ab.volatility,
            ab.volume_trend,
            ab.vwap,
            ab.relative_strength,
        )
        return {
            "moving_averages": None
            if ma is None
            else {
                "status": ma.status,
                "reason": ma.reason,
                "close": num(ma.close),
                "sma20": num(ma.sma20),
                "sma50": num(ma.sma50),
                "sma200": num(ma.sma200),
                "time": _iso(ma.time),
            },
            "trend": None
            if tr is None
            else {
                "status": tr.status,
                "reason": tr.reason,
                "close": num(tr.close),
                "sma50": num(tr.sma50),
                "sma200": num(tr.sma200),
                "condition": tr.condition,
                "time": _iso(tr.time),
                "calculation": "uptrend: close > SMA50 > SMA200; downtrend: "
                "close < SMA50 < SMA200; mixed otherwise",
            },
            "rsi": None
            if rsi is None
            else {
                "status": rsi.status,
                "reason": rsi.reason,
                "value": num(rsi.value),
                "condition": rsi.condition,
                "time": _iso(rsi.time),
            },
            "atr": None
            if atr is None
            else {
                "status": atr.status,
                "reason": atr.reason,
                "atr_pct": num(atr.atr_pct),
                "percentile": num(atr.percentile),
                "window_readings": atr.window_readings,
                "condition": atr.condition,
                "time": _iso(atr.time),
            },
            "volatility": None
            if vol is None
            else {
                "status": vol.status,
                "reason": vol.reason,
                "annualized_pct": num(vol.annualized_pct),
                "percentile": num(vol.percentile),
                "window_readings": vol.window_readings,
                "condition": vol.condition,
                "time": _iso(vol.time),
            },
            "volume_trend": None
            if vt is None
            else {
                "status": vt.status,
                "reason": vt.reason,
                "current_volume": num(vt.current_volume),
                "average_volume": num(vt.average_volume),
                "ratio": num(vt.ratio),
                "condition": vt.condition,
                "time": _iso(vt.time),
            },
            "vwap": None
            if vwap is None
            else {
                "status": vwap.status,
                "reason": vwap.reason,
                "vwap": num(vwap.vwap),
                "close": num(vwap.close),
                "position": vwap.position,
                "window_days": vwap.window_days,
                "time": _iso(vwap.time),
                "note": "Rolling-window approximation, not a session-anchored intraday VWAP.",
            },
            "support_resistance": {
                str(lookback): {
                    "status": r.status,
                    "reason": r.reason,
                    "lookback_days": r.lookback_days,
                    "support": num(r.support),
                    "resistance": num(r.resistance),
                    "close": num(r.close),
                    "time": _iso(r.time),
                }
                for lookback, r in ab.support_resistance.items()
            },
            "relative_strength_vs_benchmark": None
            if rs is None
            else {
                "status": rs.status,
                "reason": rs.reason,
                "asset_return_pct": num(rs.asset_return_pct),
                "benchmark_return_pct": num(rs.benchmark_return_pct),
                "spread_pp": num(rs.spread_pp),
                "condition": rs.condition,
                "window_days": rs.window_days,
                "time": _iso(rs.time),
            },
        }

    @staticmethod
    def _breadth(r: m.BreadthReading) -> dict[str, Any]:
        return {
            "status": r.status,
            "reason": r.reason,
            "advancing": r.advancing,
            "total": r.total,
            "fraction": num(r.fraction),
            "condition": r.condition,
            "universe": list(r.universe),
            "note": "Proxy limited to the four assets this platform tracks (BTC, ETH, SOL, XRP), "
            "never full-market breadth.",
        }

    @staticmethod
    def _total_family(r: m.TotalCapFamilyReading) -> dict[str, Any]:
        return {
            "status": r.status,
            "reason": r.reason,
            "total_usd": num(r.total_usd),
            "total2_usd": num(r.total2_usd),
            "total3_usd": num(r.total3_usd),
            "btc_dominance_pct": num(r.btc_dominance_pct),
            "eth_dominance_pct": num(r.eth_dominance_pct),
            "alt_dominance_pct": num(r.alt_dominance_pct),
            "time": _iso(r.time),
            "calculation": "BTC/ETH dominance = asset market cap / TOTAL x 100. TOTAL2 = TOTAL - "
            "BTC market cap. TOTAL3 = TOTAL2 - ETH market cap.",
        }

    @staticmethod
    def _eth_btc(r: m.EthBtcReading) -> dict[str, Any]:
        return {
            "status": r.status,
            "reason": r.reason,
            "ratio": num(r.ratio),
            "change_pct": num(r.change_pct),
            "condition": r.condition,
            "window_days": r.window_days,
            "time": _iso(r.time),
        }

    async def _quality(self, b: _Bundle) -> dict[str, Any]:
        sources = []
        for asset, ab in b.assets.items():
            instrument = VENUE.instruments[asset]
            latest = ab.bars[-1].time if ab.bars else None
            job = await self.queries.last_job(OHLCV_DATASET_ID, VENUE.provider_id, asset)
            fresh = freshness(latest, timedelta(hours=50), b.as_of)
            sources.append(
                {
                    "asset": asset,
                    "dataset_id": OHLCV_DATASET_ID,
                    "instrument_id": instrument,
                    "provider_id": VENUE.provider_id,
                    "provider_name": VENUE.display_name,
                    "bars_loaded": len(ab.bars),
                    "latest_bar_time": _iso(latest),
                    "freshness": fresh.status,
                    "freshness_limit_seconds": fresh.limit_seconds,
                    "last_run": None
                    if job is None
                    else {
                        "status": job["status"],
                        "started_at": _iso(job["started_at"]),
                        "error_code": job["error_code"],
                        "error_detail": job["error_detail"],
                    },
                }
            )
        for item in SOURCES:
            rows = b.total_cap_rows
            valued = [r for r in rows if r["value"] is not None]
            latest = max((r["event_time"] for r in valued), default=None)
            job = await self.queries.last_job(
                item.dataset.dataset_id, item.provider_id, GLOBAL_SUBJECT
            )
            fresh = freshness(latest, item.dataset.freshness_limit, b.as_of)
            sources.append(
                {
                    "provider_id": item.provider_id,
                    "provider_name": ADAPTERS[item.provider_id].capabilities.display_name,
                    "dataset_id": item.dataset.dataset_id,
                    "subject": item.subject,
                    "enabled": item.provider_id in self.enabled_providers,
                    "latest_event_time": _iso(latest),
                    "freshness": fresh.status,
                    "freshness_limit_seconds": fresh.limit_seconds,
                    "flagged_points": sum(r["quality_status"] in FLAGGED for r in rows),
                    "missing_points": sum(r["quality_status"] == "missing" for r in rows),
                    "last_run": None
                    if job is None
                    else {
                        "status": job["status"],
                        "started_at": _iso(job["started_at"]),
                        "error_code": job["error_code"],
                        "error_detail": job["error_detail"],
                    },
                }
            )
        return {
            "sources": sources,
            "note": f"Daily bars loaded for the last {LOAD_SPAN.days} days from "
            f"{VENUE.display_name} (Phase 5's priority-10 default venue), so all four tracked "
            "assets are compared on the same venue and timeframe. TOTAL market-cap points loaded "
            f"for the same {LOAD_SPAN.days}-day window; flagged = suspect or conflicting.",
        }

    # ------------------------------------------------------------------ history

    async def history(
        self, *, series: str, days: int, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        if series != "total_market_cap":
            raise NotFoundError(
                f"No market-structure history series named {series!r} "
                "(known: total_market_cap; per-asset OHLCV bars are served by "
                "/api/v1/market/bars)."
            )
        days = max(1, min(days, 365 * 3))
        start, end = as_of - timedelta(days=days), as_of + timedelta(seconds=1)
        rows = await self.queries.observations(
            TOTAL_MARKET_CAP_USD.dataset_id,
            subject=GLOBAL_SUBJECT,
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        return {
            "series": series,
            "as_of": as_of.isoformat(),
            "start": start.isoformat(),
            "days": days,
            "unit": TOTAL_MARKET_CAP_USD.unit,
            "points": [
                {
                    "time": r["event_time"].isoformat(),
                    "value": num(r["value"]),
                    "quality_status": r["quality_status"],
                }
                for r in rows
            ],
        }
