"""The regime and similarity gatherers share point-in-time reads inside one ``pit_read_scope``.

Fake domain services return values that depend on ``(as_of, knowledge_time)`` and count calls.
Nothing here touches a database, so it proves reuse/equivalence logic and read counts only — not
production speed.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from cfi.core.pit_memo import pit_read_scope
from cfi.divergence.adapters import Adapters
from cfi.regime import snapshot as regime_snapshot
from cfi.similarity import snapshot as similarity_snapshot

ASSET = "BTC"
BASE = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
KT = BASE


def _seed(as_of: datetime, knowledge_time: datetime) -> int:
    return int(as_of.timestamp() // 60) % 90 + int(knowledge_time.timestamp() // 3600) % 7


class _Calls:
    def __init__(self) -> None:
        self.n = 0
        self.by_name: dict[str, int] = {}

    def hit(self, name: str) -> None:
        self.n += 1
        self.by_name[name] = self.by_name.get(name, 0) + 1


class _Svc:
    def __init__(self, calls: _Calls, name: str) -> None:
        self._c = calls
        self._name = name

    async def score(self, *, as_of: datetime, knowledge_time: datetime, **_k: Any) -> Any:
        self._c.hit(self._name)
        return {"status": "ok", "score": str(_seed(as_of, knowledge_time)), "health": "50.5"}

    async def overview(self, *, as_of: datetime, knowledge_time: datetime, **_k: Any) -> Any:
        self._c.hit(self._name)
        s = _seed(as_of, knowledge_time)
        return {
            "activity_score": {"status": "ok", "score": str(s)},
            "speculation_score": {"status": "ok", "score": "37.25"},
            "score": {"status": "ok", "score": str(s + 1)},
            "assets": {
                ASSET: {
                    "trend": {"status": "ok", "condition": "uptrend"},
                    "rsi": {"status": "ok", "value": "61.2", "condition": "neutral"},
                    "volatility": {
                        "status": "ok",
                        "percentile": str(s),
                        "annualized_pct": "48.2",
                        "condition": "elevated",
                    },
                }
            },
            "market_breadth": {"status": "ok", "condition": "broad"},
        }

    async def overview_score(self, *, as_of: datetime, knowledge_time: datetime, **_k: Any) -> Any:
        if self._name != "macro.overview_score":  # retail / market structure: score-only overview
            return await self.overview(as_of=as_of, knowledge_time=knowledge_time)
        self._c.hit(self._name)
        return {"score": {"status": "ok", "score": str(_seed(as_of, knowledge_time) + 2)}}

    async def asset(self, *, as_of: datetime, knowledge_time: datetime, **_k: Any) -> Any:
        self._c.hit(self._name)
        return {
            "score": {"status": "ok", "health": str(_seed(as_of, knowledge_time))},
            "funding": {"annualised_7d_pct": "12.5"},
            "open_interest": {"change_7d_pct": "3.25"},
            "conditions": [{"condition_id": "liquidation_event", "state": "inactive"}],
        }


class _Adapters:
    def __init__(self, calls: _Calls, engine: object | None = None) -> None:
        self.engine = engine if engine is not None else object()
        self._c = calls

    def institutional(self) -> _Svc:
        return _Svc(self._c, "institutional.score")

    def whales(self) -> _Svc:
        return _Svc(self._c, "whales.score")

    def retail(self) -> _Svc:
        return _Svc(self._c, "retail.overview")

    def liquidity(self) -> _Svc:
        return _Svc(self._c, "liquidity.overview")

    def derivatives(self) -> _Svc:
        return _Svc(self._c, "derivatives.asset")

    def market_structure(self) -> _Svc:
        return _Svc(self._c, "market_structure.overview")


def _adapt(calls: _Calls) -> Adapters:
    return cast("Adapters", _Adapters(calls))


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    c = _Calls()

    def fake_macro_service(_queries: object) -> _Svc:
        return _Svc(c, "macro.overview_score")

    for mod in (regime_snapshot, similarity_snapshot):
        monkeypatch.setattr(mod, "MacroQueries", lambda _engine: object())
        monkeypatch.setattr(mod, "MacroService", fake_macro_service)
    return c


async def _both(adapters: Adapters, as_of: datetime, kt: datetime = KT) -> tuple[Any, Any]:
    r = await regime_snapshot.gather_snapshot(
        adapters,
        asset=ASSET,
        as_of=as_of,
        knowledge_time=kt,
    )
    s = await similarity_snapshot.gather_snapshot(
        adapters,
        asset=ASSET,
        as_of=as_of,
        knowledge_time=kt,
    )
    return r, s


async def test_second_gatherer_for_identical_inputs_reuses_all_seven_reads(calls: _Calls) -> None:
    with pit_read_scope() as stats:
        await _both(_adapt(calls), BASE)
    assert calls.n == 7  # 14 without reuse
    assert stats.hits == 7
    assert set(calls.by_name.values()) == {1}


async def test_cached_equals_uncached_for_both_gatherers(calls: _Calls) -> None:
    for offset_days in (0, 1, 7, 30):
        as_of = BASE - timedelta(days=offset_days)
        plain = await _both(_adapt(calls), as_of)
        with pit_read_scope():
            cached = await _both(_adapt(calls), as_of)
        assert asdict(plain[0]) == asdict(cached[0])
        assert asdict(plain[1]) == asdict(cached[1])


async def test_different_as_of_or_cutoff_never_reuses(calls: _Calls) -> None:
    adapters = _adapt(calls)
    with pit_read_scope() as stats:
        await _both(adapters, BASE)
        await _both(adapters, BASE + timedelta(microseconds=1))  # new as_of
        await _both(adapters, BASE, BASE - timedelta(hours=1))  # earlier knowledge cutoff
        await _both(adapters, BASE.replace(hour=0))  # same calendar date, other instant
    assert stats.misses == 28
    assert stats.hits == 28  # only the within-pair gatherer reuse (7 per distinct key)
    assert calls.n == 28


async def test_other_engine_never_reuses(calls: _Calls) -> None:
    with pit_read_scope():
        await regime_snapshot.gather_snapshot(
            _adapt(calls),
            asset=ASSET,
            as_of=BASE,
            knowledge_time=KT,
        )
        await similarity_snapshot.gather_snapshot(
            _adapt(calls),
            asset=ASSET,
            as_of=BASE,
            knowledge_time=KT,
        )
    assert calls.n == 14


async def test_unavailable_and_missing_data_keep_existing_behaviour(
    calls: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable(self: _Svc, **_k: Any) -> Any:
        self._c.hit(self._name)
        return {"status": "unavailable"}

    monkeypatch.setattr(_Svc, "score", unavailable)
    plain = await _both(_adapt(calls), BASE)
    with pit_read_scope():
        cached = await _both(_adapt(calls), BASE)
    assert asdict(plain[0]) == asdict(cached[0])
    assert asdict(plain[1]) == asdict(cached[1])
    assert cached[0].metrics["institutional_score"].status == "unavailable"
    assert cached[1].metrics["whale_score"].status == "unavailable"


async def test_historical_snapshot_build_counts_before_and_after_reuse(calls: _Calls) -> None:
    """Deterministic evidence: regime walks 10 daily dates, similarity 5 weekly dates; dates
    0 and 7 coincide exactly (same instant), the others do not."""
    regime_dates = [BASE - timedelta(days=i) for i in range(10)]
    similarity_dates = [BASE - timedelta(days=7 * j) for j in range(5)]

    async def run() -> None:
        adapters = _adapt(calls)
        for d in regime_dates:
            await regime_snapshot.gather_snapshot(
                adapters,
                asset=ASSET,
                as_of=d,
                knowledge_time=KT,
            )
        for d in similarity_dates:
            await similarity_snapshot.gather_snapshot(
                adapters,
                asset=ASSET,
                as_of=d,
                knowledge_time=KT,
            )

    await run()
    before = calls.n // 7
    calls.n = 0
    with pit_read_scope():
        await run()
    after = calls.n // 7
    assert (before, after) == (15, 13)
