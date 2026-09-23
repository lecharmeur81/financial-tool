"""Dependency health checks used by ``/health/ready``."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

HealthStatus = Literal["ok", "error"]


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    status: HealthStatus
    latency_ms: float
    detail: Mapping[str, str] = field(default_factory=dict)
    error: str | None = None


HealthCheck = Callable[[], Awaitable[Mapping[str, str]]]


async def run_check(check: HealthCheck, timeout_seconds: float) -> ComponentHealth:
    """Run one check with a timeout.

    Errors are reported by class name only, because messages can contain connection secrets.
    """
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout_seconds):
            detail = await check()
    except TimeoutError:
        return ComponentHealth(status="error", latency_ms=_elapsed_ms(started), error="timeout")
    except Exception as exc:  # health checks must report, not raise
        return ComponentHealth(
            status="error", latency_ms=_elapsed_ms(started), error=type(exc).__name__
        )
    return ComponentHealth(status="ok", latency_ms=_elapsed_ms(started), detail=detail)


async def run_checks(
    checks: Mapping[str, HealthCheck], timeout_seconds: float
) -> dict[str, ComponentHealth]:
    names = list(checks)
    results = await asyncio.gather(*(run_check(checks[n], timeout_seconds) for n in names))
    return dict(zip(names, results, strict=True))


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
