"""Structured wall-clock timing for the stages of one alert-evaluation / real-time cycle.

One log line per stage, written in a ``finally`` so an interrupted stage (a Celery time-limit
signal, a task cancellation) still reports how long it ran before the interrupt. Nothing is
suppressed or altered: the exception, if any, always propagates unchanged. Only the stage name,
status, duration and small caller-supplied scalars are logged — never payloads or settings.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded

StageStatus = Literal["ok", "failed", "interrupted"]

# An interruption is the runtime stopping the work, not the work failing.
_INTERRUPTS: tuple[type[BaseException], ...] = (
    SoftTimeLimitExceeded,
    TimeLimitExceeded,
    asyncio.CancelledError,
    KeyboardInterrupt,
    SystemExit,
)


def status_for(error: BaseException | None) -> StageStatus:
    if error is None:
        return "ok"
    return "interrupted" if isinstance(error, _INTERRUPTS) else "failed"


@contextmanager
def timed_stage(
    logger: Any, event: str, /, **fields: str | int | float | bool | None
) -> Iterator[dict[str, Any]]:
    """Log ``event`` with ``status`` and ``elapsed_ms`` when the block ends, however it ends.

    Yields a dict the block may fill with extra scalar fields (e.g. a count known only at the end).
    """
    extra: dict[str, Any] = {}
    started = time.monotonic()
    error: BaseException | None = None
    try:
        yield extra
    except BaseException as exc:
        error = exc
        raise
    finally:
        logger.info(
            event,
            status=status_for(error),
            elapsed_ms=round((time.monotonic() - started) * 1000),
            **fields,
            **extra,
        )
