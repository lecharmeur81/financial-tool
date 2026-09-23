"""Health endpoints.

- ``/health/live``  — the process is up (no dependency checks; used for container restarts).
- ``/health/ready`` — database and Redis reachable; 503 with per-component detail otherwise.

These report *system* health. *Data* health (freshness, coverage, quality) is a separate
concern (ADR-0031).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from cfi.core.health import HealthCheck, run_checks
from cfi.core.time import utc_now

router = APIRouter(prefix="/health", tags=["health"])


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ComponentReport(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float
    detail: dict[str, str]
    error: str | None


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checked_at: datetime
    components: dict[str, ComponentReport]


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse, "description": "A dependency is unavailable"}},
)
async def ready(request: Request, response: Response) -> ReadyResponse:
    checks: dict[str, HealthCheck] = request.app.state.health_checks
    timeout: float = request.app.state.settings.health_check_timeout_seconds
    results = await run_checks(checks, timeout)
    all_ok = all(r.status == "ok" for r in results.values())
    response.status_code = 200 if all_ok else 503
    return ReadyResponse(
        status="ready" if all_ok else "not_ready",
        checked_at=utc_now(),
        components={
            name: ComponentReport(
                status=r.status, latency_ms=r.latency_ms, detail=dict(r.detail), error=r.error
            )
            for name, r in results.items()
        },
    )
