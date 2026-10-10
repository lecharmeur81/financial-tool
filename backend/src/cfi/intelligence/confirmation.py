"""``cross_domain_confirmation.v0`` (Phase 45; ADR-0082): do independent directional domains agree?

A pure, deterministic function of ``unified_snapshot.v0`` (Phase 44): no database, network, clock,
provider or model, and no second snapshot. It reads each entry's own values and arranges them; it
computes no metric and produces no stance, score, risk, opportunity or recommendation.

Eligibility - only an *eligible* reading can vote. A reading is eligible when it is a Directional
entry (``independent_vote``), has status ``ok``, is ``fresh`` **and** every one of its freshness
records is explicitly ``fresh`` (none missing, empty, ``None``, ``no_data`` or unknown), carries no
quality flag, has a
direction of supportive / adverse / neutral, and its domain has an evidence family. Anything else
keeps its explicit state (``unavailable``, ``stale``, ``partial``, ``not_assessed``,
``not_tracked``) with the reason, stays visible with its provenance, and never counts as neutral,
confirming or contradicting. Regime, risk and context entries are never votes.

Rules (first match wins), per asset, over *families* (a family counts at most once per direction):

1. both directions have an eligible family -> ``mixed``. This is never hidden by the coverage
   floor: with low coverage the reason ``CF-MIXED-LOW-COVERAGE`` is added.
2. eligible coverage below the floor -> ``insufficient_evidence``.
3. at least ``min_families`` families on one side, none on the other, and (when required) one of
   them from the asset's key layer -> ``confirmed_supportive`` / ``confirmed_adverse``.
4. otherwise ``unconfirmed``, with the reason.

Differences from the Decision Center are intended (ADR-0082): the engine keeps stale readings in
its tally and answers "what is the overall stance"; this answers "how many independent, current,
complete families agree"."""

from __future__ import annotations

from typing import Any, Final

from cfi.decision.result import Tally
from cfi.decision.rules import is_conflict
from cfi.decision.universe import (
    ASSET_SPECIFIC_DOMAINS,
    PARAMETERS_V0,
    SCOPE_DOMAINS,
)
from cfi.intelligence.confirmation_universe import (
    CONFIRMATION_PARAMS_V0,
    EVIDENCE_FAMILIES,
    EVIDENCE_FAMILIES_VERSION,
    KEY_CONFIRMATION_DOMAINS,
    LIMITATIONS,
    ConfirmationParameters,
)
from cfi.intelligence.unified_snapshot import CONTRACT_VERSION as UNIFIED_CONTRACT_VERSION

__all__ = ["CONTRACT_VERSION", "ConfirmationInputError", "build_confirmation"]

CONTRACT_VERSION: Final = "cross_domain_confirmation.v0"
_SIDES: Final = {"S": "supportive", "A": "adverse"}


class ConfirmationInputError(ValueError):
    """The input is not a ``unified_snapshot.v0`` mapping this engine can read."""


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ConfirmationInputError(message)


def _validate(unified: object) -> dict[str, Any]:
    if not isinstance(unified, dict):
        raise ConfirmationInputError("input must be a mapping")
    _require(
        unified.get("contract_version") == UNIFIED_CONTRACT_VERSION,
        f"input contract_version must be {UNIFIED_CONTRACT_VERSION!r}",
    )
    _require(isinstance(unified.get("snapshot"), dict), "'snapshot' must be a mapping")
    _require(isinstance(unified.get("data_quality"), dict), "'data_quality' must be a mapping")
    global_domains = unified.get("global_domains")
    if not isinstance(global_domains, list):
        raise ConfirmationInputError("'global_domains' must be a list")
    assets = unified.get("assets")
    if not isinstance(assets, dict):
        raise ConfirmationInputError("'assets' must be a mapping")
    entries: list[Any] = list(global_domains)
    for scope in SCOPE_DOMAINS:
        block = assets.get(scope)
        if not isinstance(block, dict):
            raise ConfirmationInputError(f"assets.{scope} must be a mapping")
        if not isinstance(block.get("domains"), list):
            raise ConfirmationInputError(f"assets.{scope}.domains must be a list")
        if not isinstance(block.get("not_tracked_domains"), list):
            raise ConfirmationInputError(f"assets.{scope}.not_tracked_domains must be a list")
        entries.extend(block["domains"])
    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfirmationInputError("every domain entry must be a mapping")
        for key in ("domain", "component", "independent_vote", "status", "freshness"):
            _require(key in entry, f"domain entry is missing {key!r}")
    return unified


