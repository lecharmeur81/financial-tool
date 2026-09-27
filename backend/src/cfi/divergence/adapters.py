"""Divergence Engine data adapters (Phase 13): normalize each domain's own already-tested read
service into a plain ``cfi.divergence.metrics.Series`` (a list of ``SeriesPoint``), so the engine's
comparison logic never depends on any domain's internal storage details — only on its public
service contract, same as ``cfi.whales.service`` already composing ``InstitutionalService``.

Every adapter is read-only and computes nothing new beyond parsing the already-published decimal
strings back into ``Decimal`` and normalizing each domain's own time representation (some return a
raw ``datetime``/``date``, some an ISO string) into a timezone-aware ``datetime``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from cfi.derivatives.queries import DerivativesQueries
from cfi.derivatives.service import DerivativesService
from cfi.derivatives.universe import PERP_ASSETS
from cfi.divergence.metrics import Series, SeriesPoint
from cfi.divergence.universe import LOAD_SPAN_DAYS
from cfi.institutional.queries import InstitutionalQueries
from cfi.institutional.service import InstitutionalService
from cfi.institutional.universe import ETF_ASSETS
from cfi.liquidity.queries import LiquidityQueries
from cfi.liquidity.service import LiquidityService
from cfi.macro import metrics as macro_metrics
from cfi.macro.queries import MacroQueries
from cfi.macro.universe import (
    FED_BALANCE_SHEET,
    REVERSE_REPO,
    TREASURY_GENERAL_ACCOUNT,
    US_SUBJECT,
)
from cfi.market.queries import MarketQueries
from cfi.market.sources import VENUES
from cfi.market.universe import ASSET_SYMBOLS, ohlcv_dataset_id
from cfi.market_structure.queries import MarketStructureQueries
from cfi.market_structure.service import MarketStructureService
from cfi.retail.queries import RetailQueries
from cfi.retail.service import RetailService
from cfi.whales.queries import WhaleQueries
from cfi.whales.service import WhaleService
from cfi.whales.universe import WHALE_ASSETS

PRICE_VENUE = VENUES["coinbase"]  # same "one venue, one benchmark" precedent as market_structure
PRICE_DATASET_ID = ohlcv_dataset_id(PRICE_VENUE.quote, "1d")


def _dt(value: Any) -> datetime:
    """Normalize whatever time representation a domain service returned into an aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise TypeError(f"Cannot interpret {value!r} as a time.")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _range(as_of: datetime) -> tuple[datetime, datetime]:
    return as_of - timedelta(days=LOAD_SPAN_DAYS), as_of


