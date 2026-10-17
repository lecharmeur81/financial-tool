"""Stale-trigger expiry for the automatic ``alerts.evaluate`` producer.

Offline only: no database, no Redis, no real broker, no Docker. The first group checks the
``send_task`` wrapper (default unchanged, explicit expiry passed through). The second publishes
through a real Celery producer onto the in-memory transport and reads the message back, so
"expires reaches the message" is observed rather than assumed. The third checks which producers
set an expiry: only the automatic data-arrival trigger does.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from celery import Celery
from fastapi.testclient import TestClient

import cfi.api.routes.alerts as alerts_route
import cfi.realtime.service as realtime_module
import cfi.worker.client as client_module
from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.core.health import HealthCheck
from cfi.realtime.service import DATA_ARRIVAL_ALERT_EXPIRES_SECONDS, trigger_cycle_if_due
from cfi.worker.client import send_task
from cfi.worker.schedule import beat_schedule


@pytest.fixture(autouse=True)
def _fresh_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_producer", None)
    monkeypatch.setattr(client_module, "_producer_broker_url", None)


# ------------------------------------------------------------------ wrapper


def test_send_task_default_passes_no_expires(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = MagicMock()
    monkeypatch.setattr(Celery, "send_task", captured)

    send_task(settings, "analyst.analyze", args=("a",), queue="ai")

    assert captured.call_args.kwargs == {"args": ("a",), "queue": "ai"}  # no "expires" key at all


def test_send_task_explicit_expires_is_passed_through(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = MagicMock()
    monkeypatch.setattr(Celery, "send_task", captured)

    send_task(settings, "alerts.evaluate", args=(), queue="alerts", expires=180)

    assert captured.call_args.kwargs == {"args": (), "queue": "alerts", "expires": 180}


# ------------------------------------------------------------------ real message


def _published_message(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, **kwargs: object
) -> Any:
    """Publish through the real wrapper onto an in-memory broker; return the one queued message."""
    app = Celery("expiry-test", broker="memory://")
    monkeypatch.setattr(client_module, "_client", lambda _settings: app)
    send_task(settings, "alerts.evaluate", args=(), queue="alerts", **kwargs)  # type: ignore[arg-type]
    with app.connection_for_read() as conn:
        message = app.amqp.queues["alerts"](conn.default_channel).get(no_ack=True)
    assert message is not None
    return message


def test_expires_reaches_the_published_message(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = datetime.now(UTC)
    message = _published_message(settings, monkeypatch, expires=180)
    expires = datetime.fromisoformat(message.headers["expires"])

    assert 170 <= (expires - before).total_seconds() <= 190  # ~180 s after publishing


def test_no_expires_header_when_not_requested(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    message = _published_message(settings, monkeypatch)

    assert message.headers.get("expires") is None


# ------------------------------------------------------------------ which producers expire


class _FakeRedis:
    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        return True


async def test_data_arrival_trigger_sets_the_180_second_expiry(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = MagicMock()
    monkeypatch.setattr(realtime_module, "send_task", sent)

    assert await trigger_cycle_if_due(_FakeRedis(), settings) is True  # type: ignore[arg-type]

    assert DATA_ARRIVAL_ALERT_EXPIRES_SECONDS == 180
    assert sent.call_args.kwargs == {"args": (), "queue": "alerts", "expires": 180}


async def _ok() -> dict[str, str]:
    return {"note": "fake"}


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    checks: dict[str, HealthCheck] = {"database": _ok, "redis": _ok}
    with TestClient(create_app(settings, health_checks=checks), raise_server_exceptions=False) as c:
        yield c


def test_manual_api_trigger_sets_no_expiry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = MagicMock()
    monkeypatch.setattr(alerts_route, "send_task", sent)

    assert client.post("/api/v1/alerts/evaluate").status_code == 200

    assert sent.call_args.kwargs == {"args": (), "queue": "alerts"}  # unchanged: no "expires"


def test_beat_schedule_is_unchanged() -> None:
    entry = beat_schedule([])["alerts:evaluate"]
    assert entry["schedule"] == 900.0
    assert entry["options"] == {"queue": "ingest", "expires": 900}
