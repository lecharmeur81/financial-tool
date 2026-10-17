"""``RetailService.overview_score`` (the score-only path used by the regime and similarity snapshot
gatherers) against the full ``RetailService.overview``.

The fake stands in for ``cfi.retail.queries.RetailQueries`` and re-implements only the documented
time-range semantics (``start <= event_time < end``); it proves the service passes the right
cut-offs and ranges and that both paths agree on every shared key, in the same order. It does NOT
prove the production SQL; that needs a database-backed test.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from cfi.derivatives.universe import FUNDING_RATE, LONG_SHORT_RATIO, PERP_ASSETS
from cfi.retail import service as retail_service
from cfi.retail.queries import RetailQueries
from cfi.retail.service import RetailService
from cfi.retail.sources import SOURCES
from cfi.retail.universe import MEME_COIN_SYMBOLS, SMALL_OUTPUT_COUNT

AS_OF = datetime(2026, 9, 20, 9, tzinfo=UTC)
FROZEN_NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
FULL_KEYS = [
    "as_of",
    "knowledge_time",
    "evidence_note",
    "activity_score",
    "speculation_score",
    "sentiment",
    "derivatives_proxy",
    "meme_coin_activity",
    "small_transaction_activity",
    "percentiles",
    "data_quality",
    "not_tracked",
]


def _row(event_time: datetime, value: Decimal | None, quality: str = "ok") -> dict[str, Any]:
    return {"event_time": event_time, "value": value, "quality_status": quality}


def _within(rows: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    return [r for r in rows if start <= r["event_time"] < end]


class FakeRetailQueries:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        midnight = AS_OF.replace(hour=0, minute=0)
        self.small: list[dict[str, Any]] = []
        for n in range(200):
            t = midnight - timedelta(days=199 - n)
            value = None if n == 50 else Decimal(1000 + (n * 37) % 400)
            self.small.append(_row(t, value, "suspect" if n == 60 else "ok"))
        memes = list(MEME_COIN_SYMBOLS)
        self.trending: list[dict[str, Any]] = []
        for n in range(150):
            t = AS_OF - timedelta(hours=2, days=149 - n)  # latest poll is fresh
            assets = [*memes[: n % 4], "BTC"] if n % 5 else ["BTC"]
            for rank, asset in enumerate(assets, start=1):
                self.trending.append({**_row(t, Decimal(rank)), "asset": asset})
        self.funding: dict[str, list[dict[str, Any]]] = {}
        self.ratio: dict[str, list[dict[str, Any]]] = {}
        for k, asset in enumerate(PERP_ASSETS):
            self.funding[asset] = []
            self.ratio[asset] = []
            for n in range(160 * 3):
                t = AS_OF - timedelta(hours=1 + 8 * (160 * 3 - 1 - n))  # latest is fresh
                self.funding[asset].append(_row(t, Decimal(f"0.000{(n * 7 + k) % 90:02d}")))
                self.ratio[asset].append(
                    _row(t, Decimal("1.0") + Decimal((n * 13 + k) % 40 - 15) / 100)
                )

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
        assert dataset_id == SMALL_OUTPUT_COUNT.dataset_id
        assert subject == "BTC"
        assert as_of == AS_OF
        assert knowledge_time == AS_OF
        return _within(self.small, start, end)

    async def trending_observations(
        self, *, start: datetime, end: datetime, as_of: datetime, knowledge_time: datetime
    ) -> list[dict[str, Any]]:
        self.calls["trending_observations"] += 1
        assert as_of == AS_OF
        assert knowledge_time == AS_OF
        return _within(self.trending, start, end)

    async def derivatives_observations(
        self,
        dataset_id: str,
        *,
        asset: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        self.calls["derivatives_observations"] += 1
        assert as_of == AS_OF
        assert knowledge_time == AS_OF
        source = {FUNDING_RATE.dataset_id: self.funding, LONG_SHORT_RATIO.dataset_id: self.ratio}
        return _within(source[dataset_id][asset], start, end)

    async def last_job(self, *_a: Any) -> dict[str, Any]:
        self.calls["last_job"] += 1
        return {
            "status": "succeeded",
            "started_at": AS_OF,
            "error_code": None,
            "error_detail": None,
        }


def _service() -> tuple[RetailService, FakeRetailQueries]:
    fake = FakeRetailQueries()
    return RetailService(cast("RetailQueries", fake)), fake


def dump(value: Any) -> str:
    return json.dumps(value, indent=1, default=str)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retail_service, "utc_now", lambda: FROZEN_NOW)


async def test_overview_keeps_its_documented_key_order_and_is_meaningful() -> None:
    svc, _ = _service()
    full = await svc.overview(as_of=AS_OF, knowledge_time=AS_OF)
    assert list(full) == FULL_KEYS
    # the fixture data is rich enough that the comparison below is not vacuous
    assert full["activity_score"]["status"] == "ok"
    assert full["speculation_score"]["status"] == "ok"
    assert full["activity_score"]["calculated_at"] == FROZEN_NOW.isoformat()


async def test_overview_score_is_the_overview_minus_data_quality() -> None:
    svc, _ = _service()
    full = await svc.overview(as_of=AS_OF, knowledge_time=AS_OF)
    score_only = await svc.overview_score(as_of=AS_OF, knowledge_time=AS_OF)
    expected = {k: v for k, v in full.items() if k != "data_quality"}
    assert list(score_only) == list(expected)
    assert dump(score_only) == dump(expected)


async def test_overview_score_carries_every_field_the_gatherers_read() -> None:
    svc, _ = _service()
    full = await svc.overview(as_of=AS_OF, knowledge_time=AS_OF)
    score_only = await svc.overview_score(as_of=AS_OF, knowledge_time=AS_OF)
    for key in ("activity_score", "speculation_score"):  # regime + similarity read these
        assert score_only[key] == full[key]
        assert score_only[key]["status"] == "ok"
        assert score_only[key]["score"] is not None


async def test_overview_score_skips_only_the_quality_job_queries() -> None:
    full_svc, full_q = _service()
    await full_svc.overview(as_of=AS_OF, knowledge_time=AS_OF)
    score_svc, score_q = _service()
    await score_svc.overview_score(as_of=AS_OF, knowledge_time=AS_OF)
    assert full_q.calls["last_job"] == len(SOURCES) > 0
    assert score_q.calls["last_job"] == 0
    for name in ("observations", "trending_observations", "derivatives_observations"):
        assert score_q.calls[name] == full_q.calls[name] > 0
    assert score_q.calls["derivatives_observations"] == 2 * len(PERP_ASSETS)
