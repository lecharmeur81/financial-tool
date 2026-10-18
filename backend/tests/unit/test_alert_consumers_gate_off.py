"""Phase 51 closure — fixtures G47 and G48 of ``METHODOLOGY_INVESTMENT_ALERTS.md`` §14 (no
database, no network, no Redis).

G47: with the persistence gate off, ``list_alerts`` for every existing filter combination
(including ``status="active", limit=50``) and the ``GET /api/v1/alerts`` response body are
identical with the investment block present and absent.
G48: with the persistence gate off, the journal and paper ``relevant_alert_ids`` are identical
with the block present and absent.

Method: two ``AlertService.evaluate`` cycles run against two identically seeded in-memory stores,
one with the real investment block and one with the block replaced by a stand-in that returns
nothing (the pre-Stage 6 behavior, as in ``test_alert_service_investment``). The real
``AlertService.list_alerts``, the real route function ``cfi.api.routes.alerts.list_alerts`` and
the real ``DecisionJournalService.create_decision`` / ``PaperTradingService.create_trade`` then
read each store.

Limitation: the in-memory store reproduces the SQL of ``AlertRepository.list_alerts`` (optional
status filter, ``created_at`` descending, ``limit``) but does not execute it; the real SQL and
the HTTP transport are not exercised here. Nothing here enables or validates persistence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

import cfi.alerts.investment_alerts as investment_alerts
import cfi.api.routes.alerts as alerts_route
import cfi.journal.service as journal_module
import cfi.paper.service as paper_module
from cfi.alerts.universe import STATUS_VALUES
from cfi.core.config import Settings
from cfi.journal import context as journal_context
from cfi.journal.service import DecisionJournalService
from cfi.journal.universe import ASSET_SYMBOLS, RELEVANT_ALERTS_LIMIT
from cfi.paper import pnl
from cfi.paper.service import PaperTradingService
from tests.unit.test_alert_service_investment import (
    CREATED,
    NOW,
    SNAPSHOT_ID,
    FakeAlertRepo,
    FakeAnalystRepo,
    Harness,
    _baseline,
)

INVESTMENT_TYPE = "investment_state"
FILTERS: list[tuple[str | None, int]] = [
    (status, limit) for status in (None, *STATUS_VALUES) for limit in (1, 10, 50, 500)
]


# ----------------------------------------------------------------------------- in-memory store


def _row(
    row_id: int, alert_type: str, dedup_key: str, status: str, created_at: datetime
) -> dict[str, Any]:
    return {
        "id": row_id,
        "uuid": uuid.UUID(int=row_id),
        "created_at": created_at,
        "updated_at": created_at,
        "alert_type": alert_type,
        "severity": "notable",
        "domain": "BTC",
        "dedup_key": dedup_key,
        "trigger_condition": "seeded row",
        "observed_value": "v0",
        "reference_value": None,
        "evidence_field_ids": ["get_anomalies.data.BTC"],
        "snapshot_id": None,
        "source_tool_id": "get_anomalies",
        "component_status": "ok",
        "data_quality_state": "ok",
        "status": status,
        "superseded_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
    }


def _seed_rows() -> list[dict[str, Any]]:
    """60 rows (54 active, 6 in other states) plus the active ``divergence:BTC`` row that the
    harness cycle resolves: more than 50 active rows, so the ``limit=50`` window truncates."""
    rows = [
        _row(
            i,
            "anomaly",
            f"anomaly:SEED{i}",
            "active" if i % 10 else STATUS_VALUES[1 + (i // 10) % 3],
            CREATED - timedelta(minutes=61 - i),
        )
        for i in range(1, 61)
    ]
    rows.append(_row(99, "divergence", "divergence:BTC", "active", CREATED - timedelta(hours=2)))
    return rows


class StoreRepo(FakeAlertRepo):
    """``FakeAlertRepo`` that keeps rows, so what a cycle wrote can be read back by consumers."""

    def __init__(
        self,
        calls: list[tuple[Any, ...]],
        existing: Any,
        active: Any,
    ) -> None:
        super().__init__(calls, existing, active)
        self.rows = _seed_rows()

    async def insert_alert(self, **kwargs: Any) -> tuple[int, uuid.UUID]:
        row_id, row_uuid = await super().insert_alert(**kwargs)
        fields = dict(kwargs)
        now = fields.pop("now")
        self.rows.append(
            {
                "id": row_id,
                "uuid": row_uuid,
                "created_at": now,
                "updated_at": now,
                "status": "active",
                "superseded_by": None,
                "acknowledged_at": None,
                "resolved_at": None,
                **fields,
            }
        )
        return row_id, row_uuid

    async def resolve(self, alert_id: int, **kwargs: Any) -> None:
        await super().resolve(alert_id, **kwargs)
        for row in self.rows:
            if row["id"] == alert_id:
                row["status"] = "resolved"
                row["resolved_at"] = kwargs.get("now")
                row["updated_at"] = kwargs.get("now")

    async def supersede(self, old_id: int, **kwargs: Any) -> None:
        await super().supersede(old_id, **kwargs)
        for row in self.rows:
            if row["id"] == old_id:
                row["status"] = "expired"

    async def list_alerts(self, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        """The SQL of ``AlertRepository.list_alerts``: optional status filter, newest first."""
        selected = [r for r in self.rows if status is None or r["status"] == status]
        selected.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
        return [dict(r) for r in selected[:limit]]


@dataclass
class World:
    harness: Harness
    store: StoreRepo


def _attach_store(harness: Harness) -> StoreRepo:
    old = cast(FakeAlertRepo, harness.service.repo)
    store = StoreRepo(harness.calls, old.existing, old.active)
    harness.service.repo = cast(Any, store)
    return store


async def _worlds(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> tuple[World, World]:
    """One cycle with the block absent and one with the real block present, gate off."""
    assert investment_alerts.INVESTMENT_ALERT_PERSISTENCE_ENABLED is False
    with monkeypatch.context() as m:
        base = await _baseline(m, settings)
        base_store = _attach_store(base)
        absent_result = await base.evaluate()
    with monkeypatch.context() as m:
        full = Harness(m, settings, with_existing=True)
        full_store = _attach_store(full)
        present_result = await full.evaluate()

    # The comparison is not vacuous: the real block ran in one world and not in the other, and
    # both cycles did write and resolve rows through the existing path.
    assert absent_result.investment is None
    assert present_result.investment is not None
    assert ("reader.get_snapshot", SNAPSHOT_ID) in full.calls
    assert not any(call[0].startswith("reader.") for call in base.calls)
    assert present_result.created == absent_result.created == 1
    assert present_result.resolved == absent_result.resolved == 1

    # Gate off: the block wrote nothing, so the stores are identical and hold no investment row.
    assert full_store.rows == base_store.rows
    assert all(r["alert_type"] != INVESTMENT_TYPE for r in full_store.rows)
    assert all(not str(r["dedup_key"]).startswith("investment") for r in full_store.rows)
    return World(base, base_store), World(full, full_store)


# ----------------------------------------------------------------------------- G47


async def test_g47_list_alerts_is_identical_for_every_filter_combination(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    absent, present = await _worlds(monkeypatch, settings)
    for status, limit in FILTERS:
        expected = await absent.harness.service.list_alerts(status=status, limit=limit)
        actual = await present.harness.service.list_alerts(status=status, limit=limit)
        assert actual == expected, (status, limit)
        assert all(r["alert_type"] != INVESTMENT_TYPE for r in actual)

    window = await present.harness.service.list_alerts(status="active", limit=50)
    assert len(window) == 50
    assert any(r["id"] > 100 for r in window)  # the newly created row is inside the window


async def _body(
    monkeypatch: pytest.MonkeyPatch, store: StoreRepo, status: str | None, limit: int
) -> list[dict[str, Any]]:
    monkeypatch.setattr(alerts_route, "_repo", lambda _request: store)
    result = await alerts_route.list_alerts(
        cast(Any, SimpleNamespace()), status=status, limit=limit
    )
    return [item.model_dump(mode="json") for item in result]


async def test_g47_get_alerts_response_body_is_identical(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    absent, present = await _worlds(monkeypatch, settings)
    for status, limit in FILTERS:
        expected = await _body(monkeypatch, absent.store, status, limit)
        actual = await _body(monkeypatch, present.store, status, limit)
        assert actual == expected, (status, limit)
        assert all(item["alert_type"] != INVESTMENT_TYPE for item in actual)
    default_window = await _body(monkeypatch, present.store, None, 50)
    assert len(default_window) == 50


# ----------------------------------------------------------------------------- G48


class _Brief:
    async def latest_completed_brief(self) -> None:
        return None


class _Recorder:
    """Stands in for the journal and paper repositories and records what was inserted."""

    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []

    async def insert_decision(self, **kwargs: Any) -> tuple[int, uuid.UUID]:
        self.inserted.append(kwargs)
        return 1, uuid.UUID(int=1)

    async def insert_trade(self, **kwargs: Any) -> tuple[int, uuid.UUID]:
        self.inserted.append(kwargs)
        return 1, uuid.UUID(int=1)

    async def get_by_uuid(self, row_uuid: uuid.UUID) -> dict[str, Any]:
        return {"uuid": row_uuid}


class _Adapters:
    async def price_close(self, asset: str, as_of: datetime) -> list[Any]:
        return []


def _snapshot() -> Any:
    return SimpleNamespace(
        created_at=CREATED,
        as_of=NOW,
        knowledge_time=NOW,
        snapshot_version="analyst_snapshot.v1",
        snapshot_id="producer-hash",
        payload=lambda: {},
    )


async def _journal_ids(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: StoreRepo
) -> list[str]:
    async def fake_build(*_a: object, **_k: object) -> Any:
        return _snapshot()

    monkeypatch.setattr(journal_module, "build_snapshot", fake_build)
    monkeypatch.setattr(journal_context, "regime_label", lambda _s: None)
    monkeypatch.setattr(journal_context, "observed_price", lambda _s, _a: None)
    recorder = _Recorder()
    service = DecisionJournalService(cast(Any, object()), settings)
    service.alert_repo = cast(Any, store)
    service.analyst_repo = cast(Any, FakeAnalystRepo([]))
    service.brief_repo = cast(Any, _Brief())
    service.repo = cast(Any, recorder)
    await service.create_decision(
        asset=ASSET_SYMBOLS[0], decision_type="buy", thesis="test thesis", now=NOW
    )
    (inserted,) = recorder.inserted
    return cast(list[str], inserted["relevant_alert_ids"])


async def _paper_ids(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: StoreRepo
) -> list[str]:
    async def fake_build(*_a: object, **_k: object) -> Any:
        return _snapshot()

    monkeypatch.setattr(paper_module, "build_snapshot", fake_build)
    monkeypatch.setattr(pnl, "current_price", lambda _series, _as_of: Decimal(100))
    recorder = _Recorder()
    service = PaperTradingService(cast(Any, object()), settings)
    service.alert_repo = cast(Any, store)
    service.analyst_repo = cast(Any, FakeAnalystRepo([]))
    service.brief_repo = cast(Any, _Brief())
    service.adapters = cast(Any, _Adapters())
    service.repo = cast(Any, recorder)
    await service.create_trade(
        asset=ASSET_SYMBOLS[0], direction="long", notional=Decimal(1000), now=NOW
    )
    (inserted,) = recorder.inserted
    return cast(list[str], inserted["relevant_alert_ids"])


async def test_g48_journal_relevant_alert_ids_are_identical(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    absent, present = await _worlds(monkeypatch, settings)
    expected = await _journal_ids(monkeypatch, settings, absent.store)
    actual = await _journal_ids(monkeypatch, settings, present.store)
    assert actual == expected
    assert len(actual) == RELEVANT_ALERTS_LIMIT
    investment_ids = {
        str(r["uuid"]) for r in present.store.rows if r["alert_type"] == INVESTMENT_TYPE
    }
    assert investment_ids.isdisjoint(actual)


async def test_g48_paper_relevant_alert_ids_are_identical(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    absent, present = await _worlds(monkeypatch, settings)
    expected = await _paper_ids(monkeypatch, settings, absent.store)
    actual = await _paper_ids(monkeypatch, settings, present.store)
    assert actual == expected
    assert len(actual) == RELEVANT_ALERTS_LIMIT
