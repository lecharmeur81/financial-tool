"""Daily Market Brief: persistence for Phase 22, reusing Phase 21's AI audit infrastructure.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29

Additive only (R10):

- ai.brief — one row per generated Daily Market Brief, same queued -> running ->
  completed/failed job-record shape as ``ai.interpretation`` (Phase 21), plus the fields this
  phase's own spec asks for (Section 9): reporting period, a self-referential
  ``previous_brief_id`` (the brief that was its change-detection comparison basis, Section 5),
  and a ``changes`` jsonb column recording the computed change set itself (auditability — "what
  changed" must be reproducible after the fact, not just asserted in prose).

- ai.usage — additively widened, NOT replaced, so the brief's own Claude-call usage rows share
  the exact same table (and therefore the exact same, unmodified monthly-budget-ceiling query,
  ``AnalystRepository.monthly_cost_usd``) as the Phase 21 analyst's usage rows, rather than a
  second, parallel usage-logging table (Section 9: "reuse Phase 21 audit infrastructure where
  appropriate rather than creating duplicate logging systems"):
    * ``interpretation_id`` becomes nullable (it was ``NOT NULL``) — a brief-generated usage row
      has no interpretation.
    * a new nullable ``brief_id`` column, referencing ``ai.brief``.
    * a CHECK constraint requires exactly one of ``interpretation_id`` / ``brief_id`` to be set,
      so every usage row still has exactly one, unambiguous owner.

Downgrade refuses to run if ``ai.brief`` holds data, or if any ``ai.usage`` row already has
``brief_id`` set (R10: never destroy production data).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS = "'queued','running','completed','failed'"
VALIDATION_STATUS = "'ok','failed'"
DATA_QUALITY_STATE = "'ok','degraded','insufficient'"

UPGRADE_SQL = f"""
CREATE TABLE ai.brief (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid                    uuid NOT NULL UNIQUE,
    created_at              timestamptz NOT NULL,
    updated_at              timestamptz NOT NULL,
    reporting_period_start  timestamptz NOT NULL,
    reporting_period_end    timestamptz NOT NULL,
    snapshot_id             bigint REFERENCES ai.snapshot (id),
    previous_brief_id       bigint REFERENCES ai.brief (id),
    status                  text NOT NULL CHECK (status IN ({STATUS})),
    prompt_version          text,
    analyst_version         text,
    model                   text,
    response                jsonb,
    validation_status       text CHECK (validation_status IN ({VALIDATION_STATUS})),
    validation_errors       jsonb,
    attempt_count           integer NOT NULL DEFAULT 0,
    tools_called            jsonb,
    data_quality_state      text CHECK (data_quality_state IN ({DATA_QUALITY_STATE})),
    changes                 jsonb,
    error                   text,
    CONSTRAINT brief_completed_has_response
        CHECK (status <> 'completed' OR response IS NOT NULL),
    CONSTRAINT brief_failed_has_error
        CHECK (status <> 'failed' OR error IS NOT NULL),
    CONSTRAINT brief_reporting_period_order
        CHECK (reporting_period_end >= reporting_period_start)
);
CREATE INDEX brief_status_idx ON ai.brief (status, created_at);

ALTER TABLE ai.usage ALTER COLUMN interpretation_id DROP NOT NULL;
ALTER TABLE ai.usage ADD COLUMN brief_id bigint REFERENCES ai.brief (id);
ALTER TABLE ai.usage ADD CONSTRAINT usage_exactly_one_owner
    CHECK ((interpretation_id IS NOT NULL) <> (brief_id IS NOT NULL));
CREATE INDEX usage_brief_id_idx ON ai.usage (brief_id) WHERE brief_id IS NOT NULL;
"""

DATA_CHECKS = {
    "ai.brief": "SELECT EXISTS (SELECT 1 FROM ai.brief)",
    "ai.usage (brief_id set)": "SELECT EXISTS (SELECT 1 FROM ai.usage WHERE brief_id IS NOT NULL)",
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
            "Refusing to downgrade: these would be destroyed: " + ", ".join(non_empty)
        )
    op.execute("DROP INDEX ai.usage_brief_id_idx")
    op.execute("ALTER TABLE ai.usage DROP CONSTRAINT usage_exactly_one_owner")
    op.execute("ALTER TABLE ai.usage DROP COLUMN brief_id")
    op.execute("ALTER TABLE ai.usage ALTER COLUMN interpretation_id SET NOT NULL")
    op.execute("DROP TABLE ai.brief")
