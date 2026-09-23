"""Structured logging (ADR-0029).

- JSON lines to stdout (``console`` format available for local debugging).
- Correlation IDs (``request_id``; later ``job_id``, ``snapshot_id``) bound via context
  variables.
- Standard-library loggers (uvicorn, alembic) are routed through the same pipeline.
- Values under sensitive keys are redacted before rendering (R9).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from cfi.core.config import LogFormat, LogLevel

REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = ("password", "secret", "token", "api_key", "apikey", "authorization", "dsn")


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS) or lowered.endswith("_url")


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: replace values of sensitive keys (recursively in dicts)."""

    def scrub(mapping: MutableMapping[str, Any]) -> None:
        for key, value in list(mapping.items()):
            if _is_sensitive(key):
                mapping[key] = REDACTED
            elif isinstance(value, MutableMapping):
                scrub(value)

    scrub(event_dict)
    return event_dict


def _shared_processors() -> list[structlog.types.Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]


def configure_logging(level: LogLevel = "INFO", fmt: LogFormat = "json") -> None:
    """Configure structlog and the standard library to emit one structured event per line."""
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn installs its own handlers; route them through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
    # Access lines are emitted by our request middleware with a request_id; avoid duplicates.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
