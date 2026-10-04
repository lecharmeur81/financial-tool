"""Celery serializer configuration (Phase 28, Priority 7): ``cfi.worker.app`` builds its Celery
app and reads ``get_settings()`` at import time, so this module is imported here — not in
``tests/integration`` — with ``CFI_DATABASE_URL``/``CFI_REDIS_URL`` set to dummy-but-valid values
via ``monkeypatch``, no real Postgres/Redis needed (building a ``Celery`` app and reading
``Settings`` never opens a connection)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from types import ModuleType

import pytest

TEST_DATABASE_URL = "postgresql+psycopg://user:not-a-real-password@localhost:5432/cfi_test"
TEST_REDIS_URL = "redis://:not-a-real-password@localhost:6379/0"


@pytest.fixture
def worker_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    monkeypatch.setenv("CFI_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("CFI_REDIS_URL", TEST_REDIS_URL)
    sys.modules.pop("cfi.worker.app", None)
    import cfi.worker.app as worker_app_module

    yield worker_app_module
    sys.modules.pop("cfi.worker.app", None)


def test_celery_app_uses_the_json_serializer_explicitly(worker_app: ModuleType) -> None:
    conf = worker_app.app.conf
    assert conf.task_serializer == "json"
    assert conf.accept_content == ["json"]
    assert conf.result_serializer == "json"
