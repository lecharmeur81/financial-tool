"""Regression coverage for Phase 30 finding F-2 (downgraded on investigation — see
``cfi.api.errors.handle_unexpected_error``, already registered for every unhandled exception).

Phase 30's reproduction captured a full SQL/stack-trace in the *server log* and mistook that for
a client-facing leak; FastAPI's ``TestClient`` with its default ``raise_server_exceptions=True``
re-raises the exception into the test process instead of returning the HTTP response the handler
actually produced, which is what made it look that way. With ``raise_server_exceptions=False``
(the setting every real HTTP client's behavior corresponds to — a real client never sees the
server process's Python exception, only the HTTP response), the client receives the sanitized
RFC 9457 body ``handle_unexpected_error`` already builds.

This needs a real, reachable database (an integration test, not a unit API test): the existing
unit harness in ``tests/api/test_security.py`` deliberately never sets ``app.state.engine`` when
``health_checks`` is supplied, so every DB-touching route 503s before reaching the service layer
at all — useful for auth/rate-limit testing, but it can never reach the handler this finding is
about. Here, a real (migrated, empty-by-default) test database lets the request reach the
service layer, where a patched method raises a deliberately SQL/secret-shaped exception, exactly
as a real ``ProgrammingError`` or similar unexpected failure would."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

SENSITIVE_MESSAGE = (
    "SELECT * FROM usr.decision_journal WHERE token='sk-live-abcdef123456' "
    "AND password = 'supersecret123' -- bound params: {'decision_id': '...'}"
)


def test_an_unhandled_exception_never_reaches_the_client_as_a_raw_error(
    test_settings: Settings,
) -> None:
    """A genuine, unanticipated exception (not a ``CFIError``) — carrying SQL text, a bound
    parameter placeholder, and a secret-shaped value, exactly what a real ``ProgrammingError``
    or similar would include — must still leave the API as the generic, sanitized
    ``internal_error`` problem-details body. Nothing of ``SENSITIVE_MESSAGE`` may appear in the
    response the client actually receives."""

    async def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(SENSITIVE_MESSAGE)

    with (
        patch("cfi.journal.service.DecisionJournalService.get_decision", boom),
        TestClient(create_app(test_settings), raise_server_exceptions=False) as client,
    ):
        response = client.get("/api/v1/journal/decisions/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["error_code"] == "internal_error"
    assert body["type"] == "urn:cfi:error:internal_error"
    raw_text = response.text
    assert "supersecret123" not in raw_text
    assert "sk-live-" not in raw_text
    assert "SELECT" not in raw_text
    assert "RuntimeError" not in raw_text
    assert "Traceback" not in raw_text
    assert "bound params" not in raw_text
    assert "request_id" in body
