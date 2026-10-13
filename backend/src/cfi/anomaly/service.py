"""Market Anomaly Engine read service (Phase 19).

Evidence categories (R2): every underlying series is Observed Data or a Calculated Metric already
published by its own domain module (institutional/whales/derivatives/liquidity/retail/market/
market_structure — read through ``cfi.divergence.adapters.Adapters``, unchanged); the current
reading, percentile rank, band, magnitude and duration computed here are Calculated Metrics /
Statistical Signals (L2/L3). ``possible_interpretations`` is a fixed, versioned, non-AI-generated
registry of hedged candidate readings (still L3 territory) — never an L5 AI Interpretation, and
never labelled bullish or bearish (Phase 19's explicit instruction; Phase 20's Claude AI Analyst is
the only future place an L5 interpretation belongs, R2/R6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from cfi.anomaly import metrics as m
from cfi.anomaly.universe import (
    ANOMALY_BANDS_V1,
    DEFAULT_ASSET,
    LOAD_SPAN_DAYS,
    MAX_DURATION_LOOKBACK_DAYS,
    METRICS_BY_ID,
    MIN_PERCENTILE_SAMPLE,
    NOT_TRACKED,
    AnomalyMetricDef,
    Band,
)
from cfi.core.errors import NotFoundError
from cfi.divergence.adapters import Adapters
from cfi.divergence.metrics import Series
from cfi.liquidity.universe import TOTAL_SUBJECT

EVIDENCE_NOTE = (
    "Every series read here is Observed Data or a Calculated Metric already published by its own "
    "domain module. The current reading, historical percentile, band, magnitude and duration are "
    "Calculated Metrics / Statistical Signals (L2/L3). 'possible_interpretations' is a fixed, "
    "versioned registry of hedged candidate readings, not an AI-generated explanation — nothing "
    "here labels an anomaly bullish or bearish, forecasts a price, or gives an automatic trading "
    "recommendation."
)


def num(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


@dataclass
class AnomalyService:
    engine: Any
    _cache: dict[tuple[str, str | None], Series] = field(default_factory=dict, init=False)
    # Readings reused within ONE ``scan`` call (keyed by every argument of ``_reading``); ``None``
    # outside ``scan``, so ``detail`` and every other caller always recompute.
    _scan_memo: (
        dict[
            tuple[str, str, datetime, datetime],
            tuple[AnomalyMetricDef, m.CurrentReading, m.DurationResult, m.QualitySummary],
        ]
        | None
    ) = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.adapters = Adapters(self.engine)

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> dict[str, Any]:
        return {
            "metrics": [
                {
                    "metric_id": d.metric_id,
                    "category": d.category,
                    "label": d.label,
                    "unit": d.unit,
                    "source": d.source,
                    "asset_specific": d.asset_specific,
                    "evidence_class": d.evidence_class,
                    "proxy_caveat": d.proxy_caveat,
                    "counterparts": list(d.counterparts),
                }
                for d in METRICS_BY_ID.values()
            ],
            "bands": {
                "version": ANOMALY_BANDS_V1.version,
                "extreme_high": num(ANOMALY_BANDS_V1.extreme_high),
                "notable_high": num(ANOMALY_BANDS_V1.notable_high),
                "notable_low": num(ANOMALY_BANDS_V1.notable_low),
                "extreme_low": num(ANOMALY_BANDS_V1.extreme_low),
                "description": ANOMALY_BANDS_V1.description,
            },
            "parameters": {
                "load_span_days": LOAD_SPAN_DAYS,
                "min_percentile_sample": MIN_PERCENTILE_SAMPLE,
                "max_duration_lookback_days": MAX_DURATION_LOOKBACK_DAYS,
                "magnitude_method": m.MAGNITUDE_METHOD,
            },
            "evidence_note": EVIDENCE_NOTE,
            "not_tracked": list(NOT_TRACKED),
        }

    # ------------------------------------------------------------------ series fetch (cached)

    async def _series(
        self, metric_def: AnomalyMetricDef, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> Series:
        key = (metric_def.metric_id, asset if metric_def.asset_specific else None)
        if key in self._cache:
            return self._cache[key]
        adapter = getattr(self.adapters, metric_def.adapter)
        if metric_def.adapter in ("daily_volume", "realized_volatility"):
            series: Series = await adapter(asset, as_of)
        elif metric_def.adapter == "stablecoin_supply":
            # aggregate (TOTAL) tracked stablecoin supply — not asset-specific in this registry
            series = await adapter(TOTAL_SUBJECT, as_of, knowledge_time)
        elif metric_def.asset_specific:
            series = await adapter(asset, as_of, knowledge_time)
        else:
            series = await adapter(as_of, knowledge_time)
        self._cache[key] = series
        return series

    # ------------------------------------------------------------------ single metric

    async def _reading(
        self, metric_id: str, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> tuple[AnomalyMetricDef, m.CurrentReading, m.DurationResult, m.QualitySummary]:
        memo = self._scan_memo
        if memo is None:
            return await self._compute_reading(metric_id, asset, as_of, knowledge_time)
        key = (metric_id, asset, as_of, knowledge_time)
        cached = memo.get(key)
        if cached is None:
            cached = await self._compute_reading(metric_id, asset, as_of, knowledge_time)
            memo[key] = cached
        # Frozen readings: sharing the same objects between a metric's own entry and every
        # counterpart reference to it is safe.
        return cached

    async def _compute_reading(
        self, metric_id: str, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> tuple[AnomalyMetricDef, m.CurrentReading, m.DurationResult, m.QualitySummary]:
        try:
            metric_def = METRICS_BY_ID[metric_id]
        except KeyError:
            raise NotFoundError(f"Unknown anomaly metric '{metric_id}'.") from None
        series = await self._series(metric_def, asset, as_of, knowledge_time)
        reading = m.current_reading(series, as_of)
        dur = m.duration(series, as_of, lookback_days=LOAD_SPAN_DAYS)
        quality = m.quality_summary(series, as_of, LOAD_SPAN_DAYS)
        return metric_def, reading, dur, quality

    def _serialize(
        self,
        metric_def: AnomalyMetricDef,
        asset: str,
        as_of: datetime,
        knowledge_time: datetime,
        reading: m.CurrentReading,
        dur: m.DurationResult,
        quality: m.QualitySummary,
        contradicting: list[dict[str, Any]],
    ) -> dict[str, Any]:
        pr = reading.percentile
        return {
            "metric_id": metric_def.metric_id,
            "category": metric_def.category,
            "label": metric_def.label,
            "asset": asset if metric_def.asset_specific else None,
            "unit": metric_def.unit,
            "source": metric_def.source,
            "evidence_class": metric_def.evidence_class,
            "proxy_caveat": metric_def.proxy_caveat,
            "as_of": _iso(as_of),
            "knowledge_time": _iso(knowledge_time),
            "timestamp": _iso(reading.time),
            "status": reading.status,
            "reason": reading.reason,
            "current_value": num(reading.value),
            "historical_percentile": {
                "status": pr.status if pr else "insufficient_data",
                "percentile": num(pr.percentile) if pr else None,
                "sample_size": pr.sample_size if pr else 0,
            },
            "band": reading.band,
            "magnitude": {
                "value": num(reading.magnitude),
                "method": reading.magnitude_method,
            },
            "duration": {
                "days": dur.days,
                "capped": dur.capped,
                "since": _iso(dur.since),
            },
            "possible_interpretations": list(metric_def.interpretations.get(reading.band, ())),
            "contradicting_evidence": contradicting,
            "data_quality": {
                "status": quality.status,
                "points_considered": quality.points_considered,
                "flagged_points": quality.flagged_points,
            },
        }

    async def detail(
        self,
        *,
        metric_id: str,
        asset: str | None,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        resolved_asset = asset or DEFAULT_ASSET
        metric_def, reading, dur, quality = await self._reading(
            metric_id, resolved_asset, as_of, knowledge_time
        )
        contradicting = await self._contradicting_evidence(
            metric_def, reading.band, resolved_asset, as_of, knowledge_time
        )
        return self._serialize(
            metric_def, resolved_asset, as_of, knowledge_time, reading, dur, quality, contradicting
        )

    async def _contradicting_evidence(
        self,
        metric_def: AnomalyMetricDef,
        band: Band,
        asset: str,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for counterpart_id in metric_def.counterparts:
            counterpart_def, counterpart_reading, _, _ = await self._reading(
                counterpart_id, asset, as_of, knowledge_time
            )
            comparison = m.compare_bands(band, counterpart_reading.band)
            out.append(
                {
                    "metric_id": counterpart_def.metric_id,
                    "label": counterpart_def.label,
                    "band": counterpart_reading.band,
                    "comparison": comparison,
                }
            )
        return out

    # ------------------------------------------------------------------ full scan (13 categories)

    async def scan(
        self,
        *,
        asset: str | None,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        # A metric's reading is also needed as the counterpart of other metrics; compute each
        # reading once per scan and discard it when the call ends (normally or by exception).
        self._scan_memo = {}
        try:
            return await self._scan(asset=asset, as_of=as_of, knowledge_time=knowledge_time)
        finally:
            self._scan_memo = None

    async def _scan(
        self,
        *,
        asset: str | None,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        resolved_asset = asset or DEFAULT_ASSET
        anomalies: list[dict[str, Any]] = []
        for metric_def in METRICS_BY_ID.values():
            _, reading, dur, quality = await self._reading(
                metric_def.metric_id, resolved_asset, as_of, knowledge_time
            )
            contradicting = await self._contradicting_evidence(
                metric_def, reading.band, resolved_asset, as_of, knowledge_time
            )
            anomalies.append(
                self._serialize(
                    metric_def,
                    resolved_asset,
                    as_of,
                    knowledge_time,
                    reading,
                    dur,
                    quality,
                    contradicting,
                )
            )
        return {
            "asset": resolved_asset,
            "as_of": _iso(as_of),
            "knowledge_time": _iso(knowledge_time),
            "bands_version": ANOMALY_BANDS_V1.version,
            "anomalies": anomalies,
            "evidence_note": EVIDENCE_NOTE,
            "not_tracked": list(NOT_TRACKED),
        }
