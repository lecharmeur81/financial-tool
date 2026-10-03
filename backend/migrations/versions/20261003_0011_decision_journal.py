"""Decision journal: persistence for Phase 25 (ADR-0036, ADR-0073).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-03

Additive only (R10):

- usr.decision_journal — one row per journaled decision, in the ``usr`` schema already created
  empty by the baseline migration (0001) and already named by ADR-0036 ("Decision journal and
  paper trading"). Implements the decision-journal half of that ADR (the paper-trading half was
  implemented in Phase 24, migration 0010); ADR-0073 documents this phase's own design choices.

  ``decision_snapshot_id`` references ``ai.snapshot`` (nullable at the database level only
  because that table's own FK target must already exist; the application never inserts a
  decision without one). ``market_brief_id`` references ``ai.brief`` and ``paper_trade_id``
  references ``usr.paper_trade`` — both nullable, both contextual references only
  ("Integration with Paper Trading" / "Integration with Alerts and Briefs": "These references
  provide context only").

  Every column the application treats as decision-time evidence (set once at creation, enforced
  in ``cfi.journal.service``, never by a database constraint — the same posture Phase 24 takes
  with its own entry fields) is deliberately NOT distinguished from the outcome columns at the
  schema level; the immutability is an application invariant, documented here and in
  ARCHITECTURE.md §7b, not a column-level trigger (R13: do not over-engineer a guarantee the
  application layer already provides).

Downgrade refuses to run if ``usr.decision_journal`` holds data (R10: never destroy production
data).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS = "'open','resolved','invalidated','cancelled'"

UPGRADE_SQL = f"""
CREATE TABLE usr.decision_journal (
    id                            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid                          uuid NOT NULL UNIQUE,
    created_at                    timestamptz NOT NULL,
    updated_at                    timestamptz NOT NULL,
    decision_time                 timestamptz NOT NULL,
    asset                         text NOT NULL,
    decision_type                 text NOT NULL,
    thesis                        text NOT NULL,
    expected_scenario             text,
    alternative_scenario          text,
    time_horizon                  text,
    entry_price                   numeric,
    observed_price_at_decision    numeric,
    invalidation_condition        text,
    key_risks                     text,
    confidence                    numeric,
    notes                         text,
    status                        text NOT NULL CHECK (status IN ({STATUS})),
    outcome                       text,
    thesis_supported              boolean,
    thesis_contradicted           boolean,
    invalidation_occurred         boolean,
    evidence_changed_notes        text,
    actual_market_movement_text   text,
    actual_price_at_outcome       numeric,
    actual_market_movement_pct    numeric,
    lessons_notes                 text,
    outcome_timestamp             timestamptz,
    decision_snapshot_id          bigint REFERENCES ai.snapshot (id),
    market_brief_id               bigint REFERENCES ai.brief (id),
    relevant_alert_ids            jsonb,
    market_regime_label           text,
    paper_trade_id                bigint REFERENCES usr.paper_trade (id)
);
CREATE INDEX decision_journal_status_idx ON usr.decision_journal (status, created_at DESC);
CREATE INDEX decision_journal_asset_idx ON usr.decision_journal (asset, created_at DESC);
"""

DATA_CHECKS = {"usr.decision_journal": "SELECT EXISTS (SELECT 1 FROM usr.decision_journal)"}


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
    op.execute("DROP TABLE usr.decision_journal")
