"""Retail activity intelligence read service (Phase 10): derivatives-positioning proxy, meme-coin
trending proxy, small-transaction proxy, historical percentiles (L3), retail sentiment, and the
two scores (Retail Activity Score, Retail Speculation Score) — all point-in-time.

Evidence categories (R2): stored observations are **Observed Data**; every growth/percentile/
proxy figure is a **Calculated Metric** or **Statistical Signal** with its formula and parameters
published; the two scores are **Calculated Metrics** built from them. Nothing here is a signal,
forecast or recommendation. **Every metric is a RETAIL PROXY — see ``retail/universe.py`` and
``retail/metrics.py`` for why nothing here is DIRECT RETAIL DATA.**
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.errors import NotFoundError
from cfi.core.time import utc_now
from cfi.derivatives.universe import FUNDING_RATE, LONG_SHORT_RATIO, PERP_ASSETS
from cfi.market.service import freshness
from cfi.retail import metrics as m
from cfi.retail import score as sc
from cfi.retail.queries import RetailQueries
from cfi.retail.sources import ADAPTERS, ATTRIBUTION, SOURCES
from cfi.retail.universe import (
    MEME_COIN_SYMBOLS,
    NOT_TRACKED,
    SMALL_OUTPUT_COUNT,
    SMALL_OUTPUT_MAX_USD,
    all_datasets,
)

# Trailing window loaded for percentile history. A judgment parameter (not fitted): long enough
# for the minimum percentile sample (20) to be reachable at every cadence tracked here (daily,
# hourly, every-3h) well before 180 days of running history exist.
LOAD_SPAN = timedelta(days=180)
FLAGGED = ("suspect", "conflicting")
EVIDENCE_NOTE = (
    "Stored observations are observed data; growth, percentile rank, and the two Retail scores "
    "are calculated metrics / statistical signals with published formulas and parameters. "
    "EVERY metric here is a RETAIL PROXY (never data identified by its source as retail-only) — "
    "see 'measurement_class' on every metric and 'not_tracked' for sources not integrated."
)


def num(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _points(rows: Sequence[dict[str, Any]]) -> list[m.Point]:
    return [m.Point(r["event_time"], r["value"], r["quality_status"]) for r in rows]


def _snapshots(rows: Sequence[dict[str, Any]]) -> list[m.TrendingSnapshot]:
    """Group trending rows (one per asset per poll) into one snapshot per distinct poll time."""
    by_time: dict[datetime, dict[str, int]] = {}
    for r in rows:
        if r["value"] is None:
            continue
        by_time.setdefault(r["event_time"], {})[r["asset"]] = int(r["value"])
    return [m.TrendingSnapshot(t, ranks) for t, ranks in sorted(by_time.items())]


@dataclass
class _Bundle:
    as_of: datetime
    knowledge_time: datetime
    small_tx_rows: list[dict[str, Any]] = field(default_factory=list)
    small_tx_points: list[m.Point] = field(default_factory=list)
    trending_snapshots: list[m.TrendingSnapshot] = field(default_factory=list)
    funding_by_asset: dict[str, list[m.Point]] = field(default_factory=dict)
    ratio_by_asset: dict[str, list[m.Point]] = field(default_factory=dict)


@dataclass
class RetailService:
    queries: RetailQueries
    enabled_providers: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers

    async def _load(self, as_of: datetime, knowledge_time: datetime) -> _Bundle:
        b = _Bundle(as_of, knowledge_time)
        start, end = as_of - LOAD_SPAN, as_of + timedelta(seconds=1)

        small_tx_rows = await self.queries.observations(
            SMALL_OUTPUT_COUNT.dataset_id,
            subject="BTC",
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        b.small_tx_rows = small_tx_rows
        b.small_tx_points = _points(small_tx_rows)

        trending_rows = await self.queries.trending_observations(
            start=start, end=end, as_of=as_of, knowledge_time=knowledge_time
        )
        b.trending_snapshots = _snapshots(trending_rows)

        for asset in PERP_ASSETS:
            funding_rows = await self.queries.derivatives_observations(
                FUNDING_RATE.dataset_id,
                asset=asset,
                start=start,
                end=end,
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
            ratio_rows = await self.queries.derivatives_observations(
                LONG_SHORT_RATIO.dataset_id,
                asset=asset,
                start=start,
                end=end,
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
            b.funding_by_asset[asset] = _points(funding_rows)
            b.ratio_by_asset[asset] = _points(ratio_rows)
        return b

    @staticmethod
    def _turnover_history(b: _Bundle, span: timedelta, before: datetime) -> list[Decimal]:
        """|account ratio - 1| computed the same way as 'now', at every historical poll time
        seen across the tracked perps, within [before - span, before)."""
        candidate_times = sorted(
            {p.time for pts in b.ratio_by_asset.values() for p in pts if p.time < before}
        )
        history: list[Decimal] = []
        cutoff = before - span
        for t in candidate_times:
            if t < cutoff:
                continue
            proxy = m.derivatives_proxy(b.funding_by_asset, b.ratio_by_asset, t)
            if proxy.status == "ok" and proxy.account_ratio_avg is not None:
                history.append(abs(proxy.account_ratio_avg - 1))
        return history

    @staticmethod
    def _meme_history(
        snapshots: Sequence[m.TrendingSnapshot], span: timedelta, before: datetime
    ) -> list[Decimal]:
        cutoff = before - span
        return [
            Decimal(m.meme_coin_activity(s, MEME_COIN_SYMBOLS).meme_coins_trending_count)
            for s in snapshots
            if cutoff <= s.time < before
        ]

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> dict[str, Any]:
        return {
            "meme_coin_symbols": list(MEME_COIN_SYMBOLS),
            "small_output_max_usd": num(SMALL_OUTPUT_MAX_USD),
            "measurement_class_note": (
                "Every metric this platform computes for Phase 10 has measurement_class = "
                "'proxy'. No source found publishes data identified by itself as retail-only "
                "(see 'not_tracked' and each metric's evidence text)."
            ),
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
            "reused_derivatives_datasets": [
                {
                    "dataset_id": FUNDING_RATE.dataset_id,
                    "description": FUNDING_RATE.description,
                    "owning_module": "derivatives (Phase 8) — read here, not re-ingested",
                },
                {
                    "dataset_id": LONG_SHORT_RATIO.dataset_id,
                    "description": LONG_SHORT_RATIO.description,
                    "owning_module": "derivatives (Phase 8) — read here, not re-ingested; only "
                    "Binance's venue is used (see retail/queries.py)",
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
            "activity_score": {
                "score_id": sc.ACTIVITY_SCORE_ID,
                "version": sc.ACTIVITY_SCORE_VERSION,
                "semantic_note": sc.ACTIVITY_SEMANTIC_NOTE,
            },
            "speculation_score": {
                "score_id": sc.SPECULATION_SCORE_ID,
                "version": sc.SPECULATION_SCORE_VERSION,
                "semantic_note": sc.SPECULATION_SEMANTIC_NOTE,
            },
            "not_tracked": list(NOT_TRACKED),
            "evidence_note": EVIDENCE_NOTE,
        }

    # ------------------------------------------------------------------ overview

    async def overview(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        b = await self._load(as_of, knowledge_time)
        calculated_at = utc_now()

        derivatives = m.derivatives_proxy(b.funding_by_asset, b.ratio_by_asset, as_of)
        latest_snapshot = max(
            (s for s in b.trending_snapshots if s.time <= as_of), key=lambda s: s.time, default=None
        )
        meme_activity = m.meme_coin_activity(latest_snapshot, MEME_COIN_SYMBOLS)
        small_tx = m.small_transaction_activity(b.small_tx_points, as_of)

        small_tx_history = m.trailing_values(b.small_tx_points, as_of, LOAD_SPAN)
        small_tx_current = None if small_tx.latest_count is None else small_tx.latest_count.value
        small_tx_pct = (
            m.percentile_rank(small_tx_history[:-1] if small_tx_history else [], small_tx_current)
            if small_tx_current is not None
            else m.PercentileResult("insufficient_history", "no current small-tx count available")
        )

        meme_history = self._meme_history(b.trending_snapshots, LOAD_SPAN, as_of)
        meme_current = (
            Decimal(meme_activity.meme_coins_trending_count)
            if meme_activity.status == "ok"
            else None
        )
        meme_pct = (
            m.percentile_rank(meme_history, meme_current)
            if meme_current is not None
            else m.PercentileResult(
                "insufficient_history", "no current trending snapshot available"
            )
        )

        turnover_history = self._turnover_history(b, LOAD_SPAN, as_of)
        turnover_current = (
            abs(derivatives.account_ratio_avg - 1)
            if derivatives.account_ratio_avg is not None
            else None
        )
        turnover_pct = (
            m.percentile_rank(turnover_history, turnover_current)
            if turnover_current is not None
            else m.PercentileResult(
                "insufficient_history", "no current account-ratio reading available"
            )
        )

        activity_score = sc.compute_activity_score(
            as_of=as_of,
            calculated_at=calculated_at,
            small_tx_percentile=small_tx_pct,
            meme_trending_percentile=meme_pct,
            derivatives_turnover_percentile=turnover_pct,
        )
        speculation_score = sc.compute_speculation_score(
            as_of=as_of,
            calculated_at=calculated_at,
            derivatives=derivatives,
            meme_activity=meme_activity,
        )
        sentiment = self._sentiment(derivatives)

        return {
            "as_of": as_of.isoformat(),
            "knowledge_time": knowledge_time.isoformat(),
            "evidence_note": EVIDENCE_NOTE,
            "activity_score": self._score(activity_score, sc.ACTIVITY_SEMANTIC_NOTE),
            "speculation_score": self._score(speculation_score, sc.SPECULATION_SEMANTIC_NOTE),
            "sentiment": sentiment,
            "derivatives_proxy": self._derivatives(derivatives),
            "meme_coin_activity": self._meme(meme_activity),
            "small_transaction_activity": self._small_tx(small_tx),
            "percentiles": {
                "small_tx": self._percentile(small_tx_pct),
                "meme_trending": self._percentile(meme_pct),
                "derivatives_turnover": self._percentile(turnover_pct),
            },
            "data_quality": await self._quality(b),
            "not_tracked": list(NOT_TRACKED),
        }

    # ------------------------------------------------------------------ sentiment

    @staticmethod
    def _sentiment(derivatives: m.DerivativesProxy) -> dict[str, Any]:
        """A deterministic rule (Calculated Metric, not AI interpretation) over the two
        directional derivatives-proxy readings: do funding-rate bias and account-ratio skew
        agree, disagree, or is one/both unavailable."""
        if derivatives.status != "ok":
            return {
                "status": "unavailable",
                "label": "unknown",
                "reason": derivatives.reason,
                "measurement_class": "proxy",
            }
        f, r = derivatives.funding_condition, derivatives.ratio_condition
        if f == "unknown" or r == "unknown":
            label, reason = "unknown", "one of the two directional readings is unavailable"
        elif f == "long_biased" and r == "long_skewed":
            label, reason = "aligned_long_bias", "funding and account-ratio both lean long"
        elif f == "short_biased" and r == "short_skewed":
            label, reason = "aligned_short_bias", "funding and account-ratio both lean short"
        elif {f, r} & {"long_biased", "long_skewed"} and {f, r} & {"short_biased", "short_skewed"}:
            label, reason = "divergent", "funding and account-ratio point in different directions"
        else:
            label, reason = "neutral", "neither reading is biased past its threshold"
        return {
            "status": "ok",
            "label": label,
            "reason": reason,
            "funding_condition": f,
            "ratio_condition": r,
            "measurement_class": "proxy",
        }

    # ------------------------------------------------------------------ sections

    @staticmethod
    def _score(s: sc.ScoreResult, semantic_note: str) -> dict[str, Any]:
        return {
            "score_id": s.score_id,
            "version": s.parameter_version,
            "calculated_at": _iso(s.calculated_at),
            "evidence_category": "Calculated Metric",
            "status": s.status,
            "score": num(s.score),
            "band": s.band,
            "semantic_note": semantic_note,
            "available_weight": num(s.available_weight),
            "reason": s.reason,
            "components": [
                {
                    "component_id": c.definition.component_id,
                    "label": c.definition.label,
                    "weight": num(c.definition.weight),
                    "unit": c.definition.unit,
                    "definition": c.definition.definition,
                    "evidence": c.definition.evidence,
                    "directional": c.definition.directional,
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
    def _derivatives(d: m.DerivativesProxy) -> dict[str, Any]:
        return {
            "measurement_class": d.measurement_class,
            "status": d.status,
            "reason": d.reason,
            "assets_used": list(d.assets_used),
            "funding_rate_avg": num(d.funding_rate_avg),
            "account_ratio_avg": num(d.account_ratio_avg),
            "funding_condition": d.funding_condition,
            "ratio_condition": d.ratio_condition,
            "evidence": "Binance USDⓈ-M Futures funding rate + all-account long/short account "
            "ratio, averaged across BTC/ETH/SOL/XRP perpetuals — RETAIL PROXY, not "
            "retail-exclusive data.",
        }

    @staticmethod
    def _meme(a: m.MemeCoinActivity) -> dict[str, Any]:
        return {
            "measurement_class": a.measurement_class,
            "status": a.status,
            "reason": a.reason,
            "as_of_snapshot": _iso(a.as_of_snapshot),
            "trending_meme_coins": list(a.trending_meme_coins),
            "best_rank": dict(a.best_rank),
            "meme_coins_trending_count": a.meme_coins_trending_count,
            "tracked_symbols": list(MEME_COIN_SYMBOLS),
            "evidence": "CoinGecko /search/trending — RETAIL PROXY (search interest, not "
            "trading volume or holder count).",
        }

    @staticmethod
    def _small_tx(s: m.SmallTransactionActivity) -> dict[str, Any]:
        return {
            "measurement_class": s.measurement_class,
            "status": s.status,
            "reason": s.reason,
            "value": num(None if s.latest_count is None else s.latest_count.value),
            "time": _iso(None if s.latest_count is None else s.latest_count.time),
            "week_avg": num(s.week_avg),
            "change_vs_week_avg_pct": (
                None
                if s.change_vs_week_avg is None
                else num((s.change_vs_week_avg * 100).quantize(Decimal("0.01")))
            ),
            "threshold_usd": num(SMALL_OUTPUT_MAX_USD),
            "evidence": "Blockchair Bitcoin outputs under the threshold — RETAIL PROXY, NOT "
            "filtered for change outputs, exchange batching, or dust.",
        }

    @staticmethod
    def _percentile(p: m.PercentileResult) -> dict[str, Any]:
        return {
            "status": p.status,
            "reason": p.reason,
            "value": num(p.value),
            "percentile": num(p.percentile),
            "sample_size": p.sample_size,
            "evidence_category": "Statistical Signal",
            "method": "nearest-rank percentile of the platform's own recorded history",
        }

    async def _quality(self, b: _Bundle) -> dict[str, Any]:
        sources = []
        for item in SOURCES:
            rows = (
                b.small_tx_rows if item.dataset.dataset_id == SMALL_OUTPUT_COUNT.dataset_id else []
            )
            valued = [r for r in rows if r["value"] is not None]
            latest = max((r["event_time"] for r in valued), default=None)
            job = await self.queries.last_job(
                item.dataset.dataset_id, item.provider_id, item.subject
            )
            fresh = freshness(
                latest,
                item.dataset.freshness_limit + (item.dataset.period_length or timedelta(0)),
                b.as_of,
            )
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
            "note": f"Points loaded for the last {LOAD_SPAN.days} days. This platform also reads "
            "(does not re-ingest) two derivatives-module datasets — see 'reused_derivatives_"
            "datasets' in the catalog for their own freshness, tracked in the Derivatives phase's "
            "own data-quality section.",
        }

    # ------------------------------------------------------------------ history

    async def history(
        self, *, series: str, days: int, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        days = max(1, min(days, 365 * 3))
        start, end = as_of - timedelta(days=days), as_of + timedelta(seconds=1)
        if series == "small_transaction_count":
            rows = await self.queries.observations(
                SMALL_OUTPUT_COUNT.dataset_id,
                subject="BTC",
                start=start,
                end=end,
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
            points = [
                {
                    "time": r["event_time"].isoformat(),
                    "value": num(r["value"]),
                    "quality_status": r["quality_status"],
                }
                for r in rows
            ]
            unit = SMALL_OUTPUT_COUNT.unit
        elif series == "meme_trending_count":
            rows = await self.queries.trending_observations(
                start=start, end=end, as_of=as_of, knowledge_time=knowledge_time
            )
            snapshots = _snapshots(rows)
            points = [
                {
                    "time": s.time.isoformat(),
                    "value": str(
                        m.meme_coin_activity(s, MEME_COIN_SYMBOLS).meme_coins_trending_count
                    ),
                    "quality_status": "ok",
                }
                for s in snapshots
            ]
            unit = "count"
        else:
            raise NotFoundError(
                f"No retail history series named {series!r} "
                "(known: small_transaction_count, meme_trending_count)."
            )
        return {
            "series": series,
            "as_of": as_of.isoformat(),
            "start": start.isoformat(),
            "days": days,
            "unit": unit,
            "points": points,
        }
