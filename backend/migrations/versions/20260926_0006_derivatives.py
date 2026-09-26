"""Derivatives: futures and options quotes (Deribit chain snapshots).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26

Additive only (R10):
- obs.derivative_quote (HT) — one row per instrument per snapshot: dated futures, perpetuals and
                              options (mark price, implied volatility, open interest, 24 h volume,
                              underlying and index prices). One series per instrument; same
                              provenance columns and natural key as the other L1 tables.
- ops.dataset.kind          — now also 'quote'

Open interest, funding, long/short ratios, liquidations and the volatility index are scalar series
in obs.observation (no schema change). Downgrade refuses to run if any of this holds data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUALITY = (
    "'ok','missing','stale','partial','estimated','revised',"
    "'suspect','conflicting','provider_error'"
)
PIT = "'native','vendor_pit','backfilled_latest'"

UPGRADE_SQL = f"""
ALTER TABLE ops.dataset DROP CONSTRAINT dataset_kind_check;
ALTER TABLE ops.dataset
    ADD CONSTRAINT dataset_kind_check
    CHECK (kind IN ('scalar', 'bar', 'flow', 'transfer', 'quote'));

CREATE TABLE obs.derivative_quote (
    series_id              bigint NOT NULL REFERENCES obs.series (series_id),
    event_time             timestamptz NOT NULL,
    available_at           timestamptz NOT NULL,
    available_at_estimated boolean NOT NULL,
    ingested_at            timestamptz NOT NULL,
    instrument             text NOT NULL,
    instrument_kind        text NOT NULL
                           CHECK (instrument_kind IN ('future', 'perpetual', 'option')),
    expiry                 timestamptz,
    strike                 numeric,
    option_type            text CHECK (option_type IN ('call', 'put')),
    mark_price             numeric,
    bid_price              numeric,
    ask_price              numeric,
    mark_iv                numeric,
    underlying_price       numeric,
    index_price            numeric,
    open_interest_native   numeric,
    open_interest_usd      numeric,
    volume_native          numeric,
    volume_usd             numeric,
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
    CONSTRAINT quote_missing_means_null CHECK (
        (mark_price IS NULL) = (quality_status = 'missing')
    ),
    CONSTRAINT quote_non_ok_has_note CHECK (quality_status = 'ok' OR quality_note IS NOT NULL),
    CONSTRAINT quote_option_fields CHECK (
        (instrument_kind = 'option')
        = (strike IS NOT NULL AND option_type IS NOT NULL)
    ),
    CONSTRAINT quote_expiry CHECK ((instrument_kind = 'perpetual') = (expiry IS NULL))
);
SELECT create_hypertable(
    'obs.derivative_quote', 'event_time', chunk_time_interval => interval '7 days'
);
CREATE INDEX derivative_quote_time_idx ON obs.derivative_quote (event_time);
"""

DATA_CHECKS = {
    "obs.derivative_quote": "SELECT EXISTS (SELECT 1 FROM obs.derivative_quote)",
    "ops.dataset (kind = 'quote')": (
        "SELECT EXISTS (SELECT 1 FROM ops.dataset WHERE kind = 'quote')"
    ),
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
    op.execute("DROP TABLE obs.derivative_quote")
    op.execute("ALTER TABLE ops.dataset DROP CONSTRAINT dataset_kind_check")
    op.execute(
        "ALTER TABLE ops.dataset ADD CONSTRAINT dataset_kind_check"
        " CHECK (kind IN ('scalar', 'bar', 'flow', 'transfer'))"
    )
