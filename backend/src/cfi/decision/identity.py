"""Snapshot identity for the Decision Context (Phase 38.3).

Four identifiers are kept **distinct** and are never equated or renamed into one another:

* ``ai.snapshot.id``  - the database row key (a bigint; the D-M ``snapshot_id``);
* ``ai.snapshot.uuid`` - the external-safe row reference;
* the **producer payload hash** - ``ai.snapshot.payload_hash`` as the Phase 21 snapshot builder
  computed it (a sha256 over ``snapshot_version``, ``as_of``, ``knowledge_time``, ``question`` and
  the raw ``tool_results``);
* the **decision input hash** - the Phase 38.2 hash over the whole payload the engine was handed
  (``cfi.decision.engine.snapshot_hash``; unchanged).

They are different functions over different content. The producer hash can be recomputed from the
stored payload (all five of its parts are inside it), which gives an integrity check; a failed or
impossible check is reported, never repaired. Pure: no database, network, clock or randomness.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from cfi.decision.engine import snapshot_hash as decision_input_hash

__all__ = [
    "SUPPORTED_SNAPSHOT_VERSIONS",
    "HashCheck",
    "SnapshotIdentity",
    "SnapshotRef",
    "build_identity",
    "decision_input_hash",
    "producer_payload_hash",
    "verify_producer_hash",
]

# Pinned from ``cfi.analyst.universe.SNAPSHOT_VERSION``. Not imported: the decision package stays
# independent of the analyst package. A test asserts the pin still equals the producer's value.
SUPPORTED_SNAPSHOT_VERSIONS: tuple[str, ...] = ("analyst_snapshot.v1",)


class HashCheck(StrEnum):
    VERIFIED = "verified"  # the recomputed producer hash equals the stored one
    MISMATCH = "mismatch"  # the recomputed producer hash differs from the stored one
    UNVERIFIED = "unverified"  # no stored hash was supplied, so nothing can be compared


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    """What the caller knows about the ``ai.snapshot`` row the payload came from. Every field is
    optional: an ad hoc payload (no row) is a legitimate input and is reported as such."""

    row_id: int | None = None
    uuid: str | None = None
    payload_hash: str | None = None  # ``ai.snapshot.payload_hash``, as stored
    created_at: datetime | None = None  # ``ai.snapshot.created_at``, as stored


@dataclass(frozen=True, slots=True)
class SnapshotIdentity:
    # -- database identity (supplied by the caller, never derived)
    row_id: int | None
    uuid: str | None
    row_created_at: str | None
    # -- the producer payload hash: as stored, and as recomputed from the payload
    producer_payload_hash_stored: str | None
    producer_payload_hash_recomputed: str
    producer_hash_check: HashCheck
    # -- the Phase 38.2 hash over the payload the engine received
    decision_input_hash: str
    # -- the payload's own provenance
    snapshot_version: str
    as_of: str
    knowledge_time: str


def producer_payload_hash(payload: dict[str, Any]) -> str:
    """Recompute the Phase 21 ``Snapshot.snapshot_id`` from a stored payload.

    Mirrors ``cfi.analyst.snapshot.build_snapshot`` exactly (same keys, ``sort_keys=True``,
    ``default=str``, default separators); a test pins the two together so drift is caught."""
    canonical = json.dumps(
        {
            "snapshot_version": payload.get("snapshot_version"),
            "as_of": payload.get("as_of"),
            "knowledge_time": payload.get("knowledge_time"),
            "question": payload.get("question"),
            "raw": payload.get("tool_results"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_producer_hash(payload: dict[str, Any], stored: str | None) -> HashCheck:
    if stored is None:
        return HashCheck.UNVERIFIED
    return HashCheck.VERIFIED if producer_payload_hash(payload) == stored else HashCheck.MISMATCH


def build_identity(payload: dict[str, Any], ref: SnapshotRef | None = None) -> SnapshotIdentity:
    ref = ref or SnapshotRef()
    return SnapshotIdentity(
        row_id=ref.row_id,
        uuid=ref.uuid,
        row_created_at=None if ref.created_at is None else ref.created_at.isoformat(),
        producer_payload_hash_stored=ref.payload_hash,
        producer_payload_hash_recomputed=producer_payload_hash(payload),
        producer_hash_check=verify_producer_hash(payload, ref.payload_hash),
        decision_input_hash=decision_input_hash(payload),
        snapshot_version=str(payload.get("snapshot_version")),
        as_of=str(payload.get("as_of")),
        knowledge_time=str(payload.get("knowledge_time")),
    )
