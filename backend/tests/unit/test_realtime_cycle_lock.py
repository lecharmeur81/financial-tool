"""Ownership-safe cycle lock and structured cycle timing for ``RealtimeIntelligenceService``.

Offline: the evaluation is replaced by a stub and Redis by a small fake that honours the
compare-and-delete release script. No database, Redis or broker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog
from celery.exceptions import SoftTimeLimitExceeded

import cfi.realtime.service as realtime_module
from cfi.core.config import Settings
from cfi.realtime.service import RealtimeIntelligenceService
from cfi.realtime.universe import CYCLE_LOCK_KEY, CYCLE_LOCK_TTL_SECONDS

TIMING = "realtime_cycle_timing"


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_args: list[tuple[str, str, bool, int | None]] = []
        self.eval_error: BaseException | None = None
        self.script: str | None = None

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        self.set_args.append((key, value, nx, ex))
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        self.script = script
        if self.eval_error is not None:
            raise self.eval_error
        assert numkeys == 1
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


class FakeResult:
    snapshot_id = None
    snapshot = None


def _service(redis: FakeRedis | None, settings: Settings) -> RealtimeIntelligenceService:
    return RealtimeIntelligenceService(MagicMock(), settings, redis=redis)  # type: ignore[arg-type]


def _evaluating(svc: RealtimeIntelligenceService, behaviour: Any) -> None:
    svc.alerts = MagicMock()
    svc.alerts.evaluate = behaviour

    # nothing after the evaluation is under test here
    async def no_ai(*_a: Any, **_k: Any) -> int:
        return 0

    svc._consider_ai_analysis = no_ai  # type: ignore[method-assign]


async def _run(svc: RealtimeIntelligenceService) -> Any:
    return await svc.process_cycle(as_of=None, knowledge_time=None, now=None)  # type: ignore[arg-type]


def _timing(captured: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    events = [e for e in captured if e["event"] == TIMING]
    assert len(events) == 1
    return events[0]


# ---------------------------------------------------------------- acquisition


async def test_each_cycle_gets_a_unique_token_stored_with_nx_and_the_same_ttl(
    settings: Settings,
) -> None:
    redis = FakeRedis()
    first = await _service(redis, settings)._acquire_lock()
    redis.store.clear()
    second = await _service(redis, settings)._acquire_lock()

    assert first is not None
    assert second is not None
    assert first != second
    assert redis.set_args[0] == (CYCLE_LOCK_KEY, first, True, CYCLE_LOCK_TTL_SECONDS)
    assert CYCLE_LOCK_TTL_SECONDS == 150  # unchanged, so a hard-killed process recovers by TTL


async def test_the_lock_value_is_the_token_not_a_constant(settings: Settings) -> None:
    redis = FakeRedis()
    token = await _service(redis, settings)._acquire_lock()
    assert redis.store[CYCLE_LOCK_KEY] == token
    assert token != "1"


# ---------------------------------------------------------------- release


async def test_a_normal_cycle_releases_its_own_lock(settings: Settings) -> None:
    redis = FakeRedis()
    svc = _service(redis, settings)

    async def evaluate(**_: Any) -> FakeResult:
        assert CYCLE_LOCK_KEY in redis.store  # held while evaluating
        return FakeResult()

    _evaluating(svc, evaluate)
    with structlog.testing.capture_logs() as captured:
        result = await _run(svc)

    assert result.locked_out is False
    assert CYCLE_LOCK_KEY not in redis.store
    event = _timing(captured)
    assert event["status"] == "ok"
    assert event["lock"] == "acquired"
    assert event["lock_release"] == "released"
    assert event["elapsed_ms"] >= 0


async def test_an_exception_releases_only_its_own_lock_and_propagates(settings: Settings) -> None:
    redis = FakeRedis()
    svc = _service(redis, settings)
    boom = RuntimeError("evaluation failed")

    async def evaluate(**_: Any) -> None:
        raise boom

    _evaluating(svc, evaluate)
    with structlog.testing.capture_logs() as captured, pytest.raises(RuntimeError) as caught:
        await _run(svc)

    assert caught.value is boom
    assert CYCLE_LOCK_KEY not in redis.store
    assert _timing(captured)["status"] == "failed"


async def test_a_cycle_whose_lock_expired_does_not_delete_the_new_owners_lock(
    settings: Settings,
) -> None:
    """The 150 s TTL lapsed mid-cycle and another cycle took the lock: the first cycle's release
    must leave the second cycle's lock alone."""
    redis = FakeRedis()
    svc = _service(redis, settings)

    async def evaluate(**_: Any) -> FakeResult:
        redis.store[CYCLE_LOCK_KEY] = "second-cycles-token"  # expired, then re-acquired elsewhere
        return FakeResult()

    _evaluating(svc, evaluate)
    with structlog.testing.capture_logs() as captured:
        await _run(svc)

    assert redis.store[CYCLE_LOCK_KEY] == "second-cycles-token"
    assert _timing(captured)["lock_release"] == "not_owner"


