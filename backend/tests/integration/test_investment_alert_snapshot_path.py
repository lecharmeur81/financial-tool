"""Phase 51 Stage 6 — the real stored-snapshot path of the investment-alert engine (PostgreSQL).

A snapshot is stored through the platform's own ``AnalystRepository.insert_snapshot``, read back
through the real ``DecisionAssessmentRepository``, turned into ``investment_decision.v0`` by the
real adapter and evaluated by the real evaluator. Nothing is persisted as an alert: this checks
that the engine receives the intended snapshot, that identity and hash checks hold on a real
stored row, and that a missing snapshot or an integrity mismatch can never yield a candidate.

**This file is written but must not be run without separate, explicit authorization.** The shared
integration fixture (``tests/integration/conftest.py``) drops and recreates the database named
``<configured name>_test`` on the configured server and migrates it. A ``_test`` suffix alone does
not prove that is safe. Before any run:

1. Inspect the effective ``CFI_DATABASE_URL`` without printing credentials (host, port, name only).
2. Confirm the exact configured name **and** the derived ``<name>_test``.
3. Confirm the target is a disposable PostgreSQL+Timescale instance, not the live or development
   stack, and that no database of value is named ``<name>_test`` on that server.
4. Confirm the required infrastructure (TimescaleDB) and a role with ``CREATEDB``.
5. Obtain explicit authorization to execute.

The module is skipped unless ``evaluate_gate`` passes: confirmation exactly ``p51_scratch_test``,
host ``127.0.0.1`` or ``localhost``, port ``55432`` or ``55433``, database ``p51_scratch``,
no URL query
parameters and no runtime URL. Then run only this file with ``-m integration``. Never run an
unfiltered ``pytest`` while the service variables are set.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.investment_adapter import AdapterOutcome, read_and_build
from cfi.alerts.investment_alerts import (
    InvestmentEvaluation,
    StoredSnapshotIdentity,
    evaluate_investment_alerts,
)
from cfi.alerts.investment_block import EVENT_NAME, run_investment_cycle
from cfi.analyst.repository import AnalystRepository
from cfi.decision.identity import producer_payload_hash
from cfi.decision_store.record import StoredSnapshot
from cfi.decision_store.repository import DecisionAssessmentRepository
from tests.decision_live_payload import live_state_payload
from tests.decision_snapshots import stored_form
from tests.integration.conftest import requires_services

CONFIRM_ENV = "CFI_P51_DB_TEST_CONFIRM"
DATABASE_URL_ENV = "CFI_DATABASE_URL"
RUNTIME_URL_ENV = "CFI_DATABASE_URL_RUNTIME"

# The only target this module may ever run against: the disposable container described in
# PHASE51_SCHEMA_VERIFICATION_PROCEDURE.md (section 9). Nothing here is configurable.
ALLOWED_HOSTS: Final = ("127.0.0.1", "localhost")
EXPECTED_PORTS: Final = (55432, 55433)
EXPECTED_DATABASE: Final = "p51_scratch"
EXPECTED_TEST_DATABASE: Final = "p51_scratch_test"

# Failure codes only. A code never carries a URL, a password, a host value or an exception text.
FAIL_CONFIRM = "confirmation_not_exact"
FAIL_URL_MISSING = "database_url_missing"
FAIL_URL_UNPARSABLE = "database_url_unparsable"
FAIL_URL_QUERY = "database_url_has_query_parameters"
FAIL_HOST = "host_not_allowed"
FAIL_PORT = "port_not_expected"
FAIL_DATABASE = "database_name_not_expected"
FAIL_DERIVED = "derived_test_database_not_expected"
FAIL_RUNTIME = "runtime_url_set"


@dataclass(frozen=True, slots=True)
class GateResult:
    ok: bool
    failures: tuple[str, ...]


def evaluate_gate(environ: Mapping[str, str]) -> GateResult:
    """Pure, connection-free check of every condition for running the destructive fixture.

    It reads only the mapping it is given, opens no connection and never reveals the URL: the
    result carries failure codes, not values. A URL carrying query parameters is rejected because
    libpq/psycopg let ``?host=`` or ``?port=`` override the authority part that is checked here.
    """
    failures: list[str] = []
    if environ.get(CONFIRM_ENV) != EXPECTED_TEST_DATABASE:
        failures.append(FAIL_CONFIRM)
    raw = environ.get(DATABASE_URL_ENV)
    if not raw:
        failures.append(FAIL_URL_MISSING)
    else:
        try:
            url = make_url(raw)
            host, port, database, query = url.host, url.port, url.database, url.query
        except Exception:  # never surface the parser's message (it may echo the URL)
            failures.append(FAIL_URL_UNPARSABLE)
        else:
            if query:
                failures.append(FAIL_URL_QUERY)
            if host not in ALLOWED_HOSTS:
                failures.append(FAIL_HOST)
            if port not in EXPECTED_PORTS:
                failures.append(FAIL_PORT)
            if database != EXPECTED_DATABASE:
                failures.append(FAIL_DATABASE)
            if f"{database}_test" != EXPECTED_TEST_DATABASE:
                failures.append(FAIL_DERIVED)
    if (environ.get(RUNTIME_URL_ENV) or "").strip():
        failures.append(FAIL_RUNTIME)
    return GateResult(ok=not failures, failures=tuple(failures))


# Why this runs before any destructive step: ``skipif`` marks are evaluated in pytest's setup hook
# before any fixture of the item is created, and ``test_database_url`` (the session fixture that
# drops and recreates the database) is created only when a test that is actually set up requests
# it. A skipped test therefore never creates it. The module-level mark covers every test here.
_GATE = evaluate_gate(os.environ)

pytestmark = [
    pytest.mark.integration,
    requires_services,
    pytest.mark.skipif(
        not _GATE.ok,
        reason=(
            "Phase 51 database gate not satisfied (failed checks: "
            f"{', '.join(_GATE.failures) or 'none'}); set the target only after it has been "
            "independently verified as disposable"
        ),
    ),
]


class RecordingReader:
    """Delegates to the real repository unchanged and records every call and result."""

    def __init__(self, inner: DecisionAssessmentRepository) -> None:
        self.inner = inner
        self.calls: list[int] = []
        self.returned: list[StoredSnapshot | None] = []

    async def get_snapshot(self, snapshot_id: int) -> StoredSnapshot | None:
        self.calls.append(snapshot_id)
        row = await self.inner.get_snapshot(snapshot_id)
        self.returned.append(row)
        return row


class RecordingLog:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.calls.append(("info", event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self.calls.append(("warning", event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self.calls.append(("error", event, fields))


async def _store(
    db: AsyncEngine,
    payload: dict[str, Any] | None = None,
    *,
    payload_hash: str | None = None,
) -> tuple[int, str, str]:
    """Store through the real insert path; returns (row id, row uuid, stored payload hash)."""
    stored = stored_form(payload if payload is not None else live_state_payload())
    when = datetime.now(UTC)
    digest = payload_hash or producer_payload_hash(stored)
    row_id, row_uuid = await AnalystRepository(db).insert_snapshot(
        created_at=when,
        as_of=when,
        knowledge_time=when,
        snapshot_version=str(stored.get("snapshot_version", "analyst_snapshot.v1")),
        payload=stored,
        payload_hash=digest,
    )
    return row_id, str(row_uuid), digest


async def _count(db: AsyncEngine, table: str) -> int:
    async with db.connect() as conn:
        return int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())  # noqa: S608


def _evaluate(outcome: AdapterOutcome) -> InvestmentEvaluation:
    assert outcome.decision is not None
    assert outcome.identity is not None
    return evaluate_investment_alerts(
        outcome.decision, outcome.identity, now=datetime.now(UTC)
    )  # taken after the insert: the evaluator rejects a snapshot from the future


# ----------------------------------------------------------------------------- I-01


async def test_i01_a_real_stored_snapshot_is_retrieved_verified_matched_and_assessed(
    db: AsyncEngine,
) -> None:
    row_id, row_uuid, digest = await _store(db)
    reader = RecordingReader(DecisionAssessmentRepository(db))

    outcome = await read_and_build(reader, row_id)

    # 1. The row is retrieved through the actual repository, exactly once, by this id.
    assert reader.calls == [row_id]
    returned = reader.returned[0]
    assert isinstance(returned, StoredSnapshot)
    assert type(returned.row_id) is int
    assert returned.uuid == returned.uuid.strip()
    async with db.connect() as conn:
        raw = (
            await conn.execute(
                text(
                    "SELECT id, uuid, payload_hash, as_of, knowledge_time "
                    "FROM ai.snapshot WHERE id = :i"
                ),
                {"i": row_id},
            )
        ).one()
    assert raw.id == returned.row_id == row_id
    assert str(raw.uuid) == returned.uuid == row_uuid
    assert raw.payload_hash == returned.payload_hash == digest
    assert raw.as_of == returned.as_of
    assert raw.knowledge_time == returned.knowledge_time

    # 2. The adapter accepts the row and produces a decision with the stored identity.
    assert outcome.refusal_reason is None, outcome
    assert outcome.decision is not None
    assert outcome.identity is not None

    # 3. The hash is verified: recomputed independently, and by the Phase 46 gate.
    assert producer_payload_hash(returned.payload) == returned.payload_hash
    decision = outcome.decision
    assert decision["snapshot"]["producer_hash_check"] == "verified"
    assert decision["gates"]["producer_hash"]["triggered"] is False

    # 4. The identity matches the decision, field by field.
    assert outcome.identity == StoredSnapshotIdentity(
        row_id=row_id,
        uuid=row_uuid,
        payload_hash=digest,
        as_of=raw.as_of,
        knowledge_time=raw.knowledge_time,
    )
    assert decision["snapshot"]["row_id"] == row_id
    assert decision["snapshot"]["uuid"] == row_uuid
    assert decision["snapshot"]["producer_payload_hash"] == digest

    # 5. The evaluator does not refuse the decision.
    evaluation = _evaluate(outcome)
    assert evaluation.refused is False, evaluation.refusal_reason
    assert evaluation.refusal_reason is None
    assert len(evaluation.outcomes) == 4

    # 6. The assessment was performed (a hard assertion: never skipped or weakened).
    assert decision["assessment"]["performed"] is True, (
        "the live-state snapshot did not give performed == true; investigate the fixture or the "
        "integrity gate before accepting Stage 6"
    )


# ----------------------------------------------------------------------------- I-02 to I-07


async def test_i02_the_full_block_on_the_real_repository_evaluates_without_candidates(
    db: AsyncEngine,
) -> None:
    row_id, _, _ = await _store(db)
    reader = RecordingReader(DecisionAssessmentRepository(db))
    log = RecordingLog()
    result = await run_investment_cycle(reader, row_id, now=datetime.now(UTC), logger=log)
    assert reader.calls == [row_id]
    assert result.status == "evaluated"
    assert result.evaluation is not None
    assert result.plan is not None
    # Expected from the live-state route test (no candidate state); to be confirmed on execution.
    assert result.evaluation.candidates == ()
    assert {o.outcome_class for o in result.evaluation.outcomes} == {"C"}
    assert result.plan.persistence_enabled is False
    assert [(c[0], c[1]) for c in log.calls] == [("info", EVENT_NAME)]


async def test_i03_a_missing_snapshot_cannot_produce_a_candidate(db: AsyncEngine) -> None:
    row_id, _, _ = await _store(db)
    reader = RecordingReader(DecisionAssessmentRepository(db))
    log = RecordingLog()
    result = await run_investment_cycle(reader, row_id + 1000, now=datetime.now(UTC), logger=log)
    assert reader.returned == [None]
    assert result.status == "refused"
    assert result.refusal_reason == "snapshot_not_found"
    assert result.evaluation is not None
    assert result.evaluation.outcomes == ()
    assert result.evaluation.candidates == ()
    assert result.plan is not None
    assert result.plan.assets == ()
    assert log.calls[0][0] == "error"


async def test_i04_an_integrity_mismatch_cannot_produce_a_candidate(db: AsyncEngine) -> None:
    row_id, _, _ = await _store(db, payload_hash="f" * 64)
    reader = RecordingReader(DecisionAssessmentRepository(db))
    outcome = await read_and_build(reader, row_id)
    assert outcome.decision is not None
    assert outcome.decision["snapshot"]["producer_hash_check"] == "mismatch"
    assert outcome.decision["gates"]["producer_hash"]["triggered"] is True
    assert outcome.decision["assessment"]["performed"] is False
    evaluation = _evaluate(outcome)
    assert evaluation.refused is False
    assert [o.outcome_class for o in evaluation.outcomes] == ["B"] * 4
    assert {o.reason for o in evaluation.outcomes} == {"request_gated"}
    assert evaluation.candidates == ()


async def test_i05_an_unsupported_stored_payload_is_an_input_refusal(db: AsyncEngine) -> None:
    payload = live_state_payload()
    payload["snapshot_version"] = "analyst_snapshot.v0"
    row_id, _, _ = await _store(db, payload)
    reader = RecordingReader(DecisionAssessmentRepository(db))
    log = RecordingLog()
    result = await run_investment_cycle(reader, row_id, now=datetime.now(UTC), logger=log)
    assert result.status == "refused"
    assert result.refusal_reason == "decision_inputs_refused"
    assert result.evaluation is not None
    assert result.evaluation.candidates == ()
    assert log.calls[0][0] == "warning"
    assert log.calls[0][2]["refusal_detail"] == "InvalidSnapshotError"


async def test_i06_the_snapshot_is_fetched_by_id_not_by_recency(db: AsyncEngine) -> None:
    older = live_state_payload()
    older["as_of"] = "2026-10-05T10:00:00+00:00"
    older["knowledge_time"] = "2026-10-05T10:00:00+00:00"
    older_id, older_uuid, _ = await _store(db, older)
    newer_id, newer_uuid, _ = await _store(db)
    assert newer_id > older_id
    outcome = await read_and_build(RecordingReader(DecisionAssessmentRepository(db)), older_id)
    assert outcome.identity is not None
    assert outcome.identity.row_id == older_id
    assert outcome.identity.uuid == older_uuid != newer_uuid


async def test_i07_the_block_writes_nothing(db: AsyncEngine) -> None:
    row_id, _, _ = await _store(db)
    before = {t: await _count(db, t) for t in ("usr.alert_event", "ai.snapshot")}
    await run_investment_cycle(
        RecordingReader(DecisionAssessmentRepository(db)),
        row_id,
        now=datetime.now(UTC),
        logger=RecordingLog(),
    )
    after = {t: await _count(db, t) for t in ("usr.alert_event", "ai.snapshot")}
    assert after == before
