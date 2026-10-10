"""``opportunity_discovery.v0`` (Phase 46; ADR-0083): which assets merit further research?

A pure, deterministic function of two existing contracts, ``unified_snapshot.v0`` (Phase 44) and
``cross_domain_confirmation.v0`` (Phase 45). No database, network, clock, provider or model, no
new evidence, no score, ranking, risk assessment, decision or recommendation. Assets are listed in
the fixed ``SCOPE_DOMAINS`` order, never by merit.

Input consistency (refused with ``OpportunityInputError`` otherwise): both inputs must be the
supported contract versions and describe the *same* snapshot (identical identity block). A
confirmation from one snapshot is never combined with evidence from another.

Outcome per asset, from the Phase 45 ``agreement`` (first match; nothing is recomputed):

* ``confirmed_supportive`` -> ``candidate`` only if the supporting members are eligible with
  verified freshness and at least one distinct asset-specific family supports it; otherwise
  ``no_candidate`` with the reason. The type is ``asset_led_confirmation`` (two or more
  asset-specific families) or ``market_aligned_confirmation``.
* ``mixed`` -> ``conflicting_evidence``; ``insufficient_evidence`` -> ``insufficient_evidence``;
  ``unconfirmed`` -> ``no_candidate``; ``confirmed_adverse`` -> ``no_candidate`` with type
  ``adverse_confirmation`` (a review outcome, never an opportunity).
* Engine-wide gates: any look-ahead violation or a producer-hash ``mismatch`` turns every would-be
  candidate into ``blocked``, with the reason codes; other outcomes are unchanged.

Risk and Context entries are passed through unchanged for display (``used_for_discovery`` is
false); they never influence the outcome."""

from __future__ import annotations

from typing import Any, Final

from cfi.decision.universe import SCOPE_DOMAINS
from cfi.intelligence.confirmation import CONTRACT_VERSION as CONFIRMATION_CONTRACT_VERSION
from cfi.intelligence.confirmation import _freshness_verified
from cfi.intelligence.opportunity_universe import (
    AGREEMENTS,
    DISCOVERY_TYPES,
    DISCOVERY_TYPES_VERSION,
    LIMITATIONS,
    NOTICE,
    OPPORTUNITY_PARAMS_V0,
    SUPPORTED_CONFIRMATION_FAMILIES_VERSION,
    SUPPORTED_CONFIRMATION_PARAMS_VERSION,
    OpportunityParameters,
)
from cfi.intelligence.unified_snapshot import CONTRACT_VERSION as UNIFIED_CONTRACT_VERSION

__all__ = ["CONTRACT_VERSION", "OpportunityInputError", "build_opportunities"]

CONTRACT_VERSION: Final = "opportunity_discovery.v0"
_REF_KEYS: Final = (
    "family",
    "domain",
    "component",
    "scope_basis",
    "shared_across_assets",
    "state",
    "direction",
    "strength",
    "freshness",
    "evidence_state",
    "quality_flags",
    "source_ids",
    "field_ids",
    "freshness_records",
)
_CONTEXT_KEYS: Final = (
    "domain",
    "component",
    "role",
    "status",
    "freshness",
    "evidence_state",
    "quality_flags",
    "band",
    "source_ids",
    "field_ids",
    "freshness_records",
)


class OpportunityInputError(ValueError):
    """The inputs are unsupported, inconsistent with each other, or malformed."""


def _need(cond: bool, message: str) -> None:
    if not cond:
        raise OpportunityInputError(message)


