"""Phase 51 Stage 5 — the investment-alert adapter (no database, no network, no clock).

The reader is an in-memory fake; payloads come from the existing hand-built decision fixtures. The
fixtures added here are the adapter fixtures of ``METHODOLOGY_INVESTMENT_ALERTS.md`` §14 (G56 to
G67): success, Phase 49 route parity (G38), the three refusal reasons, the six builder refusals,
propagation of everything else, the Phase 46 hash-mismatch path, the import boundary and
lifecycle-planner compatibility. Nothing here validates persistence or real database snapshots.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import dataclasses
import inspect
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import cfi.alerts.investment_adapter as adapter
import cfi.alerts.investment_alerts as ia
from cfi.alerts.investment_adapter import (
    AdapterOutcome,
    SnapshotReader,
    StoredSnapshotRow,
    build_decision_from_row,
    read_and_build,
)
from cfi.alerts.lifecycle import ExistingAlert
from cfi.alerts.universe import BANNED_PATTERNS
from cfi.analyst.repository import SnapshotRow
from cfi.api.routes import intelligence_investment as route
from cfi.decision.context import InvalidSnapshotError
from cfi.decision.identity import producer_payload_hash
from cfi.decision.universe import SCOPE_DOMAINS
from cfi.decision_store.record import StoredSnapshot
from cfi.decision_store.repository import DecisionAssessmentRepository
from cfi.intelligence import (
    ConfirmationInputError,
    InvestmentInputError,
    OpportunityInputError,
    RankingInputError,
    RiskInputError,
)
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload

try:  # the isolated environment has Celery; the stand-ins keep the test meaningful without it
    from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded
except ImportError:  # pragma: no cover

    class SoftTimeLimitExceeded(Exception):  # type: ignore[no-redef]  # noqa: N818
        pass

    class TimeLimitExceeded(Exception):  # type: ignore[no-redef]  # noqa: N818
        pass


SNAPSHOT_ID = 4
UUID = "00000000-0000-0000-0000-000000000004"
CREATED = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
AS_OF = CREATED - timedelta(minutes=2)
KNOWLEDGE = CREATED - timedelta(minutes=1)
NOW = CREATED + timedelta(minutes=5)
KEYS = tuple(f"investment_state:{s}" for s in SCOPE_DOMAINS)
BUILDERS = (
    "build_unified_snapshot",
    "build_confirmation",
    "build_opportunities",
    "build_ranking",
    "build_risk_view",
    "build_risk_invalidation",
    "build_investment_decision",
)


def _payload() -> dict[str, Any]:
    payload = make_payload(["S2", "S1", "N", "S1", "S2"])
    payload["snapshot_version"] = "analyst_snapshot.v1"
    return payload


@dataclasses.dataclass(frozen=True)
class Row:
    """A stored-row stand-in. Deliberately unvalidated, so tests can make it invalid."""

    row_id: Any = SNAPSHOT_ID
    uuid: Any = UUID
    payload_hash: Any = None
    created_at: Any = CREATED
    as_of: Any = AS_OF
    knowledge_time: Any = KNOWLEDGE
    payload: Any = dataclasses.field(default_factory=_payload)


_DEFAULT: Any = object()


def _row(payload: Any = _DEFAULT, **overrides: Any) -> Row:
    body = _payload() if payload is _DEFAULT else payload
    # A payload that is not a dict (an invalid-row case) has no producer hash to compute.
    stored_hash = producer_payload_hash(body) if isinstance(body, dict) else "0" * 64
    base: dict[str, Any] = {"payload": body, "payload_hash": stored_hash}
    base.update(overrides)
    return Row(**base)


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


def _build(row: Row | None) -> AdapterOutcome:
    return build_decision_from_row(row, SNAPSHOT_ID)


def _success(row: Row | None = None) -> AdapterOutcome:
    outcome = _build(row or _row())
    assert not outcome.refused, outcome
    return outcome


def _boom(*_a: object, **_k: object) -> Any:
    raise AssertionError("no builder may run for a refused row")


def _patch_all_builders(monkeypatch: pytest.MonkeyPatch, fn: Callable[..., Any]) -> None:
    for name in BUILDERS:
        monkeypatch.setattr(adapter, name, fn)


def _assert_refusal(outcome: AdapterOutcome, reason: str, detail: str | None = None) -> None:
    assert outcome.refused
    assert outcome.refusal_reason == reason
    assert outcome.decision is None
    assert outcome.identity is None
    assert outcome.detail == detail


# ------------------------------------------------------------------ G56 success
def test_a_valid_row_yields_a_decision_and_the_stored_identity() -> None:
    row = _row()
    outcome = _success(row)
    assert outcome.refusal_reason is None
    assert outcome.detail is None
    assert outcome.decision is not None
    assert outcome.decision["contract_version"] == ia.CONTRACT_ID
    assert outcome.identity == ia.StoredSnapshotIdentity(
        row_id=SNAPSHOT_ID,
        uuid=UUID,
        payload_hash=row.payload_hash,
        as_of=AS_OF,
        knowledge_time=KNOWLEDGE,
    )
    snap = outcome.decision["snapshot"]
    assert (snap["row_id"], snap["uuid"], snap["producer_payload_hash"]) == (
        SNAPSHOT_ID,
        UUID,
        row.payload_hash,
    )


def test_the_stage_2_evaluator_accepts_the_adapter_output_and_classifies_it() -> None:
    outcome = _success()
    assert outcome.decision is not None
    assert outcome.identity is not None
    result = ia.evaluate_investment_alerts(outcome.decision, outcome.identity, now=NOW)
    assert not result.refused
    btc = result.outcomes[0]
    assert (btc.asset, btc.state, btc.outcome_class) == ("BTC", "candidate_unresolved", "A")
    assert len(result.outcomes) == len(SCOPE_DOMAINS)
    assert result.count("A") + result.count("B") + result.count("C") == len(SCOPE_DOMAINS)


def test_the_three_timestamps_stay_distinct() -> None:
    outcome = _success()
    assert outcome.identity is not None
    assert len({AS_OF, KNOWLEDGE, CREATED}) == 3
    assert outcome.identity.as_of == AS_OF
    assert outcome.identity.knowledge_time == KNOWLEDGE
    assert not hasattr(outcome.identity, "created_at")


def test_the_builders_run_once_each_in_the_documented_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def spy(name: str) -> Callable[..., Any]:
        original = getattr(adapter, name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return original(*args, **kwargs)

        return wrapper

    for name in BUILDERS:
        monkeypatch.setattr(adapter, name, spy(name))
    _success()
    assert calls == [
        "build_unified_snapshot",
        "build_confirmation",
        "build_opportunities",
        "build_ranking",
        "build_risk_view",
        "build_risk_invalidation",
        "build_investment_decision",
    ]


# ------------------------------------------------------------------ G38 parity with the route
class _Source:
    def __init__(self, row: SnapshotRow) -> None:
        self.row = row

    async def latest_snapshot_row(self) -> SnapshotRow | None:
        return self.row


@pytest.mark.parametrize("make", [_payload, live_state_payload])
async def test_the_decision_equals_the_phase_49_route_chain_on_the_same_payload(
    make: Callable[[], dict[str, Any]],
) -> None:
    payload = make()
    payload["snapshot_version"] = "analyst_snapshot.v1"
    row = _row(payload)
    outcome = _success(row)
    from_route = await route.investment_decision(
        _Source(
            SnapshotRow(
                row_id=SNAPSHOT_ID,
                uuid=UUID,
                payload_hash=row.payload_hash,
                created_at=CREATED,
                payload=copy.deepcopy(payload),
            )
        )
    )
    assert outcome.decision == from_route


# ------------------------------------------------------------------ G57 / G58 not found, reader
def test_a_missing_row_is_snapshot_not_found() -> None:
    _assert_refusal(_build(None), "snapshot_not_found")


async def test_read_and_build_reads_exactly_once_and_delegates() -> None:
    reader = FakeReader(_row())
    outcome = await read_and_build(reader, SNAPSHOT_ID)
    assert reader.calls == [SNAPSHOT_ID]
    assert not outcome.refused
    assert outcome == _build(_row())


async def test_read_and_build_with_no_row_reads_once_and_refuses() -> None:
    reader = FakeReader(None)
    outcome = await read_and_build(reader, SNAPSHOT_ID)
    assert reader.calls == [SNAPSHOT_ID]
    _assert_refusal(outcome, "snapshot_not_found")


@pytest.mark.parametrize("bad", [True, False, "4", 4.0, None, [4]])
async def test_a_snapshot_id_that_is_not_a_plain_integer_is_a_caller_error(bad: object) -> None:
    reader = FakeReader(_row())
    with pytest.raises(ia.InvestmentAlertValidationError):
        await read_and_build(reader, bad)  # type: ignore[arg-type]
    assert reader.calls == []
    with pytest.raises(ia.InvestmentAlertValidationError):
        build_decision_from_row(_row(), bad)  # type: ignore[arg-type]


# ------------------------------------------------------------------ G59 row validation
INVALID_ROWS: list[tuple[str, Any]] = [
    ("row_id", True),
    ("row_id", "4"),
    ("row_id", 4.0),
    ("row_id", None),
    ("row_id", 5),  # a different row than the one requested
    ("uuid", None),
    ("uuid", ""),
    ("uuid", " padded "),
    ("uuid", 7),
    ("payload_hash", None),
    ("payload_hash", ""),
    ("payload_hash", " padded "),
    ("payload_hash", 7),
    ("created_at", None),
    ("created_at", "2026-10-05T12:00:00+00:00"),
    ("as_of", None),
    ("as_of", "2026-10-05T11:58:00+00:00"),
    ("knowledge_time", None),
    ("knowledge_time", 1_700_000_000),
    ("payload", None),
    ("payload", []),
    ("payload", "{}"),
]


@pytest.mark.parametrize(("field", "value"), INVALID_ROWS)
def test_an_unusable_row_is_snapshot_row_invalid_and_no_builder_runs(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    _patch_all_builders(monkeypatch, _boom)
    _assert_refusal(_build(_row(**{field: value})), "snapshot_row_invalid")


@pytest.mark.parametrize(
    "not_a_row", [object(), {}, "row", 4, [], type("Partial", (), {"row_id": 4})()]
)
def test_something_that_is_not_a_row_is_snapshot_row_invalid(
    monkeypatch: pytest.MonkeyPatch, not_a_row: object
) -> None:
    _patch_all_builders(monkeypatch, _boom)
    _assert_refusal(_build(not_a_row), "snapshot_row_invalid")  # type: ignore[arg-type]


def test_timezone_awareness_is_left_to_the_evaluator() -> None:
    naive = _row(as_of=AS_OF.replace(tzinfo=None))
    outcome = _success(naive)
    assert outcome.decision is not None
    assert outcome.identity is not None
    result = ia.evaluate_investment_alerts(outcome.decision, outcome.identity, now=NOW)
    assert result.refused
    assert result.refusal_reason == "snapshot_time_invalid"


# ------------------------------------------------------------------ G60 builder refusals
CHAIN_STEP = {
    InvalidSnapshotError: "build_unified_snapshot",
    ConfirmationInputError: "build_confirmation",
    OpportunityInputError: "build_opportunities",
    RankingInputError: "build_ranking",
    RiskInputError: "build_risk_invalidation",
    InvestmentInputError: "build_investment_decision",
}


@pytest.mark.parametrize(("error", "step"), list(CHAIN_STEP.items()))
def test_each_known_builder_refusal_is_decision_inputs_refused(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception], step: str
) -> None:
    def refuse(*_a: object, **_k: object) -> Any:
        raise error("secret payload text that must never be copied")

    monkeypatch.setattr(adapter, step, refuse)
    outcome = _build(_row())
    _assert_refusal(outcome, "decision_inputs_refused", error.__name__)
    assert "secret" not in repr(outcome)


def test_the_view_builder_can_refuse_with_the_snapshot_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_a: object, **_k: object) -> Any:
        raise InvalidSnapshotError("x")

    monkeypatch.setattr(adapter, "build_risk_view", refuse)
    _assert_refusal(_build(_row()), "decision_inputs_refused", "InvalidSnapshotError")


def test_the_six_known_types_are_exactly_those_of_the_phase_49_route() -> None:
    assert set(adapter.KNOWN_BUILDER_REFUSALS) == set(CHAIN_STEP)
    assert ValueError not in adapter.KNOWN_BUILDER_REFUSALS


def test_a_subclass_of_a_known_refusal_is_reported_under_the_known_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Narrower(RankingInputError):  # noqa: N818
        pass

    def refuse(*_a: object, **_k: object) -> Any:
        raise Narrower("x")

    monkeypatch.setattr(adapter, "build_ranking", refuse)
    _assert_refusal(_build(_row()), "decision_inputs_refused", "RankingInputError")


def test_a_real_unsupported_payload_is_refused_by_the_real_builders() -> None:
    payload = _payload()
    payload["snapshot_version"] = "analyst_snapshot.v999"
    _assert_refusal(_build(_row(payload)), "decision_inputs_refused", "InvalidSnapshotError")


# ------------------------------------------------------------------ G61 propagation
UNEXPECTED: list[BaseException] = [
    ValueError("a plain ValueError is not a known refusal"),
    KeyError("k"),
    TypeError("t"),
    AttributeError("a"),
    RuntimeError("r"),
    RecursionError("deep"),
    SoftTimeLimitExceeded(),
    TimeLimitExceeded(),
    asyncio.CancelledError(),
    KeyboardInterrupt(),
]


@pytest.mark.parametrize("error", UNEXPECTED, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("step", BUILDERS)
def test_unexpected_and_execution_control_exceptions_from_a_builder_propagate(
    monkeypatch: pytest.MonkeyPatch, error: BaseException, step: str
) -> None:
    def raise_it(*_a: object, **_k: object) -> Any:
        raise error

    original = getattr(adapter, step)
    monkeypatch.setattr(adapter, step, raise_it)
    try:
        with pytest.raises(type(error)) as caught:
            _build(_row())
    finally:
        monkeypatch.setattr(adapter, step, original)
    assert caught.value is error


@pytest.mark.parametrize("error", UNEXPECTED, ids=lambda e: type(e).__name__)
async def test_exceptions_from_the_reader_propagate_unchanged(error: BaseException) -> None:
    reader = FakeReader(error=error)
    with pytest.raises(type(error)) as caught:
        await read_and_build(reader, SNAPSHOT_ID)
    assert caught.value is error
    assert reader.calls == [SNAPSHOT_ID]


def test_the_execution_control_exceptions_are_not_known_refusals() -> None:
    known = adapter.KNOWN_BUILDER_REFUSALS
    for error in (SoftTimeLimitExceeded(), TimeLimitExceeded(), asyncio.CancelledError()):
        assert not isinstance(error, known)


# ------------------------------------------------------------------ G62 hash policy
def test_a_matching_stored_hash_is_verified_and_a_wrong_one_is_a_mismatch() -> None:
    verified = _success(_row())
    mismatch = _success(_row(payload_hash="0" * 64))
    assert verified.decision is not None
    assert mismatch.decision is not None
    assert verified.decision["snapshot"]["producer_hash_check"] == "verified"
    assert mismatch.decision["snapshot"]["producer_hash_check"] == "mismatch"


@pytest.mark.parametrize("make", [_payload, live_state_payload])
def test_unverified_never_comes_from_the_adapter(make: Callable[[], dict[str, Any]]) -> None:
    payload = make()
    payload["snapshot_version"] = "analyst_snapshot.v1"
    for stored_hash in (producer_payload_hash(payload), "f" * 64):
        outcome = _success(_row(payload, payload_hash=stored_hash))
        assert outcome.decision is not None
        assert outcome.decision["snapshot"]["producer_hash_check"] in {"verified", "mismatch"}


def test_a_hash_mismatch_is_not_an_adapter_refusal_it_flows_through_the_phase_46_gate() -> None:
    outcome = _success(_row(payload_hash="0" * 64))
    decision, identity = outcome.decision, outcome.identity
    assert decision is not None
    assert identity is not None
    assert decision["gates"]["producer_hash"] == {"check": "mismatch", "triggered": True}
    assert decision["assessment"] == {"performed": False, "gate_reasons": ["DI-GATE-INTEGRITY"]}
    assert {a["decision_state"] for a in decision["assets"].values()} == {"withheld_integrity_gate"}
    result = ia.evaluate_investment_alerts(decision, identity, now=NOW)
    assert not result.refused
    assert {(o.outcome_class, o.reason) for o in result.outcomes} == {("B", "request_gated")}
    assert result.candidates == ()


def test_a_hash_mismatch_leaves_every_stored_alert_untouched_and_indeterminate() -> None:
    outcome = _success(_row(payload_hash="0" * 64))
    assert outcome.decision is not None
    assert outcome.identity is not None
    result = ia.evaluate_investment_alerts(outcome.decision, outcome.identity, now=NOW)
    stored = {k: ExistingAlert("candidate_unresolved", CREATED - timedelta(days=1)) for k in KEYS}
    snapshot = dict(stored)
    plan = ia.plan_investment_lifecycle(result, stored, now=NOW, persistence=True)
    assert stored == snapshot
    assert [d.disposition for d in plan.assets] == [None] * len(KEYS)
    assert [(i.dedup_key, i.reason) for i in plan.indeterminate] == [
        (k, "request_gated") for k in KEYS
    ]


# ------------------------------------------------------------------ G63 immutability, determinism
def test_the_payload_is_not_mutated_and_the_result_is_deterministic() -> None:
    row = _row()
    before = copy.deepcopy(row.payload)
    first = _build(row)
    second = _build(row)
    assert row.payload == before
    assert first == second


def test_the_returned_decision_does_not_alias_the_stored_payload() -> None:
    row = _row()
    before = copy.deepcopy(row.payload)
    outcome = _success(row)
    assert outcome.decision is not None
    outcome.decision["assets"]["BTC"]["decision_state"] = "tampered"
    outcome.decision["snapshot"]["uuid"] = "tampered"
    assert row.payload == before


# ------------------------------------------------------------------ G64 outcome invariants
def _ok_parts() -> tuple[dict[str, Any], ia.StoredSnapshotIdentity]:
    outcome = _success()
    assert outcome.decision is not None
    assert outcome.identity is not None
    return outcome.decision, outcome.identity


def test_adapter_outcome_invariants() -> None:
    decision, identity = _ok_parts()
    ia_err = ia.InvestmentAlertValidationError
    AdapterOutcome(decision, identity, None)
    AdapterOutcome(None, None, "snapshot_not_found")
    AdapterOutcome(None, None, "snapshot_row_invalid")
    AdapterOutcome(None, None, "decision_inputs_refused", "RiskInputError")
    cases: list[Callable[[], AdapterOutcome]] = [
        lambda: AdapterOutcome(None, None, None),
        lambda: AdapterOutcome(decision, None, None),
        lambda: AdapterOutcome(None, identity, None),
        lambda: AdapterOutcome(decision, identity, None, "RiskInputError"),
        lambda: AdapterOutcome(decision, identity, "snapshot_not_found"),
        lambda: AdapterOutcome(None, identity, "snapshot_not_found"),
        lambda: AdapterOutcome(decision, None, "snapshot_row_invalid"),
        lambda: AdapterOutcome(None, None, "snapshot_identity_mismatch"),
        lambda: AdapterOutcome(None, None, "not_a_reason"),
        lambda: AdapterOutcome(None, None, "decision_inputs_refused"),
        lambda: AdapterOutcome(None, None, "decision_inputs_refused", "ValueError"),
        lambda: AdapterOutcome(None, None, "decision_inputs_refused", "boom: secret text"),
        lambda: AdapterOutcome(None, None, "snapshot_not_found", "RiskInputError"),
    ]
    for case in cases:
        with pytest.raises(ia_err):
            case()


def test_every_refusal_path_carries_no_usable_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = [_build(None)]
    outcomes += [_build(_row(**{f: v})) for f, v in INVALID_ROWS]
    for error, step in CHAIN_STEP.items():

        def refuse(*_a: object, _e: type[Exception] = error, **_k: object) -> Any:
            raise _e("x")

        with monkeypatch.context() as m:
            m.setattr(adapter, step, refuse)
            outcomes.append(_build(_row()))
    assert all(o.refused and o.decision is None and o.identity is None for o in outcomes)
    assert {o.refusal_reason for o in outcomes} == set(ia.ADAPTER_REFUSAL_REASONS)


# ------------------------------------------------------------------ G65 vocabulary and planner
def test_the_refusal_vocabulary_is_closed_separate_and_unioned() -> None:
    assert ia.ADAPTER_REFUSAL_REASONS == (
        "snapshot_not_found",
        "snapshot_row_invalid",
        "decision_inputs_refused",
    )
    assert ia.EVALUATOR_REFUSAL_REASONS == (
        "decision_contract_invalid",
        "snapshot_time_invalid",
        "snapshot_time_in_future",
        "snapshot_identity_mismatch",
    )
    assert set(ia.ADAPTER_REFUSAL_REASONS).isdisjoint(ia.EVALUATOR_REFUSAL_REASONS)
    assert (*ia.EVALUATOR_REFUSAL_REASONS, *ia.ADAPTER_REFUSAL_REASONS) == ia.REFUSAL_REASONS
    assert len(set(ia.REFUSAL_REASONS)) == len(ia.REFUSAL_REASONS) == 7
    assert set(ia.REFUSAL_REASONS) <= set(ia.INDETERMINATE_REASONS)
    assert set(ia.CLASS_B_REASONS) <= set(ia.INDETERMINATE_REASONS)


def test_the_new_reasons_pass_the_banned_vocabulary_check() -> None:
    for reason in ia.ADAPTER_REFUSAL_REASONS:
        for pattern in BANNED_PATTERNS.values():
            assert not pattern.search(reason)


def test_the_evaluator_never_emits_an_adapter_reason() -> None:
    outcome = _success()
    assert outcome.decision is not None
    assert outcome.identity is not None
    emitted = set()
    junk: tuple[object, ...] = (None, {}, [], "x", {"contract_version": "other"})
    for d in junk:
        emitted.add(ia.evaluate_investment_alerts(d, outcome.identity, now=NOW).refusal_reason)
    emitted.add(ia.evaluate_investment_alerts(outcome.decision, None, now=NOW).refusal_reason)  # type: ignore[arg-type]
    emitted.add(
        ia.evaluate_investment_alerts(
            outcome.decision, dataclasses.replace(outcome.identity, row_id=999), now=NOW
        ).refusal_reason
    )
    assert emitted <= set(ia.EVALUATOR_REFUSAL_REASONS)


@pytest.mark.parametrize("reason", ia.ADAPTER_REFUSAL_REASONS)
def test_an_adapter_refusal_leaves_every_stored_alert_indeterminate(reason: str) -> None:
    refused = ia.InvestmentEvaluation(refused=True, refusal_reason=reason, outcomes=())
    stored: dict[str, ExistingAlert | None] = {
        k: ExistingAlert("candidate_unresolved", CREATED - timedelta(days=2)) for k in KEYS
    }
    stored[KEYS[1]] = None
    plan = ia.plan_investment_lifecycle(refused, stored, now=NOW, persistence=True)
    assert plan.refused
    assert plan.refusal_reason == reason
    assert plan.assets == ()
    assert [(i.dedup_key, i.reason) for i in plan.indeterminate] == [
        (k, reason) for k in KEYS if stored[k] is not None
    ]
    gated = ia.plan_investment_lifecycle(refused, None, now=NOW)
    assert gated.refused
    assert gated.indeterminate == ()


@pytest.mark.parametrize("reason", ia.ADAPTER_REFUSAL_REASONS)
def test_a_refused_adapter_outcome_cannot_become_a_usable_evaluation(reason: str) -> None:
    refusal = ia.InvestmentEvaluation(refused=True, refusal_reason=reason, outcomes=())
    assert refusal.candidates == ()
    assert refusal.outcomes == ()
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.InvestmentEvaluation(refused=False, refusal_reason=reason, outcomes=())


# ------------------------------------------------------------------ G66 import boundary
ALLOWED_IMPORTS = {
    "__future__",
    "dataclasses",
    "datetime",
    "typing",
    "cfi.alerts.investment_alerts",
    "cfi.decision.context",
    "cfi.decision.identity",
    "cfi.intelligence",
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
    "celery",
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


def _source() -> str:
    return Path(inspect.getsourcefile(adapter) or "").read_text(encoding="utf-8")


def test_the_adapter_imports_only_the_approved_modules() -> None:
    tree = ast.parse(_source())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imported.add(node.module or "")
    assert imported == ALLOWED_IMPORTS
    assert not any(m == r or m.startswith(r + ".") for m in imported for r in FORBIDDEN_ROOTS)


def test_the_adapter_uses_only_the_vocabulary_and_types_of_the_evaluator_module() -> None:
    tree = ast.parse(_source())
    names = {
        a.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "cfi.alerts.investment_alerts"
        for a in node.names
    }
    assert names == {
        "ADAPTER_REFUSAL_REASONS",
        "InvestmentAlertValidationError",
        "StoredSnapshotIdentity",
    }


def test_importing_the_adapter_loads_no_io_library_or_repository() -> None:
    code = (
        "import sys\n"
        "import cfi\n"
        "before = set(sys.modules)\n"
        "import cfi.alerts.investment_adapter\n"
        "new = sorted(set(sys.modules) - before)\n"
        f"roots = {FORBIDDEN_ROOTS!r}\n"
        "bad = [m for m in new if any(m == r or m.startswith(r + '.') for r in roots)]\n"
        "print(repr(bad))\n"
    )
    env_path = ":".join(p for p in sys.path if p)
    out = subprocess.run(  # noqa: S603 — fixed interpreter, fixed code, no user input
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": env_path, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=60,
    )
    assert out.stdout.strip() == "[]", out.stdout


def test_the_adapter_source_has_no_clock_io_writer_or_orchestration_calls() -> None:
    tree = ast.parse(_source())
    calls = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert not calls & {"now", "utcnow", "today", "time", "open", "execute", "connect"}
    assert not calls & {"insert_alert", "supersede", "resolve", "acknowledge", "insert_snapshot"}
    assert not calls & {"evaluate_investment_alerts", "plan_investment_lifecycle", "decide"}
    assert not calls & {"latest_snapshot", "latest_snapshot_row"}
    awaits = [n for n in ast.walk(tree) if isinstance(n, ast.Await)]
    assert len(awaits) == 1


def test_the_one_await_is_the_reader_call_and_is_not_guarded() -> None:
    tree = ast.parse(_source())
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "read_and_build"
    )
    assert not any(isinstance(n, ast.Try) for n in ast.walk(fn))
    assert not any(isinstance(n, ast.ExceptHandler) for n in ast.walk(fn))
    assert sum(isinstance(n, ast.Await) for n in ast.walk(fn)) == 1


def test_the_only_except_clause_names_the_six_known_refusals() -> None:
    tree = ast.parse(_source())
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    assert len(handlers) == 1
    assert isinstance(handlers[0].type, ast.Name)
    assert handlers[0].type.id == "KNOWN_BUILDER_REFUSALS"


def test_build_decision_from_row_is_synchronous() -> None:
    assert not inspect.iscoroutinefunction(build_decision_from_row)
    assert inspect.iscoroutinefunction(read_and_build)


# Static only: mypy checks that the real repository and row type satisfy the adapter protocols.
def _real_repository_is_a_reader(repo: DecisionAssessmentRepository) -> SnapshotReader:
    return repo


def _real_row_is_a_row(row: StoredSnapshot) -> StoredSnapshotRow:
    return row
