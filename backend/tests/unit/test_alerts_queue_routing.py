"""Dedicated ``alerts`` queue (alerts.evaluate isolation): which queue each producer publishes to,
that Beat is unchanged, that the debounce and the cycle lock behave as before, and that the
``worker-alerts`` compose service consumes only ``alerts``.

Offline only: no database, no Redis, no broker, no Docker. ``send_task`` is replaced by a recorder
and Redis by a small fake. The compose test reads ``compose.yaml`` from the repository root (or
the file named by ``CFI_COMPOSE_FILE``) and is skipped where that file is absent (e.g. inside the
image).
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import cfi.api.routes.alerts as alerts_route
import cfi.realtime.service as realtime_module
from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.core.health import HealthCheck
from cfi.realtime.service import RealtimeIntelligenceService, trigger_cycle_if_due
from cfi.realtime.universe import (
    CYCLE_LOCK_KEY,
    CYCLE_LOCK_TTL_SECONDS,
    DATA_ARRIVAL_DEBOUNCE_KEY,
    DATA_ARRIVAL_DEBOUNCE_SECONDS,
)
from cfi.worker.schedule import beat_schedule

# PyYAML is a locked (transitive) dependency but no type stubs are installed for it; importing it
# dynamically keeps mypy strict without a new dependency or a ``type: ignore`` (which would itself
# fail under ``warn_unused_ignores`` wherever stubs are present). A missing PyYAML still fails
# loudly at import.
yaml = importlib.import_module("yaml")


class FakeRedis:
    """Just enough of ``redis.asyncio.Redis`` for SET NX EX and the compare-and-delete release
    script, with call recording."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, dict[str, Any]]] = []
        self.deleted: list[str] = []
        self.eval_calls: list[tuple[str, str]] = []

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        self.set_calls.append((key, {"nx": nx, "ex": ex}))
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        return 1 if self.store.pop(key, None) is not None else 0

    async def eval(self, _script: str, numkeys: int, key: str, token: str) -> int:
        """The release script: delete ``key`` only when it still holds ``token``."""
        assert numkeys == 1
        self.eval_calls.append((key, token))
        if self.store.get(key) == token:
            del self.store[key]
            self.deleted.append(key)
            return 1
        return 0


# ---------------------------------------------------------------- data-arrival producer


