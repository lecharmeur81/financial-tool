"""``persist_assessments_safely`` must stay best-effort for ordinary failures but must never
swallow a Celery time limit or a task cancellation (alert-cycle soft-timeout reliability).

Offline: the assessment repository and the engine are fakes; no database, Redis or broker.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded

import cfi.decision_store.repository as store
from cfi.analyst.repository import AnalystRepository
from cfi.core.config import Settings
from tests.unit.test_alert_service_investment import Harness

CREATED = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

SIGNALS = [
    SoftTimeLimitExceeded(),
    TimeLimitExceeded(),
    asyncio.CancelledError(),
    KeyboardInterrupt(),
]


def _failing_record(error: BaseException) -> Any:
    async def record(self: object, snapshot_id: int, *, created_at: datetime) -> int:
        raise error

    return record


async def test_an_ordinary_failure_is_still_swallowed_logged_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        store.DecisionAssessmentRepository, "record_for_snapshot", _failing_record(OSError("db"))
    )
    with structlog.testing.capture_logs() as captured:
        result = await store.persist_assessments_safely(object(), 7, created_at=CREATED)  # type: ignore[arg-type]
    assert result == 0
    events = [e for e in captured if e["event"] == "decision_assessment_persist_failed"]
    assert len(events) == 1
    assert events[0]["snapshot_id"] == 7


async def test_the_success_value_is_returned_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    async def record(self: object, snapshot_id: int, *, created_at: datetime) -> int:
        return 3

    monkeypatch.setattr(store.DecisionAssessmentRepository, "record_for_snapshot", record)
    assert await store.persist_assessments_safely(object(), 7, created_at=CREATED) == 3  # type: ignore[arg-type]


@pytest.mark.parametrize("signal", SIGNALS, ids=[type(s).__name__ for s in SIGNALS])
async def test_time_limits_and_cancellation_propagate_unchanged(
    monkeypatch: pytest.MonkeyPatch, signal: BaseException
) -> None:
    monkeypatch.setattr(
        store.DecisionAssessmentRepository, "record_for_snapshot", _failing_record(signal)
    )
    with structlog.testing.capture_logs() as captured, pytest.raises(type(signal)) as caught:
        await store.persist_assessments_safely(object(), 7, created_at=CREATED)  # type: ignore[arg-type]
    assert caught.value is signal
    assert [e for e in captured if e["event"] == "decision_assessment_persist_failed"] == []


# ---------------------------------------------------------------- through the real caller chain


class _Conn:
    async def execute(self, _stmt: object) -> Any:
        return SimpleNamespace(scalar_one=lambda: 77, first=lambda: None)


class _Engine:
    """Just enough engine for ``AnalystRepository.insert_snapshot`` / ``latest_snapshot``."""

    @asynccontextmanager
    async def begin(self) -> Any:
        yield _Conn()

    @asynccontextmanager
    async def connect(self) -> Any:
        yield _Conn()


@pytest.mark.parametrize(
    "signal", [SoftTimeLimitExceeded(), TimeLimitExceeded()], ids=["soft", "hard"]
)
async def test_the_alert_cycle_stops_when_a_time_limit_hits_the_snapshot_persistence_step(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, signal: BaseException
) -> None:
    """The real ``AnalystRepository.insert_snapshot`` -> ``persist_assessments_safely`` chain: after
    the time limit, ``AlertService.evaluate`` creates no alert and does not run the investment
    block."""
    harness = Harness(monkeypatch, settings)
    harness.service.analyst_repo = AnalystRepository(_Engine())  # type: ignore[arg-type]
    monkeypatch.setattr(
        store.DecisionAssessmentRepository, "record_for_snapshot", _failing_record(signal)
    )

    with pytest.raises(type(signal)) as caught:
        await harness.evaluate()

    assert caught.value is signal
    kinds = [c[0] for c in harness.calls]
    assert "repo.insert_alert" not in kinds
    assert not any(k.startswith("reader.") for k in kinds)
    assert harness.log.investment() == []


async def test_an_ordinary_assessment_failure_still_lets_the_alert_cycle_complete(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    harness = Harness(monkeypatch, settings)
    harness.service.analyst_repo = AnalystRepository(_Engine())  # type: ignore[arg-type]
    monkeypatch.setattr(
        store.DecisionAssessmentRepository, "record_for_snapshot", _failing_record(OSError("db"))
    )

    result = await harness.evaluate()

    assert result.snapshot_id == 77
    assert result.created == 2
    assert any(c[0] == "repo.insert_alert" for c in harness.calls)
