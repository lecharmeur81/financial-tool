"""Paper trading: persistence for Phase 24 (ADR-0036, ADR-0072).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-03

Additive only (R10):

- usr.paper_trade — one row per simulated trade, in the ``usr`` schema already created empty by
  the baseline migration (0001) and already named by ADR-0036 ("Decision journal and paper
  trading"). A single consolidated table rather than the four-table account/order/fill/position
  sketch in that ADR's original planning notes (ADR-0072 documents this deviation, same precedent
  as Phase 23's deliberate omission of a separate ``alert_rule`` table): the Phase 24 spec's own
  "Core paper-trading record" asks for one flat record per trade carrying both entry and exit
  fields together, not a multi-table order-matching model this platform has no exchange
  connection to need.

  ``decision_snapshot_id`` references ``ai.snapshot`` (nullable at the database level only
  because that table's own FK target must already exist; the application never inserts a trade
  without one). ``market_brief_id`` references ``ai.brief`` (nullable — no completed brief may
  exist yet at decision time). Both are contextual evidence only, never a decision made for the
  user ("Integration with existing intelligence": "Do not automatically convert an alert or
  analyst interpretation into a trade").

Downgrade refuses to run if ``usr.paper_trade`` holds data (R10: never destroy production data).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIRECTION = "'long','short'"
STATUS = "'open','closed','cancelled'"

UPGRADE_SQL = f"""
CREATE TABLE usr.paper_trade (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid                    uuid NOT NULL UNIQUE,
    created_at              timestamptz NOT NULL,
    updated_at              timestamptz NOT NULL,
    asset                   text NOT NULL,
    direction               text NOT NULL CHECK (direction IN ({DIRECTION})),
    status                  text NOT NULL CHECK (status IN ({STATUS})),
    entry_time              timestamptz NOT NULL,
    entry_price_observed    numeric NOT NULL,
    entry_price_execution   numeric NOT NULL,
    entry_price_source      text NOT NULL,
    notional                numeric NOT NULL CHECK (notional > 0),
    leverage                numeric NOT NULL CHECK (leverage > 0),
    margin                  numeric NOT NULL,
    stop_loss               numeric,
    take_profit             numeric,
    exit_time               timestamptz,
    exit_price_observed     numeric,
    exit_price_execution    numeric,
    exit_price_source       text,
    cost_model_version      text NOT NULL,
    gross_pnl               numeric,
    slippage_cost           numeric,
    fees_total              numeric,
    realized_pnl            numeric,
    return_pct              numeric,
    max_favorable_move_pct  numeric,
    max_adverse_move_pct    numeric,
    strategy_tag            text,
    notes                   text,
    decision_snapshot_id    bigint REFERENCES ai.snapshot (id),
    market_brief_id         bigint REFERENCES ai.brief (id),
    relevant_alert_ids      jsonb
);
CREATE INDEX paper_trade_status_idx ON usr.paper_trade (status, created_at DESC);
CREATE INDEX paper_trade_asset_idx ON usr.paper_trade (asset, created_at DESC);
"""

DATA_CHECKS = {"usr.paper_trade": "SELECT EXISTS (SELECT 1 FROM usr.paper_trade)"}


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
    op.execute("DROP TABLE usr.paper_trade")