def _freshness_verified(records: object) -> bool:
    """True only for a non-empty list in which every record's status is exactly ``fresh``."""
    return (
        isinstance(records, list)
        and len(records) > 0
        and all(isinstance(r, dict) and r.get("status") == "fresh" for r in records)
    )


def _classify(entry: dict[str, Any]) -> tuple[str, str | None]:
    """(state, exclusion_reason) for one Directional entry. State is the first that applies."""
    status = str(entry["status"])
    flags = list(entry.get("quality_flags") or [])
    freshness = str(entry["freshness"])
    if status != "ok":
        return "unavailable", f"status:{status}"
    if freshness == "stale" or "stale" in flags:
        return "stale", "stale"
    if "partial" in flags or "flagged" in flags:
        return "partial", "quality_flag:" + ",".join(f for f in flags if f != "stale")
    if freshness != "fresh":
        return "not_assessed", f"freshness:{freshness}"
    # The top-level label alone is not enough: the engine labels a market-wide domain ``fresh``
    # whenever one enabled source exists and none is stale, even if a source's own freshness is
    # missing, ``None``, ``no_data`` or unknown. A vote needs explicit, verified records.
    if not _freshness_verified(entry.get("freshness_records")):
        return "not_assessed", "freshness_unverified"
    if entry.get("direction") not in ("S", "A", "N"):
        return "unavailable", f"direction:{entry.get('direction')}"
    if entry["domain"] not in EVIDENCE_FAMILIES:
        return "unmapped", "no_family_mapping"
    return "eligible", None


def _member(entry: dict[str, Any], scope: str) -> dict[str, Any]:
    state, reason = _classify(entry)
    direction = entry.get("direction")
    eligible = state == "eligible"
    domain = str(entry["domain"])
    family = EVIDENCE_FAMILIES.get(domain)
    return {
        "family": None if family is None else family.family_id,
        "domain": domain,
        "component": entry["component"],
        "scope_basis": "asset" if domain in ASSET_SPECIFIC_DOMAINS else "market_wide",
        "shared_across_assets": domain not in ASSET_SPECIFIC_DOMAINS,
        "state": (_SIDES.get(str(direction), "neutral") if eligible else state),
        "eligible": eligible,
        "exclusion_reason": reason,
        "direction": direction,
        "strength": entry.get("strength"),
        "freshness": entry["freshness"],
        "evidence_state": entry.get("evidence_state"),
        "quality_flags": list(entry.get("quality_flags") or []),
        "source_ids": list(entry.get("source_ids") or []),
        "field_ids": list(entry.get("field_ids") or []),
        "freshness_records": list(entry.get("freshness_records") or []),
    }


def _absent(domain: str, state: str, reason: str) -> dict[str, Any]:
    family = EVIDENCE_FAMILIES.get(domain)
    return {
        "family": None if family is None else family.family_id,
        "domain": domain,
        "component": None,
        "scope_basis": "asset" if domain in ASSET_SPECIFIC_DOMAINS else "market_wide",
        "shared_across_assets": domain not in ASSET_SPECIFIC_DOMAINS,
        "state": state,
        "eligible": False,
        "exclusion_reason": reason,
        "direction": None,
        "strength": None,
        "freshness": None,
        "evidence_state": None,
        "quality_flags": [],
        "source_ids": [],
        "field_ids": [],
        "freshness_records": [],
    }