def _validate(unified: object, confirmation: object) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(unified, dict) or not isinstance(confirmation, dict):
        raise OpportunityInputError("both inputs must be mappings")
    _need(
        unified.get("contract_version") == UNIFIED_CONTRACT_VERSION,
        f"unified input must be {UNIFIED_CONTRACT_VERSION!r}",
    )
    _need(
        confirmation.get("contract_version") == CONFIRMATION_CONTRACT_VERSION,
        f"confirmation input must be {CONFIRMATION_CONTRACT_VERSION!r}",
    )
    _need(
        confirmation.get("source_contract") == UNIFIED_CONTRACT_VERSION,
        "confirmation was not derived from the supported unified contract",
    )
    params = confirmation.get("parameters")
    if not isinstance(params, dict):
        raise OpportunityInputError("confirmation 'parameters' must be a mapping")
    _need(
        params.get("version") == SUPPORTED_CONFIRMATION_PARAMS_VERSION
        and params.get("families_version") == SUPPORTED_CONFIRMATION_FAMILIES_VERSION,
        "unsupported confirmation parameter or family versions",
    )
    snap_u, snap_c = unified.get("snapshot"), confirmation.get("snapshot")
    if not isinstance(snap_u, dict) or not isinstance(snap_c, dict):
        raise OpportunityInputError("'snapshot' must be a mapping")
    if snap_u != snap_c:
        differing = sorted(k for k in set(snap_u) | set(snap_c) if snap_u.get(k) != snap_c.get(k))
        raise OpportunityInputError(
            "unified snapshot and confirmation describe different snapshots "
            f"(differing identity fields: {', '.join(differing)})"
        )
    _need(isinstance(unified.get("data_quality"), dict), "'data_quality' must be a mapping")
    _need(isinstance(unified.get("global_domains"), list), "'global_domains' must be a list")
    u_assets, c_assets = unified.get("assets"), confirmation.get("assets")
    if not isinstance(u_assets, dict) or not isinstance(c_assets, dict):
        raise OpportunityInputError("'assets' must be a mapping")
    for scope in SCOPE_DOMAINS:
        ua, ca = u_assets.get(scope), c_assets.get(scope)
        _need(isinstance(ua, dict) and isinstance(ua.get("domains"), list), f"unified {scope}")
        if not isinstance(ca, dict):
            raise OpportunityInputError(f"confirmation assets.{scope} must be a mapping")
        _need(ca.get("agreement") in AGREEMENTS, f"{scope}: unknown agreement")
        _need(isinstance(ca.get("reasons"), list), f"{scope}: 'reasons' must be a list")
        _need(isinstance(ca.get("members"), list), f"{scope}: 'members' must be a list")
        _need(isinstance(ca.get("key_layer"), dict), f"{scope}: 'key_layer' must be a mapping")
        _need(isinstance(ca.get("coverage"), dict), f"{scope}: 'coverage' must be a mapping")
        for key in ("supportive_families", "adverse_families"):
            _need(isinstance(ca.get(key), list), f"{scope}: {key!r} must be a list")
        for m in ca["members"]:
            _need(isinstance(m, dict), f"{scope}: every member must be a mapping")
            for key in ("domain", "state", "eligible", "shared_across_assets", "family"):
                _need(key in m, f"{scope}: member is missing {key!r}")
    return unified, confirmation


def _pick(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: source.get(k) for k in keys}


def _supporting(block: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in block["members"] if m["eligible"] is True and m["state"] == "supportive"]


