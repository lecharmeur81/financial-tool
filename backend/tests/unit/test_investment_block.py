"""Phase 51 Stage 6 — the investment-alert cycle block (no database, no network, no clock).

The reader is an in-memory fake, the logger records its calls and the clock is a fake; decisions
come from the existing hand-built fixtures or from the real Phase 44 to 49 builders on an
in-memory row. These are the block fixtures of ``METHODOLOGY_INVESTMENT_ALERTS.md`` §11 and §14
(M-3, G36, G53, G54) and the Stage 6 plan: result invariants, refusals, the log-level table and
field whitelist, ordinary-error containment, signal propagation, source scans and the import
boundary. Nothing here validates persistence or real database snapshots.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import inspect
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded

import cfi.alerts.investment_adapter as adapter
import cfi.alerts.investment_alerts as ia
import cfi.alerts.investment_block as block
from cfi.alerts.investment_adapter import AdapterOutcome
from cfi.alerts.investment_block import (
    CYCLE_STATUSES,
    DEFECT_LIKE_REFUSALS,
    EVENT_NAME,
    LOG_FIELDS,
    WARNING_REFUSALS,
    InvestmentCycleResult,
    run_investment_cycle,
)
from cfi.decision.context import InvalidSnapshotError
from cfi.decision.identity import producer_payload_hash
from cfi.intelligence import (
    ConfirmationInputError,
    InvestmentInputError,
    OpportunityInputError,
    RankingInputError,
    RiskInputError,
)
from tests import investment_alert_builders as fx
from tests.decision_builders import make_payload

SNAPSHOT_ID = 4
UUID = "00000000-0000-0000-0000-000000000004"
CREATED = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
AS_OF = CREATED - timedelta(minutes=2)
KNOWLEDGE = CREATED - timedelta(minutes=1)
REAL_NOW = CREATED + timedelta(minutes=5)
SCOPES = fx.SCOPES
SENTINEL = "SENTINEL-MESSAGE-MUST-NOT-BE-LOGGED"


# ----------------------------------------------------------------------------- fakes


class FakeLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.calls.append(("info", event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self.calls.append(("warning", event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self.calls.append(("error", event, fields))


class Clock:
    """Each call advances by ``step`` seconds; the block calls it exactly twice."""

    def __init__(self, step: float = 0.25) -> None:
        self.now = 100.0
        self.step = step
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        value = self.now
        self.now += self.step
        return value


@dataclasses.dataclass(frozen=True)
class Row:
    row_id: Any = SNAPSHOT_ID
    uuid: Any = UUID
    payload_hash: Any = None
    created_at: Any = CREATED
    as_of: Any = AS_OF
    knowledge_time: Any = KNOWLEDGE
    payload: Any = dataclasses.field(default_factory=dict)


def _payload() -> dict[str, Any]:
    payload = make_payload(["S2", "S1", "N", "S1", "S2"])
    payload["snapshot_version"] = "analyst_snapshot.v1"
    return payload


def _row(payload_hash: str | None = None) -> Row:
    payload = _payload()
    return Row(payload=payload, payload_hash=payload_hash or producer_payload_hash(payload))


class FakeReader:
    def __init__(self, row: Row | None = None, error: BaseException | None = None) -> None:
        self.row = row
        self.error = error
        self.calls: list[int] = []

    async def get_snapshot(self, snapshot_id: int) -> Row | None:
        self.calls.append(snapshot_id)
        if self.error is not None:
            raise self.error
        return self.row


def _outcome(
    states: str | dict[str, str] = "candidate_unresolved",
    *,
    performed: bool = True,
    mutate: Callable[[dict[str, Any]], None] | None = None,
    identity: ia.StoredSnapshotIdentity | None = None,
) -> AdapterOutcome:
    return AdapterOutcome(
        decision=fx.decision(states, performed=performed, mutate=mutate),
        identity=identity or fx.stored(),
        refusal_reason=None,
    )


def _patch_outcome(monkeypatch: pytest.MonkeyPatch, outcome: AdapterOutcome) -> list[int]:
    calls: list[int] = []

    async def fake(reader: object, snapshot_id: int) -> AdapterOutcome:
        calls.append(snapshot_id)
        return outcome

    monkeypatch.setattr(block, "read_and_build", fake)
    return calls


async def _run(
    reader: Any,
    log: FakeLogger,
    *,
    now: datetime = REAL_NOW,
    snapshot_id: int = SNAPSHOT_ID,
    clock: Callable[[], float] | None = None,
) -> InvestmentCycleResult:
    return await run_investment_cycle(
        reader, snapshot_id, now=now, logger=log, monotonic=clock or Clock()
    )


def _only(log: FakeLogger) -> tuple[str, dict[str, Any]]:
    assert len(log.calls) == 1, log.calls
    level, event, fields = log.calls[0]
    assert event == EVENT_NAME
    status = fields["status"]
    assert set(fields) - {"exc_info"} == set(LOG_FIELDS[status]), fields
    assert not any("indeterminate" in key for key in fields)
    assert "payload" not in fields
    return level, fields


# ----------------------------------------------------------------------------- the result type


def test_the_vocabulary_partitions_every_refusal_reason() -> None:
    assert DEFECT_LIKE_REFUSALS.isdisjoint(WARNING_REFUSALS)
    assert set(ia.REFUSAL_REASONS) == DEFECT_LIKE_REFUSALS | WARNING_REFUSALS
    assert {"decision_inputs_refused"} == WARNING_REFUSALS
    assert CYCLE_STATUSES == ("evaluated", "refused", "internal_error")
    assert set(LOG_FIELDS) == set(CYCLE_STATUSES)


def test_the_closed_class_b_vocabulary_is_unchanged_by_stage_6() -> None:
    assert set(ia.CLASS_B_REASONS) == {
        "request_gated",
        "candidate_withheld",
        "incomplete_decision",
        "evidence_freshness_unverified",
    }
    assert ia.CLASS_C_REASONS == ("not_alertable_state",)


def _evaluation() -> ia.InvestmentEvaluation:
    return ia.evaluate_investment_alerts(fx.decision(), fx.stored(), now=fx.NOW)


def _refused() -> ia.InvestmentEvaluation:
    return ia.InvestmentEvaluation(refused=True, refusal_reason="snapshot_not_found", outcomes=())


def _plan(evaluation: ia.InvestmentEvaluation, **kwargs: Any) -> ia.InvestmentLifecyclePlan:
    return ia.plan_investment_lifecycle(
        evaluation, kwargs.pop("existing", None), now=fx.NOW, **kwargs
    )


def test_a_valid_result_of_each_status_is_accepted() -> None:
    ev = _evaluation()
    InvestmentCycleResult("evaluated", ev, _plan(ev), None, None, 3)
    rf = _refused()
    InvestmentCycleResult("refused", rf, _plan(rf), "snapshot_not_found", None, 0)
    InvestmentCycleResult("internal_error", None, None, None, "builtins.ValueError", 1)


@pytest.mark.parametrize(
    "build",
    [
        lambda: InvestmentCycleResult("unknown", None, None, None, "x", 0),
        lambda: InvestmentCycleResult("internal_error", None, None, None, None, 0),
        lambda: InvestmentCycleResult("internal_error", None, None, None, "  ", 0),
        lambda: InvestmentCycleResult("internal_error", None, None, "snapshot_not_found", "x", 0),
        lambda: InvestmentCycleResult("internal_error", _evaluation(), None, None, "x", 0),
        lambda: InvestmentCycleResult("evaluated", None, None, None, None, 0),
        lambda: InvestmentCycleResult("evaluated", _evaluation(), None, None, None, 0),
        lambda: InvestmentCycleResult(
            "evaluated", _evaluation(), _plan(_evaluation()), None, "x", 0
        ),
        lambda: InvestmentCycleResult(
            "evaluated", _evaluation(), _plan(_evaluation()), "snapshot_not_found", None, 0
        ),
        lambda: InvestmentCycleResult(
            "refused", _evaluation(), _plan(_evaluation()), None, None, 0
        ),
        lambda: InvestmentCycleResult("refused", _refused(), _plan(_refused()), None, None, 0),
        lambda: InvestmentCycleResult(
            "refused", _refused(), _plan(_refused()), "request_gated", None, 0
        ),
        lambda: InvestmentCycleResult(
            "refused", _refused(), _plan(_refused()), "snapshot_row_invalid", None, 0
        ),
        lambda: InvestmentCycleResult(
            "evaluated", _evaluation(), _plan(_evaluation()), None, None, -1
        ),
        lambda: InvestmentCycleResult(
            "evaluated", _evaluation(), _plan(_evaluation()), None, None, True
        ),
        lambda: InvestmentCycleResult(
            "evaluated",
            _evaluation(),
            _plan(_evaluation()),
            None,
            None,
            1.5,  # type: ignore[arg-type]
        ),
    ],
)
def test_an_inconsistent_result_is_rejected(build: Callable[[], object]) -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        build()


def test_a_result_whose_plan_enables_persistence_is_rejected() -> None:
    ev = _evaluation()
    keys = {ia.dedup_key_for(scope): None for scope in SCOPES}
    enabled = _plan(ev, existing=keys, persistence=True)
    assert enabled.persistence_enabled is True
    with pytest.raises(ia.InvestmentAlertValidationError):
        InvestmentCycleResult("evaluated", ev, enabled, None, None, 0)


def test_a_result_is_immutable() -> None:
    ev = _evaluation()
    result = InvestmentCycleResult("evaluated", ev, _plan(ev), None, None, 0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.status = "refused"  # type: ignore[misc]


# ----------------------------------------------------------------------------- B-01 success


async def test_b01_every_class_a_asset_is_planned_gate_disabled_and_b_and_c_have_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = dict(
        zip(
            SCOPES,
            [
                "candidate_unresolved",  # class A
                "no_opportunity",  # class C
                "withheld_integrity_gate",  # class B (candidate_withheld)
                "candidate_no_findings_detected",  # class A
            ],
            strict=True,
        )
    )
    calls = _patch_outcome(monkeypatch, _outcome(states))
    log = FakeLogger()
    clock = Clock(0.25)
    result = await _run(object(), log, snapshot_id=7, clock=clock, now=fx.NOW)

    assert calls == [7]
    assert result.status == "evaluated"
    assert result.error_class is None
    assert result.refusal_reason is None
    assert result.duration_ms == 250
    assert clock.calls == 2
    assert result.plan is not None
    assert result.evaluation is not None
    assert result.plan.persistence_enabled is False
    assert result.plan.indeterminate == ()
    by_asset = {a.asset: a for a in result.plan.assets}
    for asset, expected_class in zip(SCOPES, ["A", "C", "B", "A"], strict=True):
        plan = by_asset[asset]
        assert plan.outcome_class == expected_class
        if expected_class == "A":
            assert plan.disposition == ia.GATE_DISABLED_DISPOSITION
            assert plan.candidate is not None
        else:
            assert plan.disposition is None
            assert plan.candidate is None
    assert result.plan.count(ia.GATE_DISABLED_DISPOSITION) == 2
    level, fields = _only(log)
    assert level == "info"
    assert fields == {
        "snapshot_id": 7,
        "status": "evaluated",
        "class_a": 2,
        "class_b": 1,
        "class_c": 1,
        "incomplete_decision_assets": [],
        "integrity_gates": [],
        "persistence_enabled": False,
        "duration_ms": 250,
    }


async def test_b01_the_real_adapter_path_reads_once_and_evaluates() -> None:
    reader = FakeReader(_row())
    log = FakeLogger()
    result = await _run(reader, log)
    assert reader.calls == [SNAPSHOT_ID]
    assert result.status == "evaluated"
    assert result.evaluation is not None
    assert not result.evaluation.refused
    assert result.plan is not None
    assert not result.plan.persistence_enabled
    level, fields = _only(log)
    assert level == "info"
    assert fields["class_a"] + fields["class_b"] + fields["class_c"] == 4


# ----------------------------------------------------------------------------- B-02 / B-03


def _assert_refused(result: InvestmentCycleResult, reason: str) -> None:
    assert result.status == "refused"
    assert result.refusal_reason == reason
    assert result.error_class is None
    assert result.evaluation is not None
    assert result.evaluation.refused
    assert result.evaluation.refusal_reason == reason
    assert result.evaluation.outcomes == ()
    assert result.evaluation.candidates == ()
    assert result.plan is not None
    assert result.plan.refused
    assert result.plan.assets == ()
    assert result.plan.indeterminate == ()
    assert result.plan.persistence_enabled is False


async def test_b02_a_missing_row_is_a_refusal_with_no_candidates() -> None:
    reader = FakeReader(None)
    log = FakeLogger()
    result = await _run(reader, log)
    _assert_refused(result, "snapshot_not_found")
    assert reader.calls == [SNAPSHOT_ID]
    level, fields = _only(log)
    assert level == "error"
    assert fields["refusal_reason"] == "snapshot_not_found"
    assert fields["refusal_detail"] is None


@pytest.mark.parametrize(
    "row",
    [
        dataclasses.replace(_row(), row_id=SNAPSHOT_ID + 1),
        dataclasses.replace(_row(), uuid=" padded "),
        dataclasses.replace(_row(), payload_hash=""),
        dataclasses.replace(_row(), as_of="2026-10-05"),
        dataclasses.replace(_row(), payload=["not", "a", "dict"]),
        dataclasses.replace(_row(), row_id=True),
    ],
    ids=["id", "uuid", "hash", "as_of", "payload", "bool-id"],
)
async def test_b02_an_unusable_row_is_a_refusal_with_no_candidates(row: Row) -> None:
    log = FakeLogger()
    result = await _run(FakeReader(row), log)
    _assert_refused(result, "snapshot_row_invalid")
    level, fields = _only(log)
    assert level == "error"
    assert fields["refusal_detail"] is None


_BUILDER_REFUSALS: list[tuple[str, type[Exception]]] = [
    ("build_unified_snapshot", InvalidSnapshotError),
    ("build_confirmation", ConfirmationInputError),
    ("build_opportunities", OpportunityInputError),
    ("build_ranking", RankingInputError),
    ("build_risk_view", RiskInputError),
    ("build_investment_decision", InvestmentInputError),
]


@pytest.mark.parametrize(("builder", "error"), _BUILDER_REFUSALS)
async def test_b02_each_known_builder_refusal_is_a_warning_with_the_class_name_only(
    monkeypatch: pytest.MonkeyPatch, builder: str, error: type[Exception]
) -> None:
    def refuse(*_a: object, **_k: object) -> Any:
        raise error(SENTINEL)

    monkeypatch.setattr(adapter, builder, refuse)
    log = FakeLogger()
    result = await _run(FakeReader(_row()), log)
    _assert_refused(result, "decision_inputs_refused")
    level, fields = _only(log)
    assert level == "warning"
    assert fields["refusal_reason"] == "decision_inputs_refused"
    assert fields["refusal_detail"] == error.__name__
    assert SENTINEL not in repr(log.calls)


async def test_b02_a_refusal_reason_set_only_by_the_adapter_or_evaluator_is_used() -> None:
    log = FakeLogger()
    result = await _run(FakeReader(None), log)
    assert result.refusal_reason in ia.ADAPTER_REFUSAL_REASONS


@pytest.mark.parametrize(
    ("reason", "outcome"),
    [
        ("decision_contract_invalid", _outcome(mutate=lambda d: d.update(contract_version="x"))),
        ("snapshot_identity_mismatch", _outcome(identity=fx.stored(row_id=fx.ROW_ID + 1))),
        ("snapshot_time_in_future", _outcome(identity=fx.stored(as_of=fx.NOW + timedelta(days=1)))),
        (
            "snapshot_time_invalid",
            _outcome(identity=fx.stored(as_of=datetime(2026, 10, 11, 11, 0))),  # noqa: DTZ001
        ),
    ],
)
async def test_b03_each_evaluator_refusal_is_an_error_level_refusal_with_no_candidates(
    monkeypatch: pytest.MonkeyPatch, reason: str, outcome: AdapterOutcome
) -> None:
    _patch_outcome(monkeypatch, outcome)
    log = FakeLogger()
    result = await _run(object(), log, now=fx.NOW)
    _assert_refused(result, reason)
    level, fields = _only(log)
    assert level == "error"
    assert fields["refusal_reason"] == reason
    assert fields["refusal_detail"] is None
    assert reason in DEFECT_LIKE_REFUSALS


# ----------------------------------------------------------------------------- B-04 to B-06


async def test_b04_a_hash_mismatch_withholds_every_asset_and_logs_an_error() -> None:
    log = FakeLogger()
    result = await _run(FakeReader(_row(payload_hash="0" * 64)), log)
    assert result.status == "evaluated"
    assert result.evaluation is not None
    assert result.plan is not None
    assert [o.outcome_class for o in result.evaluation.outcomes] == ["B"] * 4
    assert {o.reason for o in result.evaluation.outcomes} == {"request_gated"}
    assert result.evaluation.candidates == ()
    assert [a.disposition for a in result.plan.assets] == [None] * 4
    assert result.plan.indeterminate == ()
    level, fields = _only(log)
    assert level == "error"
    assert fields["integrity_gates"] == ["producer_hash"]
    assert (fields["class_a"], fields["class_b"], fields["class_c"]) == (0, 4, 0)


def _gates(look_ahead: bool, producer_hash: bool) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        d["gates"] = {
            "look_ahead": {"triggered": look_ahead},
            "producer_hash": {"check": "verified", "triggered": producer_hash},
        }

    return mutate


@pytest.mark.parametrize(
    ("look_ahead", "producer_hash", "level", "names"),
    [
        (False, False, "info", []),
        (True, False, "warning", ["look_ahead"]),
        (False, True, "error", ["producer_hash"]),
        (True, True, "error", ["look_ahead", "producer_hash"]),
    ],
)
async def test_b05_the_triggered_gates_set_the_level(
    monkeypatch: pytest.MonkeyPatch,
    look_ahead: bool,
    producer_hash: bool,
    level: str,
    names: list[str],
) -> None:
    _patch_outcome(monkeypatch, _outcome(mutate=_gates(look_ahead, producer_hash)))
    log = FakeLogger()
    result = await _run(object(), log, now=fx.NOW)
    assert result.status == "evaluated"
    got_level, fields = _only(log)
    assert got_level == level
    assert fields["integrity_gates"] == names


@pytest.mark.parametrize(
    "gates",
    [
        None,
        "x",
        [],
        {},
        {"look_ahead": "x"},
        {"look_ahead": {"triggered": "yes"}},
        {"producer_hash": 1},
    ],
)
async def test_b05_a_malformed_gates_block_is_ignored_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, gates: object
) -> None:
    _patch_outcome(monkeypatch, _outcome(mutate=lambda d: d.update(gates=gates)))
    log = FakeLogger()
    result = await _run(object(), log, now=fx.NOW)
    assert result.status == "evaluated"
    level, fields = _only(log)
    assert level == "info"
    assert fields["integrity_gates"] == []


async def test_b06_an_incomplete_decision_is_a_warning_naming_the_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def break_btc(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["risk_assessment"] = None

    _patch_outcome(monkeypatch, _outcome("candidate_unresolved", mutate=break_btc))
    log = FakeLogger()
    result = await _run(object(), log, now=fx.NOW)
    assert result.status == "evaluated"
    assert result.evaluation is not None
    btc = next(o for o in result.evaluation.outcomes if o.asset == "BTC")
    assert (btc.outcome_class, btc.reason, btc.candidate) == ("B", "incomplete_decision", None)
    level, fields = _only(log)
    assert level == "warning"
    assert fields["incomplete_decision_assets"] == ["BTC"]
    assert (fields["class_a"], fields["class_b"]) == (3, 1)


# ----------------------------------------------------------------------------- B-08 logging


async def test_b08_no_identity_or_payload_content_is_ever_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_outcome(monkeypatch, _outcome())
    log = FakeLogger()
    await _run(object(), log, now=fx.NOW)
    text = repr(log.calls)
    for secret in (fx.UUID, fx.PAYLOAD_HASH, str(fx.ROW_ID)):
        assert secret not in text
    assert "evidence_field_ids" not in text
    assert "DI-" not in text


@pytest.mark.parametrize("bad_id", ["4", 4.0, None, True])
async def test_b08_a_non_integer_snapshot_id_is_an_internal_error_logged_without_the_value(
    bad_id: object,
) -> None:
    reader = FakeReader(_row())
    log = FakeLogger()
    result = await _run(reader, log, snapshot_id=bad_id)  # type: ignore[arg-type]
    assert result.status == "internal_error"
    assert reader.calls == []
    level, fields = _only(log)
    assert level == "error"
    assert fields["snapshot_id"] is None
    assert fields["error_class"].endswith("InvestmentAlertValidationError")


# ----------------------------------------------------------------------------- B-09 containment

_ORDINARY: list[Exception] = [
    ValueError(SENTINEL),
    KeyError(SENTINEL),
    TypeError(SENTINEL),
    AssertionError(SENTINEL),
    ia.InvestmentAlertValidationError(SENTINEL),
    ConnectionError(SENTINEL),
]
_STAGES = ("reader", "builder", "evaluator", "planner")


def _inject(monkeypatch: pytest.MonkeyPatch, stage: str, error: BaseException) -> FakeReader:
    def boom(*_a: object, **_k: object) -> Any:
        raise error

    reader = FakeReader(_row(), error=error if stage == "reader" else None)
    if stage == "builder":
        monkeypatch.setattr(adapter, "build_ranking", boom)
    elif stage == "evaluator":
        monkeypatch.setattr(block, "evaluate_investment_alerts", boom)
    elif stage == "planner":
        monkeypatch.setattr(block, "plan_investment_lifecycle", boom)
    return reader


@pytest.mark.parametrize("stage", _STAGES)
@pytest.mark.parametrize("error", _ORDINARY, ids=[type(e).__name__ for e in _ORDINARY])
async def test_b09_an_ordinary_exception_is_contained_and_logged_as_an_error(
    monkeypatch: pytest.MonkeyPatch, stage: str, error: Exception
) -> None:
    reader = _inject(monkeypatch, stage, error)
    log = FakeLogger()
    result = await _run(reader, log)
    assert result.status == "internal_error"
    assert result.evaluation is None
    assert result.plan is None
    assert result.refusal_reason is None
    assert result.error_class == f"{type(error).__module__}.{type(error).__qualname__}"
    level, fields = _only(log)
    assert level == "error"
    assert fields["exc_info"] is True
    assert fields["error_class"] == result.error_class
    assert SENTINEL not in repr(fields)


async def test_b09_an_internal_error_is_distinct_from_a_refusal() -> None:
    refused = await _run(FakeReader(None), FakeLogger())
    failed = await _run(FakeReader(error=ValueError("x")), FakeLogger())
    assert (refused.status, failed.status) == ("refused", "internal_error")
    assert refused.error_class is None
    assert failed.refusal_reason is None


# ----------------------------------------------------------------------------- B-10 signals

_SIGNALS: list[BaseException] = [
    SoftTimeLimitExceeded(),
    TimeLimitExceeded(),
    asyncio.CancelledError(),
    KeyboardInterrupt(),
    SystemExit(),
]


@pytest.mark.parametrize("stage", _STAGES)
@pytest.mark.parametrize("signal", _SIGNALS, ids=[type(s).__name__ for s in _SIGNALS])
async def test_b10_a_time_limit_or_cancellation_signal_propagates_unrecorded(
    monkeypatch: pytest.MonkeyPatch, stage: str, signal: BaseException
) -> None:
    reader = _inject(monkeypatch, stage, signal)
    log = FakeLogger()
    with pytest.raises(type(signal)) as caught:
        await _run(reader, log)
    assert caught.value is signal
    assert log.calls == []


# ----------------------------------------------------------------------------- B-13 / B-15


@pytest.mark.parametrize(
    ("state", "expected_class", "has_candidate"),
    [
        ("candidate_invalidation_triggered", "A", True),
        ("contradicted_evidence", "A", True),
        ("candidate_risk_findings_detected", "A", True),
        ("candidate_unresolved", "A", True),
        ("candidate_no_findings_detected", "A", True),
        ("withheld_integrity_gate", "B", False),
        ("insufficient_evidence", "C", False),
        ("no_opportunity", "C", False),
    ],
)
async def test_b15_only_an_eligible_alertable_state_yields_a_candidate_and_a_disposition(
    monkeypatch: pytest.MonkeyPatch, state: str, expected_class: str, has_candidate: bool
) -> None:
    calls = _patch_outcome(monkeypatch, _outcome(state))
    log = FakeLogger()
    result = await _run(object(), log, now=fx.NOW)
    assert calls == [SNAPSHOT_ID]
    assert result.evaluation is not None
    assert result.plan is not None
    assert {o.outcome_class for o in result.evaluation.outcomes} == {expected_class}
    assert bool(result.evaluation.candidates) is has_candidate
    expected = ia.GATE_DISABLED_DISPOSITION if has_candidate else None
    assert {a.disposition for a in result.plan.assets} == {expected}
    assert result.plan.indeterminate == ()
    assert result.plan.persistence_enabled is False


async def test_b15_a_gated_request_yields_no_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_outcome(monkeypatch, _outcome(performed=False))
    result = await _run(object(), FakeLogger(), now=fx.NOW)
    assert result.evaluation is not None
    assert result.evaluation.candidates == ()
    assert {o.reason for o in result.evaluation.outcomes} == {"request_gated"}


async def test_b13_work_is_bounded_one_read_and_two_clock_calls() -> None:
    reader = FakeReader(_row())
    clock = Clock()
    await _run(reader, FakeLogger(), clock=clock)
    assert reader.calls == [SNAPSHOT_ID]
    assert clock.calls == 2


@pytest.mark.parametrize("step", [0.0, 0.0004, 1.5])
async def test_b13_the_duration_comes_from_the_injected_clock(step: float) -> None:
    result = await _run(FakeReader(_row()), FakeLogger(), clock=Clock(step))
    assert result.duration_ms == int(step * 1000)


async def test_b13_a_backwards_clock_never_gives_a_negative_duration() -> None:
    ticks = iter([10.0, 5.0])
    result = await _run(FakeReader(_row()), FakeLogger(), clock=lambda: next(ticks))
    assert result.duration_ms == 0


# ----------------------------------------------------------------------------- source scans


def _source() -> str:
    return Path(inspect.getsourcefile(block) or "").read_text(encoding="utf-8")


def _function() -> ast.AsyncFunctionDef:
    tree = ast.parse(_source())
    return next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_investment_cycle"
    )


def test_b11_the_handlers_are_the_signal_reraise_then_exception_only() -> None:
    tries = [n for n in ast.walk(_function()) if isinstance(n, ast.Try)]
    assert len(tries) == 1
    first, second = tries[0].handlers
    assert isinstance(first.type, ast.Tuple)
    assert {ast.unparse(e) for e in first.type.elts} == {
        "SoftTimeLimitExceeded",
        "TimeLimitExceeded",
        "asyncio.CancelledError",
        "KeyboardInterrupt",
    }
    assert len(first.body) == 1
    reraise = first.body[0]
    assert isinstance(reraise, ast.Raise)
    assert reraise.exc is None
    assert reraise.cause is None
    assert second.type is not None
    assert ast.unparse(second.type) == "Exception"
    assert tries[0].orelse == []
    assert tries[0].finalbody == []


def test_b11_there_is_no_base_exception_handler_and_no_bare_except() -> None:
    handlers = [n for n in ast.walk(ast.parse(_source())) if isinstance(n, ast.ExceptHandler)]
    assert len(handlers) == 2
    for handler in handlers:
        assert handler.type is not None
        assert "BaseException" not in ast.unparse(handler.type)


def test_b11_the_celery_classes_are_imported_by_name_and_never_matched_by_string() -> None:
    tree = ast.parse(_source())
    celery = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module == "celery.exceptions"
    ]
    assert len(celery) == 1
    assert {a.name for a in celery[0].names} == {"SoftTimeLimitExceeded", "TimeLimitExceeded"}
    assert all(a.asname is None for a in celery[0].names)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            assert not attrs & {"__name__", "__module__", "__qualname__"}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"startswith", "endswith"}


def test_b12_the_block_reads_no_environment_or_settings_and_never_overrides_the_gate() -> None:
    source = _source()
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("#", '"""'))
    )
    for needle in ("os.environ", "getenv", "environ", "get_settings", "Settings", "persistence="):
        assert needle not in code, needle
    plan_calls = [
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "plan_investment_lifecycle"
    ]
    assert len(plan_calls) == 1
    call = plan_calls[0]
    assert [ast.unparse(a) for a in call.args] == ["evaluation", "None"]
    assert [k.arg for k in call.keywords] == ["now"]


