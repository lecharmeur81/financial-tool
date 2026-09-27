"""In-process fake of the FRED ``/series/observations`` endpoint — FOR TESTS ONLY.

Serves **synthetic** data through ``httpx2.MockTransport``, to the real adapter and the real HTTP
client, in FRED's documented shape (see ``cfi/providers/fred.py``). Every value is a simple
deterministic linear function of a day/week/month index, so expected metric and score figures can
be computed on paper (see ``tests/integration/macro_support.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx2

from cfi.macro.universe import FRED_SERIES, dataset_by_id
from tests.market_fakes import dumps_exact

NOW = datetime(2026, 9, 20, 9, tzinfo=UTC)  # safely in the past of the real wall clock, so the
# API's as_of=min(given, real utc_now()) clamp (cfi.api.routes.macro._times) never cuts off data
# ingested against this fixture's clock
ANCHOR = date(2020, 1, 1)  # arbitrary fixed origin so weekly/monthly cadences are deterministic

# One (base, daily_drift) pair per FRED series id used by this phase — deliberately simple linear
# series so "value N days/weeks/months from now" is computable by hand in tests.
SERIES_FORMULAS: dict[str, tuple[Decimal, Decimal]] = {
    "DTWEXBGS": (Decimal("100.00"), Decimal("-0.01")),
    "DGS2": (Decimal("3.80"), Decimal("0.001")),
    "DGS10": (Decimal("4.20"), Decimal("0.0005")),
    "DFF": (Decimal("4.33"), Decimal("0")),
    "VIXCLS": (Decimal("16.00"), Decimal("0.01")),
    "SP500": (Decimal("5800.00"), Decimal("1.00")),
    "NASDAQCOM": (Decimal("18000.00"), Decimal("2.00")),
    "DCOILWTICO": (Decimal("70.00"), Decimal("0.02")),
    "RRPONTSYD": (Decimal("0.600"), Decimal("-0.0005")),
    "WALCL": (Decimal("7100000"), Decimal("-500")),
    "WTREGEN": (Decimal("750000"), Decimal("300")),
    "WM2NS": (Decimal("21000.0"), Decimal("2.0")),
    "CPIAUCSL": (Decimal("310.000"), Decimal("0.03")),
    "PCEPI": (Decimal("125.000"), Decimal("0.015")),
    "UNRATE": (Decimal("4.10"), Decimal("0.0002")),
    "M2SL": (Decimal("21500.0"), Decimal("1.5")),
    "DFEDTARU": (Decimal("4.50"), Decimal("0")),
    "DFEDTARL": (Decimal("4.25"), Decimal("0")),
}

MISSING_ON: dict[str, date] = {}  # series_id -> a specific date this fake reports as "."


def value_on(series_id: str, day: date) -> Decimal:
    base, drift = SERIES_FORMULAS[series_id]
    days = (day - ANCHOR).days
    return (base + drift * days).quantize(Decimal("0.000001"))


def _dates_for(series_id: str, start: date, end: date) -> list[date]:
    """Real observation dates a series would carry in [start, end], on its own cadence (see
    ``cfi.macro.universe`` — daily every day, weekly every 7 days from a fixed weekday anchor,
    monthly on the 1st of each month, event the same daily grid as its underlying series)."""
    dataset_id = next(d for d, s in FRED_SERIES.items() if s == series_id)
    period = dataset_by_id(dataset_id).period
    out: list[date] = []
    if period in ("1d", "event"):
        d = start
        while d <= end:
            out.append(d)
            d += timedelta(days=1)
    elif period == "1w":
        # Anchor is itself aligned; step back/forward in whole weeks from it.
        d = ANCHOR
        while d < start:
            d += timedelta(days=7)
        while d > start:
            d -= timedelta(days=7)
        while d <= end:
            if d >= start:
                out.append(d)
            d += timedelta(days=7)
    elif period == "1mo":
        year, month = start.year, start.month
        d = date(year, month, 1)
        while d <= end:
            if d >= start:
                out.append(d)
            month += 1
            if month > 12:
                month = 1
                year += 1
            d = date(year, month, 1)
    else:  # pragma: no cover - every macro dataset uses one of the periods above
        raise AssertionError(f"unhandled period {period!r}")
    return out


@dataclass
class FredFake:
    requests: list[httpx2.Request] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path != "/fred/series/observations":
            return httpx2.Response(
                404,
                content=dumps_exact({"error": "unexpected path"}),
                headers={"content-type": "application/json"},
            )
        q = request.url.params
        series_id = q.get("series_id")
        if series_id not in SERIES_FORMULAS:
            return httpx2.Response(
                400,
                content=dumps_exact({"error": f"unknown series_id {series_id!r}"}),
                headers={"content-type": "application/json"},
            )
        start = date.fromisoformat(q["observation_start"])
        end = date.fromisoformat(q["observation_end"])
        missing_day = MISSING_ON.get(series_id)
        observations = [
            {
                "realtime_start": NOW.date().isoformat(),
                "realtime_end": NOW.date().isoformat(),
                "date": d.isoformat(),
                "value": "." if d == missing_day else str(value_on(series_id, d)),
            }
            for d in _dates_for(series_id, start, end)
        ]
        return httpx2.Response(
            200,
            content=dumps_exact(
                {
                    "realtime_start": NOW.date().isoformat(),
                    "realtime_end": NOW.date().isoformat(),
                    "observation_start": start.isoformat(),
                    "observation_end": end.isoformat(),
                    "units": "lin",
                    "output_type": 1,
                    "file_type": "json",
                    "order_by": "observation_date",
                    "sort_order": "asc",
                    "count": len(observations),
                    "offset": 0,
                    "limit": 100000,
                    "observations": observations,
                }
            ),
            headers={"content-type": "application/json"},
        )