def _context(unified: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    entries = [*unified["global_domains"], *unified["assets"][scope]["domains"]]
    return [_pick(e, _CONTEXT_KEYS) for e in entries if e.get("independent_vote") is False]


def _classify(
    block: dict[str, Any], params: OpportunityParameters
) -> tuple[str, str | None, list[str]]:
    """(status, discovery_type, reasons) from the Phase 45 result alone, before the gates."""
    agreement = block["agreement"]
    if agreement == "mixed":
        return "conflicting_evidence", None, ["OD-CONFLICT"]
    if agreement == "insufficient_evidence":
        return "insufficient_evidence", None, ["OD-INSUFFICIENT"]
    if agreement == "unconfirmed":
        return "no_candidate", None, ["OD-UNCONFIRMED"]
    if agreement == "confirmed_adverse":
        return "no_candidate", "adverse_confirmation", ["OD-ADVERSE-CONFIRMATION"]

    support = _supporting(block)
    families = sorted({m["family"] for m in support})
    _need(
        families == sorted(block["supportive_families"]) and not block["adverse_families"],
        "confirmation is internally inconsistent: its members do not match its families",
    )
    if not all(
        m["exclusion_reason"] is None and _freshness_verified(m.get("freshness_records"))
        for m in support
    ):
        return "no_candidate", None, ["OD-UNVERIFIED-SUPPORT"]
    asset_specific = {m["family"] for m in support if m["shared_across_assets"] is False}
    if (
        len(asset_specific) < params.min_asset_specific_confirmers
        or block["key_layer"].get("supportive") is not True
    ):
        return "no_candidate", None, ["OD-NO-ASSET-SPECIFIC-CONFIRMER"]
    kind = (
        "asset_led_confirmation"
        if len(asset_specific) >= params.asset_led_min_asset_specific
        else "market_aligned_confirmation"
    )
    return "candidate", kind, ["OD-CANDIDATE"]


def build_opportunities(
    unified: dict[str, Any],
    confirmation: dict[str, Any],
    *,
    params: OpportunityParameters = OPPORTUNITY_PARAMS_V0,
) -> dict[str, Any]:
    """Build ``opportunity_discovery.v0`` from the two contracts of one snapshot.

    Raises ``OpportunityInputError`` (a ``ValueError``) for unsupported, mismatched or malformed
    inputs. Missing or unverified *evidence* never raises: it is an explicit outcome."""
    unified, confirmation = _validate(unified, confirmation)
    snapshot = dict(unified["snapshot"])
    violations = list(unified["data_quality"].get("look_ahead_violations") or [])
    hash_check = snapshot.get("producer_hash_check")
    gate_reasons: list[str] = []
    if violations:
        gate_reasons.append("OD-LOOK-AHEAD-VIOLATION")
    if hash_check == "mismatch":
        gate_reasons.append("OD-SNAPSHOT-INTEGRITY")

    assets: dict[str, Any] = {}
    expected_sets: dict[str, tuple[str, ...]] = {}
    for scope in SCOPE_DOMAINS:
        block = confirmation["assets"][scope]
        status, kind, reasons = _classify(block, params)
        if status == "candidate" and gate_reasons:
            status, kind, reasons = "blocked", None, list(gate_reasons)
        elif gate_reasons:
            reasons = [*reasons, *gate_reasons]
        members = block["members"]
        expected_sets[scope] = tuple(m["domain"] for m in members if m["state"] != "not_tracked")
        assets[scope] = {
            "status": status,
            "discovery_type": kind,
            "reasons": reasons,
            "notes": [],
            "basis": {
                "confirmation_agreement": block["agreement"],
                "confirmation_reasons": list(block["reasons"]),
                "supportive_families": list(block["supportive_families"]),
                "adverse_families": list(block["adverse_families"]),
                "asset_specific_supporting_families": sorted(
                    {m["family"] for m in _supporting(block) if m["shared_across_assets"] is False}
                ),
                "market_wide_supporting_families": sorted(
                    {m["family"] for m in _supporting(block) if m["shared_across_assets"] is True}
                ),
                "key_layer": dict(block["key_layer"]),
                "coverage": dict(block["coverage"]),
            },
            "evidence_refs": [_pick(m, _REF_KEYS) for m in members if m["eligible"] is True],
            "excluded_members": [
                {**_pick(m, _REF_KEYS), "exclusion_reason": m.get("exclusion_reason")}
                for m in members
                if m["eligible"] is not True
            ],
            "context": {
                "used_for_discovery": False,
                "entries": _context(unified, scope),
            },
            "comparability": {
                "expected_domains": list(expected_sets[scope]),
                "not_tracked_domains": [
                    m["domain"] for m in members if m["state"] == "not_tracked"
                ],
                "comparable_with": [],
                "not_comparable_with": [],
            },
            "independence": {"shares_market_wide_evidence_with": []},
        }

    _link_assets(assets, expected_sets)
    candidates = [s for s in SCOPE_DOMAINS if assets[s]["status"] == "candidate"]
    shared = _shared_market_wide(assets, candidates)

    return {
        "contract_version": CONTRACT_VERSION,
        "source_contracts": {
            "unified": UNIFIED_CONTRACT_VERSION,
            "confirmation": CONFIRMATION_CONTRACT_VERSION,
            "confirmation_parameters": confirmation["parameters"]["version"],
            "confirmation_families": confirmation["parameters"]["families_version"],
        },
        "snapshot": snapshot,
        "parameters": {
            "version": params.version,
            "min_asset_specific_confirmers": params.min_asset_specific_confirmers,
            "asset_led_min_asset_specific": params.asset_led_min_asset_specific,
            "experimental": True,
        },
        "discovery_types": {
            "version": DISCOVERY_TYPES_VERSION,
            "types": [{"id": i, "meaning": m} for i, m in DISCOVERY_TYPES],
        },
        "gates": {
            "look_ahead": {"triggered": bool(violations), "violations": violations},
            "producer_hash": {"check": hash_check, "triggered": hash_check == "mismatch"},
        },
        "assets": assets,
        "market_context": {
            "candidate_assets": candidates,
            "shared_market_wide_evidence": shared,
            "candidates_independent_of_each_other": not shared,
        },
        "data_quality": dict(unified["data_quality"]),
        "notice": {"id": NOTICE[0], "text": NOTICE[1]},
        "limitations": [{"id": i, "text": t} for i, t in LIMITATIONS],
    }


def _link_assets(assets: dict[str, Any], expected: dict[str, tuple[str, ...]]) -> None:
    for scope in SCOPE_DOMAINS:
        same = [o for o in SCOPE_DOMAINS if o != scope and set(expected[o]) == set(expected[scope])]
        different = [o for o in SCOPE_DOMAINS if o != scope and o not in same]
        assets[scope]["comparability"]["comparable_with"] = same
        assets[scope]["comparability"]["not_comparable_with"] = different
        if different:
            assets[scope]["notes"].append("OD-NOT-COMPARABLE-COVERAGE")


def _shared_market_wide(assets: dict[str, Any], candidates: list[str]) -> list[dict[str, Any]]:
    by_family: dict[str, list[str]] = {}
    for scope in candidates:
        for family in assets[scope]["basis"]["market_wide_supporting_families"]:
            by_family.setdefault(family, []).append(scope)
    shared = [{"family": f, "assets": a} for f, a in sorted(by_family.items()) if len(a) > 1]
    for entry in shared:
        for scope in entry["assets"]:
            others = [a for a in entry["assets"] if a != scope]
            node = assets[scope]["independence"]["shares_market_wide_evidence_with"]
            node.extend(o for o in others if o not in node)
            if "OD-SHARED-MARKET-WIDE-EVIDENCE" not in assets[scope]["notes"]:
                assets[scope]["notes"].append("OD-SHARED-MARKET-WIDE-EVIDENCE")
    for scope in candidates:
        assets[scope]["independence"]["shares_market_wide_evidence_with"].sort(
            key=list(SCOPE_DOMAINS).index
        )
    return shared