def _assess(
    scope: str, members: list[dict[str, Any]], params: ConfirmationParameters
) -> dict[str, Any]:
    expected = len(SCOPE_DOMAINS[scope])
    voters = [m for m in members if m["eligible"]]
    families: dict[str, set[str]] = {"supportive": set(), "adverse": set()}
    for m in voters:
        if m["state"] in families:
            families[m["state"]].add(m["family"])
    key = set(KEY_CONFIRMATION_DOMAINS[scope])
    key_layer = {
        side: any(m["state"] == side and m["domain"] in key for m in voters) for side in families
    }
    num, den = params.coverage_floor
    coverage_met = len(voters) * den >= num * expected
    tally = Tally(
        s=sum(m["state"] == "supportive" for m in voters),
        a=sum(m["state"] == "adverse" for m in voters),
        n_neutral=sum(m["state"] == "neutral" for m in voters),
        u=expected - len(voters),
        s_strong=sum(m["state"] == "supportive" and m["strength"] == "Strong" for m in voters),
        a_strong=sum(m["state"] == "adverse" and m["strength"] == "Strong" for m in voters),
    )

    reasons: list[str] = []
    if families["supportive"] and families["adverse"]:
        agreement = "mixed"
        reasons.append("CF-MIXED")
        if not coverage_met:
            reasons.append("CF-MIXED-LOW-COVERAGE")
        if is_conflict(tally, PARAMETERS_V0):
            reasons.append("CF-DECISION-CONFLICT-DEFINITION-MET")
    elif not coverage_met:
        agreement = "insufficient_evidence"
        reasons.append("CF-LOW-COVERAGE")
    else:
        agreement = "unconfirmed"
        side = next(
            (s for s in ("supportive", "adverse") if len(families[s]) >= params.min_families),
            None,
        )
        if side is not None and (key_layer[side] or not params.require_key_layer):
            agreement = f"confirmed_{side}"
            reasons.append("CF-CONFIRMED")
        elif side is not None:
            reasons.append("CF-NO-KEY-LAYER")
        elif families["supportive"] or families["adverse"]:
            reasons.append("CF-TOO-FEW-FAMILIES")
        else:
            reasons.append("CF-NO-DIRECTIONAL-EVIDENCE")

    by_state: dict[str, int] = {}
    for m in members:
        by_state[m["state"]] = by_state.get(m["state"], 0) + 1
    return {
        "agreement": agreement,
        "reasons": reasons,
        "supportive_families": sorted(families["supportive"]),
        "adverse_families": sorted(families["adverse"]),
        "key_layer": {
            "domains": sorted(key),
            "supportive": key_layer["supportive"],
            "adverse": key_layer["adverse"],
        },
        "coverage": {
            "eligible": len(voters),
            "expected": expected,
            "floor": list(params.coverage_floor),
            "met": coverage_met,
        },
        "counts_by_state": dict(sorted(by_state.items())),
        "members": members,
    }


def build_confirmation(
    unified: dict[str, Any], *, params: ConfirmationParameters = CONFIRMATION_PARAMS_V0
) -> dict[str, Any]:
    """Build ``cross_domain_confirmation.v0`` from a ``unified_snapshot.v0`` mapping.

    Raises ``ConfirmationInputError`` (a ``ValueError``) for input that is not a well-formed
    ``unified_snapshot.v0``. Missing, stale or partial *evidence* never raises: it is an explicit
    state."""
    u = _validate(unified)
    global_by_domain: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    for entry in u["global_domains"]:
        if entry["independent_vote"] is True:
            global_by_domain.setdefault(entry["domain"], entry)
        else:
            excluded.append(_excluded(entry, "global"))

    assets: dict[str, Any] = {}
    for scope, domains in SCOPE_DOMAINS.items():
        block = u["assets"][scope]
        own: dict[str, dict[str, Any]] = {}
        for entry in block["domains"]:
            if entry["independent_vote"] is True:
                own.setdefault(entry["domain"], entry)
            else:
                excluded.append(_excluded(entry, scope))
        members: list[dict[str, Any]] = []
        for domain in domains:
            entry = (own if domain in ASSET_SPECIFIC_DOMAINS else global_by_domain).get(domain)
            if entry is not None:
                members.append(_member(entry, scope))
            else:
                members.append(_absent(domain, "unavailable", "missing_from_snapshot"))
        for domain in block["not_tracked_domains"]:
            if domain not in domains and domain in EVIDENCE_FAMILIES:
                members.append(_absent(domain, "not_tracked", "not_tracked_for_scope"))
        assets[scope] = _assess(scope, members, params)

    return {
        "contract_version": CONTRACT_VERSION,
        "source_contract": UNIFIED_CONTRACT_VERSION,
        "snapshot": dict(u["snapshot"]),
        "parameters": {
            "version": params.version,
            "min_families": params.min_families,
            "require_key_layer": params.require_key_layer,
            "coverage_floor": list(params.coverage_floor),
            "families_version": EVIDENCE_FAMILIES_VERSION,
        },
        "families": {
            domain: {"family": f.family_id, "lineage": f.lineage}
            for domain, f in EVIDENCE_FAMILIES.items()
        },
        "assets": assets,
        "excluded": excluded,
        "data_quality": dict(u["data_quality"]),
        "limitations": [{"id": i, "text": t} for i, t in LIMITATIONS],
    }


def _excluded(entry: dict[str, Any], scope: str) -> dict[str, Any]:
    return {
        "scope": scope,
        "domain": entry["domain"],
        "component": entry["component"],
        "role": entry.get("role"),
        "reason": "not_a_directional_vote",
    }
