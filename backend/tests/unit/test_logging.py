from __future__ import annotations

import json
import logging

import pytest
import structlog

from cfi.core.logging import REDACTED, configure_logging, get_logger, redact_sensitive


def test_redacts_sensitive_keys_recursively() -> None:
    event = {
        "event": "x",
        "api_key": "k",
        "database_url": "postgresql://u:p@h/db",
        "nested": {"password": "p", "ok": 1},
        "path": "/health",
    }
    out = redact_sensitive(None, "info", event)
    assert out["api_key"] == REDACTED
    assert out["database_url"] == REDACTED
    assert out["nested"] == {"password": REDACTED, "ok": 1}
    assert out["path"] == "/health"


def test_json_log_line_contains_context_and_no_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")
    structlog.contextvars.bind_contextvars(request_id="req-1")
    try:
        get_logger("test").info("hello", token="secret-value", rows=3)
    finally:
        structlog.contextvars.clear_contextvars()
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "hello"
    assert record["request_id"] == "req-1"
    assert record["rows"] == 3
    assert record["token"] == REDACTED
    assert record["level"] == "info"
    assert record["timestamp"].endswith("Z")
    assert "secret-value" not in line


def test_stdlib_loggers_are_structured(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")
    logging.getLogger("uvicorn.error").warning("stdlib message")
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["event"] == "stdlib message"
    assert record["logger"] == "uvicorn.error"
