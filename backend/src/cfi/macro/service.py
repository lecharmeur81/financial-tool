"""Macro read service (Phase 11): yield curve, approximate real policy rate, CPI/PCE
year-over-year inflation, VIX condition, equity/dollar/oil trend, the US net-liquidity proxy, and
the Macro Environment Score — all point-in-time.

Evidence categories (R2): stored FRED values are **Observed Data**; every slope, rate, trend and
composite figure is a **Calculated Metric** with its formula and parameters; the Macro Environment
Score is a **Calculated Metric** built from them. Nothing here is a signal, forecast or
recommendation, and nothing here converts macro data into a deterministic crypto prediction (the
phase's explicit instruction) — every reading describes the conventional macro backdrop only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.errors import NotFoundError
from cfi.core.time import utc_now
from cfi.macro import metrics as m
from cfi.macro import score as sc
from cfi.macro.queries import MacroQueries
from cfi.macro.sources import ADAPTERS, ATTRIBUTION, SOURCES, credential_configured
from cfi.macro.universe import (
    CPI,
    DXY_BROAD_PROXY,
    FED_BALANCE_SHEET,
    FED_FUNDS_EFFECTIVE,
    NOT_TRACKED,
    OIL_WTI,
    REVERSE_REPO,
    SP500,
    TREASURY_GENERAL_ACCOUNT,
    US_SUBJECT,
    UST_YIELD_2Y,
    UST_YIELD_10Y,
    VIX,
    all_datasets,
)
from cfi.market.service import freshness

# Deep enough for the longest window any component needs: CPI year-over-year (365 days) plus
# monthly tolerance (50 days) plus a safety margin.
LOAD_SPAN = timedelta(days=430)
FLAGGED = ("suspect", "conflicting")
EVIDENCE_NOTE = (
    "Stored FRED values are observed data; the yield-curve slope, real policy rate, CPI/PCE "
    "year-over-year change, VIX condition, equity/dollar/oil trend, the US net-liquidity proxy "
    "and the Macro Environment Score are calculated metrics with published formulas and "
    "parameters. Every reading describes the conventional macro backdrop (monetary-policy stance, "
    "risk appetite in traditional markets, USD strength, US liquidity conditions, inflation "
    "pressure) — never a crypto price forecast, and nothing here is a recommendation."
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
    """Everything read for every tracked series at one point in time."""

    as_of: datetime
    knowledge_time: datetime
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    points: dict[str, list[m.Point]] = field(default_factory=dict)


@dataclass
class MacroService:
    queries: MacroQueries
    enabled_providers: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers

    async def _load(self, as_of: datetime, knowledge_time: datetime) -> _Bundle:
        b = _Bundle(as_of, knowledge_time)
        start, end = as_of - LOAD_SPAN, as_of + timedelta(seconds=1)
        for dataset in all_datasets():
            rows = await self.queries.observations(
                dataset.dataset_id,
                subject=US_SUBJECT,
                start=start,
                end=end,
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
            b.rows[dataset.dataset_id] = rows
            b.points[dataset.dataset_id] = _points(rows)
        return b

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> dict[str, Any]:
        return {
            "subject": US_SUBJECT,
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
                    "credential_configured": credential_configured(pid),
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
                        "direction_note": c.direction_note,
                    }
                    for c in sc.COMPONENTS
                ],
            },
            "not_tracked": list(NOT_TRACKED),
            "evidence_note": EVIDENCE_NOTE,
        }

    # ------------------------------------------------------------------ overview

    def _overview_sections(self, b: _Bundle) -> dict[str, Any]:
        """Every ``overview`` section except ``data_quality`` and ``not_tracked``, computed from an
        already-loaded bundle. Shared by ``overview`` and ``overview_score`` so both return exactly
        the same values for the same inputs."""
        as_of = b.as_of
        knowledge_time = b.knowledge_time
        p = b.points
        yield_curve = m.yield_curve_slope(
            p[UST_YIELD_10Y.dataset_id], p[UST_YIELD_2Y.dataset_id], as_of
        )
        real_rate = m.real_policy_rate(p[FED_FUNDS_EFFECTIVE.dataset_id], p[CPI.dataset_id], as_of)
        cpi_yoy = m.cpi_year_over_year(p[CPI.dataset_id], as_of)
        vix = m.vix_condition(p[VIX.dataset_id], as_of)
        equity_trend = m.trend("sp500", p[SP500.dataset_id], as_of, m.QUARTER, m.DAILY_TOLERANCE)
        dollar_trend = m.trend(
            "dxy_broad_proxy", p[DXY_BROAD_PROXY.dataset_id], as_of, m.QUARTER, m.DAILY_TOLERANCE
        )
        oil_trend = m.trend("oil_wti", p[OIL_WTI.dataset_id], as_of, m.QUARTER, m.DAILY_TOLERANCE)
        net_liquidity = m.us_net_liquidity(
            p[FED_BALANCE_SHEET.dataset_id],
            p[TREASURY_GENERAL_ACCOUNT.dataset_id],
            p[REVERSE_REPO.dataset_id],
            as_of,
        )
        net_liquidity_trend = m.net_liquidity_trend(
            p[FED_BALANCE_SHEET.dataset_id],
            p[TREASURY_GENERAL_ACCOUNT.dataset_id],
            p[REVERSE_REPO.dataset_id],
            as_of,
        )
        calculated_at = utc_now()
        score = sc.compute_score(
            as_of=as_of,
            calculated_at=calculated_at,
            yield_curve=yield_curve,
            real_policy_rate=real_rate,
            vix=vix,
            equity_trend=equity_trend,
            dollar_trend=dollar_trend,
            net_liquidity_trend=net_liquidity_trend,
            oil_trend=oil_trend,
        )
        return {
            "as_of": as_of.isoformat(),
            "knowledge_time": knowledge_time.isoformat(),
            "evidence_note": EVIDENCE_NOTE,
            "score": self._score(score),
            "yield_curve": self._yield_curve(yield_curve),
            "real_policy_rate": self._real_rate(real_rate),
            "cpi_year_over_year": self._trend(cpi_yoy),
            "vix": self._vix(vix),
            "equity_trend": self._trend(equity_trend),
            "dollar_trend": self._trend(dollar_trend),
            "oil_trend": self._trend(oil_trend),
            "us_net_liquidity": self._net_liquidity(net_liquidity),
            "us_net_liquidity_trend": self._trend(net_liquidity_trend),
        }

    async def overview(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        b = await self._load(as_of, knowledge_time)
        return {
            **self._overview_sections(b),
            "data_quality": await self._quality(b),
            "not_tracked": list(NOT_TRACKED),
        }

    async def overview_score(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        """``overview`` without its ``data_quality`` section: the same sections, values and key
        order for the same inputs, minus ``data_quality``. It loads the same observations (one query
        per dataset, identical cut-offs) but skips the per-source ``last_job`` queries that only
        ``data_quality`` uses. For callers that consume the score alone (the similarity and regime
        snapshot gatherers); everything else keeps calling ``overview``."""
        b = await self._load(as_of, knowledge_time)
        return {**self._overview_sections(b), "not_tracked": list(NOT_TRACKED)}

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
            "vintage_risk_note": s.vintage_risk_note,
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
    def _yield_curve(y: m.YieldCurveReading) -> dict[str, Any]:
        return {
            "status": y.status,
            "reason": y.reason,
            "ust_10y_pct": num(y.ust10y),
            "ust_2y_pct": num(y.ust2y),
            "slope_pp": num(y.slope_pp),
            "time": _iso(y.time),
            "condition": y.condition,
            "condition_reason": y.condition_reason,
            "calculation": "10-year Treasury yield − 2-year Treasury yield",
        }

    @staticmethod
    def _real_rate(r: m.RealPolicyRateReading) -> dict[str, Any]:
        return {
            "status": r.status,
            "reason": r.reason,
            "fed_funds_effective_pct": num(r.fed_funds_pct),
            "cpi_year_over_year_pct": num(r.cpi_yoy_pct),
            "real_rate_pp": num(r.real_rate_pp),
            "time": _iso(r.time),
            "calculation": "effective federal funds rate − trailing 12-month CPI inflation "
            "(an approximation; not the Fed's own preferred real-rate measure)",
        }

    @staticmethod
    def _vix(v: m.VixReading) -> dict[str, Any]:
        return {
            "status": v.status,
            "reason": v.reason,
            "value": num(v.value),
            "time": _iso(v.time),
            "condition": v.condition,
            "condition_reason": v.condition_reason,
        }

    @staticmethod
    def _trend(t: m.TrendReading) -> dict[str, Any]:
        return {
            "metric": t.metric,
            "status": t.status,
            "reason": t.reason,
            "now_value": num(None if t.now is None else t.now.value),
            "now_time": _iso(None if t.now is None else t.now.time),
            "then_value": num(None if t.then is None else t.then.value),
            "then_time": _iso(None if t.then is None else t.then.time),
            "change_pct": pct(t.change_pct),
            "condition": t.condition,
            "condition_reason": t.condition_reason,
            "calculation": "(value now ÷ value ~90 days earlier − 1); CPI year-over-year uses "
            "~365 days",
        }

    @staticmethod
    def _net_liquidity(n: m.NetLiquidityReading) -> dict[str, Any]:
        return {
            "status": n.status,
            "reason": n.reason,
            "fed_balance_sheet_usd_b": num(n.fed_balance_sheet_usd_b),
            "treasury_general_account_usd_b": num(n.tga_usd_b),
            "reverse_repo_usd_b": num(n.reverse_repo_usd_b),
            "net_liquidity_usd_b": num(n.net_liquidity_usd_b),
            "time": _iso(n.time),
            "calculation": "Fed balance sheet − Treasury General Account − overnight reverse "
            "repo, USD billions (US-only proxy, not a true global aggregate)",
        }

    async def _quality(self, b: _Bundle) -> dict[str, Any]:
        sources = []
        for item in SOURCES:
            rows = b.rows.get(item.dataset.dataset_id, [])
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
                    "enabled": item.provider_id in self.enabled_providers,
                    "credential_configured": credential_configured(item.provider_id),
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
            "as the provider shows it today (FRED's current, most-revised vintage — may include "
            "later corrections); flagged = suspect or conflicting.",
        }

    # ------------------------------------------------------------------ history

    async def history(
        self,
        *,
        dataset_id: str,
        days: int,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        known = {d.dataset_id: d for d in all_datasets()}
        if dataset_id not in known:
            raise NotFoundError(
                f"No macro data is tracked for {dataset_id!r} "
                f"(tracked: {', '.join(sorted(known))})."
            )
        dataset = known[dataset_id]
        days = max(1, min(days, 365 * 15))
        start, end = as_of - timedelta(days=days), as_of + timedelta(seconds=1)
        rows = await self.queries.observations(
            dataset_id,
            subject=US_SUBJECT,
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        return {
            "dataset_id": dataset_id,
            "as_of": as_of.isoformat(),
            "start": start.isoformat(),
            "days": days,
            "unit": dataset.unit,
            "points": [
                {
                    "time": r["event_time"].isoformat(),
                    "value": num(r["value"]),
                    "quality_status": r["quality_status"],
                }
                for r in rows
            ],
        }
