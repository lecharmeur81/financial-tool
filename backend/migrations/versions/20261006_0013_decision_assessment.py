"""Decision assessments: persistence for Phase 40 (Decision Assessment Persistence Foundation).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-06

Additive only (R10):

- sig.decision_assessment — one immutable row per (stored snapshot, scope, methodology version,
  parameter version): the deterministic Phase 38.2/38.3 assessment of that snapshot, exactly as
  ``cfi.decision.context.build_decision_context(...).deterministic_dict()`` produced it. Lives in
  ``sig`` beside ``sig.intelligence_event`` (derived-from-L2 findings), not in a new schema.

  Identity (ADR-0076, D-M): ``(snapshot_id, scope, methodology_version, parameter_version)`` is
  UNIQUE, so "the same snapshot assessed twice" (a retry, two producers racing) can never create a
  second row; the writer uses ``INSERT ... ON CONFLICT DO NOTHING``. ``template_version`` is
  recorded as provenance and is deliberately NOT part of the identity.

  Four distinct identifiers are kept apart and never merged (Phase 38.3): ``snapshot_id`` (the
  ``ai.snapshot`` row key), ``producer_payload_hash`` (as stored on the snapshot row, with
  ``producer_hash_check`` saying whether it was re-verified: a ``mismatch`` is recorded, never
  repaired and never read as a completeness signal), and ``decision_input_hash`` (the engine's own
  hash over the payload it received). The row's uuid is the external-safe reference.

  The scalar columns (stance, confidence, posture, coverage, conflict) are copies of values inside
  ``assessment`` so history queries can filter without parsing JSON. They are never calculated
  here. The producer's ``data_quality_state`` and ``has_conflicts`` are NOT stored: they are not a
  completeness signal (Phase 39).

  The CHECK vocabularies below are the closed sets of ``cfi.decision.universe`` (a unit test pins
  them to the enums, since a migration must not import application code).

Downgrade refuses to run if ``sig.decision_assessment`` holds data (R10).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPES = ("BTC", "ETH", "SOL", "XRP")
STANCES = (
    "Strongly Bullish",
    "Bullish",
    "Cautiously Bullish",
    "Neutral / Wait",
    "Cautiously Bearish",
    "Bearish",
    "Strongly Bearish",
    "Insufficient Evidence",
)
CONFIDENCES = ("High", "Moderate", "Low", "Insufficient Evidence")
POSTURES = (
    "INVESTIGATE FURTHER",
    "WAIT FOR CONFIRMATION",
    "MONITOR CONSTRUCTIVE CONDITIONS",
    "MONITOR WITH ELEVATED CAUTION",
    "AVOID ADDING HIGH-RISK EXPOSURE",
    "REASSESS / REDUCE RISK",
)
HASH_CHECKS = ("verified", "mismatch", "unverified")


def _in(values: Sequence[str]) -> str:
    return ",".join("'" + v.replace("'", "''") + "'" for v in values)


UPGRADE_SQL = f"""
CREATE TABLE sig.decision_assessment (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid                  uuid NOT NULL UNIQUE,
    created_at            timestamptz NOT NULL,
    snapshot_id           bigint NOT NULL REFERENCES ai.snapshot (id),
    scope                 text NOT NULL CHECK (scope IN ({_in(SCOPES)})),
    methodology_version   text NOT NULL,
    parameter_version     text NOT NULL,
    template_version      text NOT NULL,
    snapshot_version      text NOT NULL,
    snapshot_as_of        timestamptz NOT NULL,
    knowledge_time        timestamptz NOT NULL,
    producer_payload_hash text,
    producer_hash_check   text NOT NULL CHECK (producer_hash_check IN ({_in(HASH_CHECKS)})),
    decision_input_hash   text NOT NULL,
    stance                text NOT NULL CHECK (stance IN ({_in(STANCES)})),
    confidence            text NOT NULL CHECK (confidence IN ({_in(CONFIDENCES)})),
    posture               text NOT NULL CHECK (posture IN ({_in(POSTURES)})),
    coverage_available    smallint NOT NULL CHECK (coverage_available >= 0),
    expected_domains      smallint NOT NULL CHECK (expected_domains >= 0),
    conflict              boolean NOT NULL,
    assessment            jsonb NOT NULL,
    CONSTRAINT decision_assessment_identity_uq
        UNIQUE (snapshot_id, scope, methodology_version, parameter_version)
);
CREATE INDEX decision_assessment_scope_idx ON sig.decision_assessment (scope, created_at DESC)
"""

DATA_CHECKS = {"sig.decision_assessment": "SELECT EXISTS (SELECT 1 FROM sig.decision_assessment)"}


def upgrade() -> None:
    for statement in UPGRADE_SQL.split(";\n"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    conn = op.get_bind()
    non_empty = [name for name, sql in DATA_CHECKS.items() if conn.execute(sa.text(sql)).scalar()]
    if non_empty:
        raise RuntimeError(
            "Refusing to downgrade: these would be destroyed: " + ", ".join(non_empty)
        )
    op.execute("DROP TABLE sig.decision_assessment")