def test_b12_the_gate_default_is_still_disabled() -> None:
    assert ia.INVESTMENT_ALERT_PERSISTENCE_ENABLED is False
    assert ia.persistence_enabled() is False


def test_b13_the_block_has_no_sleep_retry_polling_or_writer_calls() -> None:
    tree = ast.parse(_source())
    calls = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert not calls & {"sleep", "wait_for", "gather", "create_task", "retry", "open", "connect"}
    assert not calls & {"insert_alert", "supersede", "resolve", "acknowledge", "insert_snapshot"}
    assert not calls & {"decide", "latest_active_for_key", "latest_snapshot"}
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.While | ast.AsyncFor)]
    # The one loop visits the two fixed gate names; nothing iterates over data or retries.
    assert [ast.unparse(n.iter) for n in ast.walk(tree) if isinstance(n, ast.For)] == ["_GATE_KEYS"]
    assert len([n for n in ast.walk(_function()) if isinstance(n, ast.Await)]) == 1


ALLOWED_IMPORTS = {
    "__future__",
    "asyncio",
    "time",
    "collections.abc",
    "dataclasses",
    "datetime",
    "typing",
    "celery.exceptions",
    "cfi.alerts.investment_adapter",
    "cfi.alerts.investment_alerts",
}
FORBIDDEN_ROOTS = (
    "sqlalchemy",
    "psycopg",
    "psycopg_pool",
    "asyncpg",
    "redis",
    "httpx",
    "requests",
    "aiohttp",
    "urllib3",
    "fastapi",
    "starlette",
    "anthropic",
    "boto3",
    "cfi.alerts.service",
    "cfi.alerts.repository",
    "cfi.analyst.repository",
    "cfi.analyst.service",
    "cfi.analyst.snapshot",
    "cfi.analyst.tools",
    "cfi.analyst.client",
    "cfi.db",
    "cfi.decision_store",
    "cfi.realtime",
    "cfi.worker",
    "cfi.api",
)


def test_b14_the_block_imports_only_the_approved_modules() -> None:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(_source())):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imported.add(node.module or "")
    assert imported == ALLOWED_IMPORTS
    assert not any(m == r or m.startswith(r + ".") for m in imported for r in FORBIDDEN_ROOTS)


def test_b14_importing_the_block_loads_no_io_library_or_repository() -> None:
    code = (
        "import sys\n"
        "import cfi\n"
        "before = set(sys.modules)\n"
        "import cfi.alerts.investment_block\n"
        "new = sorted(set(sys.modules) - before)\n"
        f"roots = {FORBIDDEN_ROOTS!r}\n"
        "bad = [m for m in new if any(m == r or m.startswith(r + '.') for r in roots)]\n"
        "print(repr(bad))\n"
    )
    env_path = os.pathsep.join(p for p in sys.path if p)
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = env_path
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    out = subprocess.run(  # noqa: S603 — fixed interpreter, fixed code, no user input
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=child_env,
        timeout=60,
    )
    assert out.stdout.strip() == "[]", out.stdout
