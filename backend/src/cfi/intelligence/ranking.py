"""Opportunity Scoring & Ranking (Phase 47; ADR-0084): Phase 46 candidates -> evidence depth.

Pure and deterministic: no database, network, clock or model. The only input is the Phase 46
contract; nothing is persisted. ``evidence_depth`` is an integer index

    evidence_depth = |F| + |F_strong|

where ``F`` is the set of distinct, eligible, verified-fresh *asset-specific* evidence families
that support a Phase 46 candidate and ``F_strong`` the families of ``F`` with at least one
eligible Strong member. A family counts once however many members it has, and market-wide
evidence counts for nothing. It is an experimental ordinal heuristic: not a probability, a
confidence, an expected return or a recommendation, and not validated against outcomes.

Rules (every one fails closed):

* Only a Phase 46 ``candidate`` is scored. Other statuses (including ``blocked``) keep their
  Phase 46 status and reasons and get ``evidence_depth: null`` (never 0).
* A triggered integrity gate (look-ahead violation, producer-hash ``mismatch``) means no asset is
  scored or ranked. A candidate that coexists with a triggered gate is an inconsistent input.
* An input that is unsupported, malformed or inconsistent with itself (a candidate whose evidence
  does not support its own claims, a relabelled member, contradictory gates) is refused with
  ``RankingInputError``; it is never repaired and no partial ranking is returned.
* Ranks are only given inside a *comparability group*: assets with identical expected evidence,
  re-derived here and checked against Phase 46's declared relationships. An asset whose
  relationships are inconsistent or not reciprocal is isolated (kept with its depth, never
  ranked). A group needs two scored assets before any rank is given."""

from __future__ import annotations

import copy
from typing import Any, Final

from cfi.decision.universe import ASSET_SPECIFIC_DOMAINS, SCOPE_DOMAINS
from cfi.intelligence.confirmation import CONTRACT_VERSION as CONFIRMATION_CONTRACT_VERSION
from cfi.intelligence.confirmation import _freshness_verified
from cfi.intelligence.confirmation_universe import EVIDENCE_FAMILIES
from cfi.intelligence.opportunity import CONTRACT_VERSION as OPPORTUNITY_CONTRACT_VERSION
from cfi.intelligence.opportunity_universe import (
    DISCOVERY_TYPES,
    OPPORTUNITY_PARAMS_V0,
    STATUSES,
    SUPPORTED_CONFIRMATION_FAMILIES_VERSION,
    SUPPORTED_CONFIRMATION_PARAMS_VERSION,
)
from cfi.intelligence.ranking_universe import (
    COMPONENTS,
    COMPONENTS_VERSION,
    LIMITATIONS,
    NOTICE,
    RANKING_PARAMS_V0,
    SCORED_STRENGTHS,
    SUPPORTED_DISCOVERY_TYPES_VERSION,
    SUPPORTED_OPPORTUNITY_PARAMS_VERSION,
    RankingParameters,
)
from cfi.intelligence.unified_snapshot import CONTRACT_VERSION as UNIFIED_CONTRACT_VERSION

__all__ = ["CONTRACT_VERSION", "RankingInputError", "build_ranking"]

