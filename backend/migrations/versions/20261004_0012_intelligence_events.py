"""Intelligence events: persistence for Phase 35 (Real-Time Intelligence).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04

Additive only (R10):

- sig.intelligence_event — one row per meaningful, deterministically-detected state transition
  (a regime change, an anomaly entering/leaving an extreme band, a new institutional/whale/retail/
  derivatives/liquidity/macro/market-structure score band, a divergence or possible capital
  rotation appearing/disappearing). Lives in ``sig`` ("L3 statistical signals and research
  results" — baseline migration 0001), already reserved for exactly this kind of derived-from-L2
  finding, rather than a new top-level schema (R13: reuse the existing layer, do not invent one).

  Every row is produced by the *same* evaluation cycle that already decides whether to create or
  re-arm a ``usr.alert_event`` (``cfi.alerts.service.AlertService.evaluate``, Phase 23, unchanged)
  — this table does not re-run or duplicate that detection; it records the cycle's own "create"/
  "rearm" decisions with the extra provenance (previous/current value, change magnitude,
  detection method) a downstream intelligence event needs that an alert row alone does not carry.

  ``alert_id`` is UNIQUE (nullable at the database level — a future event source might not have a
  companion alert — but always set today) rather than enforcing idempotency with an application-
  only check: the one alert row Phase 23's existing per-candidate loop creates for a given
  decision is itself the deterministic anchor, so ``INSERT ... ON CONFLICT (alert_id) DO NOTHING``
  is what makes "the same evaluation cycle processed twice" (a worker retry, two overlapping
  scheduled runs) produce at most one event per alert, with no new locking primitive invented
  (the Redis-based mutual-exclusion lock around the cycle itself, ``cfi.realtime.service``, is the
  first line of defense; this constraint is the second, at the only layer that can make the
  guarantee absolute). ``snapshot_id`` references ``ai.snapshot`` and ``ai_interpretation_id``
  references ``ai.interpretation`` (both nullable for the same FK-must-already-exist reason every
  other snapshot-referencing table in this codebase is nullable at the database level).

Downgrade refuses to run if ``sig.intelligence_event`` holds data (R10: never destroy production
data).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Reuses the exact severity vocabulary ``usr.alert_event`` already declares (migration 0009) —
# an intelligence event's severity is always copied from the alert candidate that produced it, so
# a second, parallel severity vocabulary would be a pure duplicate (R13).
SEVERITY = "'info','notable','elevated','critical'"
STATUS = "'new','ai_requested'"

UPGRADE_SQL = f"""
CREATE TABLE sig.intelligence_event (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid                uuid NOT NULL UNIQUE,
    created_at           timestamptz NOT NULL,
    observed_at          timestamptz NOT NULL,
    domain               text NOT NULL,
    event_type           text NOT NULL,
    severity             text NOT NULL CHECK (severity IN ({SEVERITY})),
    previous_value       text,
    current_value        text NOT NULL,
    change_magnitude     numeric,
    detection_method      text NOT NULL,
    data_quality_state   text NOT NULL,
    component_status     text NOT NULL,
    dedup_key            text NOT NULL,
    correlation_key      text NOT NULL,
    snapshot_id          bigint REFERENCES ai.snapshot (id),
    alert_id             bigint UNIQUE REFERENCES usr.alert_event (id),
    status               text NOT NULL CHECK (status IN ({STATUS})),
    ai_interpretation_id bigint REFERENCES ai.interpretation (id)
);
CREATE INDEX intelligence_event_domain_idx ON sig.intelligence_event (domain, created_at DESC);
CREATE INDEX intelligence_event_type_idx ON sig.intelligence_event (event_type, created_at DESC);
CREATE INDEX intelligence_event_severity_idx ON sig.intelligence_event (severity, created_at DESC);
CREATE INDEX intelligence_event_correlation_idx ON sig.intelligence_event (correlation_key);
"""

DATA_CHECKS = {"sig.intelligence_event": "SELECT EXISTS (SELECT 1 FROM sig.intelligence_event)"}


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
    op.execute("DROP TABLE sig.intelligence_event")
