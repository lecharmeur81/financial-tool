"""``RegimeService.current`` overlaps today's snapshot with yesterday's classification when given a
concurrency allowance; the result and the error order match the sequential path."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from cfi.regime import service as svc

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


class SnapshotError(Exception):
    pass


class YesterdayError(Exception):
    pass


def _service(monkeypatch: pytest.MonkeyPatch, *, log: list[str], fail: str | None = None) -> Any:
    async def fake_snapshot(
        adapters: Any, *, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> Any:
        log.append("snapshot-start")
        await asyncio.sleep(0.01)
        if fail == "snapshot":
            raise SnapshotError
        log.append("snapshot-end")
        return SimpleNamespace(as_of=as_of)

    def fake_classify(snapshot: Any, params: Any, *, previous_regime_id: str | None = None) -> Any:
        return SimpleNamespace(
            regime_id="mixed_unclear",
            label="Mixed",
            confidence=None,
            status="ok",
            reason=f"prev={previous_regime_id}",
            held_by_hysteresis=False,
            contributing=[],
            contradicting=[],
            candidates=[],
        )

    monkeypatch.setattr(svc, "gather_snapshot", fake_snapshot)
    monkeypatch.setattr(svc, "classify", fake_classify)
    service = svc.RegimeService(SimpleNamespace())

    async def fake_classify_at(as_of: datetime, *, previous_regime_id: str | None = None) -> Any:
        log.append("classify-at")
        await asyncio.sleep(0.01)
        if fail == "yesterday" and previous_regime_id is None:
            raise YesterdayError
        return SimpleNamespace(regime_id="mixed_unclear", status="ok", confidence=None)

    monkeypatch.setattr(service, "_classify_at", fake_classify_at)
    return service


def test_overlapped_result_equals_sequential(monkeypatch: pytest.MonkeyPatch) -> None:
    a = asyncio.run(
        _service(monkeypatch, log=[]).current(
            as_of=NOW, knowledge_time=NOW, historical_concurrency=1
        )
    )
    b = asyncio.run(
        _service(monkeypatch, log=[]).current(
            as_of=NOW, knowledge_time=NOW, historical_concurrency=3
        )
    )
    assert a == b


def test_default_stays_sequential(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    asyncio.run(_service(monkeypatch, log=log).current(as_of=NOW, knowledge_time=NOW))
    assert log.index("snapshot-end") < log.index("classify-at")


def test_with_concurrency_the_two_reads_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    asyncio.run(
        _service(monkeypatch, log=log).current(
            as_of=NOW, knowledge_time=NOW, historical_concurrency=3
        )
    )
    assert log.index("classify-at") < log.index("snapshot-end")


@pytest.mark.parametrize(
    ("fail", "exc"), [("snapshot", SnapshotError), ("yesterday", YesterdayError)]
)
def test_errors_are_the_same_either_way(
    monkeypatch: pytest.MonkeyPatch, fail: str, exc: type[Exception]
) -> None:
    for conc in (1, 3):
        with pytest.raises(exc):
            asyncio.run(
                _service(monkeypatch, log=[], fail=fail).current(
                    as_of=NOW, knowledge_time=NOW, historical_concurrency=conc
                )
            )
