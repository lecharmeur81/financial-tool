"""Structured stage timing for ``AlertService.evaluate`` and the ``alerts.evaluate`` task wiring.

Offline. The service is driven through the same fakes as ``test_alert_service_investment``; these
tests only assert that timing is reported (success and interruption), that nothing but small
scalars is logged, and that exceptions and results are untouched.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from cfi.alerts.stage_timing import status_for, timed_stage
from cfi.core.config import Settings
from tests.unit.test_alert_service_investment import Harness

STAGE = "alert_evaluate_stage_timing"
ALL_STAGES = [
    "build_snapshot",
    "persist_snapshot",
    "evaluate_rules",
    "process_candidates",
    "auto_resolve",
]


def _stages(harness: Harness) -> list[dict[str, Any]]:
    return [fields for _lvl, event, fields in harness.log.calls if event == STAGE]


async def test_every_stage_is_timed_in_order_on_success(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    harness = Harness(monkeypatch, settings)
    await harness.evaluate()

    stages = _stages(harness)
    assert [s["stage"] for s in stages] == ALL_STAGES
    for s in stages:
        assert s["status"] == "ok"
        assert isinstance(s["elapsed_ms"], int)
        assert s["elapsed_ms"] >= 0
        assert set(s) <= {"stage", "status", "elapsed_ms", "candidates"}
    assert stages[3]["candidates"] == len(harness.candidates)

    # Stage 6 is not wrapped here: the investment block reports its own duration in its one
    # ``investment_alert_cycle`` event per cycle.
    cycle = harness.log.investment()
    assert len(cycle) == 1, cycle
    duration_ms = cycle[0][2]["duration_ms"]
    assert isinstance(duration_ms, int)
    assert duration_ms >= 0


async def test_timing_does_not_change_the_evaluation_result_or_repository_calls(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    harness = Harness(monkeypatch, settings)
    result = await harness.evaluate()
    assert result.created == 2
    assert result.candidates_evaluated == 2
    assert result.snapshot_id == 77
    inserts = [c for c in harness.calls if c[0] == "repo.insert_alert"]
    assert [c[1] for c in inserts] == ["anomaly:BTC", "anomaly:ETH"]


async def test_an_interrupt_in_the_snapshot_build_is_reported_and_propagates(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    import cfi.alerts.service as service_module

    harness = Harness(monkeypatch, settings)
    soft = SoftTimeLimitExceeded()

    async def interrupted(*_a: object, **_k: object) -> None:
        raise soft

    monkeypatch.setattr(service_module, "build_snapshot", interrupted)
    with pytest.raises(SoftTimeLimitExceeded) as caught:
        await harness.evaluate()

    assert caught.value is soft
    stages = _stages(harness)
    assert [(s["stage"], s["status"]) for s in stages] == [("build_snapshot", "interrupted")]


async def test_an_ordinary_snapshot_insert_failure_is_reported_as_failed(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    boom = RuntimeError("insert failed")
    harness = Harness(monkeypatch, settings, insert_error=boom)
    with pytest.raises(RuntimeError) as caught:
        await harness.evaluate()
    assert caught.value is boom
    assert [(s["stage"], s["status"]) for s in _stages(harness)] == [
        ("build_snapshot", "ok"),
        ("persist_snapshot", "failed"),
    ]


def test_timed_stage_classifies_outcomes_and_never_swallows() -> None:
    assert status_for(None) == "ok"
    assert status_for(ValueError()) == "failed"
    assert status_for(SoftTimeLimitExceeded()) == "interrupted"
    assert status_for(KeyboardInterrupt()) == "interrupted"

    class Sink:
        def __init__(self) -> None:
            self.rows: list[tuple[str, dict[str, Any]]] = []

        def info(self, event: str, **fields: Any) -> None:
            self.rows.append((event, fields))

    sink = Sink()
    with pytest.raises(ValueError, match="nope"), timed_stage(sink, "e", stage="x", n=1):
        raise ValueError("nope")
    assert sink.rows[0][1]["status"] == "failed"
    assert sink.rows[0][1]["n"] == 1


# ---------------------------------------------------------------- the task uses run_guarded


@pytest.fixture
def worker_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    monkeypatch.setenv(
        "CFI_DATABASE_URL", "postgresql+psycopg://user:not-a-real-password@localhost:5432/cfi_test"
    )
    monkeypatch.setenv("CFI_REDIS_URL", "redis://:not-a-real-password@localhost:6379/0")
    sys.modules.pop("cfi.worker.app", None)
    import cfi.worker.app as module

    yield module
    sys.modules.pop("cfi.worker.app", None)


def test_alerts_evaluate_runs_through_run_guarded_not_plain_run(
    worker_app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class FakeRuntime:
        def run(self, coro: Any) -> None:
            coro.close()
            calls.append("run")

        def run_guarded(self, coro: Any) -> str:
            coro.close()
            calls.append("run_guarded")
            return "guarded"

        def engine(self) -> object:
            return object()

        def redis(self) -> object:
            return object()

    monkeypatch.setattr(worker_app, "runtime", lambda: FakeRuntime())

    assert worker_app.alerts_evaluate_task() == "guarded"
    assert calls == ["run_guarded"]
