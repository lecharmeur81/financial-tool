"""Reproducible work-count benchmark for the two history-heavy tools of an analyst snapshot.

Drives the REAL ``get_market_regime`` and ``find_historical_similar_periods`` tools (real
``RegimeService``/``SimilarityService``, real gatherers, classifier, scorer, history walk, candidate
grid and memo) over an in-memory synthetic two-year dataset whose every domain read is a pure
function of ``(as_of, knowledge_time)``. Each read advances a *virtual* clock by a fixed cost, so
durations here are a deterministic cost model, NOT a measurement of production:

* ``READ_COST_S`` = 0.342 s per historical snapshot build / 7 reads — the only real measurement
  available (one build on an almost empty scratch database, 79 statements). It is an assumption
  here; production data volume, indexes and caching will differ.
* Only the regime and similarity tools are modelled; the other 11 tools are not included.

What it proves: the counts of historical snapshot builds before/after the reuse
changes, and that the tool outputs are identical with and without them on the same dataset.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from cfi.analyst import tools as analyst_tools
from cfi.core.pit_memo import pit_read_scope
from cfi.regime import service as regime_service
from cfi.regime import snapshot as regime_snapshot
from cfi.similarity import service as similarity_service
from cfi.similarity import snapshot as similarity_snapshot

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
DATA_START = NOW - timedelta(days=730)
BUILD_COST_S = 0.342  # measured once on an almost empty scratch DB; an assumption, see docstring
READS_PER_BUILD = 7
SOFT_LIMIT_S = 100.0

Profile = Callable[[float], dict[str, Any]]


def _day(as_of: datetime) -> float:
    return (as_of - DATA_START).total_seconds() / 86400.0


def _stable(_n: float) -> dict[str, Any]:
    """Worst case for the duration walk: one regime for the whole history."""
    return {
        "inst": 40.0,
        "whale": 30.0,
        "retail": 35.0,
        "liq": 55.0,
        "deriv": 60.0,
        "macro": 55.0,
        "ms": 70.0,
        "trend": "uptrend",
        "vol": 62.0,
    }


def _cyclical(n: float) -> dict[str, Any]:
    """Several different regimes with runs of weeks."""
    a = math.sin(n / 23.0)
    b = math.sin(n / 41.0 + 1.0)
    return {
        "inst": 40.0 * a,
        "whale": 35.0 * b,
        "retail": 50.0 + 30.0 * a,
        "liq": 50.0 + 25.0 * b,
        "deriv": 50.0 + 30.0 * math.sin(n / 17.0),
        "macro": 50.0 + 20.0 * b,
        "ms": 50.0 + 45.0 * a,
        "trend": "uptrend" if a > 0.2 else ("downtrend" if a < -0.2 else "mixed"),
        "vol": 50.0 + 40.0 * math.sin(n / 29.0),
    }


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.reads = 0

    def read(self) -> None:
        self.reads += 1
        self.now += BUILD_COST_S / READS_PER_BUILD


def _s(v: float) -> str:
    return str(Decimal(str(round(v, 3))))


class _Svc:
    def __init__(self, clock: _Clock, profile: Profile, kind: str) -> None:
        self.c, self.profile, self.kind = clock, profile, kind

    def _p(self, as_of: datetime) -> dict[str, Any] | None:
        self.c.read()
        return None if as_of < DATA_START else self.profile(_day(as_of))

    async def score(self, *, as_of: datetime, knowledge_time: datetime, **_k: Any) -> Any:
        p = self._p(as_of)
        if p is None:
            return {"status": "insufficient_data"}
        return {"status": "ok", "value": _s(p["inst" if self.kind == "inst" else "whale"])}

    async def overview(self, *, as_of: datetime, knowledge_time: datetime, **_k: Any) -> Any:
        p = self._p(as_of)
        if p is None:
            return {"status": "insufficient_data"}
        if self.kind == "retail":
            return {
                "activity_score": {"status": "ok", "score": _s(p["retail"])},
                "speculation_score": {"status": "ok", "score": _s(p["retail"] * 0.8)},
            }
        if self.kind == "liq":
            return {"score": {"status": "ok", "score": _s(p["liq"])}}
        return {  # market structure
            "score": {"status": "ok", "score": _s(p["ms"])},
            "assets": {
                "BTC": {
                    "trend": {"status": "ok", "condition": p["trend"]},
                    "rsi": {"status": "ok", "value": "55", "condition": "neutral"},
                    "volatility": {
                        "status": "ok",
                        "percentile": _s(p["vol"]),
                        "annualized_pct": "45",
                        "condition": "normal",
                    },
                }
            },
            "market_breadth": {"status": "ok", "condition": "broad"},
        }

    async def overview_score(self, *, as_of: datetime, knowledge_time: datetime, **_k: Any) -> Any:
        if self.kind != "macro":  # retail / market structure: score-only overview
            return await self.overview(as_of=as_of, knowledge_time=knowledge_time)
        p = self._p(as_of)
        if p is None:
            return {"score": {"status": "insufficient_data"}}
        return {"score": {"status": "ok", "score": _s(p["macro"])}}

    async def asset(self, *, as_of: datetime, knowledge_time: datetime, **_k: Any) -> Any:
        p = self._p(as_of)
        if p is None:
            return {"score": {"status": "insufficient_data"}}
        return {
            "score": {"status": "ok", "health": _s(p["deriv"])},
            "funding": {"annualised_7d_pct": "10"},
            "open_interest": {"change_7d_pct": "2"},
            "conditions": [{"condition_id": "liquidation_event", "state": "inactive"}],
        }


class _Market:
    async def series_id(self, *_a: Any) -> int:
        return 1

    async def bars(self, _sid: int, _prov: str, start: datetime, end: datetime, _as_of: Any) -> Any:
        rows = []
        t = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while t <= end:
            close = Decimal(30000) + Decimal(_day(t) * 15)
            rows.append(
                {
                    "event_time": t,
                    "open": close,
                    "high": close + 50,
                    "low": close - 50,
                    "close": close,
                    "volume_base": Decimal(1000),
                }
            )
            t += timedelta(days=1)
        return rows


class _Adapters:
    def __init__(self, clock: _Clock, profile: Profile) -> None:
        self.engine = clock
        self.c, self.profile = clock, profile

    def institutional(self) -> _Svc:
        return _Svc(self.c, self.profile, "inst")

    def whales(self) -> _Svc:
        return _Svc(self.c, self.profile, "whale")

    def retail(self) -> _Svc:
        return _Svc(self.c, self.profile, "retail")

    def liquidity(self) -> _Svc:
        return _Svc(self.c, self.profile, "liq")

    def derivatives(self) -> _Svc:
        return _Svc(self.c, self.profile, "deriv")

    def market_structure(self) -> _Svc:
        return _Svc(self.c, self.profile, "ms")

    def market(self) -> _Market:
        return _Market()


def _install(monkeypatch: pytest.MonkeyPatch, clock: _Clock, profile: Profile) -> None:
    monkeypatch.setattr(regime_service, "Adapters", lambda _e: _Adapters(clock, profile))
    monkeypatch.setattr(similarity_service, "Adapters", lambda _e: _Adapters(clock, profile))
    for mod in (regime_snapshot, similarity_snapshot):
        monkeypatch.setattr(mod, "MacroQueries", lambda _e: object())
        monkeypatch.setattr(mod, "MacroService", lambda _q: _Svc(clock, profile, "macro"))


async def _run(
    monkeypatch: pytest.MonkeyPatch, profile: Profile, *, reuse: bool
) -> tuple[dict[str, Any], dict[str, Any], dict[str, float], int]:
    clock = _Clock()
    _install(monkeypatch, clock, profile)
    durations: dict[str, float] = {}

    async def go() -> tuple[dict[str, Any], dict[str, Any]]:
        t0 = clock.now
        regime = await analyst_tools.get_market_regime(clock, as_of=NOW, knowledge_time=NOW)
        t1 = clock.now
        sim = await analyst_tools.find_historical_similar_periods(
            clock, as_of=NOW, knowledge_time=NOW
        )
        durations["get_market_regime"] = t1 - t0
        durations["find_historical_similar_periods"] = clock.now - t1
        return regime, sim

    if reuse:
        with pit_read_scope():
            regime, sim = await go()
    else:
        regime, sim = await go()
    return regime, sim, durations, clock.reads // READS_PER_BUILD


@pytest.mark.parametrize("profile", [_stable, _cyclical], ids=["stable", "cyclical"])
async def test_reuse_keeps_outputs_identical_and_cut_history_builds(
    monkeypatch: pytest.MonkeyPatch, profile: Profile, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = {
        "baseline": await _run(monkeypatch, profile, reuse=False),
        "memo": await _run(monkeypatch, profile, reuse=True),
    }
    base_regime, base_sim, _, base_builds = runs["baseline"]
    assert base_sim["data"]["status"] == "ok"  # rich enough to exercise the full candidate grid
    for name, (regime, sim, _d, _builds) in runs.items():
        assert regime == base_regime, name  # user-facing payloads identical key for key
        assert sim == base_sim, name
    builds = {name: r[3] for name, r in runs.items()}
    assert builds["memo"] < base_builds
    totals = {name: round(sum(r[2].values()), 1) for name, r in runs.items()}
    per_tool = {n: {k: round(v, 1) for k, v in r[2].items()} for n, r in runs.items()}
    with capsys.disabled():
        print(
            f"\n[{profile.__name__}] regime={base_regime['data']['regime_id']} "
            f"duration_days={base_regime['data']['regime_duration_days']} "
            f"candidates={base_sim['data']['candidates_evaluated']}\n"
            f"  historical snapshot builds: {builds}\n"
            f"  virtual seconds (cost model, regime+similarity tools only): {totals} "
            f"(soft limit {SOFT_LIMIT_S:.0f}s)\n"
            f"  per-tool virtual s baseline={per_tool['baseline']} final={per_tool['memo']}"
        )
