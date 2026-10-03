"""AI Analyst: evidence snapshots, interpretations, and Claude API usage (Phase 21).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-28

Additive only (R10). The ``ai`` schema already existed (created empty in migration 0001, "L5 AI
snapshots, interpretations, usage") — this is the first migration to populate it:

- ai.snapshot      — one immutable, hashed evidence bundle per analysis (ARCHITECTURE.md 5.18: "the
                     complete evidence Claude may use"). Never updated after insert.
- ai.interpretation — one row per analysis request, created ``queued`` by the API before the Claude
                     worker task runs (so its id is a stable ``analysis_id`` the API can return
                     immediately), then updated in place as the task progresses
                     (queued -> running -> completed/failed). Carries the validated structured
                     response, the deterministic validator's own findings, and the auditability
                     fields the user's Phase 21 spec asks for (Section 13): question, model, prompt
                     version, tools called, data-quality state, any top-level error.
- ai.usage         — one row per Claude API call attempt (the first call, and the one retry, are
                     each their own row) — token counts, latency and estimated cost, so the monthly
                     budget ceiling (ADR-0034/0038, TODO.md B3) can be enforced by summing this
                     table, never by a separate, driftable counter.

This is the first WRITE path in this codebase outside ``cfi.ingestion`` (every engine from Phase 13
onward is read-only, computed live at request time) — the same Core-insert-per-write style as
``cfi.ingestion.repository`` is used (a new ``cfi.analyst.repository``), never one shared ORM
session, so a failed write never corrupts a wider transaction.

Downgrade refuses to run if any of this holds data (R10: never destroy production data).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS = "'queued','running','completed','failed'"
VALIDATION_STATUS = "'ok','failed'"
DATA_QUALITY_STATE = "'ok','degraded','insufficient'"

UPGRADE_SQL = f"""
CREATE TABLE ai.snapshot (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid              uuid NOT NULL UNIQUE,
    created_at        timestamptz NOT NULL,
    as_of             timestamptz NOT NULL,
    knowledge_time    timestamptz NOT NULL,
    snapshot_version  text NOT NULL,
    payload           jsonb NOT NULL,
    payload_hash      text NOT NULL
);
CREATE INDEX snapshot_payload_hash_idx ON ai.snapshot (payload_hash);

CREATE TABLE ai.interpretation (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid                uuid NOT NULL UNIQUE,
    created_at          timestamptz NOT NULL,
    updated_at          timestamptz NOT NULL,
    snapshot_id         bigint REFERENCES ai.snapshot (id),
    status              text NOT NULL CHECK (status IN ({STATUS})),
    question            text,
    prompt_version      text,
    model               text,
    response            jsonb,
    validation_status   text CHECK (validation_status IN ({VALIDATION_STATUS})),
    validation_errors    jsonb,
    attempt_count       integer NOT NULL DEFAULT 0,
    tools_called        jsonb,
    data_quality_state  text CHECK (data_quality_state IN ({DATA_QUALITY_STATE})),
    error               text,
    CONSTRAINT interpretation_completed_has_response
        CHECK (status <> 'completed' OR response IS NOT NULL),
    CONSTRAINT interpretation_failed_has_error
        CHECK (status <> 'failed' OR error IS NOT NULL)
);
CREATE INDEX interpretation_status_idx ON ai.interpretation (status, created_at);

CREATE TABLE ai.usage (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid               uuid NOT NULL UNIQUE,
    created_at         timestamptz NOT NULL,
    interpretation_id  bigint NOT NULL REFERENCES ai.interpretation (id),
    model              text NOT NULL,
    input_tokens       integer,
    output_tokens      integer,
    latency_ms         integer,
    cost_usd           numeric,
    attempt            integer NOT NULL CHECK (attempt >= 1)
);
CREATE INDEX usage_created_at_idx ON ai.usage (created_at);
"""

DATA_CHECKS = {
    "ai.snapshot": "SELECT EXISTS (SELECT 1 FROM ai.snapshot)",
    "ai.interpretation": "SELECT EXISTS (SELECT 1 FROM ai.interpretation)",
    "ai.usage": "SELECT EXISTS (SELECT 1 FROM ai.usage)",
}


def upgrade() -> None:
    for statement in UPGRADE_SQL.split(";\n"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    conn = op.get_bind()
    non_empty = [name for name, sql in DATA_CHECKS.items() if conn.execute(sa.text(sql)).scalar()]
    if non_empty:
        raise RuntimeError(
            "Refusing to downgrade: these tables contain data and would be destroyed: "
            + ", ".join(non_empty)
        )
    op.execute("DROP TABLE ai.usage")
    op.execute("DROP TABLE ai.interpretation")
    op.execute("DROP TABLE ai.snapshot")
