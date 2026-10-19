"""Phase 52 — user-driven alert status transitions (no database, no network).

``apply_user_transition`` (the logic behind ``POST /alerts/{id}/acknowledge|resolve``) runs against
an in-memory repository that applies the same guard as ``AlertRepository.set_status``; the
repository's own UPDATE statements are compiled and inspected with a recording engine. Nothing
here touches investment-alert persistence (the gate stays off) or a real database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql

from cfi.alerts.lifecycle import user_transition_sources
from cfi.alerts.repository import AlertRepository
from cfi.api.routes.alerts import apply_user_transition
from cfi.core.errors import AlertTransitionError, NotFoundError

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
LATER = T0 + timedelta(hours=1)
ID = uuid.UUID(int=7)


class MemoryRepo:
    """Stores one alert row; ``set_status`` mirrors the guarded UPDATE of the real repository."""

    def __init__(self, status: str, *, racing_to: str | None = None) -> None:
        self.row: dict[str, Any] | None = {
            "status": status,
            "acknowledged_at": T0 if status in ("acknowledged", "resolved") else None,
            "resolved_at": T0 if status == "resolved" else None,
            "updated_at": T0,
        }
        self.racing_to = racing_to
        self.writes = 0

    async def get_by_uuid(self, alert_id: uuid.UUID) -> dict[str, Any] | None:
        return None if self.row is None else dict(self.row)

    async def set_status(self, alert_id: uuid.UUID, *, status: str, now: datetime) -> bool:
        assert self.row is not None
        if self.racing_to is not None:  # another request wins between our read and our write
            self.row["status"], self.racing_to = self.racing_to, None
        if self.row["status"] not in user_transition_sources(status):
            return False
        self.row["status"] = status
        self.row["updated_at"] = now
        self.row["acknowledged_at" if status == "acknowledged" else "resolved_at"] = now
        self.writes += 1
        return True


def _run(repo: MemoryRepo, target: str) -> Any:
    return apply_user_transition(cast(AlertRepository, repo), ID, target, now=LATER)


async def test_active_alert_can_be_acknowledged_then_resolved() -> None:
    repo = MemoryRepo("active")
    acked = await _run(repo, "acknowledged")
    assert (acked["status"], acked["acknowledged_at"]) == ("acknowledged", LATER)
    resolved = await _run(repo, "resolved")
    assert (resolved["status"], resolved["resolved_at"]) == ("resolved", LATER)
    assert repo.writes == 2


async def test_active_alert_can_be_resolved_directly() -> None:
    repo = MemoryRepo("active")
    assert (await _run(repo, "resolved"))["status"] == "resolved"


@pytest.mark.parametrize("status", ["acknowledged", "resolved"])
async def test_repeating_a_request_is_a_noop_and_rewrites_no_timestamp(status: str) -> None:
    repo = MemoryRepo(status)
    row = await _run(repo, status)
    assert row["status"] == status
    assert row["updated_at"] == T0
    assert repo.writes == 0


@pytest.mark.parametrize(
    ("status", "target"),
    [("resolved", "acknowledged"), ("expired", "acknowledged"), ("expired", "resolved")],
)
async def test_terminal_alerts_are_rejected_and_unchanged(status: str, target: str) -> None:
    repo = MemoryRepo(status)
    before = dict(repo.row or {})
    with pytest.raises(AlertTransitionError) as caught:
        await _run(repo, target)
    assert caught.value.http_status == 409
    assert caught.value.context["from_status"] == status
    assert repo.row == before
    assert repo.writes == 0


async def test_unknown_alert_is_not_found() -> None:
    repo = MemoryRepo("active")
    repo.row = None
    with pytest.raises(NotFoundError):
        await _run(repo, "resolved")


async def test_a_target_a_user_cannot_set_is_rejected() -> None:
    repo = MemoryRepo("active")
    with pytest.raises(AlertTransitionError):
        await _run(repo, "expired")
    assert repo.writes == 0


async def test_losing_a_race_to_a_resolve_does_not_reopen_the_alert() -> None:
    repo = MemoryRepo("active", racing_to="resolved")
    with pytest.raises(AlertTransitionError):
        await _run(repo, "acknowledged")
    assert repo.row is not None
    assert repo.row["status"] == "resolved"
    assert repo.writes == 0


async def test_losing_a_race_to_the_same_request_is_an_idempotent_success() -> None:
    repo = MemoryRepo("active", racing_to="acknowledged")
    row = await _run(repo, "acknowledged")
    assert row["status"] == "acknowledged"
    assert repo.writes == 0


# ------------------------------------------------------------- the repository's UPDATE statements
class _Conn:
    def __init__(self, sink: list[Any]) -> None:
        self.sink = sink

    async def execute(self, stmt: Any) -> Any:
        self.sink.append(stmt)
        return SimpleNamespace(rowcount=1)


class _Begin:
    def __init__(self, sink: list[Any]) -> None:
        self.conn = _Conn(sink)

    async def __aenter__(self) -> _Conn:
        return self.conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class RecordingEngine:
    def __init__(self) -> None:
        self.sink: list[Any] = []

    def begin(self) -> _Begin:
        return _Begin(self.sink)


def _sql(stmt: Any) -> str:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    return str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


async def test_set_status_update_is_guarded_by_the_permitted_source_statuses() -> None:
    engine = RecordingEngine()
    repo = AlertRepository(cast(Any, engine))
    assert await repo.set_status(ID, status="acknowledged", now=LATER)
    assert await repo.set_status(ID, status="resolved", now=LATER)
    ack, res = (_sql(s) for s in engine.sink)
    assert "status IN ('active')" in ack
    assert "status IN ('active', 'acknowledged')" in res


@pytest.mark.parametrize("status", ["active", "expired", "bogus"])
async def test_set_status_refuses_a_target_a_user_cannot_set_without_writing(status: str) -> None:
    engine = RecordingEngine()
    repo = AlertRepository(cast(Any, engine))
    assert await repo.set_status(ID, status=status, now=LATER) is False
    assert engine.sink == []


async def test_system_resolve_and_supersede_only_touch_open_alerts() -> None:
    engine = RecordingEngine()
    repo = AlertRepository(cast(Any, engine))
    await repo.resolve(5, now=LATER)
    await repo.supersede(5, now=LATER, superseded_by=6)
    for stmt in engine.sink:
        assert "status IN ('active', 'acknowledged')" in _sql(stmt)
