"""Alerts: persistence for Phase 23 (ADR-0035, ADR-0071).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03

Additive only (R10):

- usr.alert_event — one row per generated alert, in the ``usr`` schema already created empty by
  the baseline migration (0001, "L6 user layer: ... alerts") and already named ``usr.alert_event``
  by ADR-0035 ("Alert architecture") — this migration implements that pre-existing decision rather
  than introducing a new one. ``snapshot_id`` references ``ai.snapshot`` (nullable at the database
  level only because that table's own FK target must already exist; the application never inserts
  an alert without one — reproducibility, "Alerts must be reproducible from their underlying
  snapshot/data version"). ``superseded_by`` self-references ``usr.alert_event`` for the re-arm
  case (an "expired" alert that was replaced by a new one once its condition changed and the
  cooldown window had elapsed).

Downgrade refuses to run if ``usr.alert_event`` holds data (R10: never destroy production data).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEVERITY = "'info','notable','elevated','critical'"
STATUS = "'active','acknowledged','resolved','expired'"

UPGRADE_SQL = f"""
CREATE TABLE usr.alert_event (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid                uuid NOT NULL UNIQUE,
    created_at          timestamptz NOT NULL,
    updated_at          timestamptz NOT NULL,
    alert_type          text NOT NULL,
    severity            text NOT NULL CHECK (severity IN ({SEVERITY})),
    domain              text NOT NULL,
    dedup_key           text NOT NULL,
    trigger_condition   text NOT NULL,
    observed_value      text NOT NULL,
    reference_value     text,
    evidence_field_ids  jsonb NOT NULL,
    snapshot_id         bigint REFERENCES ai.snapshot (id),
    source_tool_id      text NOT NULL,
    component_status    text NOT NULL,
    data_quality_state  text NOT NULL,
    status              text NOT NULL CHECK (status IN ({STATUS})),
    superseded_by       bigint REFERENCES usr.alert_event (id),
    acknowledged_at     timestamptz,
    resolved_at         timestamptz
);
CREATE INDEX alert_event_dedup_key_idx ON usr.alert_event (dedup_key, created_at DESC);
CREATE INDEX alert_event_status_idx ON usr.alert_event (status, created_at DESC);
"""

DATA_CHECKS = {"usr.alert_event": "SELECT EXISTS (SELECT 1 FROM usr.alert_event)"}


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
    op.execute("DROP TABLE usr.alert_event")
