"""The regime and similarity gatherers now read ``overview_score`` from the retail and
market-structure services. They must gather exactly what they gathered from the full ``overview``.

Real ``RetailService`` / ``MarketStructureService`` objects (over the fake queries from their own
score-only tests) are used both ways: directly (production wiring: ``overview_score``) and behind a
wrapper that answers ``overview_score`` with the full ``overview``. The gathered snapshots must be
identical, and the score-only path must issue fewer queries.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, cast

import pytest

from cfi.divergence.adapters import Adapters
from cfi.market_structure import service as ms_service
from cfi.regime import snapshot as regime_snapshot
from cfi.retail import service as retail_service
from cfi.similarity import snapshot as similarity_snapshot
from tests.unit.test_market_structure_service_score_only import AS_OF as MS_AS_OF
from tests.unit.test_market_structure_service_score_only import (
    FROZEN_NOW,
    FakeMarketStructureQueries,
)
from tests.unit.test_market_structure_service_score_only import (
    _service as market_structure_service,
)
from tests.unit.test_retail_service_score_only import (
    FakeRetailQueries,
)
from tests.unit.test_retail_service_score_only import _service as retail_service_factory
from tests.unit.test_snapshot_gatherers_macro_score import FakeAdapters as CannedAdapters

ASSET = "BTC"
AS_OF = MS_AS_OF


class _MacroSvc:
    async def overview_score(self, **_k: Any) -> dict[str, Any]:
        return {"score": {"status": "ok", "score": "41.5"}}


class _FullOnly:
    """Answers ``overview_score`` with the full ``overview`` (the pre-change behaviour)."""

    def __init__(self, svc: Any) -> None:
        self._svc = svc

    async def overview(self, **k: Any) -> Any:
        return await self._svc.overview(**k)

    overview_score = overview


class _Adapters(CannedAdapters):
    def __init__(self, retail: Any, market_structure: Any) -> None:
        self._retail, self._market_structure = retail, market_structure

    def retail(self) -> Any:
        return self._retail

    def market_structure(self) -> Any:
        return self._market_structure


@pytest.fixture(autouse=True)
def patched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retail_service, "utc_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(ms_service, "utc_now", lambda: FROZEN_NOW)
    for mod in (regime_snapshot, similarity_snapshot):
        monkeypatch.setattr(mod, "MacroQueries", lambda _engine: object())
        monkeypatch.setattr(mod, "MacroService", lambda _queries: _MacroSvc())


def _build(*, score_only: bool) -> tuple[Adapters, FakeRetailQueries, FakeMarketStructureQueries]:
    retail, retail_q = retail_service_factory()
    market, market_q = market_structure_service()
    if not score_only:
        retail, market = _FullOnly(retail), _FullOnly(market)  # type: ignore[assignment]
    return cast("Adapters", _Adapters(retail, market)), retail_q, market_q


def dump(value: Any) -> str:
    return json.dumps(asdict(value), indent=1, default=str)


@pytest.mark.parametrize("module", [regime_snapshot, similarity_snapshot])
async def test_gathered_snapshot_is_identical_with_score_only_reads(module: Any) -> None:
    fast, fast_retail_q, fast_market_q = _build(score_only=True)
    full, full_retail_q, full_market_q = _build(score_only=False)

    snap_fast = await module.gather_snapshot(fast, asset=ASSET, as_of=AS_OF, knowledge_time=AS_OF)
    snap_full = await module.gather_snapshot(full, asset=ASSET, as_of=AS_OF, knowledge_time=AS_OF)

    assert dump(snap_fast) == dump(snap_full)
    # non-vacuous: the consumed readings are real values, not "unavailable"
    metrics = snap_fast.metrics
    assert metrics["retail_activity_score"].status == "ok"
    assert metrics["market_structure_score"].status == "ok"
    vol_key = (
        "volatility_percentile" if module is similarity_snapshot else "btc_volatility_percentile"
    )
    assert metrics[vol_key].status == "ok"
    if module is regime_snapshot:
        assert metrics["retail_speculation_score"].status == "ok"
        assert metrics["btc_trend"].status == "ok"
        assert metrics["btc_rsi"].status == "ok"
        assert metrics["market_breadth"].status == "ok"

    # and the score-only path really is cheaper
    assert fast_retail_q.calls["last_job"] == 0 < full_retail_q.calls["last_job"]
    assert fast_market_q.calls["last_job"] == 0 < full_market_q.calls["last_job"]
    assert fast_market_q.calls["observations"] == 0 < full_market_q.calls["observations"]
    assert fast_market_q.calls["latest_scalars"] == 0 < full_market_q.calls["latest_scalars"]