@dataclass
class Adapters:
    """Constructed once per request from the shared DB engine — mirrors every other module's
    ``*Service(queries, enabled_providers)`` construction pattern; nothing here has its own
    provider list because nothing here ingests (``divergence/universe.py`` docstring)."""

    engine: Any

    def institutional(self) -> InstitutionalService:
        return InstitutionalService(InstitutionalQueries(self.engine))

    def whales(self) -> WhaleService:
        return WhaleService(WhaleQueries(self.engine))

    def retail(self) -> RetailService:
        return RetailService(RetailQueries(self.engine))

    def liquidity(self) -> LiquidityService:
        return LiquidityService(LiquidityQueries(self.engine))

    def derivatives(self) -> DerivativesService:
        return DerivativesService(DerivativesQueries(self.engine))

    def market_structure(self) -> MarketStructureService:
        return MarketStructureService(MarketStructureQueries(self.engine))

    def market(self) -> MarketQueries:
        return MarketQueries(self.engine)

    def macro(self) -> MacroQueries:
        return MacroQueries(self.engine)

    # ------------------------------------------------------------------ price

    async def price_close(self, asset: str, as_of: datetime) -> Series:
        """Daily close price on Coinbase (Phase 5's priority-10 default venue, native daily bars
        for BTC/ETH/SOL/XRP) — the same canonical price source Phase 12 established."""
        if asset not in ASSET_SYMBOLS or asset not in PRICE_VENUE.instruments:
            return []
        instrument = PRICE_VENUE.instruments[asset]
        mq = self.market()
        series_id = await mq.series_id(PRICE_DATASET_ID, instrument)
        if series_id is None:
            return []
        start, end = _range(as_of)
        rows = await mq.bars(series_id, PRICE_VENUE.provider_id, start, end, as_of)
        return [
            SeriesPoint(
                _dt(r["event_time"]), _decimal(r.get("close")), r.get("quality_status", "ok")
            )
            for r in rows
            if r.get("close") is not None
        ]

    # ------------------------------------------------------------------ institutional

    async def institutional_net_flow(
        self, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> Series:
        """Daily institutional US spot ETF net flow (a single asset, or 'ALL' to sum across every
        tracked ETF asset)."""
        assets = [a for a in (list(ETF_ASSETS) if asset == "ALL" else [asset]) if a in ETF_ASSETS]
        start, end = (as_of - timedelta(days=LOAD_SPAN_DAYS)).date(), as_of.date()
        svc = self.institutional()
        return await self._institutional_buckets(svc, assets, start, end, as_of, knowledge_time)

    @staticmethod
    async def _institutional_buckets(
        svc: InstitutionalService,
        assets: list[str],
        start: date,
        end: date,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> Series:
        by_day: dict[date, Decimal] = {}
        status_by_day: dict[date, str] = {}
        for a in assets:
            resp = await svc.etf_flows(
                asset=a,
                interval="1d",
                start=start,
                end=end,
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
            for bucket in resp.get("buckets", []):
                raw_start = bucket["start"]
                d = raw_start if isinstance(raw_start, date) else date.fromisoformat(raw_start)
                v = _decimal(bucket.get("net_flow_usd"))
                if v is not None:
                    by_day[d] = by_day.get(d, Decimal(0)) + v
                status = (bucket.get("quality") or {}).get("status") or "ok"
                # worst-of across assets for the same day (any non-'ok' asset marks the day)
                if status_by_day.get(d, "ok") == "ok":
                    status_by_day[d] = status
        return [SeriesPoint(_dt(d), by_day[d], status_by_day.get(d, "ok")) for d in sorted(by_day)]

    # ------------------------------------------------------------------ whales

    async def whale_net_flow(self, asset: str, as_of: datetime, knowledge_time: datetime) -> Series:
        """Daily whale exchange net flow (exchange inflow − exchange outflow); a single asset, or
        'ALL' to sum across every tracked whale asset (BTC, ETH)."""
        assets = list(WHALE_ASSETS) if asset == "ALL" else [a for a in [asset] if a in WHALE_ASSETS]
        start, end = (as_of - timedelta(days=LOAD_SPAN_DAYS)).date(), as_of.date()
        svc = self.whales()
        by_day: dict[date, Decimal] = {}
        for a in assets:
            resp = await svc.flows(
                asset=a, start=start, end=end, as_of=as_of, knowledge_time=knowledge_time
            )
            for row in resp.get("days", []):
                v = _decimal(row.get("netflow"))
                if v is not None:
                    raw_date = row["date"]
                    d = raw_date if isinstance(raw_date, date) else date.fromisoformat(raw_date)
                    by_day[d] = by_day.get(d, Decimal(0)) + v
        return [SeriesPoint(_dt(d), v, "ok") for d, v in sorted(by_day.items())]

    # ------------------------------------------------------------------ retail

    async def retail_small_tx_count(self, as_of: datetime, knowledge_time: datetime) -> Series:
        """BTC small-output daily transaction count — a retail-activity PROXY, never labelled
        retail-exclusive data (see ``cfi.retail`` module docstring)."""
        svc = self.retail()
        resp = await svc.history(
            series="small_transaction_count",
            days=LOAD_SPAN_DAYS,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        return [
            SeriesPoint(_dt(p["time"]), _decimal(p["value"]), p.get("quality_status", "ok"))
            for p in resp["points"]
        ]

    async def retail_meme_trending_count(self, as_of: datetime, knowledge_time: datetime) -> Series:
        """Count of tracked meme coins currently trending — a retail-ATTENTION proxy, never a
        capital-flow measure (``divergence/universe.py``'s ``NOT_TRACKED`` note)."""
        svc = self.retail()
        resp = await svc.history(
            series="meme_trending_count",
            days=LOAD_SPAN_DAYS,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        return [
            SeriesPoint(_dt(p["time"]), _decimal(p["value"]), p.get("quality_status", "ok"))
            for p in resp["points"]
        ]

    # ------------------------------------------------------------------ liquidity / stablecoins

    async def stablecoin_supply(
        self, subject: str, as_of: datetime, knowledge_time: datetime
    ) -> Series:
        svc = self.liquidity()
        resp = await svc.history(
            subject=subject, days=LOAD_SPAN_DAYS, as_of=as_of, knowledge_time=knowledge_time
        )
        return [
            SeriesPoint(_dt(p["time"]), _decimal(p["value"]), p.get("quality_status", "ok"))
            for p in resp["points"]
        ]

    # ------------------------------------------------------------------ derivatives

    async def _derivatives_history(
        self, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        if asset not in PERP_ASSETS:
            return {}
        svc = self.derivatives()
        return await svc.history(
            asset=asset, days=LOAD_SPAN_DAYS, as_of=as_of, knowledge_time=knowledge_time
        )

    @staticmethod
    def _oi_from_history(resp: dict[str, Any]) -> Series:
        agg = resp.get("open_interest", {}).get("aggregate", [])
        return [
            SeriesPoint(_dt(p["time"]), _decimal(p["value"]))
            for p in agg
            if p.get("value") is not None
        ]

    @staticmethod
    def _funding_from_history(resp: dict[str, Any]) -> Series:
        venues = resp.get("funding_rate", {}).get("venues", {})
        by_time: dict[datetime, list[Decimal]] = {}
        for points in venues.values():
            for p in points:
                v = _decimal(p.get("value"))
                if v is not None:
                    by_time.setdefault(_dt(p["time"]), []).append(v)
        return [
            SeriesPoint(t, sum(vals, Decimal(0)) / len(vals)) for t, vals in sorted(by_time.items())
        ]

    @staticmethod
    def _leverage_skew_from_history(resp: dict[str, Any]) -> Series:
        """Mean |long/short account ratio − 1| across reporting venues: a directional-crowding
        proxy for implied leverage skew (distinct from raw open-interest level)."""
        venues = resp.get("long_short_account_ratio", {}).get("venues", {})
        by_time: dict[datetime, list[Decimal]] = {}
        for points in venues.values():
            for p in points:
                v = _decimal(p.get("value"))
                if v is not None:
                    by_time.setdefault(_dt(p["time"]), []).append(abs(v - 1))
        return [
            SeriesPoint(t, sum(vals, Decimal(0)) / len(vals)) for t, vals in sorted(by_time.items())
        ]

    async def open_interest(self, asset: str, as_of: datetime, knowledge_time: datetime) -> Series:
        history = await self._derivatives_history(asset, as_of, knowledge_time)
        return self._oi_from_history(history)

    async def funding_rate(self, asset: str, as_of: datetime, knowledge_time: datetime) -> Series:
        history = await self._derivatives_history(asset, as_of, knowledge_time)
        return self._funding_from_history(history)

    async def leverage_skew(self, asset: str, as_of: datetime, knowledge_time: datetime) -> Series:
        history = await self._derivatives_history(asset, as_of, knowledge_time)
        return self._leverage_skew_from_history(history)

    # ------------------------------------------------------------------ market structure (TOTAL)

    async def total_market_cap(self, as_of: datetime, knowledge_time: datetime) -> Series:
        svc = self.market_structure()
        resp = await svc.history(
            series="total_market_cap",
            days=LOAD_SPAN_DAYS,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        return [
            SeriesPoint(_dt(p["time"]), _decimal(p["value"]), p.get("quality_status", "ok"))
            for p in resp["points"]
        ]

    # ------------------------------------------------------------------ macro (US net liquidity)

    async def macro_net_liquidity(self, as_of: datetime, knowledge_time: datetime) -> Series:
        """US net liquidity proxy (Fed balance sheet − TGA − reverse repo), recomputed at daily
        resolution by re-running ``cfi.macro.metrics.us_net_liquidity`` against the same three
        already-loaded FRED point series at each day of the lookback window (no re-querying the
        database per day — the three series are weekly/daily FRED data, loaded once)."""
        mq = self.macro()
        start, end = _range(as_of)

        async def points(dataset_id: str) -> list[macro_metrics.Point]:
            rows = await mq.observations(
                dataset_id,
                subject=US_SUBJECT,
                start=start,
                end=end + timedelta(seconds=1),
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
            return [
                macro_metrics.Point(r["event_time"], r["value"], r["quality_status"]) for r in rows
            ]

        fed = await points(FED_BALANCE_SHEET.dataset_id)
        tga = await points(TREASURY_GENERAL_ACCOUNT.dataset_id)
        repo = await points(REVERSE_REPO.dataset_id)
        out: Series = []
        day = start
        while day <= as_of:
            reading = macro_metrics.us_net_liquidity(fed, tga, repo, day)
            if reading.status == "ok" and reading.net_liquidity_usd_b is not None:
                out.append(SeriesPoint(day, reading.net_liquidity_usd_b, "ok"))
            day += timedelta(days=1)
        return out
