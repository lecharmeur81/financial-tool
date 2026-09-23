"""Market-data read service: assembles bars, gaps, freshness and provenance for the API.

Everything returned is observed data (L1) or a transparent OHLCV roll-up of it (4h from 1h where
a venue does not publish 4h) — labelled as such. No metrics, signals or advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from cfi.core.errors import NotFoundError
from cfi.core.time import floor_to_period, parse_period
from cfi.ingestion.detection import expected_points
from cfi.market.queries import MarketQueries
from cfi.market.sources import ADAPTERS, VENUES, Venue
from cfi.market.universe import (
    ASSET_SYMBOLS,
    ASSETS,
    BAR_AVAILABILITY_DELAY,
    FRESHNESS,
    MARKET_CAP_USD,
    SPOT_PRICE_USD,
    TIMEFRAMES,
    ohlcv_dataset_id,
)
from cfi.providers import coingecko

MAX_BARS = 1500
MAX_LISTED_GAPS = 50
FreshnessStatus = Literal["fresh", "stale", "no_data"]


# --------------------------------------------------------------------------- pure helpers


@dataclass(frozen=True, slots=True)
class Freshness:
    status: FreshnessStatus
    latest_time: datetime | None
    age_seconds: int | None
    limit_seconds: int


def freshness(latest: datetime | None, limit: timedelta, as_of: datetime) -> Freshness:
    if latest is None:
        return Freshness("no_data", None, None, int(limit.total_seconds()))
    age = as_of - latest
    return Freshness(
        "stale" if age > limit else "fresh",
        latest,
        max(0, int(age.total_seconds())),
        int(limit.total_seconds()),
    )


def resolve_range(
    period: timedelta,
    as_of: datetime,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> tuple[datetime, datetime]:
    """[start, end) aligned to the bar grid, never beyond the current (unfinished) bar."""
    latest_end = floor_to_period(as_of, period)
    end = latest_end if end is None else min(floor_to_period(end, period), latest_end)
    if start is None:
        start = end - limit * period
    else:
        start = max(floor_to_period(start, period), end - MAX_BARS * period)
    return start, end


@dataclass(frozen=True, slots=True)
class GapReport:
    expected: int
    present: int
    missing_times: list[datetime]
    not_loaded: int


def gap_report(
    start: datetime,
    end: datetime,
    period: timedelta,
    as_of: datetime,
    present: set[datetime],
    coverage_start: datetime | None,
) -> GapReport:
    """Which bars should exist in the range and are absent (missing), versus bars before the
    first stored bar (history not loaded yet / before the instrument existed)."""
    final_by = as_of - BAR_AVAILABILITY_DELAY
    expected = expected_points(start, end, period, not_after=final_by)
    if coverage_start is None:
        return GapReport(0, 0, [], len(expected))
    in_coverage = [t for t in expected if t >= coverage_start]
    missing = [t for t in in_coverage if t not in present]
    return GapReport(
        expected=len(in_coverage),
        present=len(in_coverage) - len(missing),
        missing_times=missing,
        not_loaded=len(expected) - len(in_coverage),
    )


def _num(value: Any) -> str | None:
    """Exact decimals travel as strings (JSON numbers would lose precision)."""
    if value is None:
        return None
    return format(value, "f") if isinstance(value, Decimal) else str(value)


def derived_bar(row: dict[str, Any], parts_expected: int, source_tf: str) -> dict[str, Any]:
    """A roll-up bar is only shown when all its component bars exist; otherwise it is reported
    as missing (never a partial candle that would misstate the high, low or volume)."""
    present = int(row["parts_present"])
    flagged = int(row["parts_flagged"])
    bar: dict[str, Any] = {"time": row["event_time"], "revision": int(row["revision"] or 0)}
    if present < parts_expected:
        return {
            **bar,
            **dict.fromkeys(
                ("open", "high", "low", "close", "volume_base", "volume_quote", "trade_count")
            ),
            "quality_status": "missing",
            "quality_note": (
                f"incomplete: {present} of {parts_expected} {source_tf} bars available"
            ),
        }
    status, note = "ok", None
    if flagged:
        status = "suspect"
        note = f"{flagged} of {parts_expected} component {source_tf} bars are flagged"
    return {
        **bar,
        "open": _num(row["open"]),
        "high": _num(row["high"]),
        "low": _num(row["low"]),
        "close": _num(row["close"]),
        "volume_base": _num(row["volume_base"]),
        "volume_quote": _num(row["volume_quote"]),
        "trade_count": row["trade_count"],
        "quality_status": status,
        "quality_note": note,
    }


def stored_bar(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": row["event_time"],
        "open": _num(row["open"]),
        "high": _num(row["high"]),
        "low": _num(row["low"]),
        "close": _num(row["close"]),
        "volume_base": _num(row["volume_base"]),
        "volume_quote": _num(row["volume_quote"]),
        "trade_count": row["trade_count"],
        "quality_status": row["quality_status"],
        "quality_note": row["quality_note"],
        "revision": int(row["revision"]),
    }


# --------------------------------------------------------------------------- service


@dataclass
class MarketService:
    queries: MarketQueries
    enabled_providers: list[str] = field(default_factory=list)

    def venue(self, venue_id: str) -> Venue:
        try:
            return VENUES[venue_id]
        except KeyError:
            raise NotFoundError(f"Unknown venue '{venue_id}'.") from None

    def _source(self, provider_id: str) -> dict[str, Any]:
        caps = ADAPTERS[provider_id].capabilities
        return {
            "provider_id": provider_id,
            "provider_name": caps.display_name,
            "original_source": caps.original_source,
            "enabled": provider_id in self.enabled_providers,
            "attribution": coingecko.ATTRIBUTION if provider_id == coingecko.PROVIDER_ID else None,
        }

    def catalog(self) -> dict[str, Any]:
        venues = []
        for venue in sorted(VENUES.values(), key=lambda v: v.priority):
            timeframes = []
            for tf in TIMEFRAMES:
                if tf in venue.native_timeframes:
                    timeframes.append({"timeframe": tf, "source": "native", "derived_from": None})
                elif tf in venue.derived_timeframes:
                    timeframes.append(
                        {
                            "timeframe": tf,
                            "source": "derived",
                            "derived_from": venue.derived_timeframes[tf][0],
                        }
                    )
            venues.append(
                {
                    "venue_id": venue.venue_id,
                    "display_name": venue.display_name,
                    "quote": venue.quote,
                    "instruments": venue.instruments,
                    "timeframes": timeframes,
                    "source": self._source(venue.provider_id),
                }
            )
        return {
            "assets": [{"symbol": a.symbol, "name": a.name} for a in ASSETS],
            "timeframes": list(TIMEFRAMES),
            "venues": venues,
            "market_cap_source": self._source(coingecko.PROVIDER_ID),
        }

    async def bars(
        self,
        *,
        asset: str,
        timeframe: str,
        venue_id: str,
        as_of: datetime,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> dict[str, Any]:
        if asset not in ASSET_SYMBOLS:
            raise NotFoundError(f"Unknown asset '{asset}'.")
        if timeframe not in TIMEFRAMES:
            raise NotFoundError(f"Unknown timeframe '{timeframe}'.")
        venue = self.venue(venue_id)
        if asset not in venue.instruments:
            raise NotFoundError(f"{venue.display_name} has no instrument for {asset}.")
        instrument = venue.instruments[asset]
        period = parse_period(timeframe)
        assert period is not None  # noqa: S101 — bar timeframes are fixed periods
        range_start, range_end = resolve_range(period, as_of, start, end, limit)

        derivation = None
        if timeframe in venue.native_timeframes:
            source_tf, parts = timeframe, 1
        elif timeframe in venue.derived_timeframes:
            source_tf, parts = venue.derived_timeframes[timeframe]
            derivation = {
                "from_timeframe": source_tf,
                "bars_per_bucket": parts,
                "method": (
                    f"OHLCV roll-up of {parts} consecutive {source_tf} bars from the same venue: "
                    "open = first, high = max, low = min, close = last, volume = sum. Shown only "
                    f"when all {parts} bars exist; otherwise reported as missing."
                ),
            }
        else:
            raise NotFoundError(f"{venue.display_name} does not provide {timeframe} bars.")

        dataset_id = ohlcv_dataset_id(venue.quote, source_tf)
        series_id = await self.queries.series_id(dataset_id, instrument)
        rows: list[dict[str, Any]] = []
        coverage: dict[str, Any] = {"earliest": None, "latest": None, "last_ingested_at": None}
        if series_id is not None:
            coverage = await self.queries.coverage(series_id, venue.provider_id, as_of)
            if derivation is None:
                rows = [
                    stored_bar(r)
                    for r in await self.queries.bars(
                        series_id, venue.provider_id, range_start, range_end, as_of
                    )
                ]
            else:
                rolled = await self.queries.rollup(
                    series_id, venue.provider_id, period, range_start, range_end, as_of
                )
                rows = [derived_bar(r, parts, source_tf) for r in rolled]
                # a bucket whose component bars have not all closed yet is not a bar yet
                final_by = as_of - BAR_AVAILABILITY_DELAY
                rows = [r for r in rows if r["time"] + period <= final_by]

        coverage_start = coverage["earliest"]
        if derivation is not None and coverage_start is not None:
            # the first bucket containing the first stored component bar
            coverage_start = floor_to_period(coverage_start, period)
            if coverage_start < coverage["earliest"]:
                coverage_start += period
        present = {r["time"] for r in rows if r["quality_status"] != "missing"}
        gaps = gap_report(range_start, range_end, period, as_of, present, coverage_start)
        latest = coverage["latest"]
        if derivation is not None:
            complete = [r["time"] for r in rows if r["quality_status"] != "missing"]
            latest = max(complete) if complete else None
        fresh = freshness(latest, FRESHNESS[timeframe], as_of)

        last_job = await self.queries.last_job(dataset_id, venue.provider_id, asset)
        backfill = await self.queries.backfill(dataset_id, venue.provider_id, asset)
        counts = {
            status: sum(1 for r in rows if r["quality_status"] == status)
            for status in ("suspect", "conflicting")
        }
        warnings = _bar_warnings(
            venue, timeframe, gaps, fresh, counts, backfill, last_job, derivation, self
        )
        return {
            "evidence_category": "observed",
            "as_of": as_of,
            "asset": asset,
            "timeframe": timeframe,
            "instrument": {
                "venue_id": venue.venue_id,
                "venue_name": venue.display_name,
                "instrument_id": instrument,
                "price_unit": venue.quote,
                "volume_unit": asset,
                "quote_volume_unit": venue.quote,
            },
            "source": self._source(venue.provider_id),
            "derivation": derivation,
            "range": {"start": range_start, "end": range_end},
            "bars": rows,
            "quality": {
                "expected": gaps.expected,
                "present": gaps.present,
                "missing": len(gaps.missing_times),
                "missing_times": gaps.missing_times[:MAX_LISTED_GAPS],
                "not_loaded": gaps.not_loaded,
                "coverage_start": coverage_start,
                "suspect": counts["suspect"],
                "conflicting": counts["conflicting"],
                "revised": sum(1 for r in rows if r["revision"] > 0),
            },
            "freshness": {
                "status": fresh.status,
                "latest_bar_time": fresh.latest_time,
                "age_seconds": fresh.age_seconds,
                "limit_seconds": fresh.limit_seconds,
                "last_ingested_at": coverage["last_ingested_at"],
            },
            "ingestion": {"last_run": last_job, "backfill": backfill},
            "warnings": warnings,
        }

    async def overview(self, as_of: datetime) -> dict[str, Any]:
        coinbase_venue = VENUES["coinbase"]
        prices = await self.queries.latest_scalars(
            SPOT_PRICE_USD.dataset_id, list(coinbase_venue.instruments.values()), as_of
        )
        caps = await self.queries.latest_scalars(
            MARKET_CAP_USD.dataset_id, list(ASSET_SYMBOLS), as_of
        )
        bars_by_venue = {
            v.venue_id: await self.queries.latest_bars(
                ohlcv_dataset_id(v.quote, "1m"), list(v.instruments.values()), as_of
            )
            for v in VENUES.values()
        }
        assets = []
        for asset in ASSETS:
            price_row = prices.get(coinbase_venue.instruments[asset.symbol])
            cap_row = caps.get(asset.symbol)
            latest_bars = []
            for venue in sorted(VENUES.values(), key=lambda v: v.priority):
                row = bars_by_venue[venue.venue_id].get(venue.instruments[asset.symbol])
                fresh = freshness(row["event_time"] if row else None, FRESHNESS["1m"], as_of)
                latest_bars.append(
                    {
                        "venue_id": venue.venue_id,
                        "venue_name": venue.display_name,
                        "instrument_id": venue.instruments[asset.symbol],
                        "timeframe": "1m",
                        "bar_time": row["event_time"] if row else None,
                        "close": _num(row["close"]) if row else None,
                        "unit": venue.quote,
                        "quality_status": row["quality_status"] if row else None,
                        "ingested_at": row["ingested_at"] if row else None,
                        "freshness": fresh.status,
                        "age_seconds": fresh.age_seconds,
                        "source": self._source(venue.provider_id),
                    }
                )
            assets.append(
                {
                    "symbol": asset.symbol,
                    "name": asset.name,
                    "last_trade": _scalar(
                        price_row,
                        SPOT_PRICE_USD.freshness_limit,
                        as_of,
                        self._source(coinbase_venue.provider_id),
                        instrument=coinbase_venue.instruments[asset.symbol],
                    ),
                    "latest_bars": latest_bars,
                    "market_cap": _scalar(
                        cap_row,
                        MARKET_CAP_USD.freshness_limit,
                        as_of,
                        self._source(coingecko.PROVIDER_ID),
                    ),
                }
            )
        return {"evidence_category": "observed", "as_of": as_of, "assets": assets}


def _scalar(
    row: dict[str, Any] | None,
    limit: timedelta,
    as_of: datetime,
    source: dict[str, Any],
    instrument: str | None = None,
) -> dict[str, Any]:
    fresh = freshness(row["event_time"] if row else None, limit, as_of)
    return {
        "value": _num(row["value"]) if row else None,
        "unit": row["unit"] if row else None,
        "time": row["event_time"] if row else None,
        "ingested_at": row["ingested_at"] if row else None,
        "quality_status": row["quality_status"] if row else None,
        "quality_note": row["quality_note"] if row else None,
        "instrument_id": instrument,
        "freshness": fresh.status,
        "age_seconds": fresh.age_seconds,
        "limit_seconds": fresh.limit_seconds,
        "source": source,
    }


def _bar_warnings(
    venue: Venue,
    timeframe: str,
    gaps: GapReport,
    fresh: Freshness,
    counts: dict[str, int],
    backfill: dict[str, Any] | None,
    last_job: dict[str, Any] | None,
    derivation: dict[str, Any] | None,
    service: MarketService,
) -> list[str]:
    warnings = []
    if venue.provider_id not in service.enabled_providers:
        warnings.append(f"{venue.display_name} ingestion is disabled in settings.")
    if fresh.status == "no_data":
        warnings.append(f"No {timeframe} data stored yet for this instrument.")
    elif fresh.status == "stale":
        warnings.append(
            f"Data is stale: newest bar is {fresh.age_seconds} s old "
            f"(limit {fresh.limit_seconds} s)."
        )
    if gaps.missing_times:
        warnings.append(f"{len(gaps.missing_times)} bar(s) missing in this range.")
    if gaps.not_loaded and fresh.status != "no_data":
        state = (
            "history backfill in progress"
            if backfill is not None and not backfill["complete"]
            else "no earlier data stored"
        )
        warnings.append(f"{gaps.not_loaded} earlier bar(s) in this range not loaded ({state}).")
    if counts["suspect"]:
        warnings.append(f"{counts['suspect']} bar(s) failed a consistency check (suspect).")
    if counts["conflicting"]:
        warnings.append(f"{counts['conflicting']} bar(s) conflict with another provider.")
    if last_job is not None and last_job["status"] == "failed":
        warnings.append(
            f"Last ingestion failed: {last_job['error_code']} — {last_job['error_detail']}"
        )
    if derivation is not None:
        warnings.append(
            f"{venue.display_name} does not publish {timeframe} bars; these are rolled up from "
            f"{derivation['from_timeframe']} bars."
        )
    return warnings
