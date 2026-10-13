"""``MacroService.overview_score`` (the score-only path used by the similarity and regime snapshot
gatherers) against the full ``MacroService.overview``.

The fake below stands in for ``cfi.macro.queries.MacroQueries``. It re-implements the *documented*
semantics of the real query in Python (latest revision per ``event_time`` that is visible under both
``available_at <= as_of`` and ``ingested_at <= knowledge_time``, within ``[start, end)``). It
therefore proves the service passes the right cut-offs and ranges and that both paths agree with
each other and with the golden output captured from the unmodified code. It does NOT prove the
production SQL itself; that needs a database-backed test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from cfi.macro import service as macro_service
from cfi.macro.service import MacroService
from cfi.macro.sources import SOURCES
from cfi.macro.universe import VIX, all_datasets

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "perf_change_set_a"

AS_EARLY = datetime(2026, 9, 10, 9, tzinfo=UTC)
AS_LATE = datetime(2026, 9, 20, 9, tzinfo=UTC)
KT_BETWEEN = datetime(2026, 9, 20, 2, 30, tzinfo=UTC)  # after the revision's available_at only
FROZEN_NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
DAYS = 460

SCENARIOS: dict[str, tuple[datetime, datetime]] = {
    "early": (AS_EARLY, AS_EARLY),
    "late": (AS_LATE, AS_LATE),
    "late_before_revision_ingested": (AS_LATE, KT_BETWEEN),
}


def _row(
    event_time: datetime,
    value: Decimal,
    revision: int,
    available_at: datetime,
    ingested_at: datetime,
) -> dict[str, Any]:
    return {
        "event_time": event_time,
        "value": value,
        "quality_status": "ok",
        "quality_note": None,
        "revision": revision,
        "pit_reliability": "point_in_time",
        "available_at": available_at,
        "available_at_estimated": False,
        "ingested_at": ingested_at,
        "source_provider": "fred",
        "original_source": "fake",
    }


def build_rows() -> dict[str, list[dict[str, Any]]]:
    """Deterministic synthetic observations for every macro dataset (daily event times)."""
    last_day = datetime(2026, 9, 19, tzinfo=UTC)
    rows: dict[str, list[dict[str, Any]]] = {}
    for i, dataset in enumerate(all_datasets()):
        out: list[dict[str, Any]] = []
        for n in range(DAYS):
            event_time = last_day - timedelta(days=DAYS - 1 - n)
            value = (
                Decimal(100 + 7 * i)
                + Decimal(i + 1) / Decimal(100) * n
                + Decimal(n % 5) / Decimal(10)
            )
            available_at = event_time + timedelta(days=1)
            out.append(_row(event_time, value, 0, available_at, available_at + timedelta(hours=1)))
        if dataset.dataset_id == VIX.dataset_id:
            latest = out[-1]
            out.append(
                _row(
                    latest["event_time"],
                    latest["value"] + Decimal(5),
                    1,
                    datetime(2026, 9, 20, 2, tzinfo=UTC),
                    datetime(2026, 9, 20, 3, tzinfo=UTC),
                )
            )
        rows[dataset.dataset_id] = out
    return rows


@dataclass
class FakeMacroQueries:
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=build_rows)
    observation_calls: list[dict[str, Any]] = field(default_factory=list)
    last_job_calls: list[tuple[str, str, str | None]] = field(default_factory=list)

    async def observations(
        self,
        dataset_id: str,
        *,
        subject: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        self.observation_calls.append(
            {
                "dataset_id": dataset_id,
                "subject": subject,
                "start": start,
                "end": end,
                "as_of": as_of,
                "knowledge_time": knowledge_time,
            }
        )
        best: dict[datetime, dict[str, Any]] = {}
        for r in self.rows.get(dataset_id, []):
            if not (start <= r["event_time"] < end):
                continue
            if r["available_at"] > as_of or r["ingested_at"] > knowledge_time:
                continue
            current = best.get(r["event_time"])
            if current is None or r["revision"] > current["revision"]:
                best[r["event_time"]] = r
        return [dict(best[t]) for t in sorted(best)]

    async def last_job(
        self, dataset_id: str, provider_id: str, subject: str | None
    ) -> dict[str, Any] | None:
        self.last_job_calls.append((dataset_id, provider_id, subject))
        return {
            "job_run_id": 1,
            "job_type": "ingest",
            "status": "succeeded",
            "started_at": datetime(2026, 9, 20, 8, tzinfo=UTC),
            "finished_at": datetime(2026, 9, 20, 8, 1, tzinfo=UTC),
            "error_code": None,
            "error_detail": None,
        }


def make_service(queries: FakeMacroQueries | None = None) -> tuple[MacroService, FakeMacroQueries]:
    fake = queries or FakeMacroQueries()
    return MacroService(fake), fake  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macro_service, "utc_now", lambda: FROZEN_NOW)


def dump(value: Any) -> str:
    return json.dumps(value, indent=1, default=str)


def _golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
async def test_full_overview_matches_golden_captured_from_unmodified_code(scenario: str) -> None:
    as_of, kt = SCENARIOS[scenario]
    svc, _ = make_service()
    out = await svc.overview(as_of=as_of, knowledge_time=kt)
    assert dump(out) == _golden(f"macro_overview_{scenario}.json")


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
async def test_score_only_equals_full_overview_without_data_quality(scenario: str) -> None:
    as_of, kt = SCENARIOS[scenario]
    svc, _ = make_service()
    full = await svc.overview(as_of=as_of, knowledge_time=kt)
    svc2, _ = make_service()
    score_only = await svc2.overview_score(as_of=as_of, knowledge_time=kt)
    expected = {k: v for k, v in full.items() if k != "data_quality"}
    assert score_only == expected
    # same key order too (the golden is order-sensitive)
    assert list(score_only) == list(expected)
    assert "data_quality" not in score_only


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
async def test_score_only_matches_golden_minus_data_quality(scenario: str) -> None:
    as_of, kt = SCENARIOS[scenario]
    svc, _ = make_service()
    score_only = await svc.overview_score(as_of=as_of, knowledge_time=kt)
    golden = json.loads(_golden(f"macro_overview_{scenario}.json"))
    golden.pop("data_quality")
    assert json.loads(dump(score_only)) == golden


async def test_score_only_makes_18_observation_calls_and_no_last_job_calls() -> None:
    svc, fake = make_service()
    await svc.overview_score(as_of=AS_LATE, knowledge_time=AS_LATE)
    assert len(fake.observation_calls) == len(all_datasets()) == 18
    assert fake.last_job_calls == []


async def test_full_overview_still_makes_18_observation_and_18_last_job_calls() -> None:
    svc, fake = make_service()
    await svc.overview(as_of=AS_LATE, knowledge_time=AS_LATE)
    assert len(fake.observation_calls) == 18
    assert len(fake.last_job_calls) == len(SOURCES) == 18


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
async def test_both_paths_issue_identical_observation_queries(scenario: str) -> None:
    as_of, kt = SCENARIOS[scenario]
    svc_full, fake_full = make_service()
    svc_score, fake_score = make_service()
    await svc_full.overview(as_of=as_of, knowledge_time=kt)
    await svc_score.overview_score(as_of=as_of, knowledge_time=kt)
    assert fake_score.observation_calls == fake_full.observation_calls
    # the historical range is exactly [as_of - 430 days, as_of + 1 second) for every dataset
    for call in fake_score.observation_calls:
        assert call["start"] == as_of - timedelta(days=430)
        assert call["end"] == as_of + timedelta(seconds=1)
        assert call["as_of"] == as_of
        assert call["knowledge_time"] == kt
    assert [c["dataset_id"] for c in fake_score.observation_calls] == [
        d.dataset_id for d in all_datasets()
    ]


async def test_revision_and_availability_cut_offs_change_the_result_consistently() -> None:
    """The fixture is sensitive: the later revision (and data not yet available) only shows up when
    both ``as_of`` and ``knowledge_time`` allow it, and the score-only path agrees every time."""
    seen: dict[str, Any] = {}
    for name, (as_of, kt) in SCENARIOS.items():
        svc, _ = make_service()
        full = await svc.overview(as_of=as_of, knowledge_time=kt)
        svc2, _ = make_service()
        score_only = await svc2.overview_score(as_of=as_of, knowledge_time=kt)
        assert score_only == {k: v for k, v in full.items() if k != "data_quality"}
        seen[name] = full["vix"]
    assert seen["late"]["value"] != seen["late_before_revision_ingested"]["value"]
    assert seen["early"]["time"] != seen["late"]["time"]
