"""``unified_snapshot.v0`` (Phase 44; ADR-0081): one deterministic view of every evidence domain in
one stored snapshot payload.

Pure: no database, network, clock, provider or model. It adds no evidence and computes no score:
every status, freshness, quality flag, band, direction and freshness record is the Decision
Context's own (``cfi.decision.context``), copied unchanged. This module only *arranges* them:

* ``global_domains`` - evidence that does not depend on the asset (liquidity, macro, market
  structure, regime, retail, anomaly and the context readings). Each appears **once**; it is read
  from the BTC assessment, which is the benchmark scope the other scopes share (never copied per
  asset).
* ``assets`` - for each defined scope, only the asset-specific domains (institutional, whale where
  tracked, derivatives). A domain the scope does not track is named in ``not_tracked_domains``,
  never shown as neutral or negative.

Unavailable, insufficient, stale, partial, not-assessed and no-data stay distinct states
(``evidence_state``). Regime is a Context reading: ``independent_vote`` is false for it and for
every Risk and Context reading, so a later phase cannot count it as a confirmation vote. Nothing
here is a stance, a score or a recommendation."""

from __future__ import annotations

from collections import Counter
from typing import Any, Final

from cfi.decision.context import DecisionContext, build_decision_context
from cfi.decision.identity import SnapshotRef
from cfi.decision.read_service import _evidence_state
from cfi.decision.universe import SCOPE_DOMAINS, Role

__all__ = ["ASSET_DOMAINS", "BENCHMARK_SCOPE", "CONTRACT_VERSION", "build_unified_snapshot"]

CONTRACT_VERSION: Final = "unified_snapshot.v0"
BENCHMARK_SCOPE: Final = "BTC"
# Domains whose reading is looked up per asset by the evidence layer
# (``ASSET_SPECIFIC_DOMAINS`` plus the derivatives assets list). Every other domain is global.
ASSET_DOMAINS: Final = ("institutional", "whale", "derivatives")
# The asset-level domains each scope tracks: derivatives is read for every scope; institutional
# and whale follow ``SCOPE_DOMAINS`` (whale is not tracked for SOL / XRP).
_TRACKED: Final = {
    scope: {d for d in domains if d in ("institutional", "whale")} | {"derivatives"}
    for scope, domains in SCOPE_DOMAINS.items()
}


def _entry(ctx: DecisionContext, reading: Any) -> dict[str, Any]:
    flags = list(reading.quality_flags)
    status = str(reading.status)
    freshness = str(reading.freshness.value)
    return {
        "domain": reading.domain,
        "component": reading.component,
        "role": reading.role.value,
        # Only a Directional reading can ever be a vote; regime, risk and context never are.
        "independent_vote": reading.role is Role.DIRECTIONAL,
        "status": status,
        "freshness": freshness,
        "evidence_state": _evidence_state(status, freshness, flags),
        "insufficient_data": status != "ok",
        "quality_flags": flags,
        "direction": None if reading.direction is None else reading.direction.value,
        "strength": None if reading.strength is None else reading.strength.value,
        "band": reading.band,
        "source_ids": list(reading.source_ids),
        "field_ids": list(reading.field_ids),
        "freshness_records": [
            {
                "path": s.path,
                "status": s.status,
                "latest": s.latest,
                "expected_latest": s.expected_latest,
                "age_seconds": s.age_seconds,
                "rule": s.rule,
                "note": s.note,
                "after_knowledge_time": s.after_knowledge_time,
            }
            for s in ctx.source_freshness
            if s.domain == reading.domain
        ],
    }


def _entries(ctx: DecisionContext, *, asset_level: bool) -> list[dict[str, Any]]:
    return [
        _entry(ctx, r)
        for r in ctx.assessment.readings
        if (r.domain in ASSET_DOMAINS) is asset_level
    ]


def build_unified_snapshot(
    payload: dict[str, Any], *, snapshot_ref: SnapshotRef | None = None
) -> dict[str, Any]:
    """Build ``unified_snapshot.v0`` from a stored payload.

    Raises ``InvalidSnapshotError`` (a ``ValueError``) for a payload the context layer refuses
    (not a mapping, unsupported ``snapshot_version``, malformed times or ``tool_results``).
    Missing or unavailable *evidence* never raises: it is an explicit state."""
    contexts = {
        scope: build_decision_context(payload, scope, snapshot_ref=snapshot_ref)
        for scope in SCOPE_DOMAINS
    }
    benchmark = contexts[BENCHMARK_SCOPE]
    identity = benchmark.identity
    dq = benchmark.data_quality

    global_domains = _entries(benchmark, asset_level=False)
    assets: dict[str, Any] = {}
    for scope, ctx in contexts.items():
        assets[scope] = {
            "domains": _entries(ctx, asset_level=True),
            "not_tracked_domains": sorted(set(ASSET_DOMAINS) - _TRACKED[scope]),
        }

    everything = [*global_domains, *(e for a in assets.values() for e in a["domains"])]
    states = Counter(e["evidence_state"] for e in everything)
    look_ahead = sorted(
        {v for c in contexts.values() for v in c.data_quality.look_ahead_violations}
    )

    return {
        "contract_version": CONTRACT_VERSION,
        "snapshot": {
            "row_id": identity.row_id,
            "uuid": identity.uuid,
            "row_created_at": identity.row_created_at,
            "as_of": identity.as_of,
            "knowledge_time": identity.knowledge_time,
            "snapshot_version": identity.snapshot_version,
            "producer_payload_hash": identity.producer_payload_hash_stored,
            "producer_hash_check": identity.producer_hash_check.value,
            "decision_input_hash": identity.decision_input_hash,
            "snapshot_data_quality_state": dq.snapshot_state,
            "source_conflicts": dq.source_conflicts,
        },
        "global_domains": global_domains,
        "assets": assets,
        "coverage": {
            "entries": len(everything),
            "available": sum(1 for e in everything if not e["insufficient_data"]),
            "insufficient": sum(1 for e in everything if e["insufficient_data"]),
            "by_evidence_state": dict(sorted(states.items())),
        },
        "data_quality": {
            "unavailable_tools": list(dq.unavailable_tools),
            "degraded_tools": list(dq.degraded_tools),
            "conflicting_tools": list(dq.conflicting_tools),
            "look_ahead_violations": look_ahead,
            "platform_limits": list(dq.not_tracked),
        },
    }