CONTRACT_VERSION: Final = "opportunity_ranking.v0"
_SCOPES: Final = tuple(SCOPE_DOMAINS)
_ALL_DOMAINS: Final = frozenset(d for domains in SCOPE_DOMAINS.values() for d in domains)
_CANDIDATE_TYPES: Final = ("asset_led_confirmation", "market_aligned_confirmation")
_TYPE_IDS: Final = tuple(i for i, _ in DISCOVERY_TYPES)
_MEMBER_KEYS: Final = (
    "domain",
    "component",
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
_REQUIRED_MEMBER_KEYS: Final = (
    "domain",
    "family",
    "state",
    "scope_basis",
    "shared_across_assets",
    "direction",
    "strength",
    "quality_flags",
    "freshness_records",
)
_REQUIRED_ASSET_KEYS: Final = (
    "status",
    "discovery_type",
    "reasons",
    "notes",
    "basis",
    "evidence_refs",
    "comparability",
)
_REQUIRED_BASIS_KEYS: Final = (
    "confirmation_agreement",
    "supportive_families",
    "adverse_families",
    "asset_specific_supporting_families",
    "market_wide_supporting_families",
    "coverage",
)


class RankingInputError(ValueError):
    """The Phase 46 input is unsupported, malformed or inconsistent with itself."""


def _need(cond: bool, message: str) -> None:
    if not cond:
        raise RankingInputError(message)


def _mapping(value: object, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RankingInputError(f"{what} must be a mapping")
    return value


def _strings(value: object, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise RankingInputError(f"{what} must be a list of strings")
    return list(value)


def _int(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RankingInputError(f"{what} must be an integer")
    return value


# ----------------------------------------------------------------------------- validation
def _validate_header(opp: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Versions, parameters, assets, gates. Returns (assets, triggered gate reasons)."""
    _need(
        opp.get("contract_version") == OPPORTUNITY_CONTRACT_VERSION,
        f"input must be {OPPORTUNITY_CONTRACT_VERSION!r}",
    )
    source = _mapping(opp.get("source_contracts"), "'source_contracts'")
    _need(
        source.get("unified") == UNIFIED_CONTRACT_VERSION
        and source.get("confirmation") == CONFIRMATION_CONTRACT_VERSION
        and source.get("confirmation_parameters") == SUPPORTED_CONFIRMATION_PARAMS_VERSION
        and source.get("confirmation_families") == SUPPORTED_CONFIRMATION_FAMILIES_VERSION,
        "unsupported source contract, parameter or family versions",
    )
    params = _mapping(opp.get("parameters"), "'parameters'")
    _need(
        params.get("version") == SUPPORTED_OPPORTUNITY_PARAMS_VERSION
        and params.get("min_asset_specific_confirmers")
        == OPPORTUNITY_PARAMS_V0.min_asset_specific_confirmers
        and params.get("asset_led_min_asset_specific")
        == OPPORTUNITY_PARAMS_V0.asset_led_min_asset_specific,
        "unsupported opportunity parameter version or values",
    )
    types = _mapping(opp.get("discovery_types"), "'discovery_types'")
    _need(
        types.get("version") == SUPPORTED_DISCOVERY_TYPES_VERSION,
        "unsupported discovery types version",
    )
    snapshot = _mapping(opp.get("snapshot"), "'snapshot'")
    quality = _mapping(opp.get("data_quality"), "'data_quality'")
    _mapping(opp.get("market_context"), "'market_context'")
    assets = _mapping(opp.get("assets"), "'assets'")
    _need(set(assets) == set(_SCOPES), "'assets' must hold exactly BTC, ETH, SOL and XRP")

    gates = _mapping(opp.get("gates"), "'gates'")
    look = _mapping(gates.get("look_ahead"), "'gates.look_ahead'")
    hashed = _mapping(gates.get("producer_hash"), "'gates.producer_hash'")
    violations = _strings(look.get("violations"), "'gates.look_ahead.violations'")
    _need(
        isinstance(look.get("triggered"), bool) and look["triggered"] == bool(violations),
        "look-ahead gate contradicts its violations",
    )
    _need(
        violations == list(quality.get("look_ahead_violations") or []),
        "look-ahead gate does not match data_quality",
    )
    check = hashed.get("check")
    _need(
        check == snapshot.get("producer_hash_check")
        and isinstance(hashed.get("triggered"), bool)
        and hashed["triggered"] == (check == "mismatch"),
        "producer-hash gate contradicts the snapshot identity",
    )
    reasons = []
    if look["triggered"]:
        reasons.append("RK-GATE-LOOK-AHEAD")
    if hashed["triggered"]:
        reasons.append("RK-GATE-INTEGRITY")
    return assets, reasons


def _validate_asset(scope: str, a: dict[str, Any], gated: bool) -> None:
    for key in _REQUIRED_ASSET_KEYS:
        _need(key in a, f"{scope}: missing {key!r}")
    status, kind = a["status"], a["discovery_type"]
    _need(status in STATUSES, f"{scope}: unknown status {status!r}")
    _need(kind is None or kind in _TYPE_IDS, f"{scope}: unknown discovery type")
    _strings(a["reasons"], f"{scope}: 'reasons'")
    _strings(a["notes"], f"{scope}: 'notes'")
    basis = _mapping(a["basis"], f"{scope}: 'basis'")
    for key in _REQUIRED_BASIS_KEYS:
        _need(key in basis, f"{scope}: basis is missing {key!r}")
    for key in ("supportive_families", "adverse_families"):
        _strings(basis[key], f"{scope}: basis.{key}")
    for key in ("asset_specific_supporting_families", "market_wide_supporting_families"):
        _strings(basis[key], f"{scope}: basis.{key}")
    cov = _mapping(basis["coverage"], f"{scope}: basis.coverage")
    _need(
        _int(cov.get("eligible"), f"{scope}: coverage.eligible") >= 0
        and _int(cov.get("expected"), f"{scope}: coverage.expected") > 0,
        f"{scope}: coverage is malformed",
    )
    refs = a["evidence_refs"]
    _need(isinstance(refs, list), f"{scope}: 'evidence_refs' must be a list")
    for m in refs:
        _mapping(m, f"{scope}: every evidence ref")
    if status == "candidate":
        _need(not gated, f"{scope}: a candidate cannot coexist with a triggered integrity gate")
        _need(kind in _CANDIDATE_TYPES, f"{scope}: a candidate needs a candidate discovery type")
        _need(a["reasons"] == ["OD-CANDIDATE"], f"{scope}: candidate reasons are inconsistent")
    elif status == "blocked":
        _need(gated, f"{scope}: 'blocked' without a triggered integrity gate")
        _need(kind is None, f"{scope}: a blocked asset has no discovery type")
    else:
        _need(
            kind is None or (kind == "adverse_confirmation" and status == "no_candidate"),
            f"{scope}: discovery type is inconsistent with the status",
        )


# --------------------------------------------------------------------------- comparability
def _expected(scope: str, a: dict[str, Any]) -> list[str]:
    c = _mapping(a["comparability"], f"{scope}: 'comparability'")
    expected = _strings(c.get("expected_domains"), f"{scope}: expected_domains")
    untracked = _strings(c.get("not_tracked_domains"), f"{scope}: not_tracked_domains")
    _need(
        len(set(expected)) == len(expected) and len(set(untracked)) == len(untracked),
        f"{scope}: comparability domains must be unique",
    )
    _need(
        set(expected) == set(SCOPE_DOMAINS[scope])
        and not set(expected) & set(untracked)
        and set(expected) | set(untracked) == set(_ALL_DOMAINS),
        f"{scope}: comparability domains do not match the tracked domains of the asset",
    )
    return expected


def _declared(scope: str, a: dict[str, Any]) -> tuple[set[str], set[str]]:
    c = a["comparability"]
    same = _strings(c.get("comparable_with"), f"{scope}: comparable_with")
    different = _strings(c.get("not_comparable_with"), f"{scope}: not_comparable_with")
    others = set(_SCOPES) - {scope}
    _need(
        len(set(same)) == len(same)
        and len(set(different)) == len(different)
        and set(same) <= others
        and set(different) <= others
        and not set(same) & set(different)
        and set(same) | set(different) == others,
        f"{scope}: comparability relationships are malformed",
    )
    return set(same), set(different)


def _groups(assets: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Group id per asset and the group descriptions.

    Groups are derived from each asset's expected domains. Phase 46's declared relationships must
    agree with that derivation and be reciprocal; the assets they do not hold for are isolated."""
    key = {s: frozenset(_expected(s, assets[s])) for s in _SCOPES}
    derived = {s: {o for o in _SCOPES if o != s and key[o] == key[s]} for s in _SCOPES}
    declared = {s: _declared(s, assets[s])[0] for s in _SCOPES}
    affected = {s for s in _SCOPES if declared[s] != derived[s]}
    for s in _SCOPES:  # a claim the other asset does not return isolates both ends
        for o in declared[s]:
            if s not in declared[o]:
                affected |= {s, o}
    group_of: dict[str, str] = {}
    info: dict[str, dict[str, Any]] = {}
    for s in _SCOPES:
        if s in group_of:
            continue
        members = (
            [s] if s in affected else [o for o in _SCOPES if o not in affected and key[o] == key[s]]
        )
        gid = "+".join(members)
        for m in members:
            group_of[m] = gid
        info[gid] = {
            "group_id": gid,
            "members": members,
            "comparability_verified": s not in affected,
            "expected_domains": sorted(key[s], key=list(SCOPE_DOMAINS[s]).index),
        }
    return group_of, info


# ------------------------------------------------------------------------------- scoring
def _score(
    scope: str, a: dict[str, Any], expected: list[str], params: RankingParameters
) -> dict[str, Any]:
    basis = a["basis"]
    by_family: dict[str, list[dict[str, Any]]] = {}
    market_wide: set[str] = set()
    for m in a["evidence_refs"]:
        for key in _REQUIRED_MEMBER_KEYS:
            _need(key in m, f"{scope}: an evidence ref is missing {key!r}")
        domain = m["domain"]
        _need(isinstance(domain, str), f"{scope}: evidence ref 'domain' must be a string")
        _need(domain in EVIDENCE_FAMILIES, f"{scope}: evidence ref has an unknown domain")
        _need(domain in expected, f"{scope}: evidence ref for an untracked domain {domain!r}")
        specific = domain in ASSET_SPECIFIC_DOMAINS
        _need(
            m["shared_across_assets"] is (not specific)
            and m["scope_basis"] == ("asset" if specific else "market_wide")
            and m["family"] == EVIDENCE_FAMILIES[domain].family_id,
            f"{scope}: evidence ref {domain!r} is mislabelled for its domain",
        )
        _need(m["state"] != "adverse", f"{scope}: a candidate cannot hold adverse evidence")
        if m["state"] != "supportive":
            continue
        if not specific:
            market_wide.add(m["family"])
            continue
        _need(
            m["direction"] == "S"
            and m["quality_flags"] == []
            and _freshness_verified(m["freshness_records"])
            and m["strength"] in SCORED_STRENGTHS,
            f"{scope}: supporting evidence {domain!r} is not eligible and fresh-verified",
        )
        by_family.setdefault(m["family"], []).append(m)

    families = sorted(by_family)
    _need(
        families == sorted(basis["asset_specific_supporting_families"])
        and sorted(market_wide) == sorted(basis["market_wide_supporting_families"])
        and sorted(set(families) | market_wide) == sorted(basis["supportive_families"])
        and basis["confirmation_agreement"] == "confirmed_supportive"
        and basis["adverse_families"] == [],
        f"{scope}: the candidate's evidence does not match its confirmation basis",
    )
    _need(
        len(families) >= OPPORTUNITY_PARAMS_V0.min_asset_specific_confirmers,
        f"{scope}: a candidate needs an asset-specific supporting family",
    )
    led = len(families) >= OPPORTUNITY_PARAMS_V0.asset_led_min_asset_specific
    _need(
        a["discovery_type"] == ("asset_led_confirmation" if led else "market_aligned_confirmation"),
        f"{scope}: the discovery type does not match the supporting families",
    )
    strong = [f for f in families if any(m["strength"] == "Strong" for m in by_family[f])]
    base = len(families) * params.family_base_points
    bonus = len(strong) * params.strong_bonus_points
    maximum = sum(1 for d in expected if d in ASSET_SPECIFIC_DOMAINS) * (
        params.family_base_points + params.strong_bonus_points
    )
    _need(base + bonus <= maximum, f"{scope}: the evidence depth exceeds the attainable maximum")
    return {
        "evidence_depth": base + bonus,
        "families": families,
        "strong": strong,
        "components": {
            "asset_specific_families": families,
            "strong_families": strong,
            "base_points": base,
            "strong_bonus_points": bonus,
            "market_wide": {
                "families": sorted(market_wide),
                "points": params.market_wide_points,
            },
            "family_detail": [
                {
                    "family": f,
                    "domain": by_family[f][0]["domain"],
                    "base_points": params.family_base_points,
                    "strong_bonus_points": (params.strong_bonus_points if f in strong else 0),
                    "member_count": len(by_family[f]),
                    "members": [
                        {k: copy.deepcopy(m.get(k)) for k in _MEMBER_KEYS} for m in by_family[f]
                    ],
                }
                for f in families
            ],
        },
    }


def _rank(group: dict[str, Any], key_of: dict[str, tuple[int, int]], min_scored: int) -> None:
    """Fill ``group['ranks']`` ({scope: (rank | None, reason)}) for one group."""
    members = [s for s in group["members"] if s in key_of]
    group["scored"] = members
    group["ranks"] = {}
    if not members:
        return
    if not group["comparability_verified"]:
        for s in members:
            group["ranks"][s] = (None, "RK-NOT-RANKED-COMPARABILITY-UNVERIFIED")
        return
    if len(members) < min_scored:
        for s in members:
            group["ranks"][s] = (None, "RK-NOT-RANKED-SOLE-IN-GROUP")
        return
    distinct = sorted({key_of[s] for s in members}, reverse=True)
    for s in members:
        group["ranks"][s] = (distinct.index(key_of[s]) + 1, "RK-RANKED")


def build_ranking(
    opportunities: dict[str, Any], *, params: RankingParameters = RANKING_PARAMS_V0
) -> dict[str, Any]:
    """Build ``opportunity_ranking.v0`` from one ``opportunity_discovery.v0`` mapping.

    Raises ``RankingInputError`` (a ``ValueError``) for unsupported, malformed or internally
    inconsistent input. Missing or unverified *evidence* never raises: Phase 46 already reports
    it as an outcome, and it is never scored."""
    opp = _mapping(opportunities, "the input")
    assets_in, gate_reasons = _validate_header(opp)
    gated = bool(gate_reasons)
    for scope in _SCOPES:
        _validate_asset(scope, _mapping(assets_in[scope], f"assets.{scope}"), gated)

    group_of, group_info = _groups(assets_in)
    expected = {s: _expected(s, assets_in[s]) for s in _SCOPES}

    scored: dict[str, dict[str, Any]] = {}
    if not gated:
        for scope in _SCOPES:
            if assets_in[scope]["status"] == "candidate":
                scored[scope] = _score(scope, assets_in[scope], expected[scope], params)
    key_of = {s: (v["evidence_depth"], len(v["families"])) for s, v in scored.items()}
    for group in group_info.values():
        _rank(group, key_of, params.min_scored_to_rank)
        eligible = {s: assets_in[s]["basis"]["coverage"]["eligible"] for s in group["scored"]}
        group["eligible_coverage_differs"] = len(set(eligible.values())) > 1

    assets: dict[str, Any] = {}
    for scope in _SCOPES:
        a = assets_in[scope]
        group = group_info[group_of[scope]]
        score = scored.get(scope)
        rank, rank_reason = group["ranks"].get(scope, (None, None))
        tied = (
            []
            if rank is None
            else [o for o in group["scored"] if o != scope and key_of[o] == key_of[scope]]
        )
        ranking_reasons: list[str] = list(gate_reasons)
        if score is not None:
            ranking_reasons += ["RK-SCORED", rank_reason or ""]
            ranking_reasons = [r for r in ranking_reasons if r]
        elif a["status"] == "blocked":
            ranking_reasons.append("RK-WITHHELD-BLOCKED")
        else:
            ranking_reasons.append("RK-WITHHELD-NOT-CANDIDATE")
        notes: list[str] = []
        if score is not None and group["eligible_coverage_differs"]:
            notes.append("RK-UNEQUAL-ELIGIBLE-COVERAGE")
        if "OD-SHARED-MARKET-WIDE-EVIDENCE" in a["notes"]:
            notes.append("RK-SHARED-MARKET-WIDE-EVIDENCE")
        if len(group_info) > 1:
            notes.append("RK-NOT-COMPARABLE-ACROSS-GROUPS")
        assets[scope] = {
            "status": a["status"],
            "discovery_type": a["discovery_type"],
            "reasons": list(a["reasons"]),
            "ranking_reasons": ranking_reasons,
            "notes": notes,
            "scored": score is not None,
            "evidence_depth": None if score is None else score["evidence_depth"],
            "max_attainable_depth": sum(1 for d in expected[scope] if d in ASSET_SPECIFIC_DOMAINS)
            * (params.family_base_points + params.strong_bonus_points),
            "score_withheld_reason": (
                None
                if score is not None
                else "blocked_by_integrity_gate"
                if a["status"] == "blocked"
                else a["status"]
            ),
            "components": None if score is None else score["components"],
            "rank": rank,
            "tied_with": tied,
            "rank_scope": None if gated else group["group_id"],  # no ranking under a gate
            "not_ranked_against": [s for s in _SCOPES if group_of[s] != group_of[scope]],
            "coverage": copy.deepcopy(a["basis"]["coverage"]),
            "comparability": {
                "group_id": group["group_id"],
                "verified": group["comparability_verified"],
                "comparable_with": [o for o in group["members"] if o != scope],
            },
        }

    groups = []
    for group in group_info.values():
        ordered = sorted(
            group["scored"],
            key=lambda s: (
                group["ranks"][s][0] is None,
                group["ranks"][s][0] or 0,
                _SCOPES.index(s),
            ),
        )
        groups.append(
            {
                "group_id": group["group_id"],
                "members": list(group["members"]),
                "comparability_verified": group["comparability_verified"],
                "expected_domains": list(group["expected_domains"]),
                "scored_assets": ordered,
                "ranked": any(group["ranks"][s][0] is not None for s in group["scored"]),
                "eligible_coverage": {
                    s: copy.deepcopy(assets_in[s]["basis"]["coverage"]) for s in group["members"]
                },
            }
        )
    snapshot = copy.deepcopy(opp["snapshot"])
    return {
        "contract_version": CONTRACT_VERSION,
        "source_contracts": {
            "opportunity": OPPORTUNITY_CONTRACT_VERSION,
            "opportunity_parameters": opp["parameters"]["version"],
            "discovery_types": opp["discovery_types"]["version"],
            **copy.deepcopy(opp["source_contracts"]),
        },
        "snapshot": snapshot,
        "parameters": {
            "version": params.version,
            "family_base_points": params.family_base_points,
            "strong_bonus_points": params.strong_bonus_points,
            "market_wide_points": params.market_wide_points,
            "min_scored_to_rank": params.min_scored_to_rank,
            "experimental": True,
        },
        "components": {
            "version": COMPONENTS_VERSION,
            "items": [{"id": i, "meaning": m} for i, m in COMPONENTS],
        },
        "gates": copy.deepcopy(opp["gates"]),
        "scoring": {"performed": not gated, "gate_reasons": gate_reasons},
        "assets": assets,
        "groups": groups,
        "market_context": copy.deepcopy(opp["market_context"]),
        "data_quality": copy.deepcopy(opp["data_quality"]),
        "notice": {"id": NOTICE[0], "text": NOTICE[1]},
        "limitations": [{"id": i, "text": t} for i, t in LIMITATIONS],
    }
