"""Alert-cycle reliability against REAL Redis and REAL PostgreSQL — throwaway services only.

These tests run the cycle lock's Lua compare-and-delete on a real Redis server and interrupt a
real database query with a real signal-raised ``SoftTimeLimitExceeded`` (the way Celery does),
through the real ``WorkerRuntime``, ``create_engine`` and ``create_redis``.

They are **opt-in and never use the application's own services**: they run only when
``CFI_TEST_ISOLATED_REDIS_URL`` (and, for the database tests, ``CFI_TEST_ISOLATED_DATABASE_URL``)
point at disposable instances created just for the test run. They write one Redis key
(``cfi:realtime:cycle_lock``) and run ``SELECT pg_sleep(...)``; nothing is migrated or stored.
Do not point these variables at the running stack.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import psycopg
import pytest
from celery.exceptions import SoftTimeLimitExceeded
from pydantic import SecretStr
from sqlalchemy import text

import cfi.decision_store.repository as decision_store
from cfi.core.config import Settings
from cfi.realtime.service import RealtimeIntelligenceService
from cfi.realtime.universe import CYCLE_LOCK_KEY, CYCLE_LOCK_TTL_SECONDS
from cfi.worker.runtime import WorkerRuntime

REDIS_URL = os.environ.get("CFI_TEST_ISOLATED_REDIS_URL")
DATABASE_URL = os.environ.get("CFI_TEST_ISOLATED_DATABASE_URL")

pytestmark = pytest.mark.integration

needs_redis = pytest.mark.skipif(
    not REDIS_URL, reason="CFI_TEST_ISOLATED_REDIS_URL not set (disposable Redis required)"
)
needs_both = pytest.mark.skipif(
    not (REDIS_URL and DATABASE_URL),
    reason="CFI_TEST_ISOLATED_REDIS_URL / CFI_TEST_ISOLATED_DATABASE_URL not set",
)
needs_signals = pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="needs POSIX timers")


@pytest.fixture
def isolated_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "redis_url": SecretStr(REDIS_URL or settings.redis_url.get_secret_value()),
            "database_url": SecretStr(DATABASE_URL or settings.database_url.get_secret_value()),
            "health_check_timeout_seconds": 5.0,
            "db_pool_size": 2,
        }
    )


@pytest.fixture
def rt(isolated_settings: Settings) -> Iterator[WorkerRuntime]:
    runtime = WorkerRuntime(isolated_settings)
    if REDIS_URL:
        runtime.run(_await(runtime.redis().delete(CYCLE_LOCK_KEY)))
    yield runtime
    # leave the throwaway services tidy: stop any task a test left behind, drop the key, close
    pending = asyncio.all_tasks(runtime.loop)
    for task in pending:
        task.cancel()
    if pending:
        runtime.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    if REDIS_URL:
        runtime.run(_await(runtime.redis().delete(CYCLE_LOCK_KEY)))
    runtime.run(runtime.aclose())
    runtime.loop.close()


@contextmanager
def _soft_limit_after(seconds: float) -> Iterator[None]:
    def handler(_signum: int, _frame: object) -> None:
        raise SoftTimeLimitExceeded()

    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


async def _await(call: Awaitable[Any]) -> Any:
    return await call


def _service(rt: WorkerRuntime, settings: Settings) -> RealtimeIntelligenceService:
    return RealtimeIntelligenceService(
        rt.engine() if DATABASE_URL else MagicMock(), settings, redis=rt.redis()
    )


class _Result:
    snapshot_id = None
    snapshot = None


def _stub_evaluate(svc: RealtimeIntelligenceService, behaviour: Any) -> None:
    svc.alerts = MagicMock()
    svc.alerts.evaluate = behaviour

    async def no_ai(*_a: Any, **_k: Any) -> int:
        return 0

    svc._consider_ai_analysis = no_ai  # type: ignore[method-assign]


def _active_sleep_queries() -> int:
    assert DATABASE_URL
    dsn = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE state = 'active' AND query LIKE '%pg_sleep(30)%' AND pid <> pg_backend_pid()"
        ).fetchone()
    assert row is not None
    return int(row[0])


# ---------------------------------------------------------------- real Redis: the Lua script


@needs_redis
def test_release_script_deletes_only_a_matching_token(
    rt: WorkerRuntime, isolated_settings: Settings
) -> None:
    svc = _service(rt, isolated_settings)
    redis = rt.redis()

    async def scenario() -> tuple[str, str | None, str, str | None, str]:
        token = await svc._acquire_lock()
        assert token is not None
        wrong = await svc._release_lock("not-the-owner")
        still = await redis.get(CYCLE_LOCK_KEY)
        right = await svc._release_lock(token)
        gone = await redis.get(CYCLE_LOCK_KEY)
        absent = await svc._release_lock(token)  # already gone
        return wrong, still if still == token else "MISSING", right, gone, absent

    wrong, still, right, gone, absent = rt.run(scenario())
    assert wrong == "not_owner"
    assert still != "MISSING"  # a wrong token left the owner's lock in place
    assert right == "released"
    assert gone is None
    assert absent == "not_owner"  # nothing to delete: reported, not raised


@needs_redis
def test_acquire_stores_the_token_with_nx_and_the_documented_ttl(
    rt: WorkerRuntime, isolated_settings: Settings
) -> None:
    svc = _service(rt, isolated_settings)
    redis = rt.redis()

    async def scenario() -> tuple[str | None, str | None, str | None, int]:
        first = await svc._acquire_lock()
        second = await svc._acquire_lock()  # NX: refused while held
        stored = await redis.get(CYCLE_LOCK_KEY)
        ttl = await redis.ttl(CYCLE_LOCK_KEY)
        return first, second, stored, ttl

    first, second, stored, ttl = rt.run(scenario())
    assert first is not None
    assert second is None
    assert stored == first
    assert 0 < ttl <= CYCLE_LOCK_TTL_SECONDS


@needs_redis
def test_an_expired_lock_reacquired_by_another_cycle_survives_the_stale_owners_release(
    rt: WorkerRuntime, isolated_settings: Settings
) -> None:
    redis = rt.redis()
    first = _service(rt, isolated_settings)
    second = _service(rt, isolated_settings)

    async def scenario() -> tuple[str, str | None, str | None]:
        old_token = await first._acquire_lock()
        assert old_token is not None
        await redis.pexpire(CYCLE_LOCK_KEY, 50)  # the 150 s TTL lapses (shortened for the test)
        await asyncio.sleep(0.2)
        new_token = await second._acquire_lock()
        assert new_token is not None
        outcome = await first._release_lock(old_token)  # the slow, stale cycle finishes late
        return outcome, await redis.get(CYCLE_LOCK_KEY), new_token

    outcome, held, new_token = rt.run(scenario())
    assert outcome == "not_owner"
    assert held == new_token  # the newer cycle's lock was not deleted


@needs_redis
def test_a_full_cycle_holds_a_unique_token_while_evaluating_and_releases_it(
    rt: WorkerRuntime, isolated_settings: Settings
) -> None:
    svc = _service(rt, isolated_settings)
    seen: list[str | None] = []

    async def evaluate(**_: Any) -> _Result:
        seen.append(await rt.redis().get(CYCLE_LOCK_KEY))
        return _Result()

    _stub_evaluate(svc, evaluate)

    async def go() -> Any:
        return await svc.process_cycle(as_of=None, knowledge_time=None, now=None)  # type: ignore[arg-type]

    result = rt.run(go())
    assert result.locked_out is False
    assert seen[0] is not None
    assert len(seen[0]) == 32  # a uuid4 hex token, not the old constant
    assert rt.run(_await(rt.redis().get(CYCLE_LOCK_KEY))) is None


@needs_redis
def test_a_locked_out_cycle_leaves_the_holders_lock_untouched(
    rt: WorkerRuntime, isolated_settings: Settings
) -> None:
    holder = uuid.uuid4().hex
    rt.run(_await(rt.redis().set(CYCLE_LOCK_KEY, holder, ex=60)))
    svc = _service(rt, isolated_settings)
    _stub_evaluate(svc, MagicMock())

    async def go() -> Any:
        return await svc.process_cycle(as_of=None, knowledge_time=None, now=None)  # type: ignore[arg-type]

    result = rt.run(go())
    assert result.locked_out is True
    assert rt.run(_await(rt.redis().get(CYCLE_LOCK_KEY))) == holder


# ---------------------------------------------------------------- real Redis + real PostgreSQL


@needs_both
@needs_signals
def test_a_soft_limit_during_a_database_query_releases_the_lock_and_leaves_nothing_running(
    rt: WorkerRuntime, isolated_settings: Settings
) -> None:
    svc = _service(rt, isolated_settings)
    engine = rt.engine()

    async def evaluate(**_: Any) -> _Result:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT pg_sleep(30)"))
        return _Result()

    _stub_evaluate(svc, evaluate)

    async def go() -> Any:
        return await svc.process_cycle(as_of=None, knowledge_time=None, now=None)  # type: ignore[arg-type]

    started = time.monotonic()
    with _soft_limit_after(0.5), pytest.raises(SoftTimeLimitExceeded):
        rt.run_guarded(go())
    assert time.monotonic() - started < 10  # the drain did not wait for the 30 s query

    assert (
        rt.run(_await(rt.redis().get(CYCLE_LOCK_KEY))) is None
    )  # lock released by the cancelled cycle
    # the cancelled cycle's own coroutine is gone; any remaining task is connection-close cleanup
    time.sleep(0.5)
    rt.run(asyncio.sleep(0.2))  # lets shielded close tasks finish; must not resume the cycle
    assert [t for t in asyncio.all_tasks(rt.loop)] == []
    assert _active_sleep_queries() == 0  # the server is not still running the abandoned query

    async def reuse() -> int:  # engine and loop are reusable (no "autocommit … ACTIVE" error)
        async with engine.connect() as conn:
            return int((await conn.execute(text("SELECT 41 + 1"))).scalar_one())

    assert rt.run(reuse()) == 42
    assert rt.run_guarded(reuse()) == 42


@needs_both
@needs_signals
def test_plain_run_after_a_soft_limit_leaves_the_lock_held_and_the_query_running(
    rt: WorkerRuntime, isolated_settings: Settings
) -> None:
    """Characterization of the old ``run`` against real services: the interrupted cycle keeps its
    Redis lock (until the TTL) and its database query keeps running."""
    svc = _service(rt, isolated_settings)
    engine = rt.engine()

    async def evaluate(**_: Any) -> _Result:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT pg_sleep(30)"))
        return _Result()

    _stub_evaluate(svc, evaluate)

    async def go() -> Any:
        return await svc.process_cycle(as_of=None, knowledge_time=None, now=None)  # type: ignore[arg-type]

    with _soft_limit_after(0.5), pytest.raises(SoftTimeLimitExceeded):
        rt.run(go())

    assert rt.run(_await(rt.redis().get(CYCLE_LOCK_KEY))) is not None  # still held
    assert _active_sleep_queries() == 1  # the abandoned query is still running on the server
    assert len(asyncio.all_tasks(rt.loop)) >= 1


@needs_both
@needs_signals
def test_a_soft_limit_inside_the_assessment_persistence_path_is_not_swallowed(
    rt: WorkerRuntime, isolated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``persist_assessments_safely`` against a real engine: the database read inside it (replaced
    here by a real ``pg_sleep`` because the throwaway PostgreSQL has no ``ai.*`` tables) is
    interrupted by a real signal-raised ``SoftTimeLimitExceeded``. Here the signal lands while the
    loop waits on the database, i.e. outside coroutine code, so ``run_guarded`` cancels the task;
    this checks that path end to end. (The in-coroutine case, where the old ``except Exception``
    would have swallowed the signal, is the next test.)"""
    engine = rt.engine()

    async def slow_read(self: object, snapshot_id: int) -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT pg_sleep(30)"))

    monkeypatch.setattr(decision_store.DecisionAssessmentRepository, "get_snapshot", slow_read)

    async def go() -> int:
        return await decision_store.persist_assessments_safely(
            engine, 1, created_at=datetime.now(UTC)
        )

    started = time.monotonic()
    with _soft_limit_after(0.5), pytest.raises(SoftTimeLimitExceeded):
        rt.run_guarded(go())
    assert time.monotonic() - started < 10

    rt.run(asyncio.sleep(0.3))
    assert asyncio.all_tasks(rt.loop) == set()
    assert _active_sleep_queries() == 0

    async def reuse() -> int:
        async with engine.connect() as conn:
            return int((await conn.execute(text("SELECT 41 + 1"))).scalar_one())

    assert rt.run(reuse()) == 42


