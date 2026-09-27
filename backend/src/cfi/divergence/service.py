"""Capital Flow Divergence Engine read service (Phase 13).

Evidence categories (R2): every underlying series is Observed Data or a Calculated Metric already
published by its own domain module (institutional/whales/retail/liquidity/derivatives/macro/
market_structure/market); the window direction, magnitude and duration computed here are
Calculated Metrics; the historical percentile is a Statistical Signal (L3). The Capital Flow Map's
"inferred rotation" edges are explicitly labelled ``evidence_class: "inferred"`` hypotheses, never
observed fact (R1/R3/R5). Nothing here is a signal, forecast or automatic trading recommendation —
this phase's explicit instruction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from cfi.core.errors import NotFoundError
from cfi.divergence import metrics as m
from cfi.divergence.adapters import Adapters
from cfi.divergence.capital_flow_map import NODES, classify_edge
from cfi.divergence.comparisons import (
    COMPARISONS,
    ComparisonDef,
    is_divergent,
    quadrant_label,
    standard_matrix,
)
from cfi.divergence.universe import (
    LOAD_SPAN_DAYS,
    MAX_DURATION_LOOKBACK_DAYS,
    NOT_TRACKED,
    WINDOW_DAYS_DEFAULT,
    WINDOW_DAYS_MAX,
    WINDOW_DAYS_MIN,
)

EVIDENCE_NOTE = (
    "Every series compared here is Observed Data or a Calculated Metric already published by its "
    "own domain module. The window direction, magnitude and duration are Calculated Metrics; the "
    "historical percentile is a Statistical Signal. Nothing here is a signal, forecast or "
    "automatic trading recommendation — the system identifies divergence, it does not call it "
    "bullish or bearish."
)


def num(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


@dataclass
class DivergenceService:
    engine: Any
    _cache: dict[tuple[str, str | None], m.Series] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.adapters = Adapters(self.engine)

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> dict[str, Any]:
        return {
            "comparisons": [
                {
                    "comparison_id": c.comparison_id,
                    "number": c.number,
                    "title": c.title,
                    "metric_a": {
                        "label": c.leg_a.label,
                        "short_label": c.leg_a.short_label,
                        "unit": c.leg_a.unit,
                    },
                    "metric_b": {
                        "label": c.leg_b.label,
                        "short_label": c.leg_b.short_label,
                        "unit": c.leg_b.unit,
                    },
                    "asset_scope": c.asset_scope,
                    "allowed_assets": list(c.allowed_assets) if c.allowed_assets else None,
                    "notes": c.notes,
                }
                for c in sorted(COMPARISONS.values(), key=lambda c: c.number)
            ],
            "capital_flow_map_nodes": [
                {
                    "node_id": n.node_id,
                    "label": n.label,
                    "measurement_class": n.measurement_class,
                    "scope_note": n.scope_note,
                }
                for n in NODES
            ],
            "parameters": {
                "window_days_default": WINDOW_DAYS_DEFAULT,
                "window_days_min": WINDOW_DAYS_MIN,
                "window_days_max": WINDOW_DAYS_MAX,
                "load_span_days": LOAD_SPAN_DAYS,
                "max_duration_lookback_days": MAX_DURATION_LOOKBACK_DAYS,
            },
            "evidence_note": EVIDENCE_NOTE,
            "not_tracked": list(NOT_TRACKED),
        }

    # ------------------------------------------------------------------ fetch dispatch

    async def _fetch(
        self, key: str, asset: str | None, as_of: datetime, knowledge_time: datetime
    ) -> m.Series:
        cache_key = (key, asset)
        if cache_key in self._cache:
            return self._cache[cache_key]
        a = self.adapters
        if key == "institutional_net_flow":
            series = await a.institutional_net_flow(asset or "ALL", as_of, knowledge_time)
        elif key == "whale_net_flow":
            series = await a.whale_net_flow(asset or "ALL", as_of, knowledge_time)
        elif key == "retail_small_tx":
            series = await a.retail_small_tx_count(as_of, knowledge_time)
        elif key == "retail_meme_trending":
            series = await a.retail_meme_trending_count(as_of, knowledge_time)
        elif key == "price":
            series = await a.price_close(asset or "", as_of)
        elif key == "stablecoin_supply_total":
            series = await a.stablecoin_supply("TOTAL", as_of, knowledge_time)
        elif key == "stablecoin_supply_usdt":
            series = await a.stablecoin_supply("USDT", as_of, knowledge_time)
        elif key == "open_interest":
            series = await a.open_interest(asset or "", as_of, knowledge_time)
        elif key == "funding_rate":
            series = await a.funding_rate(asset or "", as_of, knowledge_time)
        elif key == "leverage_skew":
            series = await a.leverage_skew(asset or "", as_of, knowledge_time)
        elif key == "macro_net_liquidity":
            series = await a.macro_net_liquidity(as_of, knowledge_time)
        elif key == "total_market_cap":
            series = await a.total_market_cap(as_of, knowledge_time)
        else:
            raise KeyError(f"Unknown divergence fetch key {key!r}.")
        self._cache[cache_key] = series
        return series

    @staticmethod
    def _resolve_assets(c: ComparisonDef, asset: str | None) -> tuple[str | None, str | None]:
        a = asset or (c.allowed_assets[0] if c.allowed_assets else None)
        if c.asset_scope == "none":
            return None, None
        if c.asset_scope == "shared":
            return a, a
        if c.asset_scope == "leg_a_only":
            return a, None
        if c.asset_scope == "leg_b_only":
            return None, a
        raise AssertionError(f"unknown asset_scope {c.asset_scope!r}")

    # ------------------------------------------------------------------ pair

    async def pair(
        self,
        *,
        comparison_id: str,
        asset: str | None,
        window_days: int,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        try:
            c = COMPARISONS[comparison_id]
        except KeyError:
            raise NotFoundError(
                f"No divergence comparison named {comparison_id!r} "
                f"(known: {', '.join(sorted(COMPARISONS))})."
            ) from None
        if c.allowed_assets is not None and asset is not None and asset not in c.allowed_assets:
            raise NotFoundError(
                f"Comparison {comparison_id!r} does not track asset {asset!r} "
                f"(tracked: {', '.join(c.allowed_assets)})."
            )
        window_days = max(WINDOW_DAYS_MIN, min(window_days, WINDOW_DAYS_MAX))
        asset_a, asset_b = self._resolve_assets(c, asset)

        series_a = await self._fetch(c.leg_a.key, asset_a, as_of, knowledge_time)
        series_b = await self._fetch(c.leg_b.key, asset_b, as_of, knowledge_time)

        lookback = max(1, LOAD_SPAN_DAYS - window_days)
        roll_a = m.rolling_series(
            series_a, window_days=window_days, as_of=as_of, lookback_days=lookback
        )
        roll_b = m.rolling_series(
            series_b, window_days=window_days, as_of=as_of, lookback_days=lookback
        )

        reading_a = m.window_reading(series_a, as_of, window_days)
        reading_b = m.window_reading(series_b, as_of, window_days)
        magnitude_a, percentile_a = m.magnitude_and_percentile(roll_a)
        magnitude_b, percentile_b = m.magnitude_and_percentile(roll_b)
        quality_a = m.quality_summary(series_a, as_of, window_days)
        quality_b = m.quality_summary(series_b, as_of, window_days)
        dur = m.duration(roll_a.directions, roll_b.directions, roll_a.dates)
        episodes = m.historical_examples(roll_a, roll_b, dur.days)
        supporting, contradicting = m.evidence(
            reading_a=reading_a,
            reading_b=reading_b,
            percentile_a=percentile_a,
            percentile_b=percentile_b,
            dur=dur,
            quality_a=quality_a,
            quality_b=quality_b,
        )
        dir_a, dir_b = reading_a.direction, reading_b.direction
        quadrant = (
            None
            if "unavailable" in (dir_a, dir_b)
            else quadrant_label(c.leg_a.short_label, c.leg_b.short_label, dir_a, dir_b)
        )

        return {
            "comparison_id": c.comparison_id,
            "number": c.number,
            "title": c.title,
            "asset": asset_a or asset_b,
            "window_days": window_days,
            "as_of": _iso(as_of),
            "knowledge_time": _iso(knowledge_time),
            "matrix": standard_matrix(c.leg_a.short_label, c.leg_b.short_label),
            "observed_quadrant": quadrant,
            "is_divergent": None if "unavailable" in (dir_a, dir_b) else is_divergent(dir_a, dir_b),
            "metric_a": self._leg_result(c.leg_a, reading_a, magnitude_a, percentile_a, quality_a),
            "metric_b": self._leg_result(c.leg_b, reading_b, magnitude_b, percentile_b, quality_b),
            "duration": {
                "days": dur.days,
                "capped": dur.capped,
                "since": _iso(dur.since),
            },
            "historical_examples": [
                {
                    "start": _iso(e.start),
                    "end": _iso(e.end),
                    "days": e.days,
                    "peak_abs_delta_metric_a": num(e.peak_abs_delta_a),
                    "peak_percentile_metric_a": num(e.peak_percentile_a),
                }
                for e in episodes
            ],
            "supporting_evidence": supporting,
            "contradicting_evidence": contradicting,
            "notes": c.notes,
            "evidence_note": EVIDENCE_NOTE,
        }

    @staticmethod
    def _leg_result(
        leg: Any,
        reading: m.WindowReading,
        magnitude: Decimal | None,
        percentile: m.PercentileResult,
        quality: m.QualitySummary,
    ) -> dict[str, Any]:
        return {
            "label": leg.label,
            "unit": leg.unit,
            "status": reading.status,
            "reason": reading.reason,
            "direction": reading.direction,
            "first_time": _iso(reading.first_time),
            "first_value": num(reading.first_value),
            "last_time": _iso(reading.last_time),
            "last_value": num(reading.last_value),
            "delta": num(reading.delta),
            "change_pct": num(reading.change_pct),
            "magnitude": num(magnitude),
            "historical_percentile": {
                "status": percentile.status,
                "reason": percentile.reason,
                "percentile": num(percentile.percentile),
                "sample_size": percentile.sample_size,
            },
            "data_quality": {
                "status": quality.status,
                "points_in_window": quality.points_in_window,
                "flagged_points": quality.flagged_points,
            },
        }

    # ------------------------------------------------------------------ matrix (all 10 comparisons)

    async def matrix(
        self, *, window_days: int, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        self._cache.clear()
        results = []
        for c in sorted(COMPARISONS.values(), key=lambda c: c.number):
            asset = c.allowed_assets[0] if c.allowed_assets else None
            results.append(
                await self.pair(
                    comparison_id=c.comparison_id,
                    asset=asset,
                    window_days=window_days,
                    as_of=as_of,
                    knowledge_time=knowledge_time,
                )
            )
        return {
            "as_of": _iso(as_of),
            "knowledge_time": _iso(knowledge_time),
            "window_days": window_days,
            "comparisons": results,
            "evidence_note": EVIDENCE_NOTE,
            "not_tracked": list(NOT_TRACKED),
        }

    # ------------------------------------------------------------------ capital flow map

    async def capital_flow_map(
        self, *, window_days: int, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        self._cache.clear()
        window_days = max(WINDOW_DAYS_MIN, min(window_days, WINDOW_DAYS_MAX))
        observed: dict[str, dict[str, Any]] = {}
        directions: dict[str, str | None] = {}
        for node in NODES:
            if node.fetch_key is None:
                observed[node.node_id] = {
                    "label": node.label,
                    "measurement_class": "unavailable",
                    "status": "unavailable",
                    "reason": node.scope_note,
                }
                directions[node.node_id] = None
                continue
            series = await self._fetch(node.fetch_key, node.asset, as_of, knowledge_time)
            reading = m.window_reading(series, as_of, window_days)
            observed[node.node_id] = {
                "label": node.label,
                "measurement_class": node.measurement_class,
                "scope_note": node.scope_note,
                "status": reading.status,
                "reason": reading.reason,
                "direction": reading.direction,
                "delta": num(reading.delta),
                "change_pct": num(reading.change_pct),
                "last_time": _iso(reading.last_time),
                "last_value": num(reading.last_value),
            }
            directions[node.node_id] = reading.direction

        edges = []
        for i in range(len(NODES) - 1):
            a, b = NODES[i], NODES[i + 1]
            e = classify_edge(a, b, directions[a.node_id], directions[b.node_id])
            edges.append(
                {
                    "from": e.from_node,
                    "to": e.to_node,
                    "status": e.status,
                    "evidence_class": e.evidence_class,
                    "hypothesis": e.hypothesis,
                    "from_direction": e.from_direction,
                    "to_direction": e.to_direction,
                }
            )

        return {
            "as_of": _iso(as_of),
            "knowledge_time": _iso(knowledge_time),
            "window_days": window_days,
            "node_order": [n.node_id for n in NODES],
            "observed_flow": observed,
            "inferred_rotation": edges,
            "rotation_note": (
                "Each edge compares two adjacent nodes' own window direction only. A "
                "'possible_rotation' edge is a hedged hypothesis (evidence_class: 'inferred'), "
                "never a claim that money moved between assets — no on-chain or ETF-flow linkage "
                "between the two nodes is directly observed or asserted."
            ),
            "not_tracked": list(NOT_TRACKED),
            "evidence_note": EVIDENCE_NOTE,
        }
