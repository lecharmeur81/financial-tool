"""The API process's lightweight Celery producer (Phase 21): it must send tasks using the caller's
own ``Settings``, never the global ``get_settings()``, and it must never import ``cfi.worker.app``
(that module eagerly builds every ingestion domain's adapters and calls ``get_settings()`` at
import time, which is exactly what made the API endpoint fail under test settings before this
module existed — see ADR-0068)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from celery import Celery

import cfi.worker.client as client_module
from cfi.core.config import Settings
from cfi.worker.client import send_task


def test_send_task_uses_the_given_settings_broker_url(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client_module, "_producer", None)
    monkeypatch.setattr(client_module, "_producer_broker_url", None)

    captured = MagicMock()
    monkeypatch.setattr(Celery, "send_task", captured)

    send_task(settings, "analyst.analyze", args=("id-1", "2026-01-01T00:00:00Z"), queue="ai")

    captured.assert_called_once()
    (name,) = captured.call_args.args
    assert name == "analyst.analyze"
    assert captured.call_args.kwargs["args"] == ("id-1", "2026-01-01T00:00:00Z")
    assert captured.call_args.kwargs["queue"] == "ai"
