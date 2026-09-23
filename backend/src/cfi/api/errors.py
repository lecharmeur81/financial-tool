"""Exception handlers: every error leaves the API as RFC 9457 problem details (ADR-0030)."""

from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from cfi.api.middleware import REQUEST_ID_HEADER
from cfi.core.errors import PROBLEM_JSON, CFIError, problem_details
from cfi.core.logging import get_logger

log = get_logger(__name__)


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _problem_response(
    request: Request, *, status: int, title: str, detail: str, error_code: str
) -> JSONResponse:
    request_id = _request_id(request)
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(
        status_code=status,
        content=problem_details(
            status=status,
            title=title,
            detail=detail,
            error_code=error_code,
            request_id=request_id,
            instance=request.url.path,
        ),
        media_type=PROBLEM_JSON,
        headers=headers,
    )


async def handle_cfi_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CFIError)  # noqa: S101 — registered for CFIError only
    level = "error" if exc.http_status >= HTTPStatus.INTERNAL_SERVER_ERROR else "warning"
    getattr(log, level)("request_failed", error_code=exc.error_code, detail=exc.detail)
    return _problem_response(
        request,
        status=int(exc.http_status),
        title=exc.title,
        detail=exc.detail,
        error_code=exc.error_code,
    )


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    status = exc.status_code
    title = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "HTTP error"
    code = {404: "not_found", 405: "method_not_allowed"}.get(status, f"http_{status}")
    return _problem_response(
        request, status=status, title=title, detail=str(exc.detail), error_code=code
    )


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    fields = ", ".join(".".join(str(p) for p in err.get("loc", ())) for err in exc.errors())
    return _problem_response(
        request,
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        title="Request validation failed",
        detail=f"Invalid request parameters: {fields}" if fields else "Invalid request",
        error_code="request_validation_error",
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Full details go to the log (with stack trace); the client gets a generic message + request ID.
    log.exception(
        "unhandled_exception", error_type=type(exc).__name__, request_id=_request_id(request)
    )
    return _problem_response(
        request,
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        title="Internal error",
        detail="An unexpected error occurred. Quote the request_id when reporting it.",
        error_code="internal_error",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(CFIError, handle_cfi_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
