"""Address labels in the database (``ref.entity``, ``ref.entity_label``).

Labels are append-only: importing a file never changes or deletes a stored label (a correction is
a new label with a later ``available_at``; an ended one gets a new label with ``valid_to``). An
entity id that already exists with a different name or class stops the import — it is never
overwritten silently.

Command line (inside the backend container)::

    python -m cfi.whales.label_store import <file.csv>
    python -m cfi.whales.label_store check <file.csv>     # validate only

The label files shipped with the code (``cfi/whales/seed_labels``) are imported by the worker at
start (idempotent: labels already stored are counted, not duplicated).
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.time import utc_now
from cfi.db import tables as t
from cfi.domain.enums import EvidenceClass
from cfi.whales.labels import Entity, Label, LabelError, LabelFile, parse_label_csv

SEED_FILES: tuple[str, ...] = ("labels_bitinfocharts_btc_2026-09-24.csv",)


@dataclass(frozen=True, slots=True)
class ImportResult:
    entities_added: int
    entities_existing: int
    labels_added: int
    labels_existing: int


def seed_text(name: str) -> str:
    return (resources.files("cfi.whales") / "seed_labels" / name).read_text(encoding="utf-8")


async def import_labels(
    engine: AsyncEngine, label_file: LabelFile, recorded_at: datetime
) -> ImportResult:
    """Insert entities and labels that are not stored yet, in one transaction."""
    ent_added = ent_existing = added = existing = 0
    async with engine.begin() as conn:
        ids = list(label_file.entities)
        stored = {
            r.entity_id: r
            for r in (
                await conn.execute(select(t.entity).where(t.entity.c.entity_id.in_(ids)))
            ).all()
        }
        for entity in label_file.entities.values():
            row = stored.get(entity.entity_id)
            if row is None:
                await conn.execute(
                    insert(t.entity).values(
                        entity_id=entity.entity_id,
                        name=entity.name,
                        actor_class=entity.actor_class,
                        description=entity.description,
                        created_at=recorded_at,
                    )
                )
                ent_added += 1
            elif (row.name, row.actor_class) != (entity.name, entity.actor_class):
                raise LabelError(
                    f"entity {entity.entity_id!r} is stored as {row.name!r} ({row.actor_class}); "
                    f"the file says {entity.name!r} ({entity.actor_class}). Use a new entity id "
                    "or correct the file — stored entities are not overwritten."
                )
            else:
                ent_existing += 1
        for label in label_file.labels:
            stmt = (
                insert(t.entity_label)
                .values(
                    chain=label.chain,
                    address=label.address,
                    actor_class=label.actor_class,
                    entity_id=label.entity_id,
                    evidence_class=str(label.evidence_class),
                    confidence=label.confidence,
                    evidence=label.evidence,
                    source=label.source,
                    source_url=label.source_url,
                    valid_from=label.valid_from,
                    valid_to=label.valid_to,
                    available_at=label.available_at,
                    recorded_at=recorded_at,
                )
                .on_conflict_do_nothing(constraint="label_unique")
                .returning(t.entity_label.c.label_id)
            )
            # rowcount is not reliable for ON CONFLICT DO NOTHING; a returned id means inserted
            if (await conn.execute(stmt)).first() is not None:
                added += 1
            else:
                existing += 1
    return ImportResult(ent_added, ent_existing, added, existing)


async def import_seed_files(engine: AsyncEngine, recorded_at: datetime) -> list[ImportResult]:
    return [
        await import_labels(engine, parse_label_csv(seed_text(name)), recorded_at)
        for name in SEED_FILES
    ]


def _label(row: Any) -> Label:
    return Label(
        chain=row.chain,
        address=row.address,
        actor_class=row.actor_class,
        entity_id=row.entity_id,
        evidence_class=EvidenceClass(row.evidence_class),
        confidence=row.confidence,
        evidence=row.evidence,
        source=row.source,
        source_url=row.source_url,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        available_at=row.available_at,
        recorded_at=row.recorded_at,
        label_id=row.label_id,
    )


async def load_labels(
    engine: AsyncEngine, chain: str | None = None, addresses: list[str] | None = None
) -> list[Label]:
    """Every stored label (optionally for one chain / some addresses); callers apply the
    point-in-time rules (:meth:`Label.counts`)."""
    stmt = select(t.entity_label).order_by(t.entity_label.c.label_id)
    if chain is not None:
        stmt = stmt.where(t.entity_label.c.chain == chain)
    if addresses is not None:
        stmt = stmt.where(t.entity_label.c.address.in_(addresses))
    async with engine.connect() as conn:
        rows = (await conn.execute(stmt)).all()
    return [_label(r) for r in rows]


async def load_entities(engine: AsyncEngine) -> dict[str, Entity]:
    async with engine.connect() as conn:
        rows = (await conn.execute(select(t.entity))).all()
    return {r.entity_id: Entity(r.entity_id, r.name, r.actor_class, r.description) for r in rows}


def main(argv: list[str]) -> int:  # pragma: no cover — thin command-line wrapper
    if len(argv) != 2 or argv[0] not in ("import", "check"):
        print(__doc__)
        return 2
    try:
        label_file = parse_label_csv(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, LabelError) as exc:
        print(f"rejected: {exc}")
        return 1
    print(f"valid: {len(label_file.entities)} entities, {len(label_file.labels)} labels")
    if argv[0] == "check":
        return 0
    from cfi.core.config import get_settings
    from cfi.db.engine import create_engine

    async def go() -> ImportResult:
        engine = create_engine(get_settings())
        try:
            return await import_labels(engine, label_file, utc_now())
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(go())
    except LabelError as exc:
        print(f"rejected: {exc}")
        return 1
    print(
        f"imported: {result.entities_added} new entities ({result.entities_existing} existing), "
        f"{result.labels_added} new labels ({result.labels_existing} already stored)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
