"""Phase 51 Stage 6 — ``AlertService`` with the investment-alert block (no database, no network).

The repositories, the snapshot builder, the 11 evaluators and the clock are fakes; the reader is an
in-memory fake whose rows go through the *real* adapter, evaluator and planner. Fixtures G34, G35,
G36, G39, G44, G53 and G54 of ``METHODOLOGY_INVESTMENT_ALERTS.md`` §11 and §14: the 11 existing
types behave identically with the block present and absent, investment outcomes never enter
``EvaluationResult.decisions``, the real realtime event and AI-trigger paths see nothing from the
block, an ordinary failure is contained, and time-limit and cancellation signals escape
``evaluate``. Nothing here validates persistence or real database snapshots.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded
from pydantic import SecretStr

import cfi.alerts.investment_block as block
import cfi.alerts.service as service_module
import cfi.realtime.service as realtime_module
from cfi.alerts.investment_block import InvestmentCycleResult
from cfi.alerts.lifecycle import ExistingAlert
from cfi.alerts.rules import AlertCandidate
from cfi.alerts.service import AlertService, CandidateDecision, EvaluationResult
from cfi.alerts.universe import ALERT_TYPE_TOOL_IDS
from cfi.core.config import Settings
from cfi.decision.identity import producer_payload_hash
from cfi.decision_store.repository import DecisionAssessmentRepository
from cfi.realtime.service import RealtimeIntelligenceService
from tests.decision_builders import make_payload

SNAPSHOT_ID = 77
ROW_UUID = "00000000-0000-0000-0000-000000000077"
CREATED = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
AS_OF = CREATED - timedelta(minutes=2)
KNOWLEDGE = CREATED - timedelta(minutes=1)
NOW = CREATED + timedelta(minutes=5)


# ----------------------------------------------------------------------------- fakes


class Row:
    def __init__(self) -> None:
        payload = make_payload(["S2", "S1", "N", "S1", "S2"])
        payload["snapshot_version"] = "analyst_snapshot.v1"
        self.row_id = SNAPSHOT_ID
        self.uuid = ROW_UUID
        self.payload_hash = producer_payload_hash(payload)
        self.created_at = CREATED
        self.as_of = AS_OF
        self.knowledge_time = KNOWLEDGE
        self.payload = payload


class RecordingReader:
    """Exposes ``get_snapshot`` and nothing else: any other attribute access fails the test."""

    def __init__(
        self,
        calls: list[tuple[Any, ...]],
        *,
        row: Row | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._calls = calls
        self._row = row
        self._error = error

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the block may only call get_snapshot, not {name}")

    async def get_snapshot(self, snapshot_id: int) -> Row | None:
        self._calls.append(("reader.get_snapshot", snapshot_id))
        if self._error is not None:
            raise self._error
        return self._row


class FakeAlertRepo:
    def __init__(
        self,
        calls: list[tuple[Any, ...]],
        existing: dict[str, ExistingAlert] | None = None,
        active: dict[str, list[tuple[str, int]]] | None = None,
    ) -> None:
        self.calls = calls
        self.existing = existing or {}
        self.active = active or {}
        self.next_id = 100

    async def latest_active_for_key(self, key: str) -> ExistingAlert | None:
        self.calls.append(("repo.latest_active_for_key", key))
        return self.existing.get(key)

    async def insert_alert(self, **kwargs: Any) -> tuple[int, uuid.UUID]:
        self.calls.append(("repo.insert_alert", kwargs["dedup_key"], kwargs["observed_value"]))
        self.next_id += 1
        return self.next_id, uuid.UUID(int=self.next_id)

    async def latest_active_id_for_key(self, key: str) -> int | None:
        self.calls.append(("repo.latest_active_id_for_key", key))
        return None

    async def supersede(self, old_id: int, **kwargs: Any) -> None:
        self.calls.append(("repo.supersede", old_id))

    async def active_entries_with_prefix(self, prefix: str) -> list[tuple[str, int]]:
        self.calls.append(("repo.active_entries_with_prefix", prefix))
        return list(self.active.get(prefix, []))

    async def resolve(self, alert_id: int, **kwargs: Any) -> None:
        self.calls.append(("repo.resolve", alert_id))


class FakeAnalystRepo:
    def __init__(self, calls: list[tuple[Any, ...]], error: BaseException | None = None) -> None:
        self.calls = calls
        self.error = error
        self.queued: list[str] = []

    async def latest_snapshot(self) -> tuple[int, dict[str, Any]] | None:
        self.calls.append(("analyst.latest_snapshot",))
        return None

    async def insert_snapshot(self, **kwargs: Any) -> tuple[int, uuid.UUID]:
        self.calls.append(("analyst.insert_snapshot",))
        if self.error is not None:
            raise self.error
        return SNAPSHOT_ID, uuid.UUID(ROW_UUID)

    async def create_queued_interpretation(self, *, now: datetime, question: str) -> Any:
        self.queued.append(question)
        return 1, uuid.UUID(int=1)


class FakeEvents:
    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []
        self.marked: list[Any] = []

    async def insert_event(self, **kwargs: Any) -> int | None:
        self.inserted.append(kwargs)
        return len(self.inserted)

    async def latest_ai_requested_at(self) -> datetime | None:
        return None

    async def mark_ai_requested(self, event: Any, **kwargs: Any) -> None:
        self.marked.append(event)


class FakeLog:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.calls.append(("info", event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self.calls.append(("warning", event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self.calls.append(("error", event, fields))

    def investment(self) -> list[tuple[str, str, dict[str, Any]]]:
        return [c for c in self.calls if c[1] == block.EVENT_NAME]


def _candidate(
    key: str = "anomaly:BTC", value: str = "v1", severity: str = "notable"
) -> AlertCandidate:
    return AlertCandidate(
        alert_type="anomaly",
        severity=severity,
        domain="BTC",
        trigger_condition="a BTC anomaly was detected",
        observed_value=value,
        reference_value=None,
        evidence_field_ids=("get_anomalies.data.BTC",),
        source_tool_id="get_anomalies",
        component_status="ok",
        dedup_key=key,
    )


class Harness:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        settings: Settings,
        *,
        candidates: list[AlertCandidate] | None = None,
        reader_row: Row | None = None,
        reader_error: BaseException | None = None,
        insert_error: BaseException | None = None,
        with_existing: bool = False,
    ) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.log = FakeLog()
        self.settings = settings
        self.candidates = candidates if candidates is not None else self.default_candidates()
        existing = (
            {"anomaly:ETH": ExistingAlert(observed_value="v1", timestamp=NOW - timedelta(hours=3))}
            if with_existing
            else {}
        )
        active = {"divergence:": [("divergence:BTC", 99)]} if with_existing else {}
        self.reader = RecordingReader(
            self.calls,
            row=reader_row if reader_row is not None else Row(),
            error=reader_error,
        )
        self.service = AlertService(
            cast(Any, object()), settings, snapshot_reader=cast(Any, self.reader)
        )
        self.service.repo = cast(Any, FakeAlertRepo(self.calls, existing, active))
        self.analyst = FakeAnalystRepo(self.calls, insert_error)
        self.service.analyst_repo = cast(Any, self.analyst)
        snapshot = SimpleNamespace(
            created_at=CREATED,
            as_of=AS_OF,
            knowledge_time=KNOWLEDGE,
            snapshot_version="analyst_snapshot.v1",
            snapshot_id="producer-hash",
            data_quality_state="ok",
            payload=lambda: {},
        )
        self.snapshot = snapshot

        async def fake_build(*_a: object, **_k: object) -> Any:
            return snapshot

        monkeypatch.setattr(service_module, "build_snapshot", fake_build)
        monkeypatch.setattr(
            service_module,
            "compute_changes",
            lambda *_a, **_k: SimpleNamespace(comparison_basis="none", changes=[]),
        )
        monkeypatch.setattr(service_module, "evaluate_all", lambda _s: list(self.candidates))
        # Phase 52: auto-resolve needs explicit clearance evidence. The stub snapshot has no raw
        # tool results, so the evidence is stated here: the divergence alert in ``active`` cleared.
        monkeypatch.setattr(
            service_module, "cleared_dedup_keys", lambda _s: frozenset({"divergence:BTC"})
        )
        monkeypatch.setattr(service_module, "log", self.log)

    @staticmethod
    def default_candidates() -> list[AlertCandidate]:
        return [_candidate("anomaly:BTC", "v1"), _candidate("anomaly:ETH", "v1")]

    async def evaluate(self) -> EvaluationResult:
        return await self.service.evaluate(as_of=AS_OF, knowledge_time=KNOWLEDGE, now=NOW)

    def existing_type_calls(self) -> list[tuple[Any, ...]]:
        return [c for c in self.calls if not c[0].startswith("reader.")]


def _comparable(result: EvaluationResult) -> dict[str, Any]:
    return {
        f.name: getattr(result, f.name)
        for f in dataclasses.fields(result)
        if f.name != "investment"
    }


async def _baseline(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Harness:
    """The pre-Stage 6 behavior: the block replaced by a stand-in that returns nothing."""
    harness = Harness(monkeypatch, settings, with_existing=True)

    async def absent(*_a: object, **_k: object) -> Any:
        return None

    monkeypatch.setattr(service_module, "run_investment_cycle", absent)
    return harness


# ----------------------------------------------------------------------------- S-01 parity


@pytest.mark.parametrize("scenario", ["evaluated", "refused", "internal_error"])
async def test_s01_the_11_types_and_the_repository_calls_are_identical_with_and_without_the_block(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, scenario: str
) -> None:
    with monkeypatch.context() as m:
        base = await _baseline(m, settings)
        expected = await base.evaluate()
    assert expected.investment is None
    assert expected.created == 1
    assert expected.skipped_unchanged == 1
    assert expected.resolved == 1

    with monkeypatch.context() as m:
        kwargs: dict[str, Any] = {"with_existing": True}
        if scenario == "refused":
            kwargs["reader_row"] = None
        if scenario == "internal_error":
            kwargs["reader_error"] = ValueError("boom")
        harness = Harness(m, settings, **kwargs)
        if scenario == "refused":
            harness.reader._row = None
        actual = await harness.evaluate()

    assert actual.investment is not None
    assert actual.investment.status == scenario
    assert actual.created == expected.created
    assert actual.rearmed == expected.rearmed
    assert actual.resolved == expected.resolved
    assert actual.skipped_unchanged == expected.skipped_unchanged
    assert actual.skipped_cooldown == expected.skipped_cooldown
    assert actual.candidates_evaluated == expected.candidates_evaluated
    assert actual.comparison_basis == expected.comparison_basis
    assert actual.snapshot_id == expected.snapshot_id == SNAPSHOT_ID
    assert [(d.action, d.alert_id, d.candidate.dedup_key) for d in actual.decisions] == [
        (d.action, d.alert_id, d.candidate.dedup_key) for d in expected.decisions
    ]
    assert harness.existing_type_calls() == base.existing_type_calls()


# ----------------------------------------------------------------------------- S-02 separation


async def test_s02_investment_outcomes_never_enter_the_decisions(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    harness = Harness(monkeypatch, settings)
    result = await harness.evaluate()
    assert result.investment is not None
    assert result.investment.status == "evaluated"
    assert result.investment.evaluation is not None
    assert result.investment.evaluation.candidates  # the real adapter and evaluator found some
    assert all(isinstance(d, CandidateDecision) for d in result.decisions)
    assert all(d.candidate.alert_type != "investment_state" for d in result.decisions)
    assert all(not d.candidate.dedup_key.startswith("investment_state:") for d in result.decisions)
    assert len(result.decisions) == 2  # the two existing-type candidates, both created
    written = [c for c in harness.calls if c[0] == "repo.insert_alert"]
    assert all(not str(c[1]).startswith("investment_state:") for c in written)
    assert not [c for c in harness.calls if "investment_state:" in repr(c)]
    assert result.investment.plan is not None
    assert result.investment.plan.persistence_enabled is False


async def test_s02_the_result_fields_the_worker_reports_are_unchanged() -> None:
    names = [f.name for f in dataclasses.fields(EvaluationResult)]
    assert names == [
        "created",
        "rearmed",
        "resolved",
        "skipped_unchanged",
        "skipped_cooldown",
        "candidates_evaluated",
        "comparison_basis",
        "decisions",
        "snapshot_id",
        "snapshot",
        "investment",
    ]
    old = EvaluationResult(1, 0, 0, 0, 0, 1, "none")
    assert old.investment is None
    assert old.decisions == ()


# ----------------------------------------------------------------------------- realtime paths


def _realtime(
    harness: Harness, settings: Settings
) -> tuple[RealtimeIntelligenceService, FakeEvents]:
    rt = RealtimeIntelligenceService(cast(Any, object()), settings, redis=None)
    rt.alerts = harness.service
    events = FakeEvents()
    rt.events = cast(Any, events)
    rt.analyst_repo = cast(Any, harness.analyst)

    async def no_event_lookup(_alert_id: int) -> int | None:
        return None

    rt._event_for_alert = no_event_lookup  # type: ignore[method-assign,assignment]
    return rt, events


async def test_s02_g34_the_real_event_path_writes_nothing_for_investment_alerts(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    harness = Harness(monkeypatch, settings, candidates=[])  # no existing-type candidate at all
    rt, events = _realtime(harness, settings)
    process = await rt.process_cycle(as_of=AS_OF, knowledge_time=KNOWLEDGE, now=NOW)
    assert process.alerts is not None
    assert process.alerts.investment is not None
    assert process.alerts.investment.evaluation is not None
    assert process.alerts.investment.evaluation.candidates
    assert process.alerts.decisions == ()
    assert events.inserted == []
    assert (process.events_created, process.events_deduplicated) == (0, 0)


async def test_s03_g44_no_ai_analysis_is_queued_for_investment_alerts(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(realtime_module, "send_task", lambda *a, **k: sent.append((a, k)))
    keyed = settings.model_copy(update={"anthropic_api_key": SecretStr("not-a-real-key")})
    harness = Harness(monkeypatch, keyed, candidates=[])
    rt, events = _realtime(harness, keyed)
    process = await rt.process_cycle(as_of=AS_OF, knowledge_time=KNOWLEDGE, now=NOW)
    assert process.alerts is not None
    assert process.alerts.investment is not None
    assert process.alerts.investment.evaluation is not None
    assert process.alerts.investment.evaluation.candidates
    assert process.ai_requested == 0
    assert harness.analyst.queued == []
    assert sent == []
    assert events.inserted == []


async def test_s03_g44_control_an_existing_type_candidate_still_queues_its_analysis(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(realtime_module, "send_task", lambda *a, **k: sent.append((a, k)))
    keyed = settings.model_copy(update={"anthropic_api_key": SecretStr("not-a-real-key")})
    harness = Harness(
        monkeypatch, keyed, candidates=[_candidate("anomaly:BTC", "v9", severity="critical")]
    )
    rt, events = _realtime(harness, keyed)
    process = await rt.process_cycle(as_of=AS_OF, knowledge_time=KNOWLEDGE, now=NOW)
    assert process.ai_requested == 1
    assert len(sent) == 1
    assert len(harness.analyst.queued) == 1
    assert "BTC anomaly" in harness.analyst.queued[0]
    assert "investment" not in harness.analyst.queued[0].lower()
    assert [e["event_type"] for e in events.inserted] == ["anomaly"]


# ----------------------------------------------------------------------------- S-04 / S-05


def _stage(monkeypatch: pytest.MonkeyPatch, stage: str, error: BaseException) -> dict[str, Any]:
    def boom(*_a: object, **_k: object) -> Any:
        raise error

    if stage == "evaluator":
        monkeypatch.setattr(block, "evaluate_investment_alerts", boom)
    elif stage == "planner":
        monkeypatch.setattr(block, "plan_investment_lifecycle", boom)
    return {"reader_error": error} if stage == "reader" else {}


_STAGES = ("reader", "evaluator", "planner")


@pytest.mark.parametrize("stage", _STAGES)
async def test_s04_g36_an_ordinary_failure_is_contained_and_the_11_types_are_unchanged(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, stage: str
) -> None:
    with monkeypatch.context() as m:
        base = await _baseline(m, settings)
        expected = await base.evaluate()
    with monkeypatch.context() as m:
        extra = _stage(m, stage, ValueError("boom"))
        harness = Harness(m, settings, with_existing=True, **extra)
        actual = await harness.evaluate()
    assert actual.investment is not None
    assert actual.investment.status == "internal_error"
    assert actual.investment.error_class == "builtins.ValueError"
    assert _comparable(actual).keys() == _comparable(expected).keys()
    assert (actual.created, actual.resolved, actual.skipped_unchanged) == (1, 1, 1)
    assert harness.existing_type_calls() == base.existing_type_calls()
    cycle = harness.log.investment()
    assert len(cycle) == 1
    assert cycle[0][0] == "error"
    assert cycle[0][2]["exc_info"] is True


_SIGNALS: list[BaseException] = [
    SoftTimeLimitExceeded(),
    TimeLimitExceeded(),
    asyncio.CancelledError(),
    KeyboardInterrupt(),
    SystemExit(),
]


@pytest.mark.parametrize("stage", _STAGES)
@pytest.mark.parametrize("signal", _SIGNALS, ids=[type(s).__name__ for s in _SIGNALS])
async def test_s05_g53_a_time_limit_or_cancellation_signal_escapes_evaluate(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, stage: str, signal: BaseException
) -> None:
    extra = _stage(monkeypatch, stage, signal)
    harness = Harness(monkeypatch, settings, with_existing=True, **extra)
    with pytest.raises(type(signal)) as caught:
        await harness.evaluate()
    assert caught.value is signal
    assert harness.log.investment() == []
    kinds = [c[0] for c in harness.calls]
    # the 11 types' writes were already made before the block ran, and are not undone
    assert "repo.insert_alert" in kinds
    assert "repo.resolve" in kinds
    last_write = max(i for i, k in enumerate(kinds) if k.startswith(("repo.", "analyst.")))
    assert last_write < kinds.index("reader.get_snapshot")


# ----------------------------------------------------------------------------- S-06 / S-07 / S-10


async def test_s06_the_block_runs_once_after_the_11_types_with_the_inserted_snapshot_id(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    harness = Harness(monkeypatch, settings, with_existing=True)
    result = await harness.evaluate()
    kinds = [c[0] for c in harness.calls]
    assert kinds.count("reader.get_snapshot") == 1
    assert harness.calls[-1] == ("reader.get_snapshot", SNAPSHOT_ID)
    assert kinds.index("analyst.insert_snapshot") < kinds.index("repo.insert_alert")
    assert kinds.index("repo.resolve") < kinds.index("reader.get_snapshot")
    assert max(i for i, k in enumerate(kinds) if k.startswith("repo.")) < kinds.index(
        "reader.get_snapshot"
    )
    assert result.snapshot_id == SNAPSHOT_ID
    cycle = harness.log.investment()
    assert len(cycle) == 1
    assert cycle[0][2]["snapshot_id"] == SNAPSHOT_ID


async def test_s06_a_failed_snapshot_insert_means_the_block_never_runs(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    harness = Harness(monkeypatch, settings, insert_error=RuntimeError("insert failed"))
    with pytest.raises(RuntimeError, match="insert failed"):
        await harness.evaluate()
    assert [c for c in harness.calls if c[0].startswith("reader.")] == []
    assert harness.log.investment() == []


async def test_s07_the_block_adds_no_repository_call_and_uses_only_get_snapshot(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    harness = Harness(monkeypatch, settings, with_existing=True)
    await harness.evaluate()
    after_reader = harness.calls[[c[0] for c in harness.calls].index("reader.get_snapshot") + 1 :]
    assert after_reader == []
    assert [c[0] for c in harness.calls if c[0].startswith("reader.")] == ["reader.get_snapshot"]


async def test_s10_g54_the_block_reads_no_stored_alert(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    harness = Harness(monkeypatch, settings, with_existing=True)
    await harness.evaluate()
    looked_up = [c[1] for c in harness.calls if c[0] == "repo.latest_active_for_key"]
    assert looked_up == [c.dedup_key for c in harness.candidates]
    assert not [k for k in looked_up if str(k).startswith("investment_state:")]


# ----------------------------------------------------------------------------- S-08 / S-09


def test_s08_the_constructor_is_backward_compatible_and_wires_the_real_reader_by_default() -> None:
    service = AlertService(cast(Any, object()), cast(Any, object()))
    assert isinstance(service._snapshot_reader, DecisionAssessmentRepository)
    params = inspect.signature(AlertService.__init__).parameters
    assert list(params) == ["self", "engine", "settings", "snapshot_reader"]
    assert params["snapshot_reader"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["snapshot_reader"].default is None


def test_s08_the_realtime_service_still_builds_its_alert_service_with_the_real_reader(
    settings: Settings,
) -> None:
    rt = RealtimeIntelligenceService(cast(Any, object()), settings)
    assert isinstance(rt.alerts._snapshot_reader, DecisionAssessmentRepository)


def test_s09_g39_the_alert_type_registration_is_unchanged() -> None:
    assert len(ALERT_TYPE_TOOL_IDS) == 11
    assert "investment_state" not in ALERT_TYPE_TOOL_IDS


async def test_s01_the_persistence_gate_is_off_in_every_cycle(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    harness = Harness(monkeypatch, settings)
    result = await harness.evaluate()
    assert isinstance(result.investment, InvestmentCycleResult)
    assert result.investment.plan is not None
    assert result.investment.plan.persistence_enabled is False
    assert result.investment.plan.indeterminate == ()
    fields = harness.log.investment()[0][2]
    assert fields["persistence_enabled"] is False
