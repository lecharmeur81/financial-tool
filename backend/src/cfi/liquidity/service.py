"""Liquidity / stablecoin read service (Phase 9): supply growth, market share, growth
acceleration, the (always unavailable) exchange liquidity change, and the Liquidity Score — all
point-in-time.

Evidence categories (R2): stored DefiLlama circulating-supply values are **Observed Data**; every
change, share and acceleration figure is a **Calculated Metric** with its formula and parameters;
the Liquidity Score is a **Calculated Metric** built from them. Nothing here is a signal, forecast
or recommendation, and no reading is labelled bullish or bearish.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.errors import NotFoundError
from cfi.core.time import utc_now
from cfi.liquidity import metrics as m
from cfi.liquidity import score as sc
from cfi.liquidity.queries import LiquidityQueries
from cfi.liquidity.sources import ADAPTERS, ATTRIBUTION, SOURCES
from cfi.liquidity.universe import (
    NOT_TRACKED,
    STABLECOINS,
    SUBJECTS,
    SUPPLY,
    TOTAL_SUBJECT,
    all_datasets,
)
from cfi.market.service import freshness

# 30-day growth plus the two 7-day windows acceleration compares, plus tolerance for a missed day.
LOAD_SPAN = timedelta(days=46)
FLAGGED = ("suspect", "conflicting")
EVIDENCE_NOTE = (
    "Stored circulating-supply values are observed data; growth, market share, acceleration and "
    "the Liquidity Score are calculated metrics with published formulas and parameters. Rising "
    "stablecoin supply describes more fiat-equivalent liquidity existing in the tracked pool — "
    "it is not labelled bullish or bearish, and nothing here is a recommendation."
)


def num(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def pct(value: Decimal | None, places: str = "0.0001") -> str | None:
    return None if value is None else format((value * 100).quantize(Decimal(places)), "f")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _points(rows: Sequence[dict[str, Any]]) -> list[m.Point]:
    return [m.Point(r["event_time"], r["value"], r["quality_status"]) for r in rows]


@dataclass
class _Bundle:
    """Everything read for every subject at one point in time."""

    as_of: datetime
    knowledge_time: datetime
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    points: dict[str, list[m.Point]] = field(default_factory=dict)


@dataclass
class LiquidityService:
    queries: LiquidityQueries
    enabled_providers: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers

    async def _load(self, as_of: datetime, knowledge_time: datetime) -> _Bundle:
        b = _Bundle(as_of, knowledge_time)
        start, end = as_of - LOAD_SPAN, as_of + timedelta(seconds=1)
        for subject in SUBJECTS:
            rows = await self.queries.observations(
                SUPPLY.dataset_id,
                subject=subject,
                start=start,
                end=end,
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
            b.rows[subject] = rows
            b.points[subject] = _points(rows)
        return b

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> dict[str, Any]:
        return {
            "subjects": list(SUBJECTS),
            "stablecoins": dict(STABLECOINS),
            "total_subject": TOTAL_SUBJECT,
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
                    "history_days": s.history_days,
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
        growth = {
            subject: m.supply_growth(subject, b.points[subject], as_of) for subject in SUBJECTS
        }
        shares = {
            symbol: m.market_share(symbol, b.points[symbol], b.points[TOTAL_SUBJECT], as_of)
            for symbol in STABLECOINS
        }
        acceleration = m.growth_acceleration(b.points[TOTAL_SUBJECT], as_of)
        exchange_liquidity = m.exchange_liquidity_change()
        calculated_at = utc_now()
        score = sc.compute_score(
            as_of=as_of,
            calculated_at=calculated_at,
            usdt_growth=growth["USDT"],
            usdc_growth=growth["USDC"],
            total_growth=growth[TOTAL_SUBJECT],
            total_acceleration=acceleration,
        )
        return {
            "as_of": as_of.isoformat(),
            "knowledge_time": knowledge_time.isoformat(),
            "evidence_note": EVIDENCE_NOTE,
            "score": self._score(score),
            "supply": {subject: self._growth(g) for subject, g in growth.items()},
            "market_share": {symbol: self._share(s) for symbol, s in shares.items()},
            "growth_acceleration": self._acceleration(acceleration),
            "exchange_liquidity_change": self._exchange_liquidity(exchange_liquidity),
            "data_quality": await self._quality(b),
            "not_tracked": list(NOT_TRACKED),
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
    def _growth(g: m.SupplyGrowth) -> dict[str, Any]:
        return {
            "subject": g.subject,
            "status": g.status,
            "reason": g.reason,
            "value": num(None if g.now is None else g.now.value),
            "time": _iso(None if g.now is None else g.now.time),
            "change_24h_pct": pct(g.change_24h),
            "change_7d_pct": pct(g.change_7d),
            "change_30d_pct": pct(g.change_30d),
            "condition": g.condition,
            "condition_reason": g.condition_reason,
            "calculation": "(supply now ÷ supply N days earlier − 1) for N = 1, 7, 30",
        }

    @staticmethod
    def _share(s: m.MarketShare) -> dict[str, Any]:
        return {
            "subject": s.subject,
            "status": s.status,
            "reason": s.reason,
            "value": num(s.subject_value),
            "total": num(s.total_value),
            "share_pct": pct(s.share, "0.01"),
            "as_of_used": _iso(s.as_of_used),
            "calculation": "subject circulating supply ÷ total stablecoin circulating supply, "
            "same stored snapshot time",
        }

    @staticmethod
    def _acceleration(a: m.GrowthAcceleration) -> dict[str, Any]:
        return {
            "status": a.status,
            "reason": a.reason,
            "subject": TOTAL_SUBJECT,
            "rate_now_7d_pct": pct(a.rate_now_7d),
            "rate_prior_7d_pct": pct(a.rate_prior_7d),
            "change_pct_points": pct(a.change),
            "condition": a.condition,
            "calculation": "7-day growth rate ending now − 7-day growth rate ending 7 days "
            "earlier, for total stablecoin supply",
        }

    @staticmethod
    def _exchange_liquidity(e: m.ExchangeLiquidityChange) -> dict[str, Any]:
        return {"status": e.status, "reason": e.reason}

    async def _quality(self, b: _Bundle) -> dict[str, Any]:
        sources = []
        for item in SOURCES:
            rows = b.rows.get(item.subject, [])
            valued = [r for r in rows if r["value"] is not None]
            latest = max((r["event_time"] for r in valued), default=None)
            flagged = sum(r["quality_status"] in FLAGGED for r in rows)
            backfilled = sum(r["pit_reliability"] == "backfilled_latest" for r in rows)
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
                    "flagged_points": flagged,
                    "backfilled_points": backfilled,
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
            "note": f"Points loaded for the last {LOAD_SPAN.days} days. 'backfilled' = history "
            "as the provider shows it today (may include later corrections); flagged = suspect "
            "or conflicting.",
        }

    # ------------------------------------------------------------------ history

    async def history(
        self,
        *,
        subject: str,
        days: int,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        if subject not in SUBJECTS:
            raise NotFoundError(
                f"No liquidity data is tracked for {subject!r} (tracked: {', '.join(SUBJECTS)})."
            )
        days = max(1, min(days, 365 * 3))
        start, end = as_of - timedelta(days=days), as_of + timedelta(seconds=1)
        rows = await self.queries.observations(
            SUPPLY.dataset_id,
            subject=subject,
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        return {
            "subject": subject,
            "as_of": as_of.isoformat(),
            "start": start.isoformat(),
            "days": days,
            "unit": SUPPLY.unit,
            "points": [
                {
                    "time": r["event_time"].isoformat(),
                    "value": num(r["value"]),
                    "quality_status": r["quality_status"],
                }
                for r in rows
            ],
        }
