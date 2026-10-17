"""Timeout/cancellation lifecycle of ``WorkerRuntime`` (alerts.evaluate reliability).

Celery's soft time limit is a signal handler that raises ``SoftTimeLimitExceeded`` in the worker's
main thread. When it fires while the persistent event loop is idle in ``select()`` the exception
leaves ``run_until_complete`` from the loop machinery itself, not from inside the coroutine, and
asyncio does not cancel the task it was running. The tests inject that exact situation with a real
``SIGALRM`` (no Celery, database or Redis involved).
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from cfi.core.config import Settings
from cfi.worker.runtime import WorkerRuntime

pytestmark = pytest.mark.skipif(
    not hasattr(signal, "setitimer"), reason="needs POSIX interval timers"
)


@contextmanager
def _signal_raises(exc: BaseException, after: float = 0.05) -> Iterator[None]:
    """Raise ``exc`` from a signal handler ``after`` seconds from now, as Celery does."""

    def handler(_signum: int, _frame: object) -> None:
        raise exc

    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, after)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.fixture
def rt(settings: Settings) -> Iterator[WorkerRuntime]:
    runtime = WorkerRuntime(settings)
    yield runtime
    pending = asyncio.all_tasks(runtime.loop)
    for task in pending:
        task.cancel()
    if pending:
        runtime.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    runtime.loop.close()


class _Trace:
    def __init__(self) -> None:
        self.cleaned = False
        self.resumed = False


async def _long_job(trace: _Trace) -> str:
    try:
        await asyncio.sleep(5)
        trace.resumed = True
        return "finished"
    finally:
        trace.cleaned = True


def test_plain_run_leaves_the_interrupted_task_pending_on_the_persistent_loop(
    rt: WorkerRuntime,
) -> None:
    """Characterization of the existing shared ``run`` (unchanged): the signal exception
    propagates, but the coroutine is neither cancelled nor cleaned up and stays on the loop."""
    trace = _Trace()
    with _signal_raises(SoftTimeLimitExceeded()), pytest.raises(SoftTimeLimitExceeded):
        rt.run(_long_job(trace))

    assert trace.cleaned is False  # its ``finally`` has not run
    assert len(asyncio.all_tasks(rt.loop)) == 1  # still pending, will resume on the next run()


def test_a_pending_task_resumes_during_the_next_unrelated_run(rt: WorkerRuntime) -> None:
    """The consequence: the stale coroutine continues inside a later, unrelated task."""
    resumed_at: list[bool] = []

    async def stale() -> None:
        try:
            await asyncio.sleep(0.2)
        finally:
            resumed_at.append(True)

    with _signal_raises(SoftTimeLimitExceeded()), pytest.raises(SoftTimeLimitExceeded):
        rt.run(stale())
    assert resumed_at == []

    rt.run(asyncio.sleep(0.4))  # a later, unrelated task
    assert resumed_at == [True]  # the stale coroutine ran inside it


# ---------------------------------------------------------------- run_guarded


def test_guarded_run_returns_the_result_normally(rt: WorkerRuntime) -> None:
    async def job() -> int:
        await asyncio.sleep(0)
        return 7

    assert rt.run_guarded(job()) == 7
    assert asyncio.all_tasks(rt.loop) == set()


def test_guarded_run_cancels_and_cleans_up_an_interrupted_task(rt: WorkerRuntime) -> None:
    trace = _Trace()
    soft = SoftTimeLimitExceeded()
    with _signal_raises(soft), pytest.raises(SoftTimeLimitExceeded) as caught:
        rt.run_guarded(_long_job(trace))

    assert caught.value is soft  # the original exception, not wrapped or replaced
    assert trace.cleaned is True  # ``finally`` ran inside the drain
    assert trace.resumed is False
    assert asyncio.all_tasks(rt.loop) == set()  # nothing left on the persistent loop


def test_the_loop_is_reusable_and_no_stale_work_resumes_afterwards(rt: WorkerRuntime) -> None:
    trace = _Trace()
    with _signal_raises(SoftTimeLimitExceeded()), pytest.raises(SoftTimeLimitExceeded):
        rt.run_guarded(_long_job(trace))

    async def next_task() -> str:
        await asyncio.sleep(0.2)
        return "next"

    assert rt.run(next_task()) == "next"
    assert rt.run_guarded(next_task()) == "next"
    assert trace.resumed is False
    assert asyncio.all_tasks(rt.loop) == set()


def test_guarded_run_does_not_suppress_other_base_exceptions(rt: WorkerRuntime) -> None:
    trace = _Trace()
    with _signal_raises(KeyboardInterrupt()), pytest.raises(KeyboardInterrupt):
        rt.run_guarded(_long_job(trace))
    assert trace.cleaned is True
    assert asyncio.all_tasks(rt.loop) == set()


def test_an_exception_raised_inside_the_coroutine_propagates_unchanged(rt: WorkerRuntime) -> None:
    trace = _Trace()
    soft = SoftTimeLimitExceeded()

    async def job() -> None:
        try:
            await asyncio.sleep(0)
            raise soft
        finally:
            trace.cleaned = True

    with pytest.raises(SoftTimeLimitExceeded) as caught:
        rt.run_guarded(job())
    assert caught.value is soft
    assert trace.cleaned is True
    assert asyncio.all_tasks(rt.loop) == set()


def test_a_failing_cleanup_does_not_replace_the_interrupt(rt: WorkerRuntime) -> None:
    async def job() -> None:
        try:
            await asyncio.sleep(5)
        finally:
            raise ValueError("cleanup failed")

    soft = SoftTimeLimitExceeded()
    with _signal_raises(soft), pytest.raises(SoftTimeLimitExceeded) as caught:
        rt.run_guarded(job())
    assert caught.value is soft
    assert asyncio.all_tasks(rt.loop) == set()


def test_a_coroutine_that_ignores_cancellation_cannot_hang_the_worker(rt: WorkerRuntime) -> None:
    stop = asyncio.Event()

    async def stubborn() -> None:
        while not stop.is_set():
            try:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                continue  # swallows the cancellation

    with _signal_raises(SoftTimeLimitExceeded()), pytest.raises(SoftTimeLimitExceeded):
        rt.run_guarded(stubborn(), drain_timeout=0.2)  # returns after the drain budget

    stop.set()  # let the fixture's teardown finish it
    rt.loop.run_until_complete(asyncio.sleep(0.1))
