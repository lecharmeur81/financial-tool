"""``MarketStructureService.overview_score`` (the score-only path used by the regime and
similarity snapshot gatherers) against the full ``MarketStructureService.overview``.

The fake stands in for ``cfi.market_structure.queries.MarketStructureQueries`` and re-implements
only the documented time-range semantics (``start <= event_time < end``). It proves the service
passes the right cut-offs and ranges and that both paths agree on every shared key, in the same
order. It does NOT prove the production SQL; that needs a database-backed test.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from cfi.market_structure import metrics as m
from cfi.market_structure import service as ms_service
from cfi.market_structure.queries import MarketStructureQueries
from cfi.market_structure.service import VENUE, MarketStructureService
from cfi.market_structure.sources import SOURCES
from cfi.market_structure.universe import STRUCTURE_ASSETS, TOTAL_MARKET_CAP_USD

AS_OF = datetime(2026, 9, 20, 9, tzinfo=UTC)
FROZEN_NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
DAYS = 470
FULL_KEYS = [
    "as_of",
    "knowledge_time",
    "evidence_note",
    "score",
    "assets",
    "market_breadth",
    "total_cap_family",
    "eth_btc",
    "data_quality",
    "not_tracked",
]
SCORE_ONLY_KEYS = [
    "as_of",
    "knowledge_time",
    "evidence_note",
    "score",
    "assets",
    "market_breadth",
    "not_tracked",
]


class FakeMarketStructureQueries:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.series = {VENUE.instruments[a]: i + 1 for i, a in enumerate(STRUCTURE_ASSETS)}
        self.bar_rows: dict[int, list[dict[str, Any]]] = {}
        midnight = AS_OF.replace(hour=0, minute=0)
        for i in range(len(STRUCTURE_ASSETS)):
            rng = random.Random(100 + i)  # noqa: S311 - deterministic fixture data
            price = 50.0 * (i + 1)
            rows: list[dict[str, Any]] = []
            for n in range(DAYS):
                if rng.random() > 0.08:
                    price *= 1 + rng.uniform(-0.035, 0.037)
                close = Decimal(f"{price:.{rng.choice([2, 2, 3, 4])}f}")
                rows.append(
                    {
                        "event_time": midnight - timedelta(days=DAYS - n),
                        "open": close,
                        "high": close * Decimal("1.01"),
                        "low": close * Decimal("0.99"),
                        "close": close,
                        "volume_base": Decimal(1000 + (n * 17 + i) % 300),
                    }
                )
            self.bar_rows[i + 1] = rows
        self.total_cap: list[dict[str, Any]] = [
            {
                "event_time": midnight - timedelta(days=DAYS - n),
                "value": Decimal(2_000_000_000_000 + n * 1_000_000_000),
                "quality_status": "suspect" if n == 40 else "ok",
            }
            for n in range(DAYS)
        ]

    async def series_id(self, dataset_id: str, instrument: str) -> int | None:
        self.calls["series_id"] += 1
        return self.series.get(instrument)

    async def bars(
        self, series_id: int, provider_id: str, start: datetime, end: datetime, as_of: datetime
    ) -> list[dict[str, Any]]:
        self.calls["bars"] += 1
        assert as_of == AS_OF
        return [r for r in self.bar_rows[series_id] if start <= r["event_time"] < end]

    async def observations(
        self,
        dataset_id: str,
        *,
        subject: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        self.calls["observations"] += 1
        assert dataset_id == TOTAL_MARKET_CAP_USD.dataset_id
        assert as_of == AS_OF
        assert knowledge_time == AS_OF
        return [r for r in self.total_cap if start <= r["event_time"] < end]

    async def latest_scalars(
        self, dataset_id: str, assets: list[str], as_of: datetime
    ) -> dict[str, dict[str, Any]]:
        self.calls["latest_scalars"] += 1
        values = {"BTC": Decimal(1_100_000_000_000), "ETH": Decimal(300_000_000_000)}
        return {a: {"value": values[a], "event_time": as_of} for a in assets}

    async def last_job(self, *_a: Any) -> dict[str, Any]:
        self.calls["last_job"] += 1
        return {
            "status": "succeeded",
            "started_at": AS_OF,
            "error_code": None,
            "error_detail": None,
        }


def _service() -> tuple[MarketStructureService, FakeMarketStructureQueries]:
    fake = FakeMarketStructureQueries()
    return MarketStructureService(cast("MarketStructureQueries", fake)), fake


def dump(value: Any) -> str:
    return json.dumps(value, indent=1, default=str)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ms_service, "utc_now", lambda: FROZEN_NOW)


async def test_overview_keeps_its_documented_key_order_and_is_meaningful() -> None:
    svc, _ = _service()
    full = await svc.overview(as_of=AS_OF, knowledge_time=AS_OF)
    assert list(full) == FULL_KEYS
    btc = full["assets"]["BTC"]
    assert full["score"]["status"] == "ok"
    assert full["score"]["calculated_at"] == FROZEN_NOW.isoformat()
    assert btc["trend"]["status"] == "ok"
    assert btc["rsi"]["status"] == "ok"
    assert btc["volatility"]["status"] == "ok"
    assert full["market_breadth"]["status"] == "ok"
    assert full["total_cap_family"]["status"] == "ok"
    assert full["eth_btc"]["status"] == "ok"


async def test_overview_score_is_the_overview_minus_the_three_skipped_sections() -> None:
    svc, _ = _service()
    full = await svc.overview(as_of=AS_OF, knowledge_time=AS_OF)
    score_only = await svc.overview_score(as_of=AS_OF, knowledge_time=AS_OF)
    expected = {
        k: v for k, v in full.items() if k not in ("total_cap_family", "eth_btc", "data_quality")
    }
    assert list(score_only) == SCORE_ONLY_KEYS == list(expected)
    assert dump(score_only) == dump(expected)


async def test_overview_score_carries_every_field_the_gatherers_read() -> None:
    svc, _ = _service()
    full = await svc.overview(as_of=AS_OF, knowledge_time=AS_OF)
    score_only = await svc.overview_score(as_of=AS_OF, knowledge_time=AS_OF)
    assert score_only["score"] == full["score"]  # regime + similarity: score
    assert score_only["market_breadth"] == full["market_breadth"]  # regime: breadth
    for asset in STRUCTURE_ASSETS:  # regime: trend/rsi/volatility; similarity: volatility
        assert score_only["assets"][asset] == full["assets"][asset]
    vol = score_only["assets"]["BTC"]["volatility"]
    assert vol["percentile"] is not None
    assert vol["annualized_pct"] is not None


async def test_volatility_reading_equals_the_unmemoised_reference() -> None:
    from tests.unit.test_realized_volatility_memo import reference_series

    svc, fake = _service()
    got = await svc.overview_score(as_of=AS_OF, knowledge_time=AS_OF)
    btc_rows = fake.bar_rows[fake.series[VENUE.instruments["BTC"]]]
    start = AS_OF - ms_service.LOAD_SPAN
    bars = m.bars_from_rows([r for r in btc_rows if start <= r["event_time"]])
    series = reference_series(bars)
    assert got["assets"]["BTC"]["volatility"]["annualized_pct"] == format(series[-1][1], "f")


async def test_overview_score_skips_only_the_queries_behind_the_skipped_sections() -> None:
    full_svc, full_q = _service()
    await full_svc.overview(as_of=AS_OF, knowledge_time=AS_OF)
    score_svc, score_q = _service()
    await score_svc.overview_score(as_of=AS_OF, knowledge_time=AS_OF)
    assert dict(score_q.calls) == {"series_id": 4, "bars": 4}
    assert full_q.calls["series_id"] == full_q.calls["bars"] == 4
    assert full_q.calls["observations"] == 1
    assert full_q.calls["latest_scalars"] == 1
    assert full_q.calls["last_job"] == len(STRUCTURE_ASSETS) + len(SOURCES)
