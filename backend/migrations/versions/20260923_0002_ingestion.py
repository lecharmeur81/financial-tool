"""Ingestion engine tables: registry, job runs, request log, payloads, series, observations, checks.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23

Tables (DATA_DICTIONARY.md §4):
- ops.provider, ops.dataset, ops.dataset_provider — provider/dataset registry
- ops.job_run                    — one row per ingestion run (ingestion log, failure tracking)
- ops.provider_request      (HT) — every HTTP attempt (provider health, rate limits, failures)
- ops.quality_check_result  (HT) — duplicate / missing / stale / conflict / rejection findings
- raw.payload               (HT) — index of archived provider responses (L0)
- obs.series                     — one row per observed series (what is measured)
- obs.observation           (HT) — canonical observations (L1), append-only, revisions as new rows

Downgrade refuses to run if any of these tables contains rows (R10: never destroy data).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUALITY = (
    "'ok','missing','stale','partial','estimated','revised',"
    "'suspect','conflicting','provider_error'"
)
PIT = "'native','vendor_pit','backfilled_latest'"
JOB_STATUS = "'running','succeeded','partial','failed'"
OUTCOMES = (
    "'success','timeout','connection_error','rate_limited','server_error',"
    "'auth_failed','client_error','circuit_open'"
)

TABLES_IN_DROP_ORDER = (
    "ops.quality_check_result",
    "obs.observation",
    "obs.series",
    "raw.payload",
    "ops.provider_request",
    "ops.job_run",
    "ops.dataset_provider",
    "ops.dataset",
    "ops.provider",
)

UPGRADE_SQL = f"""
CREATE TABLE ops.provider (
    provider_id     text PRIMARY KEY,
    display_name    text NOT NULL,
    base_url        text NOT NULL,
    auth_type       text NOT NULL,
    original_source text NOT NULL,
    terms_verified  boolean NOT NULL DEFAULT false,
    notes           text NOT NULL DEFAULT '',
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ops.dataset (
    dataset_id              text PRIMARY KEY,
    metric                  text NOT NULL,
    unit                    text NOT NULL,
    period                  text NOT NULL,
    availability_rule       jsonb NOT NULL,
    freshness_limit_seconds integer NOT NULL CHECK (freshness_limit_seconds > 0),
    conflict_tolerance      numeric NOT NULL CHECK (conflict_tolerance >= 0),
    revisable               boolean NOT NULL,
    expect_continuous       boolean NOT NULL,
    description             text NOT NULL DEFAULT '',
    updated_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ops.dataset_provider (
    dataset_id  text NOT NULL REFERENCES ops.dataset (dataset_id),
    provider_id text NOT NULL REFERENCES ops.provider (provider_id),
    priority    integer NOT NULL DEFAULT 100,
    enabled     boolean NOT NULL DEFAULT true,
    PRIMARY KEY (dataset_id, provider_id)
);

CREATE TABLE ops.job_run (
    job_run_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_type         text NOT NULL,
    dataset_id       text NOT NULL,
    provider_id      text NOT NULL,
    window_start     timestamptz NOT NULL,
    window_end       timestamptz NOT NULL,
    status           text NOT NULL CHECK (status IN ({JOB_STATUS})),
    started_at       timestamptz NOT NULL,
    finished_at      timestamptz,
    pages            integer NOT NULL DEFAULT 0,
    records_received integer NOT NULL DEFAULT 0,
    inserted         integer NOT NULL DEFAULT 0,
    duplicates       integer NOT NULL DEFAULT 0,
    revisions        integer NOT NULL DEFAULT 0,
    missing          integer NOT NULL DEFAULT 0,
    conflicts        integer NOT NULL DEFAULT 0,
    rejected         integer NOT NULL DEFAULT 0,
    stale            boolean,
    error_code       text,
    error_detail     text,
    code_version     text NOT NULL
);
CREATE INDEX job_run_provider_started_idx ON ops.job_run (provider_id, started_at DESC);

CREATE TABLE ops.provider_request (
    request_id   bigint GENERATED ALWAYS AS IDENTITY,
    provider_id  text NOT NULL,
    dataset_id   text,
    job_run_id   bigint,
    endpoint     text NOT NULL,
    attempt      integer NOT NULL,
    started_at   timestamptz NOT NULL,
    latency_ms   numeric NOT NULL,
    outcome      text NOT NULL CHECK (outcome IN ({OUTCOMES})),
    http_status  integer,
    error_class  text,
    PRIMARY KEY (request_id, started_at)
);
SELECT create_hypertable('ops.provider_request', 'started_at');
CREATE INDEX provider_request_provider_idx ON ops.provider_request (provider_id, started_at DESC);

CREATE TABLE raw.payload (
    payload_id     bigint GENERATED ALWAYS AS IDENTITY,
    provider_id    text NOT NULL,
    dataset_id     text NOT NULL,
    job_run_id     bigint,
    endpoint       text NOT NULL,
    request_params jsonb NOT NULL,
    http_status    integer NOT NULL,
    content_type   text NOT NULL,
    received_at    timestamptz NOT NULL,
    content_hash   text NOT NULL,
    archive_uri    text NOT NULL,
    bytes          integer NOT NULL,
    schema_ok      boolean,
    schema_error   text,
    PRIMARY KEY (payload_id, received_at)
);
SELECT create_hypertable('raw.payload', 'received_at');

CREATE TABLE obs.series (
    series_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_id   text NOT NULL REFERENCES ops.dataset (dataset_id),
    metric       text NOT NULL,
    asset        text,
    subject_ref  text NOT NULL,
    venue        text,
    period       text NOT NULL,
    unit         text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT series_identity UNIQUE NULLS NOT DISTINCT (dataset_id, subject_ref, venue, period)
);

CREATE TABLE obs.observation (
    series_id              bigint NOT NULL REFERENCES obs.series (series_id),
    event_time             timestamptz NOT NULL,
    available_at           timestamptz NOT NULL,
    available_at_estimated boolean NOT NULL,
    ingested_at            timestamptz NOT NULL,
    value                  numeric,
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
    CONSTRAINT missing_means_null CHECK ((value IS NULL) = (quality_status = 'missing')),
    CONSTRAINT non_ok_has_note CHECK (quality_status = 'ok' OR quality_note IS NOT NULL)
);
SELECT create_hypertable('obs.observation', 'event_time');
CREATE INDEX observation_available_idx ON obs.observation (series_id, available_at);

CREATE TABLE ops.quality_check_result (
    check_id     bigint GENERATED ALWAYS AS IDENTITY,
    dataset_id   text NOT NULL,
    series_id    bigint,
    provider_id  text,
    job_run_id   bigint,
    check_name   text NOT NULL,
    status       text NOT NULL,
    details      jsonb NOT NULL DEFAULT '{{}}',
    checked_at   timestamptz NOT NULL,
    PRIMARY KEY (check_id, checked_at)
);
SELECT create_hypertable('ops.quality_check_result', 'checked_at');
CREATE INDEX quality_check_dataset_idx ON ops.quality_check_result (dataset_id, checked_at DESC);
"""


def upgrade() -> None:
    for statement in UPGRADE_SQL.split(";\n"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    conn = op.get_bind()
    non_empty = [
        table
        for table in TABLES_IN_DROP_ORDER
        if conn.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()  # noqa: S608
    ]
    if non_empty:
        raise RuntimeError(
            "Refusing to downgrade: these tables contain data and would be destroyed: "
            + ", ".join(non_empty)
        )
    for table in TABLES_IN_DROP_ORDER:
        op.execute(f"DROP TABLE {table}")
