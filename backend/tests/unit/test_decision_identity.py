"""Phase 38.3 snapshot identity: four distinct identifiers, a recomputable producer hash, and the
decision-input hash (Phase 38.2, unchanged) staying stable across the stored-JSON round trip.

These tests run on a payload produced by the real ``build_snapshot`` with canned tool results; they
do not touch a database (the PostgreSQL JSONB round trip is in ``tests/integration``).
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cfi.analyst.universe import SNAPSHOT_VERSION
from cfi.core.config import Settings
from cfi.decision import identity
from cfi.decision.engine import snapshot_hash
from cfi.decision.identity import (
    SUPPORTED_SNAPSHOT_VERSIONS,
    HashCheck,
    SnapshotRef,
    build_identity,
    decision_input_hash,
    producer_payload_hash,
    verify_producer_hash,
)
from tests.decision_snapshots import build_real_snapshot, stored_form

CODES = ["S2", "S1", "N", "S1", "S2"]
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def test_supported_snapshot_version_matches_the_producer() -> None:
    assert SUPPORTED_SNAPSHOT_VERSIONS == (SNAPSHOT_VERSION,)


async def test_producer_hash_recomputes_the_phase21_snapshot_id(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    snap = await build_real_snapshot(monkeypatch, settings, CODES, question="What changed?")
    live = snap.payload()
    assert producer_payload_hash(live) == snap.snapshot_id
    # ... and from the payload as the database holds it (strings instead of date/Decimal objects).
    assert producer_payload_hash(stored_form(live)) == snap.snapshot_id


async def test_decision_input_hash_is_stable_across_the_stored_json_round_trip(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    snap = await build_real_snapshot(monkeypatch, settings, CODES)
    live = snap.payload()
    stored = stored_form(live)
    assert decision_input_hash(live) == decision_input_hash(stored)
    assert decision_input_hash(stored) == decision_input_hash(stored_form(stored))
    assert decision_input_hash is snapshot_hash  # the Phase 38.2 function, not a re-implementation


async def test_the_four_identifiers_are_distinct_and_never_equated(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    snap = await build_real_snapshot(monkeypatch, settings, CODES)
    payload = stored_form(snap.payload())
    ref = SnapshotRef(
        row_id=4242,
        uuid="0b9c9a6e-6f0c-4a5e-9d57-1f6f3f3a9a11",
        payload_hash=snap.snapshot_id,
        created_at=datetime(2026, 10, 5, 12, 6, tzinfo=UTC),
    )
    ident = build_identity(payload, ref)
    assert ident.row_id == 4242
    assert ident.uuid == "0b9c9a6e-6f0c-4a5e-9d57-1f6f3f3a9a11"
    assert ident.row_created_at == "2026-10-05T12:06:00+00:00"
    assert ident.producer_payload_hash_stored == snap.snapshot_id
    assert ident.producer_payload_hash_recomputed == snap.snapshot_id
    assert ident.producer_hash_check is HashCheck.VERIFIED
    assert SHA256.match(ident.decision_input_hash)
    # Different functions over different content: the two hashes are not the same value.
    assert ident.decision_input_hash != ident.producer_payload_hash_recomputed
    assert str(ident.row_id) not in (ident.uuid, ident.decision_input_hash)


async def test_producer_and_decision_hashes_respond_to_different_content(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """Only the decision hash covers ``fields`` (the producer hash covers raw tool_results, the
    question and the two timestamps) - so one can change while the other does not."""
    snap = await build_real_snapshot(monkeypatch, settings, CODES)
    base = stored_form(snap.payload())
    edited = stored_form(snap.payload())
    edited["fields"]["get_market_data.assets[0].asset"]["display"] = "EDITED"
    assert producer_payload_hash(edited) == producer_payload_hash(base)
    assert decision_input_hash(edited) != decision_input_hash(base)
    edited_raw = stored_form(snap.payload())
    edited_raw["question"] = "a different question"
    assert producer_payload_hash(edited_raw) != producer_payload_hash(base)


async def test_hash_check_reports_verified_mismatch_and_unverified(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    snap = await build_real_snapshot(monkeypatch, settings, CODES)
    payload = stored_form(snap.payload())
    assert verify_producer_hash(payload, snap.snapshot_id) is HashCheck.VERIFIED
    assert verify_producer_hash(payload, "0" * 64) is HashCheck.MISMATCH
    assert verify_producer_hash(payload, None) is HashCheck.UNVERIFIED
    tampered = stored_form(snap.payload())
    tampered["tool_results"]["get_market_regime"]["data"]["regime_id"] = "contraction"
    assert verify_producer_hash(tampered, snap.snapshot_id) is HashCheck.MISMATCH


async def test_an_ad_hoc_payload_has_no_database_identity(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    snap = await build_real_snapshot(monkeypatch, settings, CODES)
    ident = build_identity(stored_form(snap.payload()))
    assert (ident.row_id, ident.uuid, ident.row_created_at) == (None, None, None)
    assert ident.producer_payload_hash_stored is None
    assert ident.producer_hash_check is HashCheck.UNVERIFIED
    assert ident.snapshot_version == SNAPSHOT_VERSION


def test_identity_module_is_pure() -> None:
    tree = ast.parse(Path(identity.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    allowed = {
        "__future__",
        "hashlib",
        "json",
        "dataclasses",
        "datetime",
        "enum",
        "typing",
        "cfi.decision.engine",
    }
    assert imported <= allowed, imported - allowed
