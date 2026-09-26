"""Derivatives read service (Phase 8): open interest, leverage, funding, basis, liquidations,
options, context, and the Derivatives Health Score — all point-in-time.

Evidence categories (R2): stored venue values are **Observed Data**; every change, ratio, sum and
flag is a **Calculated Metric** with its formula and parameters; the health score is a
**Calculated Metric** built from them. Nothing here is a signal, forecast or recommendation, and
no reading is labelled bullish or bearish.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.errors import NotFoundError
from cfi.derivatives import metrics as m
from cfi.derivatives import score as sc
from cfi.derivatives.queries import DerivativesQueries
from cfi.derivatives.sources import ADAPTERS, ATTRIBUTION, SOURCES, providers_for
from cfi.derivatives.universe import (
    NOT_TRACKED,
    OPTION_ASSETS,
    PERP_ASSETS,
    all_datasets,
    dataset,
)
from cfi.market.service import freshness
from cfi.market.universe import MARKET_CAP_USD_1D, ohlcv_dataset_id
from cfi.providers import coinbase

HISTORY_DAYS_DEFAULT = 7
HISTORY_DAYS_MAX = 30
LOAD_SPAN = timedelta(days=8)  # 7-day windows plus tolerance
FLAGGED = ("suspect", "conflicting")
PRICE_DATASET = ohlcv_dataset_id("usd", "1h")
VENUE_PROVIDER = {"binance": "binance_futures", "okx": "okx_derivatives", "deribit": "deribit"}
POPULATION = {
    "binance": "all accounts on the USDT perpetual",
    "okx": "all accounts holding OKX contracts on the coin",
}
EVIDENCE_NOTE = (
    "Venue values are observed data; changes, ratios, flags and the health score are calculated "
    "metrics with published formulas and parameters. Rising or falling leverage, funding sign, "
    "basis and put/call positioning describe how positions are built — they are not labelled "
    "bullish or bearish, and nothing here is a recommendation."
)


def num(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def pct(value: Decimal | None, places: str = "0.01") -> str | None:
    return None if value is None else format((value * 100).quantize(Decimal(places)), "f")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _points(rows: Sequence[dict[str, Any]]) -> list[m.Point]:
    return [m.Point(r["event_time"], r["value"], r["quality_status"]) for r in rows]


def _by(rows: Sequence[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[str(r[key])].append(r)
    return dict(out)


def _quote(r: dict[str, Any]) -> m.Quote:
    return m.Quote(
        time=r["event_time"],
        instrument=r["instrument"],
        kind=r["instrument_kind"],
        expiry=r["expiry"],
        mark=r["mark_price"],
        index=r["index_price"],
        open_interest_usd=r["open_interest_usd"],
        strike=r["strike"],
        option_type=r["option_type"],
        mark_iv=r["mark_iv"],
        underlying=r["underlying_price"],
        open_interest=r["open_interest_native"],
        volume=r["volume_native"],
    )


@dataclass
class _Bundle:
    """Everything read for one asset at one point in time."""

    asset: str
    as_of: datetime
    knowledge_time: datetime
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    futures: list[dict[str, Any]] = field(default_factory=list)
    chain: list[dict[str, Any]] = field(default_factory=list)
    price: list[m.Point] = field(default_factory=list)
    market_cap: list[m.Point] = field(default_factory=list)


@dataclass
class DerivativesService:
    queries: DerivativesQueries
    enabled_providers: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _asset(asset: str) -> str:
        if asset not in PERP_ASSETS:
            raise NotFoundError(
                f"No derivatives data is tracked for {asset!r} (tracked: {', '.join(PERP_ASSETS)})."
            )
        return asset

    async def _load(self, asset: str, as_of: datetime, knowledge_time: datetime) -> _Bundle:
        b = _Bundle(asset, as_of, knowledge_time)
        start, end = as_of - LOAD_SPAN, as_of + timedelta(seconds=1)
        metrics = ["open_interest", "funding_rate", "long_short_account_ratio", "liquidations"]
        if asset in OPTION_ASSETS:
            metrics.append("volatility_index")
        for metric in metrics:
            b.rows[metric] = await self.queries.observations(
                dataset(metric, asset).dataset_id,
                asset=asset,
                start=start,
                end=end,
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
        if asset in OPTION_ASSETS:
            b.futures = await self.queries.latest_snapshot(
                dataset("futures_curve", asset).dataset_id,
                asset=asset,
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
            b.chain = await self.queries.latest_snapshot(
                dataset("option_chain", asset).dataset_id,
                asset=asset,
                as_of=as_of,
                knowledge_time=knowledge_time,
            )
        closes = await self.queries.hourly_closes(
            PRICE_DATASET,
            subject_ref=coinbase.instrument_ref(coinbase.PRODUCTS[asset]),
            provider_id=coinbase.PROVIDER_ID,
            start=start - timedelta(hours=2),
            end=end,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        b.price = [m.Point(r["event_time"], r["close"], r["quality_status"]) for r in closes]
        caps = await self.queries.observations(
            MARKET_CAP_USD_1D.dataset_id,
            asset=asset,
            start=start - timedelta(days=3),
            end=end,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        b.market_cap = _points(caps)
        return b

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> dict[str, Any]:
        return {
            "perpetual_assets": list(PERP_ASSETS),
            "option_assets": list(OPTION_ASSETS),
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
            "score": sc.definition(),
            "not_tracked": list(NOT_TRACKED),
            "evidence_note": EVIDENCE_NOTE,
        }

    # ------------------------------------------------------------------ asset detail

    async def asset(
        self, *, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        asset = self._asset(asset)
        b = await self._load(asset, as_of, knowledge_time)
        return await self._detail(b)

    async def _detail(self, b: _Bundle) -> dict[str, Any]:
        asset, as_of = b.asset, b.as_of
        oi_by_venue = {
            v: _points(rows) for v, rows in _by(b.rows["open_interest"], "venue").items()
        }
        oi = m.open_interest(oi_by_venue, as_of)
        lev = m.leverage(oi, b.price, b.market_cap)
        fund = m.funding(
            {v: _points(rows) for v, rows in _by(b.rows["funding_rate"], "venue").items()},
            oi,
            as_of,
        )
        liq_rows = _by(b.rows["liquidations"], "subject_ref")
        liq = m.liquidations(
            _points(liq_rows.get(f"PERP:{asset}-USDT:long", [])),
            _points(liq_rows.get(f"PERP:{asset}-USDT:short", [])),
            oi_by_venue.get("okx", []),
            as_of,
        )
        has_options = asset in OPTION_ASSETS
        basis = (
            m.basis(
                [_quote(r) for r in b.futures],
                as_of,
                dataset("futures_curve", asset).freshness_limit,
            )
            if has_options
            else None
        )
        opts = (
            m.options(
                [_quote(r) for r in b.chain], as_of, dataset("option_chain", asset).freshness_limit
            )
            if has_options
            else None
        )
        dvol_points = _points(b.rows.get("volatility_index", []))
        # an hourly candle is final at the end of its hour: judge its age by that time
        dvol_now = m.latest(dvol_points, as_of - m.HOUR, m.LATEST_TOLERANCE)
        components = [
            sc.funding_component(fund),
            sc.basis_component(basis),
            sc.leverage_component(lev),
            sc.liquidation_component(liq),
            sc.volatility_component(asset, dvol_now, has_options),
        ]
        score = sc.compute(asset, as_of, components)
        price_now, price_24h = m.change(b.price, as_of - m.HOUR, m.DAY)
        _, price_7d = m.change(b.price, as_of - m.HOUR, m.WEEK)
        return {
            "asset": asset,
            "as_of": as_of.isoformat(),
            "knowledge_time": b.knowledge_time.isoformat(),
            "evidence_note": EVIDENCE_NOTE,
            "score": self._score(score),
            "conditions": self._conditions(oi, lev, fund, basis, liq, score),
            "open_interest": self._oi(asset, oi, b.price),
            "leverage": self._leverage(lev),
            "funding": self._funding(fund),
            "basis": self._basis(basis),
            "liquidations": self._liquidations(asset, liq),
            "options": self._options(opts),
            "volatility": self._volatility(dvol_points, dvol_now, as_of, has_options),
            "positioning": self._positioning(b),
            "price_context": {
                "source": "Coinbase hourly close (USD)",
                "price": num(None if price_now is None else price_now.value),
                "time": _iso(None if price_now is None else price_now.time + m.HOUR),
                "change_24h_pct": pct(price_24h),
                "change_7d_pct": pct(price_7d),
                "oi_change_24h_pct": pct(oi.change_24h),
                "description": m.price_oi_context(price_24h, oi.change_24h),
                "note": "Describes price and open interest moving together over 24 hours; it "
                "does not say who is buying or selling, or what comes next.",
            },
            "data_quality": await self._quality(b),
            "not_tracked": list(NOT_TRACKED),
        }

    # ------------------------------------------------------------------ sections

    @staticmethod
    def _score(s: sc.ScoreResult) -> dict[str, Any]:
        return {
            "score_id": sc.SCORE_ID,
            "version": s.parameter_version,
            "calculated_at": s.calculated_at.isoformat(),
            "evidence_category": "Calculated Metric",
            "status": s.status,
            "health": num(s.health),
            "stress": num(s.stress),
            "band": s.band,
            "band_note": sc.BAND_NOTE,
            "semantic_note": sc.SEMANTIC_NOTE,
            "available_weight": num(s.available_weight),
            "reason": s.reason,
            "components": [
                {
                    "component_id": c.definition.component_id,
                    "metric_id": c.definition.metric_id,
                    "label": c.definition.label,
                    "weight": num(c.definition.weight),
                    "scale": c.definition.scale,
                    "definition": c.definition.definition,
                    "status": c.status,
                    "reason": c.reason,
                    "value": num(c.value),
                    "value_unit": c.value_unit,
                    "stress": num(c.stress),
                    "effective_weight": num(c.effective_weight),
                    "contribution": num(c.contribution),
                    "calculation": c.calculation,
                    "context": c.context,
                    "inputs": c.inputs,
                }
                for c in s.components
            ],
        }

    @staticmethod
    def _conditions(
        oi: m.OpenInterest,
        lev: m.Leverage,
        fund: m.Funding,
        basis: m.Basis | None,
        liq: m.Liquidations,
        score: sc.ScoreResult,
    ) -> list[dict[str, Any]]:
        def state(known: bool, active: bool) -> str:
            return "unknown" if not known else "active" if active else "inactive"

        recent = [e for e in liq.events if liq.window_start and e.hour >= liq.window_start]
        oi_known = oi.condition != "unknown"
        oi_detail = (
            f"24 h {pct(oi.change_24h) or '—'} %, 7 d {pct(oi.change_7d) or '—'} % "
            f"({m.PARAMETERS['oi_expansion_24h']}; {m.PARAMETERS['oi_expansion_7d']}). "
            f"{oi.reason}"
        )
        lev_detail = lev.reason or (
            f"OI ÷ market cap, 7 d: {pct(lev.change_7d)} % ({m.PARAMETERS['leverage_change_7d']})"
        )
        if basis is None:
            basis_state, basis_detail = "not_applicable", "no Deribit futures for this asset"
        else:
            headline = basis.headline.annualised if basis.headline else None
            basis_state = state(headline is not None, basis.condition.startswith("extreme"))
            basis_detail = (
                f"headline {pct(headline) or '—'} % a year ({m.PARAMETERS['basis_extreme']})"
            )
        stress_detail = (
            "Insufficient data"
            if score.stress is None
            else f"stress {score.stress} (health {score.health}, {score.band}); active from "
            "'elevated stress' (health below 50)"
        )
        return [
            {
                "condition_id": "oi_expansion",
                "label": "Open interest expansion",
                "state": state(oi_known, oi.condition in ("expansion", "mixed")),
                "detail": oi_detail,
            },
            {
                "condition_id": "oi_contraction",
                "label": "Open interest contraction",
                "state": state(oi_known, oi.condition in ("contraction", "mixed")),
                "detail": oi_detail,
            },
            {
                "condition_id": "leverage_expansion",
                "label": "Leverage expansion",
                "state": state(lev.change_7d is not None, lev.condition == "expansion"),
                "detail": lev_detail,
            },
            {
                "condition_id": "leverage_reduction",
                "label": "Leverage reduction",
                "state": state(lev.change_7d is not None, lev.condition == "reduction"),
                "detail": lev_detail,
            },
            {
                "condition_id": "funding_extreme",
                "label": "Funding extreme",
                "state": state(
                    fund.annualised_7d is not None, fund.condition.startswith("extreme")
                ),
                "detail": f"7-day annualised {pct(fund.annualised_7d) or '—'} % "
                f"({m.PARAMETERS['funding_extreme']}); {fund.direction or 'no direction'}",
            },
            {
                "condition_id": "basis_extreme",
                "label": "Basis extreme",
                "state": basis_state,
                "detail": basis_detail,
            },
            {
                "condition_id": "liquidation_event",
                "label": "Liquidation event (last 24 h)",
                "state": state(liq.events_note is None, bool(recent)),
                "detail": liq.events_note
                or f"{len(recent)} event hour(s) in the last 24 h, {len(liq.events)} in 7 days "
                f"({m.PARAMETERS['liquidation_event']})",
            },
            {
                "condition_id": "derivatives_stress",
                "label": "Derivatives stress",
                "state": state(
                    score.stress is not None, score.band in ("elevated stress", "high stress")
                ),
                "detail": stress_detail,
            },
        ]

    @staticmethod
    def _oi(asset: str, oi: m.OpenInterest, price: Sequence[m.Point]) -> dict[str, Any]:
        venues = []
        total_usd = Decimal(0)
        usd_complete = bool(oi.venues)
        for v in oi.venues:
            usd = None
            if v.now is not None and v.now.value is not None:
                close = m.at(price, v.now.time - m.HOUR)
                if close is not None and close.value is not None:
                    usd = v.now.value * close.value
                    total_usd += usd
                else:
                    usd_complete = False
            venues.append(
                {
                    "venue": v.venue,
                    "provider_id": VENUE_PROVIDER.get(v.venue),
                    "open_interest": num(None if v.now is None else v.now.value),
                    "time": _iso(None if v.now is None else v.now.time),
                    "open_interest_usd": num(None if usd is None else usd.quantize(Decimal(1))),
                    "change_24h_pct": pct(v.change_24h),
                    "change_7d_pct": pct(v.change_7d),
                    "status": "ok" if v.now is not None else "no recent value",
                }
            )
        return {
            "unit": asset,
            "total": num(oi.total_now),
            "total_usd": num(total_usd.quantize(Decimal(1)))
            if usd_complete and oi.venues
            else None,
            "usd_note": "coins × Coinbase USD close of the hour ending at the snapshot "
            "(calculated; venues' own USDT values are not used)",
            "change_24h_pct": pct(oi.change_24h),
            "change_7d_pct": pct(oi.change_7d),
            "venues_24h": oi.venues_24h,
            "venues_7d": oi.venues_7d,
            "condition": oi.condition,
            "reason": oi.reason,
            "venues": venues,
            "calculation": "Σ open interest (coins) of the venues with both values ÷ the same "
            "venues' sum 24 h / 7 d earlier − 1",
        }

    @staticmethod
    def _leverage(lev: m.Leverage) -> dict[str, Any]:
        return {
            "status": lev.status,
            "reason": lev.reason,
            "ratio_now_pct": pct(lev.ratio_now, "0.0001"),
            "ratio_week_ago_pct": pct(lev.ratio_week_ago, "0.0001"),
            "change_7d_pct": pct(lev.change_7d),
            "condition": lev.condition,
            "venues": lev.venues,
            "inputs": lev.inputs,
            "calculation": "open interest (coins, Binance + OKX) × Coinbase USD price ÷ market "
            "capitalisation (CoinGecko daily); change = now ÷ 7 days earlier − 1",
            "note": "Leverage building or unwinding is shown without a direction call: it says "
            "how much of the market is held through derivatives, not which way price moves.",
        }

    @staticmethod
    def _funding(f: m.Funding) -> dict[str, Any]:
        return {
            "annualised_7d_pct": pct(f.annualised_7d),
            "weighting": f.weighting,
            "condition": f.condition,
            "direction": f.direction,
            "venues": [
                {
                    "venue": v.venue,
                    "provider_id": VENUE_PROVIDER.get(v.venue),
                    "status": v.status,
                    "reason": v.reason,
                    "settlements_7d": v.settlements,
                    "sum_7d_pct": pct(v.sum_7d, "0.0001"),
                    "annualised_7d_pct": pct(v.annualised_7d),
                    "latest_rate_pct": pct(v.latest_rate, "0.0001"),
                    "latest_time": _iso(v.latest_time),
                    "interval_hours": num(v.interval_hours),
                    "latest_annualised_pct": pct(v.latest_annualised),
                    "largest_gap_hours": num(v.largest_gap_hours),
                }
                for v in f.venues
            ],
            "calculation": "Σ funding rates settled in the last 7 days × 365 ÷ 7 (independent of "
            "the settlement interval; only when no settlement is missing)",
        }

    @staticmethod
    def _basis(b: m.Basis | None) -> dict[str, Any]:
        if b is None:
            return {"status": "not_applicable", "reason": "no Deribit futures for this asset"}

        def point(c: m.CurvePoint) -> dict[str, Any]:
            return {
                "instrument": c.instrument,
                "expiry": _iso(c.expiry),
                "days_to_expiry": num(None if c.days is None else c.days.quantize(Decimal("0.01"))),
                "mark": num(c.mark),
                "index": num(c.index),
                "premium_pct": pct(c.premium, "0.0001"),
                "annualised_pct": pct(c.annualised),
                "open_interest_usd": num(c.open_interest_usd),
            }

        return {
            "status": b.status,
            "reason": b.reason,
            "venue": "deribit",
            "snapshot": _iso(b.snapshot),
            "shape": b.shape,
            "condition": b.condition,
            "headline": None if b.headline is None else point(b.headline),
            "perpetual_premium_pct": pct(b.perpetual_premium, "0.0001"),
            "curve": [point(c) for c in b.curve],
            "calculation": "(future mark ÷ index − 1) × 365 ÷ days to expiry; headline = "
            + m.PARAMETERS["basis_headline"],
        }

    @staticmethod
    def _liquidations(asset: str, liq: m.Liquidations) -> dict[str, Any]:
        return {
            "status": liq.status,
            "reason": liq.reason,
            "venue": "okx",
            "unit": asset,
            "window_start": _iso(liq.window_start),
            "window_end": _iso(liq.window_end),
            "hours_expected": liq.hours_expected,
            "hours_present": liq.hours_present,
            "long_24h": num(liq.long_24h),
            "short_24h": num(liq.short_24h),
            "total_24h": num(liq.total_24h),
            "long_share_pct": pct(liq.long_share, "0.1"),
            "share_of_oi_pct": pct(liq.share_of_oi, "0.0001"),
            "open_interest": num(liq.open_interest),
            "events": [
                {
                    "hour": e.hour.isoformat(),
                    "total": num(e.total),
                    "long": num(e.long),
                    "short": num(e.short),
                    "median_before": num(e.median_before),
                    "share_of_oi_pct": pct(e.share_of_oi, "0.0001"),
                }
                for e in liq.events
            ],
            "events_note": liq.events_note,
            "note": "OKX USDT perpetual only (Binance publishes no liquidation history); a "
            "market-wide total would be larger.",
        }

    @staticmethod
    def _options(o: m.Options | None) -> dict[str, Any]:
        if o is None:
            return {"status": "not_applicable", "reason": "no Deribit options for this asset"}
        return {
            "status": o.status,
            "reason": o.reason,
            "venue": "deribit",
            "snapshot": _iso(o.snapshot),
            "instruments": o.instruments,
            "call_open_interest": num(o.call_oi),
            "put_open_interest": num(o.put_oi),
            "put_call_oi_ratio": num(
                None if o.put_call_oi is None else o.put_call_oi.quantize(Decimal("0.0001"))
            ),
            "call_volume_24h": num(o.call_volume),
            "put_volume_24h": num(o.put_volume),
            "put_call_volume_ratio": num(
                None if o.put_call_volume is None else o.put_call_volume.quantize(Decimal("0.0001"))
            ),
            "notional_open_interest_usd": num(
                None if o.notional_oi_usd is None else o.notional_oi_usd.quantize(Decimal(1))
            ),
            "index": num(o.index),
            "expiry": _iso(o.expiry),
            "expiry_days": num(
                None if o.expiry_days is None else o.expiry_days.quantize(Decimal("0.01"))
            ),
            "forward": num(o.forward),
            "atm_strike": num(o.atm_strike),
            "atm_iv_pct": pct(o.atm_iv),
            "skew_pct_points": pct(o.skew),
            "skew_put": None
            if o.skew_put is None
            else {"strike": num(o.skew_put[0]), "iv_pct": pct(o.skew_put[1])},
            "skew_call": None
            if o.skew_call is None
            else {"strike": num(o.skew_call[0]), "iv_pct": pct(o.skew_call[1])},
            "skew_reason": o.skew_reason,
            "skew_context": None
            if o.skew is None
            else (
                "puts priced at higher implied volatility than calls (demand for downside "
                "protection)"
                if o.skew > 0
                else "calls priced at higher implied volatility than puts (demand for upside "
                "exposure)"
                if o.skew < 0
                else "puts and calls priced alike"
            ),
            "definitions": {
                "put_call_ratio": "put open interest (or 24 h volume) ÷ call, in contracts "
                "(1 contract = 1 coin)",
                "skew": m.PARAMETERS["skew"],
                "atm_iv": "mean mark implied volatility of the call and put at the strike "
                "nearest the forward, same expiry",
            },
        }

    @staticmethod
    def _volatility(
        points: Sequence[m.Point], now: m.Point | None, as_of: datetime, applicable: bool
    ) -> dict[str, Any]:
        if not applicable:
            return {"status": "not_applicable", "reason": "no DVOL index for this asset"}
        if now is None or now.value is None:
            return {"status": "unavailable", "reason": "no recent DVOL value"}
        before = m.at(points, now.time - m.WEEK)
        return {
            "status": "ok",
            "index": "Deribit DVOL (30-day implied volatility)",
            "dvol_pct": pct(now.value),
            "hour": now.time.isoformat(),
            "change_7d_points": None
            if before is None or before.value is None
            else pct(now.value - before.value),
        }

    @staticmethod
    def _positioning(b: _Bundle) -> dict[str, Any]:
        out = []
        for venue, rows in sorted(_by(b.rows["long_short_account_ratio"], "venue").items()):
            points = _points(rows)
            now, change = m.change(points, b.as_of, m.WEEK)
            out.append(
                {
                    "venue": venue,
                    "provider_id": VENUE_PROVIDER.get(venue),
                    "population": POPULATION.get(venue),
                    "ratio": num(None if now is None else now.value),
                    "time": _iso(None if now is None else now.time),
                    "change_7d_pct": pct(change),
                }
            )
        return {
            "long_short_account_ratio": out,
            "note": "Accounts net long ÷ accounts net short. Counts accounts, not position size; "
            "venues count different populations and are never combined. Context only — not "
            "part of the score.",
        }

    async def _quality(self, b: _Bundle) -> dict[str, Any]:
        sources = []
        for item in SOURCES:
            if item.subject != b.asset:
                continue
            spec = item.dataset
            if spec.kind == "quote":
                rows = b.futures if spec.metric == "futures_curve" else b.chain
                latest = max((r["event_time"] for r in rows), default=None)
                flagged = sum(r["quality_status"] in FLAGGED for r in rows)
                backfilled = 0
            else:
                rows = [
                    r
                    for r in b.rows.get(spec.metric, [])
                    if r["source_provider"] == item.provider_id
                ]
                valued = [r for r in rows if r["value"] is not None]
                latest = max((r["event_time"] for r in valued), default=None)
                flagged = sum(r["quality_status"] in FLAGGED for r in rows)
                backfilled = sum(r["pit_reliability"] == "backfilled_latest" for r in rows)
            job = await self.queries.last_job(spec.dataset_id, item.provider_id, b.asset)
            fresh = freshness(
                latest, spec.freshness_limit + (spec.period_length or timedelta(0)), b.as_of
            )
            sources.append(
                {
                    "provider_id": item.provider_id,
                    "provider_name": ADAPTERS[item.provider_id].capabilities.display_name,
                    "dataset_id": spec.dataset_id,
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
            "price_source": f"Coinbase {b.asset}-USD hourly bars (market data)",
            "price_points": len(b.price),
            "market_cap_points": len(b.market_cap),
            "note": "Points loaded for the last 8 days. 'backfilled' = history as the provider "
            "shows it today (may include later corrections); flagged = suspect or conflicting.",
        }

    # ------------------------------------------------------------------ overview

    async def overview(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        assets = []
        for asset in PERP_ASSETS:
            d = await self._detail(await self._load(asset, as_of, knowledge_time))
            assets.append(
                {
                    "asset": asset,
                    "health": d["score"]["health"],
                    "stress": d["score"]["stress"],
                    "band": d["score"]["band"],
                    "score_status": d["score"]["status"],
                    "score_reason": d["score"]["reason"],
                    "open_interest": d["open_interest"]["total"],
                    "open_interest_usd": d["open_interest"]["total_usd"],
                    "oi_change_24h_pct": d["open_interest"]["change_24h_pct"],
                    "oi_condition": d["open_interest"]["condition"],
                    "funding_annualised_7d_pct": d["funding"]["annualised_7d_pct"],
                    "basis_annualised_pct": (d["basis"].get("headline") or {}).get(
                        "annualised_pct"
                    ),
                    "liquidations_24h": d["liquidations"]["total_24h"],
                    "dvol_pct": d["volatility"].get("dvol_pct"),
                    "active_conditions": [
                        c["label"] for c in d["conditions"] if c["state"] == "active"
                    ],
                }
            )
        return {
            "as_of": as_of.isoformat(),
            "knowledge_time": knowledge_time.isoformat(),
            "assets": assets,
            "evidence_note": EVIDENCE_NOTE,
        }

    # ------------------------------------------------------------------ history

    async def history(
        self,
        *,
        asset: str,
        days: int,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        asset = self._asset(asset)
        days = max(1, min(days, HISTORY_DAYS_MAX))
        start, end = as_of - timedelta(days=days), as_of + timedelta(seconds=1)

        async def rows(metric: str) -> list[dict[str, Any]]:
            if metric == "volatility_index" and asset not in OPTION_ASSETS:
                return []
            return await self.queries.observations(
                dataset(metric, asset).dataset_id,
                asset=asset,
                start=start,
                end=end,
                as_of=as_of,
                knowledge_time=knowledge_time,
            )

        def series(items: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
            return {
                k: [
                    {
                        "time": r["event_time"].isoformat(),
                        "value": num(r["value"]),
                        "quality_status": r["quality_status"],
                    }
                    for r in v
                ]
                for k, v in _by(items, key).items()
            }

        oi = await rows("open_interest")
        # the aggregate only covers hours at which every venue reported (never a mixed set)
        per_hour: dict[datetime, dict[str, Decimal]] = defaultdict(dict)
        for r in oi:
            if r["value"] is not None:
                per_hour[r["event_time"]][r["venue"]] = r["value"]
        venues = sorted({r["venue"] for r in oi})
        aggregate = [
            {"time": t.isoformat(), "value": num(sum(v.values(), Decimal(0)))}
            for t, v in sorted(per_hour.items())
            if len(v) == len(venues)
        ]
        closes = await self.queries.hourly_closes(
            PRICE_DATASET,
            subject_ref=coinbase.instrument_ref(coinbase.PRODUCTS[asset]),
            provider_id=coinbase.PROVIDER_ID,
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        return {
            "asset": asset,
            "as_of": as_of.isoformat(),
            "start": start.isoformat(),
            "days": days,
            "open_interest": {
                "unit": asset,
                "venues": series(oi, "venue"),
                "aggregate": aggregate,
                "aggregate_venues": venues,
            },
            "funding_rate": {
                "unit": "ratio per interval",
                "venues": series(await rows("funding_rate"), "venue"),
            },
            "long_short_account_ratio": {
                "unit": "ratio",
                "venues": series(await rows("long_short_account_ratio"), "venue"),
            },
            "liquidations": {
                "unit": asset,
                "venue": "okx",
                "sides": {
                    k.rsplit(":", 1)[-1]: v
                    for k, v in series(await rows("liquidations"), "subject_ref").items()
                },
            },
            "volatility_index": {
                "unit": "ratio",
                "points": [
                    {"time": r["event_time"].isoformat(), "value": num(r["value"])}
                    for r in await rows("volatility_index")
                ],
            },
            "price": {
                "unit": "usd",
                "source": "Coinbase hourly close",
                "points": [
                    # the close of the bar starting at t is the price at t + 1 h
                    {"time": (r["event_time"] + m.HOUR).isoformat(), "value": num(r["close"])}
                    for r in closes
                    if r["close"] is not None
                ],
            },
            "providers": {
                metric: providers_for(dataset(metric, asset).dataset_id, asset)
                for metric in (
                    "open_interest",
                    "funding_rate",
                    "long_short_account_ratio",
                    "liquidations",
                )
            },
        }
