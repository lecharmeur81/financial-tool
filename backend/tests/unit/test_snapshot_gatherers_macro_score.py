"""The similarity and regime ``gather_snapshot`` functions only consume ``macro['score']``; they
must produce the same snapshot as before while no longer running the macro data-quality queries.

Every domain except macro is a canned fake; macro runs the real ``MacroService`` on the fake
queries from ``test_macro_service_score_only``. These tests do not touch a database and do not
prove production SQL behaviour.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any

import pytest

from cfi.macro import service as macro_service
from cfi.regime import snapshot as regime_snapshot
from cfi.similarity import snapshot as similarity_snapshot
from tests.unit.test_macro_service_score_only import (
    AS_LATE,
    FROZEN_NOW,
    GOLDEN_DIR,
    FakeMacroQueries,
)

ASSET = "BTC"


class _Svc:
    async def score(self, **_k: Any) -> dict[str, Any]:
        return {"status": "ok", "score": "61.5", "health": "58.25"}

    async def overview(self, **_k: Any) -> dict[str, Any]:
        return {
            "activity_score": {"status": "ok", "score": "44.5"},
            "speculation_score": {"status": "ok", "score": "37.25"},
            "score": {"status": "ok", "score": "52.75"},
            "assets": {
                ASSET: {
                    "trend": {"status": "ok", "condition": "uptrend"},
                    "rsi": {"status": "ok", "value": "61.2", "condition": "neutral"},
                    "volatility": {
                        "status": "ok",
                        "percentile": "72.5",
                        "annualized_pct": "48.2",
                        "condition": "elevated",
                    },
                }
            },
            "market_breadth": {"status": "ok", "condition": "broad"},
        }

    async def overview_score(self, **_k: Any) -> dict[str, Any]:
        return await self.overview()

    async def asset(self, **_k: Any) -> dict[str, Any]:
        return {
            "score": {"status": "ok", "health": "58.25"},
            "funding": {"annualised_7d_pct": "12.5"},
            "open_interest": {"change_7d_pct": "3.25"},
            "conditions": [{"condition_id": "liquidation_event", "state": "inactive"}],
        }


class FakeAdapters:
    engine = object()

    def institutional(self) -> _Svc:
        return _Svc()

    def whales(self) -> _Svc:
        return _Svc()

    def retail(self) -> _Svc:
        return _Svc()

    def liquidity(self) -> _Svc:
        return _Svc()

    def derivatives(self) -> _Svc:
        return _Svc()

    def market_structure(self) -> _Svc:
        return _Svc()


@pytest.fixture
def macro_queries(monkeypatch: pytest.MonkeyPatch) -> FakeMacroQueries:
    fake = FakeMacroQueries()
    monkeypatch.setattr(macro_service, "utc_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(similarity_snapshot, "MacroQueries", lambda _engine: fake)
    monkeypatch.setattr(regime_snapshot, "MacroQueries", lambda _engine: fake)
    return fake


def dump(value: Any) -> str:
    return json.dumps(asdict(value), indent=1, default=str)


def _golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_text(encoding="utf-8")


async def test_similarity_gather_snapshot_matches_golden_from_unmodified_code(
    macro_queries: FakeMacroQueries,
) -> None:
    snap = await similarity_snapshot.gather_snapshot(
        FakeAdapters(),  # type: ignore[arg-type]
        asset=ASSET,
        as_of=AS_LATE,
        knowledge_time=AS_LATE,
    )
    assert dump(snap) == _golden("similarity_gather_late.json")


async def test_regime_gather_snapshot_matches_golden_from_unmodified_code(
    macro_queries: FakeMacroQueries,
) -> None:
    snap = await regime_snapshot.gather_snapshot(
        FakeAdapters(),  # type: ignore[arg-type]
        asset=ASSET,
        as_of=AS_LATE,
        knowledge_time=AS_LATE,
    )
    assert dump(snap) == _golden("regime_gather_late.json")


@pytest.mark.parametrize("module", [similarity_snapshot, regime_snapshot])
async def test_gatherers_skip_the_macro_quality_queries_but_keep_the_observation_queries(
    module: Any, macro_queries: FakeMacroQueries
) -> None:
    await module.gather_snapshot(FakeAdapters(), asset=ASSET, as_of=AS_LATE, knowledge_time=AS_LATE)
    assert len(macro_queries.observation_calls) == 18
    assert macro_queries.last_job_calls == []
    assert all(
        c["as_of"] == AS_LATE and c["knowledge_time"] == AS_LATE
        for c in macro_queries.observation_calls
    )


@pytest.mark.parametrize("module", [similarity_snapshot, regime_snapshot])
async def test_gathered_macro_score_equals_the_full_overview_score(
    module: Any, macro_queries: FakeMacroQueries
) -> None:
    snap = await module.gather_snapshot(
        FakeAdapters(), asset=ASSET, as_of=AS_LATE, knowledge_time=AS_LATE
    )
    golden = json.loads(_golden("macro_overview_late.json"))
    reading = snap.metrics["macro_score"]
    assert reading.status == "ok"
    assert reading.value == Decimal(golden["score"]["score"])