@needs_both
def test_an_ordinary_database_error_in_the_persistence_path_is_still_best_effort(
    rt: WorkerRuntime, isolated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = rt.engine()

    async def failing_read(self: object, snapshot_id: int) -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 / 0"))  # a real PostgreSQL error

    monkeypatch.setattr(decision_store.DecisionAssessmentRepository, "get_snapshot", failing_read)

    async def go() -> int:
        return await decision_store.persist_assessments_safely(
            engine, 1, created_at=datetime.now(UTC)
        )

    assert rt.run(go()) == 0


@needs_signals
def test_a_soft_limit_raised_inside_coroutine_code_is_not_swallowed_by_the_persistence_guard(
    rt: WorkerRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case the old ``except Exception`` got wrong: the real signal handler fires while Python
    code of the persistence call is running (a CPU-bound step), so the exception is raised inside
    the coroutine, through ``persist_assessments_safely``. It must propagate, not become ``0``."""

    async def busy_read(self: object, snapshot_id: int) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:  # runs Python code: the signal is raised in here
            pass

    monkeypatch.setattr(decision_store.DecisionAssessmentRepository, "get_snapshot", busy_read)

    async def go() -> int:
        return await decision_store.persist_assessments_safely(
            MagicMock(), 1, created_at=datetime.now(UTC)
        )

    started = time.monotonic()
    with _soft_limit_after(0.3), pytest.raises(SoftTimeLimitExceeded):
        rt.run_guarded(go())
    assert time.monotonic() - started < 3
    assert asyncio.all_tasks(rt.loop) == set()
