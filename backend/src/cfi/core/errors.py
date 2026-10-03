"""Error taxonomy (ADR-0030) and RFC 9457 problem-details rendering.

Every error has a stable ``error_code``. Handling rules:
- ProviderTransientError: retry with backoff.
- ProviderPermanentError, ProviderNotConfiguredError: do not retry; alert.
- SchemaMismatchError: store raw payload, mark provider_error, alert, stop the dataset.
- DataValidationError: keep the row as ``suspect``.
- InsufficientDataError: the result is ``missing`` — reported, never guessed.
- ComputationError: a bug; fail loudly.
- AIValidationError: reject or flag the AI output.
- AIBudgetExceededError: refuse the analysis; do not call the API; do not retry.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, ClassVar


class CFIError(Exception):
    """Base class for all expected, typed errors in the system."""

    error_code: ClassVar[str] = "internal_error"
    http_status: ClassVar[int] = HTTPStatus.INTERNAL_SERVER_ERROR
    title: ClassVar[str] = "Internal error"
    retryable: ClassVar[bool] = False

    def __init__(self, detail: str, **context: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.context = context


class ConfigurationError(CFIError):
    error_code = "configuration_error"
    title = "Configuration error"


class ServiceUnavailableError(CFIError):
    error_code = "service_unavailable"
    http_status = HTTPStatus.SERVICE_UNAVAILABLE
    title = "Service unavailable"
    retryable = True


class ProviderError(CFIError):
    """Base for provider (external data source) failures."""

    error_code = "provider_error"
    http_status = HTTPStatus.BAD_GATEWAY
    title = "Data provider error"


class ProviderTransientError(ProviderError):
    error_code = "provider_transient_error"
    title = "Data provider temporarily unavailable"
    retryable = True


class ProviderPermanentError(ProviderError):
    error_code = "provider_permanent_error"
    title = "Data provider request failed permanently"


class ProviderNotConfiguredError(ProviderError):
    error_code = "provider_not_configured"
    http_status = HTTPStatus.NOT_IMPLEMENTED
    title = "Data provider not configured"


class SchemaMismatchError(ProviderError):
    error_code = "schema_mismatch"
    title = "Provider payload does not match the expected schema"


class DataValidationError(CFIError):
    error_code = "data_validation_error"
    http_status = HTTPStatus.UNPROCESSABLE_ENTITY
    title = "Data failed validation"


class NotYetFinalError(DataValidationError):
    """A record that was not final when received (an unfinished bar, a provider's running value).

    Not an error in the data: the record is skipped, counted, and fetched again once final.
    """

    error_code = "not_yet_final"
    title = "Value not final yet"


class NotFoundError(CFIError):
    error_code = "not_found"
    http_status = HTTPStatus.NOT_FOUND
    title = "Not found"


class InsufficientDataError(CFIError):
    error_code = "insufficient_data"
    http_status = HTTPStatus.UNPROCESSABLE_ENTITY
    title = "Insufficient data."


class ComputationError(CFIError):
    error_code = "computation_error"
    title = "Computation failed"


class AIValidationError(CFIError):
    error_code = "ai_validation_error"
    http_status = HTTPStatus.UNPROCESSABLE_ENTITY
    title = "AI output failed validation"


class AIBudgetExceededError(CFIError):
    """The monthly Claude API budget ceiling (Settings.ai_monthly_budget_usd, TODO.md B3) has been
    met or exceeded for the current calendar month. Never a silent skip (R3): the analysis fails
    explicitly with this error, visible to the caller and recorded on the interpretation row."""

    error_code = "ai_budget_exceeded"
    http_status = HTTPStatus.SERVICE_UNAVAILABLE
    title = "AI monthly budget exceeded"


PROBLEM_JSON = "application/problem+json"


def problem_details(
    *,
    status: int,
    title: str,
    detail: str,
    error_code: str,
    request_id: str | None,
    instance: str | None = None,
) -> dict[str, Any]:
    """Build an RFC 9457 problem-details body. Never includes stack traces or secrets."""
    body: dict[str, Any] = {
        "type": f"urn:cfi:error:{error_code}",
        "title": title,
        "status": status,
        "detail": detail,
        "error_code": error_code,
    }
    if instance is not None:
        body["instance"] = instance
    if request_id is not None:
        body["request_id"] = request_id
    return body