async def test_a_locked_out_cycle_never_touches_the_holders_lock(settings: Settings) -> None:
    redis = FakeRedis()
    redis.store[CYCLE_LOCK_KEY] = "holder-token"
    svc = _service(redis, settings)
    svc.alerts = MagicMock()

    with structlog.testing.capture_logs() as captured:
        result = await _run(svc)

    assert result.locked_out is True
    assert not svc.alerts.evaluate.called
    assert redis.store[CYCLE_LOCK_KEY] == "holder-token"
    assert redis.script is None  # no release attempted at all
    event = _timing(captured)
    assert event["status"] == "locked_out"
    assert event["lock"] == "not_acquired"


async def test_the_release_script_is_a_compare_and_delete() -> None:
    script = realtime_module._RELEASE_IF_OWNER_LUA
    assert "redis.call('get', KEYS[1]) == ARGV[1]" in script
    assert "redis.call('del', KEYS[1])" in script


async def test_a_redis_error_on_release_neither_masks_the_result_nor_the_exception(
    settings: Settings,
) -> None:
    redis = FakeRedis()
    redis.eval_error = ConnectionError("redis down")
    svc = _service(redis, settings)

    async def ok(**_: Any) -> FakeResult:
        return FakeResult()

    _evaluating(svc, ok)
    with structlog.testing.capture_logs() as captured:
        result = await _run(svc)  # no exception from the failed release
    assert result.locked_out is False
    assert _timing(captured)["lock_release"] == "failed"
    assert CYCLE_LOCK_KEY in redis.store  # left for the TTL to expire
    redis.store.clear()

    soft = SoftTimeLimitExceeded()

    async def interrupted(**_: Any) -> None:
        raise soft

    _evaluating(svc, interrupted)
    with pytest.raises(SoftTimeLimitExceeded) as caught:
        await _run(svc)
    assert caught.value is soft  # the interrupt, not the Redis error


async def test_without_redis_the_cycle_still_runs_and_reports_no_lock(settings: Settings) -> None:
    svc = _service(None, settings)

    async def ok(**_: Any) -> FakeResult:
        return FakeResult()

    _evaluating(svc, ok)
    with structlog.testing.capture_logs() as captured:
        result = await _run(svc)
    assert result.locked_out is False
    assert _timing(captured)["lock_release"] == "no_lock"


# ---------------------------------------------------------------- interruption


async def test_a_soft_limit_interrupt_is_logged_as_interrupted_and_still_releases(
    settings: Settings,
) -> None:
    redis = FakeRedis()
    svc = _service(redis, settings)
    soft = SoftTimeLimitExceeded()

    async def evaluate(**_: Any) -> None:
        raise soft

    _evaluating(svc, evaluate)
    with structlog.testing.capture_logs() as captured, pytest.raises(SoftTimeLimitExceeded) as c:
        await _run(svc)

    assert c.value is soft
    assert CYCLE_LOCK_KEY not in redis.store
    event = _timing(captured)
    assert event["status"] == "interrupted"
    assert event["lock_release"] == "released"


async def test_a_cancelled_cycle_releases_its_lock_and_reports_interrupted(
    settings: Settings,
) -> None:
    redis = FakeRedis()
    svc = _service(redis, settings)
    started = asyncio.Event()

    async def evaluate(**_: Any) -> None:
        started.set()
        await asyncio.sleep(30)

    _evaluating(svc, evaluate)
    with structlog.testing.capture_logs() as captured:
        task = asyncio.create_task(_run(svc))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert CYCLE_LOCK_KEY not in redis.store
    assert _timing(captured)["status"] == "interrupted"
