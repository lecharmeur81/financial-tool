"""Market data: OHLCV bars, backfill checkpoints, per-subject job runs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23

Additive only (R10):
- obs.market_bar      (HT) — OHLCV bars (L1), same provenance columns and natural key as
                             obs.observation; append-only, revisions as new rows
- ops.backfill_state        — resumable history backfill checkpoint per dataset/provider/subject
- ops.dataset.kind          — record family stored for the dataset: 'scalar' or 'bar'
- ops.job_run.subject       — canonical subject (asset) the run covered, if scoped
- ops.job_run.skipped       — records not final yet (e.g. the unfinished current bar)
- ops.job_run.suspect       — records that failed a consistency check (kept, flagged)

Downgrade refuses to run if any of these hold data (R10: never destroy data).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUALITY = (
    "'ok','missing','stale','partial','estimated','revised',"
    "'suspect','conflicting','provider_error'"
)
PIT = "'native','vendor_pit','backfilled_latest'"

UPGRADE_SQL = f"""
ALTER TABLE ops.dataset
    ADD COLUMN kind text NOT NULL DEFAULT 'scalar' CHECK (kind IN ('scalar', 'bar'));

ALTER TABLE ops.job_run
    ADD COLUMN subject text,
    ADD COLUMN skipped integer NOT NULL DEFAULT 0,
    ADD COLUMN suspect integer NOT NULL DEFAULT 0;
ALTER TABLE ops.job_run
    ADD CONSTRAINT job_run_type CHECK (job_type IN ('ingest', 'backfill'));
CREATE INDEX job_run_dataset_subject_idx
    ON ops.job_run (dataset_id, provider_id, subject, started_at DESC);

CREATE TABLE obs.market_bar (
    series_id              bigint NOT NULL REFERENCES obs.series (series_id),
    event_time             timestamptz NOT NULL,
    available_at           timestamptz NOT NULL,
    available_at_estimated boolean NOT NULL,
    ingested_at            timestamptz NOT NULL,
    open                   numeric,
    high                   numeric,
    low                    numeric,
    close                  numeric,
    volume_base            numeric,
    volume_quote           numeric,
    trade_count            bigint,
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
    CONSTRAINT bar_prices_all_or_none CHECK (
        (open IS NULL AND high IS NULL AND low IS NULL AND close IS NULL)
        OR (open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL)
    ),
    CONSTRAINT bar_missing_means_null CHECK ((close IS NULL) = (quality_status = 'missing')),
    CONSTRAINT bar_missing_has_no_volume CHECK (
        close IS NOT NULL OR (volume_base IS NULL AND volume_quote IS NULL)
    ),
    CONSTRAINT bar_non_ok_has_note CHECK (quality_status = 'ok' OR quality_note IS NOT NULL)
);
SELECT create_hypertable('obs.market_bar', 'event_time', chunk_time_interval => interval '30 days');
CREATE INDEX market_bar_available_idx ON obs.market_bar (series_id, available_at);

CREATE TABLE ops.backfill_state (
    dataset_id   text NOT NULL,
    provider_id  text NOT NULL,
    subject      text NOT NULL,
    covered_from timestamptz NOT NULL,
    covered_to   timestamptz NOT NULL,
    target_start timestamptz NOT NULL,
    complete     boolean NOT NULL DEFAULT false,
    empty_chunks integer NOT NULL DEFAULT 0,
    note         text,
    updated_at   timestamptz NOT NULL,
    PRIMARY KEY (dataset_id, provider_id, subject),
    CHECK (covered_from <= covered_to)
);
"""

DATA_CHECKS = {
    "obs.market_bar": "SELECT EXISTS (SELECT 1 FROM obs.market_bar)",
    "ops.backfill_state": "SELECT EXISTS (SELECT 1 FROM ops.backfill_state)",
    "ops.dataset (kind = 'bar')": (
        "SELECT EXISTS (SELECT 1 FROM ops.dataset WHERE kind <> 'scalar')"
    ),
    "ops.job_run (subject / skipped / suspect)": (
        "SELECT EXISTS (SELECT 1 FROM ops.job_run"
        " WHERE subject IS NOT NULL OR skipped <> 0 OR suspect <> 0)"
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
    op.execute("DROP TABLE ops.backfill_state")
    op.execute("DROP TABLE obs.market_bar")
    op.execute("DROP INDEX ops.job_run_dataset_subject_idx")
    op.execute("ALTER TABLE ops.job_run DROP CONSTRAINT job_run_type")
    op.execute(
        "ALTER TABLE ops.job_run DROP COLUMN subject, DROP COLUMN skipped, DROP COLUMN suspect"
    )
    op.execute("ALTER TABLE ops.dataset DROP COLUMN kind")
