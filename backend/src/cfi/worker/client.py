"""A minimal Celery producer for the API process (Phase 21).

``cfi.worker.app`` builds the *real* Celery application — the one workers run — and constructing
it pulls in every ingestion domain's adapters, sources and jobs (it also eagerly calls
``get_settings()`` at import time, which fails outside a fully configured environment; see
ADR-0068). The API process only ever needs to enqueue a task by name; it must never import that
module just to do so. This module is a separate, deliberately tiny ``Celery`` instance, configured
from whatever ``Settings`` the caller already has (never the global ``get_settings()``), used
purely to call ``send_task`` — it never defines a task and is never run as a worker.
"""

from __future__ import annotations

from celery import Celery

from cfi.core.config import Settings

_producer: Celery | None = None
_producer_broker_url: str | None = None


def _client(settings: Settings) -> Celery:
    global _producer, _producer_broker_url
    broker_url = settings.redis_url.get_secret_value()
    if _producer is None or _producer_broker_url != broker_url:
        producer = Celery("cfi-api-producer")
        producer.conf.update(broker_url=broker_url, broker_connection_retry_on_startup=True)
        _producer, _producer_broker_url = producer, broker_url
    return _producer


def send_task(settings: Settings, name: str, *, args: tuple[object, ...], queue: str) -> None:
    """Enqueue ``name`` with ``args`` on ``queue``. Fire-and-forget (``task_ignore_result`` on the
    real worker app, mirrored here by never waiting on a result)."""
    _client(settings).send_task(name, args=args, queue=queue)
