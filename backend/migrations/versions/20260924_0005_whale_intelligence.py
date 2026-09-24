"""Whale intelligence: entity registry, address labels, large on-chain transfers.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-24

Additive only (R10):
- ref.entity              — real-world actors (exchanges, institutions, funds, market makers,
                            protocols, miners, governments, other known actors)
- ref.entity_label        — bitemporal address labels with evidence, source and confidence.
                            Database rules (R5): an inferred label can only say
                            "unknown large holder"; institution / fund / market maker labels need
                            direct or attributed evidence — never size alone.
- obs.large_transfer (HT) — large on-chain transfers (L1), one series per transfer, same
                            provenance columns and natural key as the other L1 tables
- ops.dataset.kind        — now also 'transfer'

Downgrade refuses to run if any of these hold data (R10: never destroy data).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUALITY = (
    "'ok','missing','stale','partial','estimated','revised',"
    "'suspect','conflicting','provider_error'"
)
PIT = "'native','vendor_pit','backfilled_latest'"
KNOWN = "'exchange','institution','fund','market_maker','protocol','miner','government','other'"
CLASSES = KNOWN + ",'unknown_large_holder'"

UPGRADE_SQL = f"""
ALTER TABLE ops.dataset DROP CONSTRAINT dataset_kind_check;
ALTER TABLE ops.dataset
    ADD CONSTRAINT dataset_kind_check CHECK (kind IN ('scalar', 'bar', 'flow', 'transfer'));

CREATE TABLE ref.entity (
    entity_id   text PRIMARY KEY,
    name        text NOT NULL,
    actor_class text NOT NULL CHECK (actor_class IN ({KNOWN})),
    description text,
    created_at  timestamptz NOT NULL
);

CREATE TABLE ref.entity_label (
    label_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chain          text NOT NULL CHECK (chain IN ('bitcoin', 'ethereum')),
    address        text NOT NULL,
    actor_class    text NOT NULL CHECK (actor_class IN ({CLASSES})),
    entity_id      text REFERENCES ref.entity (entity_id),
    evidence_class text NOT NULL CHECK (evidence_class IN ('direct', 'attributed', 'inferred')),
    confidence     numeric NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence       text NOT NULL CHECK (length(evidence) > 0),
    source         text NOT NULL CHECK (length(source) > 0),
    source_url     text,
    valid_from     timestamptz,
    valid_to       timestamptz,
    available_at   timestamptz NOT NULL,
    recorded_at    timestamptz NOT NULL,
    CONSTRAINT label_unique UNIQUE NULLS NOT DISTINCT (
        chain, address, actor_class, entity_id, source, available_at
    ),
    CONSTRAINT label_inferred_only_unknown CHECK (
        evidence_class <> 'inferred' OR actor_class = 'unknown_large_holder'
    ),
    CONSTRAINT label_known_needs_entity CHECK (
        (actor_class = 'unknown_large_holder') = (entity_id IS NULL)
    ),
    CONSTRAINT label_institution_never_inferred CHECK (
        actor_class NOT IN ('institution', 'fund', 'market_maker')
        OR evidence_class IN ('direct', 'attributed')
    ),
    CONSTRAINT label_valid_period CHECK (
        valid_to IS NULL OR valid_from IS NULL OR valid_from < valid_to
    )
);
CREATE INDEX entity_label_address_idx ON ref.entity_label (chain, address);

CREATE TABLE obs.large_transfer (
    series_id              bigint NOT NULL REFERENCES obs.series (series_id),
    event_time             timestamptz NOT NULL,
    available_at           timestamptz NOT NULL,
    available_at_estimated boolean NOT NULL,
    ingested_at            timestamptz NOT NULL,
    chain                  text NOT NULL CHECK (chain IN ('bitcoin', 'ethereum')),
    tx_hash                text NOT NULL,
    output_index           integer,
    block_height           bigint,
    sender                 text,
    recipient              text,
    value_native           numeric,
    value_usd              numeric,
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
    CONSTRAINT transfer_missing_means_null CHECK (
        (value_native IS NULL) = (quality_status = 'missing')
    ),
    CONSTRAINT transfer_non_ok_has_note CHECK (quality_status = 'ok' OR quality_note IS NOT NULL)
);
SELECT create_hypertable(
    'obs.large_transfer', 'event_time', chunk_time_interval => interval '30 days'
);
CREATE INDEX large_transfer_recipient_idx ON obs.large_transfer (chain, recipient, event_time);
CREATE INDEX large_transfer_sender_idx ON obs.large_transfer (chain, sender, event_time);
"""

DATA_CHECKS = {
    "ref.entity": "SELECT EXISTS (SELECT 1 FROM ref.entity)",
    "ref.entity_label": "SELECT EXISTS (SELECT 1 FROM ref.entity_label)",
    "obs.large_transfer": "SELECT EXISTS (SELECT 1 FROM obs.large_transfer)",
    "ops.dataset (kind = 'transfer')": (
        "SELECT EXISTS (SELECT 1 FROM ops.dataset WHERE kind = 'transfer')"
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
    op.execute("DROP TABLE obs.large_transfer")
    op.execute("DROP TABLE ref.entity_label")
    op.execute("DROP TABLE ref.entity")
    op.execute("ALTER TABLE ops.dataset DROP CONSTRAINT dataset_kind_check")
    op.execute(
        "ALTER TABLE ops.dataset"
        " ADD CONSTRAINT dataset_kind_check CHECK (kind IN ('scalar', 'bar', 'flow'))"
    )
