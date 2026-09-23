"""Institutional capital: ETF flows and corporate treasury flows/holdings.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24

Additive only (R10):
- obs.institutional_flow (HT) — flows and holdings of identified institutional vehicles and
                                entities (L1): US spot ETFs (per fund and aggregated by the
                                provider) and listed-company treasuries. Same provenance columns
                                and natural key as obs.observation; append-only, revisions as
                                new rows.
- ops.dataset.kind            — now also 'flow' (constraint widened, no data changed)

Downgrade refuses to run if institutional data exists (R10: never destroy data).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUALITY = (
    "'ok','missing','stale','partial','estimated','revised',"
    "'suspect','conflicting','provider_error'"
)
PIT = "'native','vendor_pit','backfilled_latest'"
ENTITY_TYPES = "'etf_group','etf_fund','public_company','public_company_group'"

UPGRADE_SQL = f"""
ALTER TABLE ops.dataset DROP CONSTRAINT dataset_kind_check;
ALTER TABLE ops.dataset
    ADD CONSTRAINT dataset_kind_check CHECK (kind IN ('scalar', 'bar', 'flow'));

CREATE TABLE obs.institutional_flow (
    series_id              bigint NOT NULL REFERENCES obs.series (series_id),
    event_time             timestamptz NOT NULL,
    available_at           timestamptz NOT NULL,
    available_at_estimated boolean NOT NULL,
    ingested_at            timestamptz NOT NULL,
    entity_type            text NOT NULL CHECK (entity_type IN ({ENTITY_TYPES})),
    evidence_class         text NOT NULL CHECK (evidence_class IN ('direct', 'attributed')),
    entity_name            text,
    flow_usd               numeric,
    flow_native            numeric,
    holdings_usd           numeric,
    holdings_native        numeric,
    cum_flow_usd           numeric,
    value_traded_usd       numeric,
    premium_discount       numeric,
    unit_cost_usd          numeric,
    source_provider        text NOT NULL,
    original_source        text NOT NULL,
    raw_ref                bigint,
    revision               integer NOT NULL CHECK (revision >= 0),
    pit_reliability        text NOT NULL CHECK (pit_reliability IN ({PIT})),
    quality_status         text NOT NULL CHECK (quality_status IN ({QUALITY})),
    quality_note           text,
    confidence             numeric CHECK (confidence BETWEEN 0 AND 1),
    transformations        text[] NOT NULL DEFAULT '{{}}',
    PRIMARY KEY (series_id, event_time, source_provider, revision),
    CONSTRAINT flow_missing_means_null CHECK (
        (flow_usd IS NULL AND flow_native IS NULL AND holdings_usd IS NULL
         AND holdings_native IS NULL) = (quality_status = 'missing')
    ),
    CONSTRAINT flow_non_ok_has_note CHECK (quality_status = 'ok' OR quality_note IS NOT NULL)
);
SELECT create_hypertable(
    'obs.institutional_flow', 'event_time', chunk_time_interval => interval '180 days'
);
CREATE INDEX institutional_flow_available_idx
    ON obs.institutional_flow (series_id, available_at);
"""

DATA_CHECKS = {
    "obs.institutional_flow": "SELECT EXISTS (SELECT 1 FROM obs.institutional_flow)",
    "ops.dataset (kind = 'flow')": "SELECT EXISTS (SELECT 1 FROM ops.dataset WHERE kind = 'flow')",
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
    op.execute("DROP TABLE obs.institutional_flow")
    op.execute("ALTER TABLE ops.dataset DROP CONSTRAINT dataset_kind_check")
    op.execute(
        "ALTER TABLE ops.dataset"
        " ADD CONSTRAINT dataset_kind_check CHECK (kind IN ('scalar', 'bar'))"
    )
