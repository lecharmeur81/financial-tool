"""Request middleware: correlation IDs and one structured access-log event per request."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response

from cfi.core.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

log = get_logger("cfi.access")


def resolve_request_id(incoming: str | None) -> str:
    """Accept a well-formed incoming ID (for tracing across services); otherwise generate one."""
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        structlog.contextvars.unbind_contextvars("request_id")
