"""Baseline: TimescaleDB extension and one schema per layer.

Revision ID: 0001
Revises:
Create Date: 2026-09-23

Creates only the empty structure agreed in ARCHITECTURE.md §3 / §5.1:
ref · raw · obs · calc · sig · regime · ai · usr · ops.
Tables and database roles (ADR-0027) are added by later migrations.

Downgrade drops the schemas with RESTRICT, so it fails instead of deleting data if any schema
contains objects (R10). The extension is left installed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LAYER_SCHEMAS: dict[str, str] = {
    "ref": "Reference data (assets, venues, instruments, entity labels) — bitemporal",
    "raw": "L0 raw provider payload index",
    "obs": "L1 observed data",
    "calc": "L2 calculated metrics",
    "sig": "L3 statistical signals and research results",
    "regime": "L4 regime classifications",
    "ai": "L5 AI snapshots, interpretations, usage",
    "usr": "L6 user layer: accounts, journal, paper trading, alerts",
    "ops": "Operations: registry, jobs, quality, provider health, audit",
}


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    for schema, description in LAYER_SCHEMAS.items():
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        escaped = description.replace("'", "''")
        op.execute(f"COMMENT ON SCHEMA \"{schema}\" IS '{escaped}'")


def downgrade() -> None:
    for schema in reversed(LAYER_SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" RESTRICT')