async def test_data_arrival_trigger_publishes_to_the_alerts_queue(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = MagicMock()
    monkeypatch.setattr(realtime_module, "send_task", sent)
    redis = FakeRedis()

    assert await trigger_cycle_if_due(redis, settings) is True  # type: ignore[arg-type]

    sent.assert_called_once_with(settings, "alerts.evaluate", args=(), queue="alerts", expires=180)


async def test_data_arrival_debounce_is_unchanged(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = MagicMock()
    monkeypatch.setattr(realtime_module, "send_task", sent)
    redis = FakeRedis()

    assert await trigger_cycle_if_due(redis, settings) is True  # type: ignore[arg-type]
    assert await trigger_cycle_if_due(redis, settings) is False  # type: ignore[arg-type]

    assert sent.call_count == 1  # the second call, inside the window, published nothing
    assert redis.set_calls[0] == (
        DATA_ARRIVAL_DEBOUNCE_KEY,
        {"nx": True, "ex": DATA_ARRIVAL_DEBOUNCE_SECONDS},
    )
    assert DATA_ARRIVAL_DEBOUNCE_SECONDS == 60


# ---------------------------------------------------------------- manual API producer


async def _ok() -> Mapping[str, str]:
    return {"note": "fake"}


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    checks: dict[str, HealthCheck] = {"database": _ok, "redis": _ok}
    app = create_app(settings, health_checks=checks)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_manual_api_trigger_publishes_to_the_alerts_queue(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = MagicMock()
    monkeypatch.setattr(alerts_route, "send_task", sent)

    response = client.post("/api/v1/alerts/evaluate")

    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    sent.assert_called_once()
    assert sent.call_args.args[1] == "alerts.evaluate"
    assert sent.call_args.kwargs == {"args": (), "queue": "alerts"}


# ---------------------------------------------------------------- Beat is unchanged


def test_beat_still_publishes_alerts_evaluate_to_ingest() -> None:
    entry = beat_schedule([])["alerts:evaluate"]
    assert entry["task"] == "alerts.evaluate"
    assert entry["schedule"] == 900.0
    assert entry["options"] == {"queue": "ingest", "expires": 900}


# ---------------------------------------------------------------- cycle lock (no database)


def _service(redis: FakeRedis, settings: Settings) -> RealtimeIntelligenceService:
    svc = RealtimeIntelligenceService(MagicMock(), settings, redis=redis)  # type: ignore[arg-type]
    return svc


async def test_cycle_lock_is_a_global_nx_key_with_the_documented_ttl(
    settings: Settings,
) -> None:
    redis = FakeRedis()
    svc = _service(redis, settings)
    assert await svc._acquire_lock() is not None
    assert await svc._acquire_lock() is None  # same key, whichever worker asks
    assert redis.set_calls[0] == (CYCLE_LOCK_KEY, {"nx": True, "ex": CYCLE_LOCK_TTL_SECONDS})
    assert (CYCLE_LOCK_KEY, CYCLE_LOCK_TTL_SECONDS) == ("cfi:realtime:cycle_lock", 150)


async def test_a_held_lock_skips_the_cycle_without_evaluating(settings: Settings) -> None:
    redis = FakeRedis()
    redis.store[CYCLE_LOCK_KEY] = "another-cycle-token"
    svc = _service(redis, settings)
    svc.alerts = MagicMock()  # evaluate must never be reached

    result = await svc.process_cycle(as_of=None, knowledge_time=None, now=None)  # type: ignore[arg-type]

    assert result.locked_out is True
    assert not svc.alerts.evaluate.called
    assert redis.deleted == []  # a locked-out run must not delete the holder's lock
    assert redis.eval_calls == []  # ...nor even attempt a release
    assert redis.store[CYCLE_LOCK_KEY] == "another-cycle-token"


async def test_the_lock_is_released_when_the_evaluation_raises(settings: Settings) -> None:
    redis = FakeRedis()
    svc = _service(redis, settings)

    class BoomError(Exception):
        pass

    async def boom(**_: Any) -> None:
        raise BoomError

    svc.alerts = MagicMock()
    svc.alerts.evaluate = boom
    with pytest.raises(BoomError):
        await svc.process_cycle(as_of=None, knowledge_time=None, now=None)  # type: ignore[arg-type]

    assert CYCLE_LOCK_KEY not in redis.store
    assert redis.deleted == [CYCLE_LOCK_KEY]


# ---------------------------------------------------------------- compose: worker-alerts


def _compose_path() -> Path | None:
    override = os.environ.get("CFI_COMPOSE_FILE")
    path = Path(override) if override else Path(__file__).resolve().parents[3] / "compose.yaml"
    return path if path.is_file() else None


def _flags(command: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    it = iter(command)
    for token in it:
        if token == "-Q":
            out["-Q"] = next(it)
        elif token.startswith("--") and "=" in token:
            key, value = token.split("=", 1)
            out[key] = value
    return out


def test_worker_alerts_service_consumes_only_the_alerts_queue() -> None:
    path = _compose_path()
    if path is None:
        pytest.skip("compose.yaml is not available in this environment")
    services = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]
    svc = services["worker-alerts"]
    flags = _flags(svc["command"])

    assert svc["command"][:5] == ["celery", "-A", "cfi.worker.app", "worker", "-Q"]
    assert flags["-Q"] == "alerts"  # exactly one queue, and it is alerts
    assert flags["--concurrency"] == "1"
    assert flags["--hostname"] == "alerts@%h"
    assert flags["--max-tasks-per-child"] == "1"
    assert svc["image"] == "cfi-backend:dev"
    assert svc["restart"] == "unless-stopped"
    assert svc["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert svc["depends_on"]["redis"]["condition"] == "service_healthy"
    assert svc["environment"] == services["worker"]["environment"]  # same shared env anchor
    grace = svc["stop_grace_period"]
    assert grace.endswith("s")
    assert int(grace[:-1]) >= 125  # > 120 s hard limit + teardown


def test_no_other_service_consumes_alerts_and_beat_is_untouched() -> None:
    path = _compose_path()
    if path is None:
        pytest.skip("compose.yaml is not available in this environment")
    services = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]
    consumers = {
        name: _flags(s["command"]).get("-Q")
        for name, s in services.items()
        if isinstance(s.get("command"), list) and "worker" in s["command"]
    }
    assert consumers["worker"] == "ingest_fast,ingest"
    assert consumers["worker-backfill"] == "backfill"
    assert [n for n, q in consumers.items() if q and "alerts" in q.split(",")] == ["worker-alerts"]
    beat = services["beat"]["command"]
    assert "beat" in beat
    assert "--schedule" in beat
