"""Institutional capital read service: flows, aggregations, holdings and the flow score.

Every metric in a response carries the same envelope (``metric()``): source, timestamp, unit,
calculation, freshness and data quality, plus its evidence category (R2) and, for actor-based data,
its evidence class (R5). Observed values are labelled ``observed``; sums, ratios and the score are
``metric`` (deterministic calculations with published definitions). Nothing here is a signal,
forecast or recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from cfi.core.calendars import NEW_YORK, date_label
from cfi.core.errors import NotFoundError
from cfi.core.time import ensure_utc
from cfi.domain.datasets import DatasetSpec
from cfi.institutional.aggregation import (
    INTERVALS,
    Bucket,
    DailyPoint,
    Interval,
    aggregate,
    bucket_end,
    bucket_start,
    etf_due_date,
    to_points,
)
from cfi.institutional.queries import InstitutionalQueries
from cfi.institutional.score import (
    BAND_NOTE,
    BANDS,
    COMPONENTS,
    MIN_AVAILABLE_WEIGHT,
    MIN_COVERAGE,
    SCORE_ID,
    SCORE_VERSION,
    ComponentResult,
    Purchase,
    ScoreResult,
    compute_score,
)
from cfi.institutional.sources import ADAPTERS, ATTRIBUTION, SOURCES
from cfi.institutional.universe import (
    ETF_ASSETS,
    ETF_FLOW_US_SPOT,
    ETF_FUND_FLOW_US_SPOT,
    TREASURY_HOLDING_ASSETS,
    TREASURY_HOLDINGS_COMPANIES,
    TREASURY_PURCHASE_ASSETS,
    TREASURY_PURCHASE_BTC,
    all_datasets,
    etf_group_ref,
)
from cfi.market.universe import ASSET_SYMBOLS, ASSETS
from cfi.providers import coingecko, sosovalue

FreshnessStatus = Literal["fresh", "stale", "no_data"]
DEFAULT_RANGE: dict[str, timedelta] = {
    "1d": timedelta(days=45),
    "1w": timedelta(weeks=26),
    "1mo": timedelta(days=366),
}
MAX_RANGE = timedelta(days=5 * 366)
# How far back the score reads ETF rows: 20 trading days plus holidays and slack.
SCORE_LOOKBACK = timedelta(days=45)
# Treasury purchase sweeps run every 12 h; three missed sweeps make the data stale.
PURCHASE_SWEEP_STALE_AFTER = timedelta(hours=36)
# Sum of per-fund flows vs the provider's total: differences above this are flagged.
RECONCILE_TOLERANCE_USD = Decimal(1_000_000)
TOP_HOLDERS = 15
RECENT_PURCHASES = 25

SOSOVALUE_KEY_HINT = (
    "SoSoValue needs a free API key: set CFI_PROVIDER_SOSOVALUE_API_KEY in .env (register at "
    "https://sosovalue.com/developer/dashboard). Without it, SoSoValue jobs are skipped."
)


def num(value: Any) -> str | None:
    """Exact decimals travel as strings (JSON numbers would lose precision)."""
    if value is None:
        return None
    return format(value, "f") if isinstance(value, Decimal) else str(value)


def _day_start(day: date) -> datetime:
    return date_label(day)


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else format(value.quantize(Decimal("0.0001")), "f")


@dataclass(frozen=True, slots=True)
class Freshness:
    status: FreshnessStatus
    latest: datetime | date | None
    expected_latest: date | None
    age_seconds: int | None
    limit: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "latest": self.latest,
            "expected_latest": self.expected_latest,
            "age_seconds": self.age_seconds,
            "rule": self.limit,
            "note": self.note,
        }


def etf_freshness(
    latest_day: date | None, latest_available_at: datetime | None, due: date, as_of: datetime
) -> Freshness:
    """Calendar-aware: fresh when the newest stored trading day is at least the latest trading
    day that should be public by ``as_of``."""
    rule = "newest trading day ≥ latest day due (next trading day 18:00 New York)"
    if latest_day is None:
        return Freshness("no_data", None, due, None, rule, "no ETF data stored")
    age = (
        None if latest_available_at is None else int((as_of - latest_available_at).total_seconds())
    )
    if latest_day >= due:
        return Freshness("fresh", latest_day, due, max(0, age or 0), rule, "up to date")
    return Freshness(
        "stale",
        latest_day,
        due,
        age,
        rule,
        f"newest stored trading day {latest_day} is older than the latest day due ({due})",
    )


def age_freshness(
    latest: datetime | None, limit: timedelta, as_of: datetime, what: str
) -> Freshness:
    rule = f"{what} at most {int(limit.total_seconds() // 3600)} h old"
    if latest is None:
        return Freshness("no_data", None, None, None, rule, f"no {what} yet")
    age = int((as_of - latest).total_seconds())
    status: FreshnessStatus = "stale" if age > limit.total_seconds() else "fresh"
    return Freshness(status, latest, None, max(0, age), rule, f"{what} {max(0, age) // 3600} h old")


def quality_summary(
    *,
    status: str,
    notes: list[str],
    days_expected: int | None = None,
    days_present: int | None = None,
    flagged: int = 0,
    revised: int = 0,
    backfilled: int = 0,
    estimated_availability: int = 0,
) -> dict[str, Any]:
    out_notes = list(notes)
    if backfilled:
        out_notes.append(
            f"{backfilled} input(s) loaded after the fact (pit_reliability backfilled_latest): "
            "values as the provider shows them today, may include later corrections"
        )
    if estimated_availability:
        out_notes.append(
            f"{estimated_availability} input(s) have an estimated publication time "
            "(available_at_estimated)"
        )
    if flagged:
        out_notes.append(f"{flagged} input(s) flagged suspect or conflicting")
    if revised:
        out_notes.append(f"{revised} input(s) were revised by the provider")
    return {
        "status": status,
        "days_expected": days_expected,
        "days_present": days_present,
        "flagged": flagged,
        "revised": revised,
        "backfilled": backfilled,
        "estimated_availability": estimated_availability,
        "notes": out_notes,
    }


@dataclass
class InstitutionalService:
    queries: InstitutionalQueries
    enabled_providers: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers

    def source(self, provider_id: str, dataset: DatasetSpec) -> dict[str, Any]:
        caps = ADAPTERS[provider_id].capabilities
        return {
            "provider_id": provider_id,
            "provider_name": caps.display_name,
            "original_source": caps.original_source,
            "dataset_id": dataset.dataset_id,
            "enabled": provider_id in self.enabled_providers,
            "terms_verified": caps.terms_verified,
            "attribution": ATTRIBUTION.get(provider_id),
        }

    @staticmethod
    def metric(
        *,
        metric_id: str,
        label: str,
        evidence_category: Literal["observed", "metric"],
        evidence_class: str | None,
        value: Any,
        unit: str,
        timestamp: datetime | date | None,
        calculation: str,
        source: dict[str, Any] | list[dict[str, Any]],
        freshness: Freshness,
        quality: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "metric_id": metric_id,
            "label": label,
            "evidence_category": evidence_category,
            "evidence_class": evidence_class,
            "value": num(value),
            "unit": unit,
            "timestamp": timestamp,
            "calculation": calculation,
            "source": source,
            "freshness": freshness.as_dict(),
            "quality": quality,
        }

    @staticmethod
    def _asset(asset: str, allowed: tuple[str, ...], what: str) -> str:
        if asset not in ASSET_SYMBOLS:
            raise NotFoundError(f"Unknown asset '{asset}'.")
        if asset not in allowed:
            raise NotFoundError(f"No {what} is tracked for {asset}.")
        return asset

    @staticmethod
    def _interval(interval: str) -> Interval:
        if interval not in INTERVALS:
            raise NotFoundError(f"Unknown interval '{interval}' (use {', '.join(INTERVALS)}).")
        return interval

    @staticmethod
    def _range(
        interval: str,
        start: date | None,
        end: date | None,
        as_of: datetime,
        *,
        us_trading_dates: bool = False,
    ) -> tuple[date, date]:
        """[start, end) in dates; defaults end at ``as_of``'s date (inclusive). For US trading
        dates, "today" is the New York date — a trading day that has not started is not listed."""
        today = ensure_utc(as_of)
        last = (today.astimezone(NEW_YORK) if us_trading_dates else today).date() + timedelta(
            days=1
        )
        end = last if end is None else min(end, last)
        if start is None:
            start = end - DEFAULT_RANGE[interval]
        start = max(start, end - MAX_RANGE)
        if start >= end:
            raise NotFoundError("Empty date range.")
        return start, end

    async def _last_run(self, dataset: DatasetSpec, provider: str, subject: str | None) -> Any:
        return await self.queries.last_job(dataset.dataset_id, provider, subject)

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> dict[str, Any]:
        providers = {}
        for provider_id, adapter in ADAPTERS.items():
            caps = adapter.capabilities
            providers[provider_id] = {
                "provider_id": provider_id,
                "display_name": caps.display_name,
                "enabled": provider_id in self.enabled_providers,
                "requires_api_key": not caps.auth.optional and caps.auth.env_var != "",
                "api_key_variable": caps.auth.env_var or None,
                "terms_verified": caps.terms_verified,
                "notes": caps.notes,
                "attribution": ATTRIBUTION.get(provider_id),
            }
        return {
            "assets": [{"symbol": a.symbol, "name": a.name} for a in ASSETS],
            "coverage": {
                "etf_flows": list(ETF_ASSETS),
                "treasury_purchases": list(TREASURY_PURCHASE_ASSETS),
                "treasury_holdings": list(TREASURY_HOLDING_ASSETS),
            },
            "intervals": list(INTERVALS),
            "datasets": [
                {
                    "dataset_id": d.dataset_id,
                    "description": d.description,
                    "availability_rule": d.availability.as_dict(),
                    "providers": [s.provider_id for s in SOURCES if s.dataset == d],
                }
                for d in all_datasets()
            ],
            "providers": list(providers.values()),
            "schedule": [
                {
                    "provider_id": s.provider_id,
                    "dataset_id": s.dataset.dataset_id,
                    "subjects": list(s.subjects),
                    "every_hours": s.interval_seconds / 3600,
                }
                for s in SOURCES
            ],
            "score": score_definition(),
            "not_tracked": NOT_TRACKED,
        }

    # ------------------------------------------------------------------ ETF flows

    async def _etf_points(
        self,
        dataset: DatasetSpec,
        asset: str,
        start: date,
        end: date,
        as_of: datetime,
        knowledge_time: datetime,
        subject_refs: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return await self.queries.flows(
            dataset.dataset_id,
            asset=asset,
            start=_day_start(start),
            end=_day_start(end),
            as_of=as_of,
            knowledge_time=knowledge_time,
            subject_refs=subject_refs,
        )

    async def etf_flows(
        self,
        *,
        asset: str,
        interval: str,
        start: date | None,
        end: date | None,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        asset = self._asset(asset, ETF_ASSETS, "US spot ETF")
        iv = self._interval(interval)
        range_start, range_end = self._range(iv, start, end, as_of, us_trading_dates=True)
        # widen to whole buckets so weekly/monthly totals are never cut in the middle
        range_start = bucket_start(range_start, iv)
        rows = await self._etf_points(
            ETF_FLOW_US_SPOT,
            asset,
            range_start,
            range_end,
            as_of,
            knowledge_time,
            [etf_group_ref(asset)],
        )
        points = to_points(rows)
        earliest = await self.queries.earliest_event(
            ETF_FLOW_US_SPOT.dataset_id, asset=asset, as_of=as_of, knowledge_time=knowledge_time
        )
        coverage_start = earliest.date() if earliest else None
        due = etf_due_date(as_of)
        buckets = aggregate(
            points,
            interval=iv,
            start=range_start,
            end=range_end,
            due_until=due,
            coverage_start=coverage_start,
        )
        reconciliation = {}
        if iv == "1d":
            reconciliation = await self._reconcile(
                asset, range_start, range_end, as_of, knowledge_time, points
            )
        latest = max((p for p in points if p.has_value), key=lambda p: p.day, default=None)
        latest_any = await self._latest_etf(asset, as_of, knowledge_time)
        fresh = etf_freshness(
            latest_any.day if latest_any else None,
            latest_any.available_at if latest_any else None,
            due,
            as_of,
        )
        src = self.source(sosovalue.PROVIDER_ID, ETF_FLOW_US_SPOT)
        last_run = await self._last_run(ETF_FLOW_US_SPOT, sosovalue.PROVIDER_ID, asset)
        observed = iv == "1d"
        out_buckets = [
            self._bucket(b, iv, reconciliation.get(b.start), src, observed) for b in buckets
        ]
        warnings = self._etf_warnings(buckets, fresh, last_run, coverage_start, iv)
        return {
            "asset": asset,
            "interval": iv,
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "range": {"start": range_start, "end": range_end},
            "evidence_category": "observed" if observed else "metric",
            "evidence_class": "direct",
            "definition": {
                "metric_id": f"etf_net_flow.us_spot.{iv}.v1",
                "label": f"US spot {asset} ETF net flow"
                + ("" if observed else f" ({'weekly' if iv == '1w' else 'monthly'} total)"),
                "unit": "usd",
                "calculation": (
                    "As reported by SoSoValue: daily total net inflow across all US spot ETFs "
                    "(creations − redemptions, USD)."
                    if observed
                    else "Σ reported daily net inflow over the trading days of the "
                    f"{'week (Monday–Sunday)' if iv == '1w' else 'calendar month'} that have "
                    "data; net assets = last day with data in the bucket."
                ),
                "sign": "positive = net creations (inflow); negative = net redemptions (outflow)",
                "event_time": "US trading date (sessions end 16:00 New York time)",
            },
            "source": src,
            "buckets": out_buckets,
            "latest_day": latest.day if latest else None,
            "coverage_start": coverage_start,
            "freshness": fresh.as_dict(),
            "ingestion": {"last_run": last_run},
            "warnings": warnings,
        }

    async def _latest_etf(
        self, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> DailyPoint | None:
        rows = await self.queries.latest_per_series(
            ETF_FLOW_US_SPOT.dataset_id, asset=asset, as_of=as_of, knowledge_time=knowledge_time
        )
        points = to_points([r for r in rows if r["subject_ref"] == etf_group_ref(asset)])
        return points[0] if points else None

    def _bucket(
        self,
        b: Bucket,
        interval: Interval,
        recon: dict[str, Any] | None,
        src: dict[str, Any],
        observed: bool,
    ) -> dict[str, Any]:
        notes = []
        if b.missing_days:
            notes.append(
                f"{len(b.missing_days)} trading day(s) missing: "
                + ", ".join(d.isoformat() for d in b.missing_days)
            )
        if b.not_loaded:
            notes.append(f"{b.not_loaded} trading day(s) before stored history (not loaded)")
        if b.not_due:
            notes.append(f"{b.not_due} trading day(s) not reported yet (not due)")
        return {
            "start": b.start,
            "end": b.end,
            "net_flow_usd": num(b.net_flow_usd),
            "net_assets_usd": num(b.holdings_usd_end),
            "net_assets_date": b.holdings_date,
            "value_traded_usd": num(b.value_traded_usd),
            "inflow_days": b.inflow_days,
            "outflow_days": b.outflow_days,
            "status": b.status,
            "quality": quality_summary(
                status=b.status,
                notes=notes,
                days_expected=b.trading_days - b.not_due,
                days_present=b.present,
                flagged=b.flagged,
                revised=b.revised,
                backfilled=b.backfilled,
                estimated_availability=b.estimated_availability,
            )
            | {"missing_days": b.missing_days, "not_loaded": b.not_loaded, "not_due": b.not_due},
            "reconciliation": recon,
        }

    async def _reconcile(
        self,
        asset: str,
        start: date,
        end: date,
        as_of: datetime,
        knowledge_time: datetime,
        totals: list[DailyPoint],
    ) -> dict[date, dict[str, Any]]:
        """Per day: Σ per-fund flows vs the provider's total (a cross-check, not a correction)."""
        rows = await self._etf_points(
            ETF_FUND_FLOW_US_SPOT, asset, start, end, as_of, knowledge_time
        )
        by_day: dict[date, list[Decimal]] = {}
        for r in rows:
            if r["quality_status"] != "missing" and r["flow_usd"] is not None:
                by_day.setdefault(r["event_time"].date(), []).append(r["flow_usd"])
        out: dict[date, dict[str, Any]] = {}
        for p in totals:
            flows = by_day.get(p.day)
            if not flows or p.flow_usd is None:
                continue
            funds_total = sum(flows, Decimal(0))
            diff = p.flow_usd - funds_total
            out[p.day] = {
                "funds_reporting": len(flows),
                "funds_total_usd": num(funds_total),
                "difference_usd": num(diff),
                "reconciles": abs(diff) <= RECONCILE_TOLERANCE_USD,
                "tolerance_usd": num(RECONCILE_TOLERANCE_USD),
            }
        return out

    @staticmethod
    def _etf_warnings(
        buckets: list[Bucket],
        fresh: Freshness,
        last_run: dict[str, Any] | None,
        coverage_start: date | None,
        interval: Interval,
    ) -> list[str]:
        warnings = []
        if fresh.status == "no_data":
            warnings.append("No ETF flow data stored yet. " + SOSOVALUE_KEY_HINT)
        elif fresh.status == "stale":
            warnings.append(f"ETF data is stale: {fresh.note}.")
        missing = sum(len(b.missing_days) for b in buckets)
        if missing:
            warnings.append(f"{missing} trading day(s) in this range have no reported flow.")
        if coverage_start is not None and any(b.not_loaded for b in buckets):
            warnings.append(
                f"Stored history starts {coverage_start}: the provider's API serves only the most "
                "recent month, and older history builds up as the system runs."
            )
        if interval != "1d" and any(b.status == "partial" for b in buckets):
            warnings.append("Some totals are partial: they sum only the days with data.")
        if last_run is not None and last_run["status"] == "failed":
            warnings.append(
                f"Last ingestion failed: {last_run['error_code']} — {last_run['error_detail']}"
            )
        return warnings

    # ------------------------------------------------------------------ ETF funds

    async def etf_funds(
        self,
        *,
        asset: str,
        start: date | None,
        end: date | None,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        asset = self._asset(asset, ETF_ASSETS, "US spot ETF")
        range_start, range_end = self._range("1d", start, end, as_of, us_trading_dates=True)
        rows = await self._etf_points(
            ETF_FUND_FLOW_US_SPOT, asset, range_start, range_end, as_of, knowledge_time
        )
        latest_rows = await self.queries.latest_per_series(
            ETF_FUND_FLOW_US_SPOT.dataset_id,
            asset=asset,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        due = etf_due_date(as_of)
        funds: dict[str, dict[str, Any]] = {}
        for r in latest_rows:
            funds[r["subject_ref"]] = {
                "subject_ref": r["subject_ref"],
                "ticker": r["subject_ref"].split(":", 1)[1],
                "name": r["entity_name"],
                "latest_day": r["event_time"].date(),
                "net_assets_usd": r["holdings_usd"],
                "premium_discount": r["premium_discount"],
                "cum_flow_usd": r["cum_flow_usd"],
                "range_flow_usd": Decimal(0),
                "days_present": 0,
                "flagged": 0,
                "backfilled": 0,
                "revised": 0,
                "missing_rows": 0,
            }
        for r in rows:
            fund = funds.get(r["subject_ref"])
            if fund is None:
                continue
            if r["quality_status"] == "missing" or r["flow_usd"] is None:
                fund["missing_rows"] += 1
                continue
            fund["range_flow_usd"] += r["flow_usd"]
            fund["days_present"] += 1
            fund["flagged"] += r["quality_status"] in ("suspect", "conflicting")
            fund["backfilled"] += r["pit_reliability"] == "backfilled_latest"
            fund["revised"] += r["revision"] > 0
        total_aum = sum(
            (f["net_assets_usd"] for f in funds.values() if f["net_assets_usd"] is not None),
            Decimal(0),
        )
        src = self.source(sosovalue.PROVIDER_ID, ETF_FUND_FLOW_US_SPOT)
        out = []
        for f in sorted(
            funds.values(), key=lambda f: f["net_assets_usd"] or Decimal(0), reverse=True
        ):
            fresh = etf_freshness(f["latest_day"], None, due, as_of)
            share = (
                f["net_assets_usd"] / total_aum * 100
                if total_aum and f["net_assets_usd"] is not None
                else None
            )
            status = "ok" if not f["flagged"] and not f["missing_rows"] else "partial"
            out.append(
                {
                    "ticker": f["ticker"],
                    "name": f["name"],
                    "latest_day": f["latest_day"],
                    "net_assets_usd": num(f["net_assets_usd"]),
                    "share_of_net_assets_pct": _pct(share),
                    "premium_discount": num(f["premium_discount"]),
                    "cum_flow_usd": num(f["cum_flow_usd"]),
                    "range_flow_usd": num(f["range_flow_usd"]),
                    "days_present": f["days_present"],
                    "freshness": fresh.as_dict(),
                    "quality": quality_summary(
                        status=status,
                        notes=(
                            [f"{f['missing_rows']} day(s) with no settled figures"]
                            if f["missing_rows"]
                            else []
                        ),
                        days_present=f["days_present"],
                        flagged=f["flagged"],
                        revised=f["revised"],
                        backfilled=f["backfilled"],
                    ),
                }
            )
        last_run = await self._last_run(ETF_FUND_FLOW_US_SPOT, sosovalue.PROVIDER_ID, asset)
        warnings = []
        if not out:
            warnings.append("No per-fund data stored yet. " + SOSOVALUE_KEY_HINT)
        if last_run is not None and last_run["status"] == "failed":
            warnings.append(
                f"Last ingestion failed: {last_run['error_code']} — {last_run['error_detail']}"
            )
        return {
            "asset": asset,
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "range": {"start": range_start, "end": range_end},
            "evidence_category": "metric",
            "evidence_class": "direct",
            "definition": {
                "range_flow_usd": "Σ reported daily net inflow of the fund over the range "
                "(days with data only)",
                "net_assets_usd": "latest reported net assets of the fund (USD)",
                "share_of_net_assets_pct": "fund net assets ÷ Σ net assets of the listed funds "
                "× 100 (latest values)",
                "premium_discount": "market price premium (+) or discount (−) to NAV, ratio",
            },
            "source": src,
            "funds": out,
            "total_net_assets_usd": num(total_aum) if out else None,
            "ingestion": {"last_run": last_run},
            "warnings": warnings,
        }

    # ------------------------------------------------------------------ treasuries

    async def treasury(
        self,
        *,
        asset: str,
        interval: str,
        start: date | None,
        end: date | None,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        if asset not in ASSET_SYMBOLS:
            raise NotFoundError(f"Unknown asset '{asset}'.")
        iv = self._interval(interval)
        range_start, range_end = self._range(iv, start, end, as_of)
        range_start = bucket_start(range_start, iv)
        warnings: list[str] = []
        purchases: dict[str, Any] | None = None
        if asset in TREASURY_PURCHASE_ASSETS:
            purchases = await self._purchases(
                asset, iv, range_start, range_end, as_of, knowledge_time, warnings
            )
        else:
            warnings.append(
                f"Dated listed-company purchases are not tracked for {asset}: no verified free "
                "source publishes them (SoSoValue covers bitcoin only)."
            )
        holdings = None
        if asset in TREASURY_HOLDING_ASSETS:
            holdings = await self._holdings_totals(asset, as_of, knowledge_time, warnings)
        else:
            warnings.append(f"Listed-company holdings totals are not tracked for {asset}.")
        return {
            "asset": asset,
            "interval": iv,
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "range": {"start": range_start, "end": range_end},
            "evidence_class": "attributed",
            "evidence_note": (
                "Company holdings and purchases are self-disclosed by listed companies and "
                "compiled by the provider (attributed evidence). Wallet balances are never used "
                "to label a holder institutional."
            ),
            "purchases": purchases,
            "holdings_totals": holdings,
            "warnings": warnings,
        }

    async def _purchases(
        self,
        asset: str,
        iv: Interval,
        start: date,
        end: date,
        as_of: datetime,
        knowledge_time: datetime,
        warnings: list[str],
    ) -> dict[str, Any]:
        rows = await self.queries.flows(
            TREASURY_PURCHASE_BTC.dataset_id,
            asset=asset,
            start=_day_start(start),
            end=_day_start(end),
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        latest = await self.queries.latest_per_series(
            TREASURY_PURCHASE_BTC.dataset_id,
            asset=asset,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        src = self.source(sosovalue.PROVIDER_ID, TREASURY_PURCHASE_BTC)
        buckets: dict[date, dict[str, Any]] = {}
        key = bucket_start(start, iv)
        while key < end:
            buckets[key] = {
                "start": max(key, start),
                "end": min(bucket_end(key, iv), end),
                "btc_acquired": Decimal(0),
                "cost_usd": Decimal(0),
                "cost_known_events": 0,
                "events": 0,
                "companies": set(),
                "flagged": 0,
                "backfilled": 0,
            }
            key = bucket_end(key, iv)
        events = []
        for r in rows:
            if r["quality_status"] == "missing":
                continue
            day = r["event_time"].date()
            b = buckets[bucket_start(day, iv)]
            b["events"] += 1
            b["companies"].add(r["subject_ref"])
            if r["flow_native"] is not None:
                b["btc_acquired"] += r["flow_native"]
            if r["flow_usd"] is not None:
                b["cost_usd"] += r["flow_usd"]
                b["cost_known_events"] += 1
            b["flagged"] += r["quality_status"] in ("suspect", "conflicting")
            b["backfilled"] += r["pit_reliability"] == "backfilled_latest"
            events.append(r)
        out_buckets = [
            {
                "start": b["start"],
                "end": b["end"],
                "btc_acquired": num(b["btc_acquired"]) if b["events"] else None,
                "cost_usd": num(b["cost_usd"]) if b["cost_known_events"] else None,
                "cost_known_events": b["cost_known_events"],
                "events": b["events"],
                "companies": len(b["companies"]),
                "quality": quality_summary(
                    status="ok" if not b["flagged"] else "partial",
                    notes=(
                        []
                        if b["cost_known_events"] == b["events"]
                        else [
                            f"cost reported for {b['cost_known_events']} of {b['events']} purchases"
                        ]
                    ),
                    flagged=b["flagged"],
                    backfilled=b["backfilled"],
                ),
            }
            for b in buckets.values()
        ]
        events.sort(key=lambda r: (r["event_time"], r["subject_ref"]), reverse=True)
        recent = [
            {
                "date": r["event_time"].date(),
                "company": r["entity_name"],
                "ticker": r["subject_ref"].split(":", 1)[1],
                "btc_acquired": num(r["flow_native"]),
                "cost_usd": num(r["flow_usd"]),
                "unit_cost_usd": num(r["unit_cost_usd"]),
                "holdings_after_btc": num(r["holdings_native"]),
                "available_at": r["available_at"],
                "available_at_estimated": r["available_at_estimated"],
                "pit_reliability": r["pit_reliability"],
                "quality_status": r["quality_status"],
                "quality_note": r["quality_note"],
            }
            for r in events[:RECENT_PURCHASES]
        ]
        holders = sorted(
            (r for r in latest if r["holdings_native"] is not None),
            key=lambda r: r["holdings_native"],
            reverse=True,
        )
        total = sum((r["holdings_native"] for r in holders), Decimal(0))
        last_ok = await self.queries.last_successful_job(
            TREASURY_PURCHASE_BTC.dataset_id, sosovalue.PROVIDER_ID, asset
        )
        fresh = age_freshness(last_ok, PURCHASE_SWEEP_STALE_AFTER, as_of, "last successful sweep")
        last_run = await self._last_run(TREASURY_PURCHASE_BTC, sosovalue.PROVIDER_ID, asset)
        if not latest:
            warnings.append("No treasury purchase data stored yet. " + SOSOVALUE_KEY_HINT)
        elif fresh.status == "stale":
            warnings.append(f"Treasury purchase data may be out of date: {fresh.note}.")
        if last_run is not None and last_run["status"] == "failed":
            warnings.append(
                f"Last purchase sweep failed: {last_run['error_code']} — {last_run['error_detail']}"
            )
        return {
            "definition": {
                "metric_id": f"treasury_net_acquisitions.btc.{iv}.v1",
                "label": "Listed-company BTC acquisitions",
                "calculation": (
                    "Σ BTC acquired (net of sales) and Σ reported cost (USD) of purchases "
                    "dated within each bucket, as compiled by SoSoValue. Purchase dates are the "
                    "provider's; disclosure is assumed public within 7 days (or when received, "
                    "if earlier)."
                ),
                "units": {"btc_acquired": "BTC", "cost_usd": "usd"},
                "evidence_category": "metric",
            },
            "source": src,
            "buckets": out_buckets,
            "recent": recent,
            "top_holders": [
                {
                    "ticker": r["subject_ref"].split(":", 1)[1],
                    "company": r["entity_name"],
                    "holdings_btc": num(r["holdings_native"]),
                    "as_of_purchase_date": r["event_time"].date(),
                    "pit_reliability": r["pit_reliability"],
                }
                for r in holders[:TOP_HOLDERS]
            ],
            "reported_holdings": self.metric(
                metric_id="treasury_reported_holdings.btc.v1",
                label="BTC held by listed companies tracked by SoSoValue",
                evidence_category="metric",
                evidence_class="attributed",
                value=total if holders else None,
                unit="BTC",
                timestamp=max((r["event_time"] for r in holders), default=None),
                calculation=(
                    "Σ each tracked company's holdings after its latest reported purchase "
                    f"({len(holders)} companies). A company's holdings only update when it "
                    "reports a purchase or sale."
                ),
                source=src,
                freshness=fresh,
                quality=quality_summary(
                    status="ok" if holders else "missing",
                    notes=[],
                    backfilled=sum(r["pit_reliability"] == "backfilled_latest" for r in holders),
                ),
            ),
            "companies_tracked": len(latest),
            "freshness": fresh.as_dict(),
            "ingestion": {"last_run": last_run},
        }

    async def _holdings_totals(
        self, asset: str, as_of: datetime, knowledge_time: datetime, warnings: list[str]
    ) -> dict[str, Any]:
        dataset = TREASURY_HOLDINGS_COMPANIES
        src = self.source(coingecko.PROVIDER_ID, dataset)
        latest = await self.queries.snapshot_near(
            dataset.dataset_id,
            asset=asset,
            at_or_before=as_of,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        fresh = age_freshness(
            latest["event_time"] if latest else None, dataset.freshness_limit, as_of, "snapshot"
        )
        changes = []
        for days in (7, 30):
            earlier = None
            if latest is not None:
                earlier = await self.queries.snapshot_near(
                    dataset.dataset_id,
                    asset=asset,
                    at_or_before=latest["event_time"] - timedelta(days=days),
                    as_of=as_of,
                    knowledge_time=knowledge_time,
                )
            change = None
            if (
                latest is not None
                and earlier is not None
                and latest["holdings_native"] is not None
                and earlier["holdings_native"]
            ):
                change = latest["holdings_native"] - earlier["holdings_native"]
            changes.append(
                {
                    "days": days,
                    "compared_with": earlier["event_time"] if earlier else None,
                    "change_native": num(change),
                    "change_pct": _pct(
                        change / earlier["holdings_native"] * 100
                        if change is not None and earlier is not None
                        else None
                    ),
                    "note": None
                    if earlier
                    else f"no snapshot {days} days before the latest one stored yet",
                }
            )
        last_run = await self._last_run(dataset, coingecko.PROVIDER_ID, asset)
        if latest is None:
            warnings.append("No listed-company holdings snapshot stored yet.")
        elif fresh.status == "stale":
            warnings.append(f"Holdings snapshot is stale: {fresh.note}.")
        quality = quality_summary(
            status=latest["quality_status"] if latest else "missing",
            notes=["snapshot receipt time used as timestamp (the response has none)"],
            estimated_availability=int(bool(latest and latest["available_at_estimated"])),
        )
        return {
            "holdings": self.metric(
                metric_id=f"treasury_holdings.public_companies.{asset.lower()}.v1",
                label=f"{asset} held by listed companies (CoinGecko)",
                evidence_category="observed",
                evidence_class="attributed",
                value=latest["holdings_native"] if latest else None,
                unit=asset,
                timestamp=latest["event_time"] if latest else None,
                calculation="As reported by CoinGecko: total holdings of the listed companies "
                "it tracks (company disclosures compiled by CoinGecko).",
                source=src,
                freshness=fresh,
                quality=quality,
            ),
            "value_usd": self.metric(
                metric_id=f"treasury_holdings_value.public_companies.{asset.lower()}.v1",
                label=f"Value of {asset} held by listed companies (CoinGecko)",
                evidence_category="observed",
                evidence_class="attributed",
                value=latest["holdings_usd"] if latest else None,
                unit="usd",
                timestamp=latest["event_time"] if latest else None,
                calculation="As reported by CoinGecko (current value of the holdings, USD).",
                source=src,
                freshness=fresh,
                quality=quality,
            ),
            "changes": changes,
            "ingestion": {"last_run": last_run},
        }

    # ------------------------------------------------------------------ score

    async def score(
        self, *, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        asset = self._asset(asset, ETF_ASSETS, "institutional flow score")
        result, context = await self._score(asset, as_of, knowledge_time)
        return self._score_payload(result, context)

    async def _score(
        self, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> tuple[ScoreResult, dict[str, Any]]:
        as_of_day = ensure_utc(as_of).date()
        end = as_of_day + timedelta(days=1)
        rows = await self._etf_points(
            ETF_FLOW_US_SPOT,
            asset,
            as_of_day - SCORE_LOOKBACK,
            end,
            as_of,
            knowledge_time,
            [etf_group_ref(asset)],
        )
        points = to_points(rows)
        purchases: list[Purchase] = []
        holdings: dict[str, Decimal] = {}
        last_sweep = None
        if asset in TREASURY_PURCHASE_ASSETS:
            purchase_rows = await self.queries.flows(
                TREASURY_PURCHASE_BTC.dataset_id,
                asset=asset,
                start=_day_start(as_of_day - timedelta(days=40)),
                end=_day_start(end),
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
            purchases = [
                Purchase(
                    day=r["event_time"].date(),
                    company=r["subject_ref"],
                    flow_native=r["flow_native"],
                    quality_status=r["quality_status"],
                    pit_reliability=r["pit_reliability"],
                    available_at_estimated=r["available_at_estimated"],
                )
                for r in purchase_rows
                if r["quality_status"] != "missing"
            ]
            for r in await self.queries.latest_per_series(
                TREASURY_PURCHASE_BTC.dataset_id,
                asset=asset,
                as_of=as_of,
                knowledge_time=knowledge_time,
            ):
                if r["holdings_native"] is not None:
                    holdings[r["subject_ref"]] = r["holdings_native"]
            last_sweep = await self.queries.last_successful_job(
                TREASURY_PURCHASE_BTC.dataset_id, sosovalue.PROVIDER_ID, asset
            )
        due = etf_due_date(as_of)
        result = compute_score(
            asset=asset,
            as_of=as_of,
            etf_points=points,
            due_until=due,
            purchases=purchases,
            holdings=holdings,
        )
        latest = max((p for p in points if p.has_value), key=lambda p: p.day, default=None)
        context = {
            "knowledge_time": knowledge_time,
            "due": due,
            "etf_fresh": etf_freshness(
                latest.day if latest else None,
                latest.available_at if latest else None,
                due,
                as_of,
            ),
            "treasury_fresh": age_freshness(
                last_sweep if last_sweep and last_sweep <= knowledge_time else None,
                PURCHASE_SWEEP_STALE_AFTER,
                as_of,
                "last successful sweep",
            ),
        }
        return result, context

    def _component(self, c: ComponentResult, context: dict[str, Any]) -> dict[str, Any]:
        d = c.definition
        treasury = d.component_id.startswith("treasury")
        src = (
            self.source(sosovalue.PROVIDER_ID, TREASURY_PURCHASE_BTC)
            if treasury
            else self.source(sosovalue.PROVIDER_ID, ETF_FLOW_US_SPOT)
        )
        notes = [c.reason] if c.reason else []
        if c.missing_days and c.status == "ok":
            notes.append(
                "missing inside the window (excluded from the sum): "
                + ", ".join(x.isoformat() for x in c.missing_days)
            )
        body = self.metric(
            metric_id=d.metric_id,
            label=d.label,
            evidence_category="metric",
            evidence_class="attributed" if treasury else "direct",
            value=c.value,
            unit=d.unit,
            timestamp=c.latest_input,
            calculation=c.calculation or d.definition,
            source=src,
            freshness=context["treasury_fresh"] if treasury else context["etf_fresh"],
            quality=quality_summary(
                status="ok"
                if c.status == "ok" and not c.missing_days
                else ("partial" if c.status == "ok" else "missing"),
                notes=notes,
                days_expected=None if treasury else c.days_expected,
                days_present=None if treasury else c.days_present,
                flagged=c.flagged,
                revised=c.revised,
                backfilled=c.backfilled,
                estimated_availability=c.estimated_availability,
            ),
        )
        return {
            "component_id": d.component_id,
            "status": c.status,
            "reason": c.reason,
            "definition": d.definition,
            "evidence": d.evidence,
            "weight": num(d.weight),
            "effective_weight": num(c.effective_weight),
            "reference_scale": num(d.scale),
            "sub_score": num(c.sub_score),
            "contribution": num(c.contribution),
            "window": {"start": c.window_start, "end": c.window_end},
            "inputs": c.inputs,
            "metric": body,
        }

    def _score_payload(self, result: ScoreResult, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "score_id": SCORE_ID,
            "version": SCORE_VERSION,
            "asset": result.asset,
            "as_of": result.as_of,
            "knowledge_time": context["knowledge_time"],
            "evidence_category": "metric",
            "status": result.status,
            "value": num(result.score),
            "unit": "points (−100 … +100)",
            "band": result.band,
            "reason": result.reason,
            "available_weight": num(result.available_weight),
            "calculation": (
                "score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components)"
            ),
            "etf_due_until": context["due"],
            "components": [self._component(c, context) for c in result.components],
            "interpretation_limits": INTERPRETATION_LIMITS,
            "bands_note": BAND_NOTE,
        }

    # ------------------------------------------------------------------ overview

    async def overview(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        assets = []
        for asset in ETF_ASSETS:
            result, context = await self._score(asset, as_of, knowledge_time)
            latest = await self._latest_etf(asset, as_of, knowledge_time)
            five = next(c for c in result.components if c.definition.component_id == "etf_flow_5d")
            assets.append(
                {
                    "asset": asset,
                    "score": {
                        "status": result.status,
                        "value": num(result.score),
                        "band": result.band,
                        "reason": result.reason,
                        "available_weight": num(result.available_weight),
                    },
                    "latest_day": {
                        "date": latest.day if latest else None,
                        "net_flow_usd": num(latest.flow_usd) if latest else None,
                        "net_assets_usd": num(latest.holdings_usd) if latest else None,
                        "quality_status": latest.quality_status if latest else None,
                    },
                    "flow_5d": {
                        "status": five.status,
                        "net_flow_usd": five.inputs.get("net_flow_usd"),
                        "pct_of_net_assets": num(five.value),
                        "window": {"start": five.window_start, "end": five.window_end},
                        "reason": five.reason,
                    },
                    "freshness": context["etf_fresh"].as_dict(),
                }
            )
        return {
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "evidence_category": "metric",
            "assets": assets,
            "source": self.source(sosovalue.PROVIDER_ID, ETF_FLOW_US_SPOT),
            "interpretation_limits": INTERPRETATION_LIMITS,
        }


INTERPRETATION_LIMITS = [
    "ETF flows are direct evidence of creations and redemptions in regulated funds — not of who "
    "bought the fund shares; end investors include retail.",
    "Company treasury data is self-disclosed by listed companies and compiled by the provider "
    "(attributed evidence). No wallet is labelled institutional.",
    "The score describes recent flow direction and size; it is not a forecast, a signal to act, "
    "or investment advice.",
]

NOT_TRACKED = [
    {
        "item": "Global institutional fund flows (e.g. CoinShares weekly digital asset fund flows)",
        "reason": "published as weekly reports without a free API; not ingested",
    },
    {
        "item": "Institutional holdings from 13F filings",
        "reason": "quarterly, filed up to 45 days after quarter end; not ingested in this phase",
    },
    {
        "item": "Hong Kong spot ETFs",
        "reason": "available from SoSoValue but not configured in this phase",
    },
    {
        "item": "Dated purchases for ETH, SOL and XRP treasuries",
        "reason": "no verified free source with dated purchases",
    },
    {
        "item": "US spot ETF history older than one month",
        "reason": "the SoSoValue API serves only the most recent month; older history builds up "
        "as the system runs",
    },
]


def score_definition() -> dict[str, Any]:
    return {
        "score_id": SCORE_ID,
        "version": SCORE_VERSION,
        "evidence_category": "metric",
        "formula": "score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components)",
        "sub_score": "metric ÷ reference scale, capped to −1 … +1",
        "min_coverage": num(MIN_COVERAGE),
        "min_available_weight": num(MIN_AVAILABLE_WEIGHT),
        "components": [
            {
                "component_id": c.component_id,
                "metric_id": c.metric_id,
                "label": c.label,
                "weight": num(c.weight),
                "reference_scale": num(c.scale),
                "unit": c.unit,
                "definition": c.definition,
                "evidence": c.evidence,
            }
            for c in COMPONENTS
        ],
        "bands": [{"lower_bound": num(lower), "label": label} for lower, label in BANDS],
        "bands_note": BAND_NOTE,
        "parameters_note": (
            "Weights, reference scales and bands are judgment parameters chosen by design and "
            "published here; they are not fitted to price outcomes. Changing any of them creates "
            "a new score version."
        ),
        "interpretation_limits": INTERPRETATION_LIMITS,
    }
