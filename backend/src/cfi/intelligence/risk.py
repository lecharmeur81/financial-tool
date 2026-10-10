"""Risk & Invalidation (Phase 48; ADR-0085): explicit findings about a Phase 46/47 candidate.

Pure and deterministic: no database, network, clock or model. Inputs are three views of **one**
stored snapshot: ``opportunity_ranking.v0`` (Phase 47, the principal input), the
``opportunity_discovery.v0`` it was derived from (Phase 46, which carries the excluded members and
Risk and Context entries that ranking drops) and ``risk_view.v0`` (the decision engine's own risk
dimensions and caps). They overlap: they are one body of evidence seen three ways, never three
confirmations, and no finding is strengthened or weakened by appearing in more than one of them.

No risk model is defined here. Levels (Low, Moderate, Elevated, High, Not assessed) come from the
decision engine's v0 judgment mappings; this module only classifies each into an explicit result:

* ``passed`` - the condition is not met on verified-fresh evidence (never "safe");
* ``detected`` - the condition is met (reported even when freshness is unverified, flagged);
* ``unverified`` - evaluable, but freshness cannot be verified (not reassuring);
* ``unavailable`` - missing data or an unevaluable source (never counted as passed or adverse);
* ``not_applicable`` and ``withheld`` (an integrity gate is triggered).

Only a Phase 46 candidate is assessed; every other asset keeps its Phase 46 status and reasons and
is never labelled low risk. There is no risk score, rating, probability or recommendation. An
unsupported, malformed or mutually inconsistent input raises ``RiskInputError``; no partial
assessment is produced."""

from __future__ import annotations

import copy
from typing import Any, Final

from cfi.decision.universe import SCOPE_DOMAINS, RiskDimension, RiskLevel
from cfi.intelligence.confirmation import _freshness_verified
from cfi.intelligence.confirmation_universe import CONFIRMATION_PARAMS_V0
from cfi.intelligence.opportunity_universe import OPPORTUNITY_PARAMS_V0
from cfi.intelligence.ranking import (
    CONTRACT_VERSION as RANKING_CONTRACT_VERSION,
)
from cfi.intelligence.ranking import RankingInputError, build_ranking
from cfi.intelligence.risk_universe import (
    CAP_RULES,
    CHECKS,
    CHECKS_VERSION,
    DECLARED_UNAVAILABLE,
    INVALIDATION_CONDITIONS,
    INVALIDATION_RESULTS,
    LIMITATIONS,
    NOTICE,
    RESULTS,
    RISK_PARAMS_V0,
    RiskParameters,
)
from cfi.intelligence.risk_view import CONTRACT_VERSION as RISK_VIEW_VERSION

__all__ = ["CONTRACT_VERSION", "RiskInputError", "build_risk_invalidation"]

CONTRACT_VERSION: Final = "risk_invalidation.v0"
_SCOPES: Final = tuple(SCOPE_DOMAINS)
_BENCHMARK: Final = "BTC"
_IDENTITY_KEYS: Final = (
    "row_id",
    "uuid",
    "row_created_at",
    "as_of",
    "knowledge_time",
    "snapshot_version",
    "producer_payload_hash",
    "producer_hash_check",
    "decision_input_hash",
)
_LEVELS: Final = frozenset(level.value for level in RiskLevel)
_DIMENSIONS: Final = tuple(d.value for d in RiskDimension)
# Dimensions that depend on market-wide evidence: identical for every asset, reported once.
_MARKET_DIMS: Final = (
    ("market", "RI-MKT-01", "market_stress"),
    ("liquidity", "RI-LIQ-01", "liquidity_backdrop"),
    ("volatility", "RI-VOL-01", "volatility"),
    ("narrative", "RI-NAR-01", "speculation"),
)
_ASSET_DIMS: Final = (
    ("leverage", "RI-LEV-01", "leverage"),
    ("data_quality", "RI-DQ-01", "data_quality"),
)
_RESULT_IDS: Final = tuple(r for r, _ in RESULTS)


class RiskInputError(ValueError):
    """An input is unsupported, malformed or inconsistent with another input."""


def _need(cond: bool, message: str) -> None:
    if not cond:
        raise RiskInputError(message)


def _mapping(value: object, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RiskInputError(f"{what} must be a mapping")
    return value


def _list(value: object, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise RiskInputError(f"{what} must be a list")
    return value


def _strings(value: object, what: str) -> list[str]:
    items = _list(value, what)
    if not all(isinstance(v, str) for v in items):
        raise RiskInputError(f"{what} must be a list of strings")
    return list(items)


# ----------------------------------------------------------------------------- validation
def _validate_view(view: object, snapshot: dict[str, Any]) -> dict[str, Any]:
    v = _mapping(view, "the risk view")
    _need(
        v.get("contract_version") == RISK_VIEW_VERSION and v.get("source") == "decision_engine",
        f"the risk view must be {RISK_VIEW_VERSION!r}",
    )
    decision = _mapping(v.get("decision"), "risk view 'decision'")
    _need(
        all(isinstance(decision.get(k), str) for k in ("methodology_version", "parameter_version")),
        "risk view 'decision' versions must be strings",
    )
    identity = _mapping(v.get("identity"), "risk view 'identity'")
    differing = sorted(k for k in _IDENTITY_KEYS if identity.get(k) != snapshot.get(k))
    _need(
        not differing,
        "the risk view and the opportunities describe different snapshots "
        f"(differing identity fields: {', '.join(differing)})",
    )
    scopes = _mapping(v.get("scopes"), "risk view 'scopes'")
    _need(set(scopes) == set(_SCOPES), "risk view 'scopes' must hold exactly BTC, ETH, SOL, XRP")
    for scope in _SCOPES:
        s = _mapping(scopes[scope], f"risk view {scope}")
        _need(isinstance(s.get("caps_evaluated"), bool), f"{scope}: caps_evaluated must be a bool")
        risks = _list(s.get("risks"), f"{scope}: risks")
        seen = []
        for r in risks:
            _mapping(r, f"{scope}: every risk")
            _need(r.get("dimension") in _DIMENSIONS, f"{scope}: unknown risk dimension")
            _need(r.get("level") in _LEVELS, f"{scope}: unknown risk level")
            _strings(r.get("reason_ids"), f"{scope}: risk reason_ids")
            _strings(r.get("field_ids"), f"{scope}: risk field_ids")
            seen.append(r["dimension"])
        _need(sorted(seen) == sorted(_DIMENSIONS), f"{scope}: all six risk dimensions are required")
        _need(s.get("max_risk") in _LEVELS, f"{scope}: unknown max_risk")
        known_rules = {c[0] for c in CAP_RULES}
        for c in _list(s.get("observed_caps"), f"{scope}: observed_caps"):
            _mapping(c, f"{scope}: every observed cap")
            _need(c.get("rule_id") in known_rules, f"{scope}: unknown cap rule")
            _need(isinstance(c.get("binding"), bool), f"{scope}: cap binding must be a bool")
            _strings(c.get("source_field_ids"), f"{scope}: cap source_field_ids")
        for c in _list(s.get("cap_u"), f"{scope}: cap_u"):
            _mapping(c, f"{scope}: every CAP-U record")
            _need(isinstance(c.get("rule_id"), str), f"{scope}: CAP-U rule id")
        status = _mapping(s.get("source_status"), f"{scope}: source_status")
        _need(
            all(isinstance(status.get(d), str) for d in ("regime", "derivatives", "anomaly")),
            f"{scope}: source_status must name regime, derivatives and anomaly",
        )
    for dim, _, _ in _MARKET_DIMS:
        base = _risk(scopes[_BENCHMARK], dim)
        for scope in _SCOPES:
            other = _risk(scopes[scope], dim)
            _need(
                (other["level"], other["reason_ids"], other["field_ids"])
                == (base["level"], base["reason_ids"], base["field_ids"]),
                f"the market-wide {dim} risk differs between {_BENCHMARK} and {scope}",
            )
    return v


def _risk(scope_view: dict[str, Any], dimension: str) -> dict[str, Any]:
    return next(r for r in scope_view["risks"] if r["dimension"] == dimension)


def _validate_inputs(
    opp: object, ranking: object, view: object
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    o = _mapping(opp, "the opportunities input")
    r = _mapping(ranking, "the ranking input")
    _need(
        r.get("contract_version") == RANKING_CONTRACT_VERSION,
        f"the ranking input must be {RANKING_CONTRACT_VERSION!r}",
    )
    try:
        expected = build_ranking(o)
    except RankingInputError as exc:
        raise RiskInputError(
            f"the opportunities input was refused by ranking validation: {exc}"
        ) from exc
    _need(expected == r, "the ranking was not derived from these opportunities")
    snapshot = _mapping(o.get("snapshot"), "'snapshot'")
    v = _validate_view(view, snapshot)
    for scope in _SCOPES:
        a = o["assets"][scope]
        ctx = _mapping(a.get("context"), f"{scope}: 'context'")
        _need(ctx.get("used_for_discovery") is False, f"{scope}: context must be display-only")
        for key in ("evidence_refs", "excluded_members"):
            for e in _list(a.get(key), f"{scope}: {key}"):
                _strings(_mapping(e, f"{scope}: every {key} item").get("field_ids"), "field_ids")
        for e in _list(ctx.get("entries"), f"{scope}: context entries"):
            _strings(_mapping(e, f"{scope}: every context entry").get("field_ids"), "field_ids")
            _need(isinstance(e.get("domain"), str), f"{scope}: context entry domain")
    dq = _mapping(o.get("data_quality"), "'data_quality'")
    for key in ("unavailable_tools", "degraded_tools", "conflicting_tools"):
        _strings(dq.get(key), f"data_quality.{key}")
    return o, r, v


# ------------------------------------------------------------------------------ helpers
def _verified(entry: dict[str, Any]) -> bool:
    return bool(
        entry.get("freshness") == "fresh"
        and _freshness_verified(entry.get("freshness_records"))
        and not entry.get("quality_flags")
        and entry.get("status", "ok") == "ok"
    )


def _entries(a: dict[str, Any]) -> list[dict[str, Any]]:
    return [*a["evidence_refs"], *a["excluded_members"], *a["context"]["entries"]]


def _by_fields(entries: list[dict[str, Any]], field_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(field_ids)
    return [e for e in entries if wanted & set(e["field_ids"])] if wanted else []


def _by_domain(entries: list[dict[str, Any]], domain: str) -> list[dict[str, Any]]:
    return [e for e in entries if e.get("domain") == domain]


def _all_verified(contributors: list[dict[str, Any]]) -> bool:
    return bool(contributors) and all(_verified(c) for c in contributors)


def _unique(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop repeated entries so the same evidence is never listed (or counted) twice."""
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for e in entries:
        key = (e.get("domain"), e.get("component"), tuple(e["field_ids"]), e.get("freshness"))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def _finding(
    check_id: str,
    category: str,
    scope: str,
    result: str,
    *,
    level: str | None = None,
    reasons: list[str] | None = None,
    verified: bool | None = None,
    field_ids: list[str] | None = None,
    contributors: list[dict[str, Any]] | None = None,
    engine_reason_ids: list[str] | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contributors = _unique(contributors or [])
    field_ids = list(dict.fromkeys(field_ids or []))
    sources = sorted({s for c in contributors for s in c.get("source_ids") or []})
    return {
        "check_id": check_id,
        "category": category,
        "scope": scope,
        "applicable": result != "not_applicable",
        "result": result,
        "level": level,
        "reason_ids": list(reasons or []),
        "engine_reason_ids": list(engine_reason_ids or []),
        "freshness_verified": verified,
        "field_ids": field_ids,
        "source_ids": sources,
        "contributors": [
            {
                "domain": c.get("domain"),
                "component": c.get("component"),
                "freshness": c.get("freshness"),
                "freshness_verified": _verified(c),
            }
            for c in contributors
        ],
        "freshness_records": copy.deepcopy(
            [x for c in contributors for x in c["freshness_records"]]
        ),
        "detail": copy.deepcopy(detail or {}),
    }


def _level_result(
    level: str, verified: bool | None, params: RiskParameters
) -> tuple[str, list[str]]:
    if level == RiskLevel.NOT_ASSESSED.value:
        return "unavailable", ["RI-LEVEL-NOT-ASSESSED"]
    visible = ["RI-LEVEL-MODERATE-VISIBLE"] if level in params.visible_levels else []
    if level in params.detected_levels:
        return "detected", []
    if verified is None:
        return "unverified", [*visible, "RI-FRESHNESS-NOT-APPLICABLE"]
    if verified:
        return "passed", visible
    return "unverified", [*visible, "RI-FRESHNESS-UNVERIFIED"]


def _risk_finding(
    check_id: str,
    category: str,
    scope: str,
    risk: dict[str, Any],
    entries: list[dict[str, Any]],
    params: RiskParameters,
    *,
    withheld: bool,
) -> dict[str, Any]:
    contributors = _by_fields(entries, risk["field_ids"])
    verified: bool | None = _all_verified(contributors) if risk["field_ids"] else None
    result, reasons = (
        ("withheld", []) if withheld else _level_result(risk["level"], verified, params)
    )
    return _finding(
        check_id,
        category,
        scope,
        result,
        level=risk["level"],
        reasons=reasons,
        verified=verified,
        field_ids=risk["field_ids"],
        contributors=contributors,
        engine_reason_ids=risk["reason_ids"],
        detail={"dimension": risk["dimension"]},
    )


# ------------------------------------------------------------------------------ findings
def _integrity(o: dict[str, Any], gate_reasons: list[str]) -> list[dict[str, Any]]:
    gates, snap, dq = o["gates"], o["snapshot"], o["data_quality"]
    look = gates["look_ahead"]
    out = [
        _finding(
            "RI-INT-01",
            "integrity",
            "integrity",
            "detected" if look["triggered"] else "passed",
            reasons=["RI-GATE-LOOK-AHEAD"] if look["triggered"] else [],
            detail={"violations": list(look["violations"])},
        )
    ]
    check = gates["producer_hash"]["check"]
    out.append(
        _finding(
            "RI-INT-02",
            "integrity",
            "integrity",
            "detected"
            if check == "mismatch"
            else "passed"
            if check == "verified"
            else "unverified",
            reasons=(
                ["RI-GATE-INTEGRITY"]
                if check == "mismatch"
                else []
                if check == "verified"
                else ["RI-HASH-UNVERIFIED"]
            ),
            detail={"check": check},
        )
    )
    conflict = (
        bool(dq["conflicting_tools"])
        or bool(dq["degraded_tools"])
        or snap.get("source_conflicts") is True
        or snap.get("snapshot_data_quality_state") in ("degraded", "insufficient")
    )
    known = snap.get("snapshot_data_quality_state") == "ok" and isinstance(
        snap.get("source_conflicts"), bool
    )
    out.append(
        _finding(
            "RI-INT-03",
            "integrity",
            "integrity",
            "detected" if conflict else "passed" if known else "unverified",
            reasons=["RI-SOURCE-CONFLICT"] if conflict else [],
            detail={
                "conflicting_tools": list(dq["conflicting_tools"]),
                "degraded_tools": list(dq["degraded_tools"]),
                "unavailable_tools": list(dq["unavailable_tools"]),
                "source_conflicts": snap.get("source_conflicts"),
                "snapshot_data_quality_state": snap.get("snapshot_data_quality_state"),
            },
        )
    )
    return out


def _caps(
    scope: str,
    view: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    withheld: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    observed = {c["rule_id"]: c for c in view["observed_caps"]}
    for rule, check_id, domain, meaning in CAP_RULES:
        source = view["source_status"][domain]
        domain_entries = _by_domain(entries, domain)
        cap = observed.get(rule)
        detail = {
            "rule_id": rule,
            "condition": meaning,
            "caps_evaluated": view["caps_evaluated"],
            "observed": cap is not None,
            "binding": None if cap is None else cap["binding"],
            "source_status": source,
        }
        if withheld:
            result, reasons, verified = "withheld", [], None
        elif cap is not None:
            result, reasons = "detected", ["RI-CAP-OBSERVED"]
            verified = _all_verified(domain_entries)
        elif not view["caps_evaluated"]:
            result, reasons, verified = (
                "not_applicable",
                ["RI-CAP-NOT-EVALUATED-RAW-NOT-BULLISH"],
                None,
            )
        elif source != "ok":
            result, reasons, verified = "unavailable", ["RI-CAP-SOURCE-NOT-EVALUABLE"], None
        else:
            verified = _all_verified(domain_entries)
            result = "passed" if verified else "unverified"
            reasons = [] if verified else ["RI-FRESHNESS-UNVERIFIED"]
        out.append(
            _finding(
                check_id,
                "decision_caps",
                scope,
                result,
                reasons=reasons,
                verified=verified,
                field_ids=sorted({f for e in domain_entries for f in e["field_ids"]})
                if cap is None
                else cap["source_field_ids"],
                contributors=domain_entries,
                detail=detail,
            )
        )
    return out


def _supporting(a: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in a["evidence_refs"] if m["state"] == "supportive"]


def _scoped_pass(check_id: str, scope: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    """No eligible member in scope is adverse. Scope is the eligible members only."""
    unique = _unique(members)
    verified = _all_verified(unique) if unique else None
    if not unique:
        result, reasons = "unavailable", ["RI-NO-ELIGIBLE-MEMBERS-IN-SCOPE"]
    elif verified:
        result, reasons = "passed", []
    else:
        result, reasons = "unverified", ["RI-FRESHNESS-UNVERIFIED"]
    return _finding(
        check_id,
        "evidence_disagreement",
        scope,
        result,
        reasons=reasons,
        verified=verified,
        field_ids=[f for m in unique for f in m["field_ids"]],
        contributors=unique,
        detail={"adverse_members": 0, "examined": "eligible_members_only", "members": len(unique)},
    )


def _evidence(scope: str, a: dict[str, Any]) -> list[dict[str, Any]]:
    refs = a["evidence_refs"]
    adverse = [m for m in refs if m["state"] == "adverse"]
    # A Phase 46 candidate cannot hold adverse eligible evidence; one that does is inconsistent.
    _need(not adverse, f"{scope}: a candidate cannot hold adverse eligible evidence")
    # A candidate meets the Phase 45 and 46 supporting-family minimums. One that does not
    # contradicts its own status: that is an inconsistent input, not an invalidation.
    _need(
        len(a["basis"]["supportive_families"]) >= CONFIRMATION_PARAMS_V0.min_families
        and len(a["basis"]["asset_specific_supporting_families"])
        >= OPPORTUNITY_PARAMS_V0.min_asset_specific_confirmers,
        f"{scope}: a candidate holds fewer supporting families than the Phase 45 and 46 minimums",
    )
    specific = [m for m in refs if m["shared_across_assets"] is False]
    wide = [m for m in refs if m["shared_across_assets"] is True]
    expected = set(a["comparability"]["expected_domains"])
    unusable = [m for m in a["excluded_members"] if m["domain"] in expected]
    cov = a["basis"]["coverage"]
    families = a["basis"]["asset_specific_supporting_families"]
    sharing = a["independence"]["shares_market_wide_evidence_with"]
    out = [
        _scoped_pass("RI-EVD-01", scope, specific),
        _scoped_pass("RI-EVD-02", scope, wide),
        _finding(
            "RI-EVD-03",
            "coverage",
            scope,
            "detected" if unusable else "passed",
            reasons=["RI-MISSING-NOT-ADVERSE"] if unusable else [],
            verified=None if unusable else True,
            field_ids=[f for m in unusable for f in m["field_ids"]],
            contributors=unusable,
            detail={
                "unusable_domains": [
                    {
                        "domain": m["domain"],
                        "state": m["state"],
                        "exclusion_reason": m.get("exclusion_reason"),
                    }
                    for m in unusable
                ],
                "coverage": copy.deepcopy(cov),
            },
        ),
        _finding(
            "RI-EVD-04",
            "coverage",
            scope,
            "passed" if len(families) >= 2 else "detected",
            detail={"asset_specific_supporting_families": list(families)},
        ),
        _finding(
            "RI-EVD-05",
            "evidence_dependence",
            scope,
            "detected" if sharing else "passed",
            detail={
                "market_wide_supporting_families": list(
                    a["basis"]["market_wide_supporting_families"]
                ),
                "shares_market_wide_evidence_with": list(sharing),
            },
        ),
    ]
    return out


def _invalidation(
    scope: str, a: dict[str, Any], caps: list[dict[str, Any]], view: dict[str, Any]
) -> dict[str, Any]:
    support = _supporting(a)
    basis = a["basis"]
    asset_families = basis["asset_specific_supporting_families"]
    verified = _all_verified(support)
    conditions: list[dict[str, Any]] = []

    def add(cid: str, result: str, reasons: list[str], watch: list[str], **detail: Any) -> None:
        meaning = next(m for i, _, m in INVALIDATION_CONDITIONS if i == cid)
        name = next(n for i, n, _ in INVALIDATION_CONDITIONS if i == cid)
        conditions.append(
            {
                "condition_id": cid,
                "name": name,
                "meaning": meaning,
                "result": result,
                "reason_ids": reasons,
                "monitor_field_ids": watch,
                "detail": detail,
            }
        )

    support_fields = sorted({f for m in support for f in m["field_ids"]})
    specific_fields = sorted(
        {f for m in support if m["shared_across_assets"] is False for f in m["field_ids"]}
    )
    enough_specific = len(asset_families) >= OPPORTUNITY_PARAMS_V0.min_asset_specific_confirmers
    add(
        "INV-01",
        "not_triggered"
        if enough_specific and verified
        else "triggered"
        if not enough_specific
        else "cannot_evaluate",
        []
        if enough_specific and verified
        else ["RI-FRESHNESS-UNVERIFIED"]
        if enough_specific
        else [],
        specific_fields,
        asset_specific_families=list(asset_families),
        minimum=OPPORTUNITY_PARAMS_V0.min_asset_specific_confirmers,
    )
    enough = len(basis["supportive_families"]) >= CONFIRMATION_PARAMS_V0.min_families
    add(
        "INV-02",
        "not_triggered"
        if enough and verified
        else "triggered"
        if not enough
        else "cannot_evaluate",
        [] if enough and verified else ["RI-FRESHNESS-UNVERIFIED"] if enough else [],
        support_fields,
        supportive_families=list(basis["supportive_families"]),
        minimum=CONFIRMATION_PARAMS_V0.min_families,
    )
    adverse = list(basis["adverse_families"])
    add(
        "INV-03",
        "triggered" if adverse else "not_triggered",
        [],
        support_fields,
        adverse_families=adverse,
    )
    add(
        "INV-04",
        "not_triggered" if verified else "cannot_evaluate",
        [] if verified else ["RI-FRESHNESS-UNVERIFIED", "RI-FRESHNESS-LOSS-NOT-OBSERVABLE"],
        support_fields,
        supporting_members=len(support),
        verified_members=sum(1 for m in support if _verified(m)),
    )
    add("INV-05", "not_triggered", [], [], note="A triggered gate withholds the whole assessment.")
    cap_results = [c["result"] for c in caps]
    cap_fields = sorted({f for c in caps for f in c["field_ids"]})
    if any(r == "detected" for r in cap_results):
        res, reasons = "cannot_evaluate", ["RI-INV-CAP-RELATIONSHIP-NOT-ESTABLISHED"]
    elif all(r == "passed" for r in cap_results):
        res, reasons = "not_triggered", []
    elif any(r == "not_applicable" for r in cap_results):
        res, reasons = "cannot_evaluate", ["RI-CAP-NOT-EVALUATED-RAW-NOT-BULLISH"]
    elif any(r == "unavailable" for r in cap_results):
        res, reasons = "cannot_evaluate", ["RI-CAP-SOURCE-NOT-EVALUABLE"]
    else:
        res, reasons = "cannot_evaluate", ["RI-FRESHNESS-UNVERIFIED"]
    add(
        "INV-06",
        res,
        reasons,
        cap_fields,
        observed=[c["rule_id"] for c in view["observed_caps"]],
        binding=[c["rule_id"] for c in view["observed_caps"] if c["binding"]],
        cap_u=[c["rule_id"] for c in view["cap_u"]],
    )
    results = [c["result"] for c in conditions]
    summary = (
        "triggered"
        if "triggered" in results
        else "not_fully_evaluable"
        if "cannot_evaluate" in results
        else "none_triggered"
    )
    monitor = [
        {
            "condition_id": c["condition_id"],
            "field_ids": c["monitor_field_ids"],
            "when": c["meaning"],
        }
        for c in conditions
    ]
    return {"summary": summary, "conditions": conditions, "monitor": monitor}


def _counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    return {r: sum(1 for f in findings if f["result"] == r) for r in _RESULT_IDS}


# -------------------------------------------------------------------------------- engine
def build_risk_invalidation(
    opportunities: dict[str, Any],
    ranking: dict[str, Any],
    risk_view: dict[str, Any],
    *,
    params: RiskParameters = RISK_PARAMS_V0,
) -> dict[str, Any]:
    """Build ``risk_invalidation.v0`` from the three views of one snapshot.

    Raises ``RiskInputError`` (a ``ValueError``) for unsupported, malformed or mutually
    inconsistent input. Missing or unverified *evidence* never raises: it is an explicit result."""
    o, r, view = _validate_inputs(opportunities, ranking, risk_view)
    gates = o["gates"]
    gated = bool(gates["look_ahead"]["triggered"] or gates["producer_hash"]["triggered"])
    gate_reasons = (["RI-GATE-LOOK-AHEAD"] if gates["look_ahead"]["triggered"] else []) + (
        ["RI-GATE-INTEGRITY"] if gates["producer_hash"]["triggered"] else []
    )

    bench_entries = _entries(o["assets"][_BENCHMARK])
    bench_view = view["scopes"][_BENCHMARK]
    market = [
        _risk_finding(
            cid, cat, "market", _risk(bench_view, dim), bench_entries, params, withheld=gated
        )
        for dim, cid, cat in _MARKET_DIMS
    ]

    assets: dict[str, Any] = {}
    for scope in _SCOPES:
        a = o["assets"][scope]
        rank = r["assets"][scope]
        sv = view["scopes"][scope]
        context = {
            "scored": rank["scored"],
            "evidence_depth": rank["evidence_depth"],
            "rank": rank["rank"],
            "rank_scope": rank["rank_scope"],
            "used_for_risk": False,
        }
        base: dict[str, Any] = {
            "status": a["status"],
            "discovery_type": a["discovery_type"],
            "reasons": list(a["reasons"]),
            "ranking_context": context,
        }
        if a["status"] != "candidate":
            blocked = a["status"] == "blocked"
            assets[scope] = {
                **base,
                "assessment": "withheld" if blocked else "not_applicable",
                "assessment_reasons": ["RI-WITHHELD-BLOCKED" if blocked else "RI-NOT-A-CANDIDATE"],
                "findings": [],
                "counts": _counts([]),
                "invalidation": None,
                "market_risks_detected": [],
            }
            continue
        _need(not gated, f"{scope}: a candidate cannot coexist with a triggered integrity gate")
        entries = _entries(a)
        findings = [
            _risk_finding(cid, cat, scope, _risk(sv, dim), entries, params, withheld=False)
            for dim, cid, cat in _ASSET_DIMS
        ]
        findings += _evidence(scope, a)
        caps = _caps(scope, sv, entries, withheld=False)
        findings += caps
        assets[scope] = {
            **base,
            "assessment": "assessed",
            "assessment_reasons": ["RI-ASSESSED"],
            "findings": findings,
            "counts": _counts(findings),
            "invalidation": _invalidation(scope, a, caps, sv),
            "market_risks_detected": [f["check_id"] for f in market if f["result"] == "detected"],
        }

    return {
        "contract_version": CONTRACT_VERSION,
        "source_contracts": {
            "ranking": r["contract_version"],
            "opportunity": o["contract_version"],
            "risk_view": view["contract_version"],
            "unified": o["source_contracts"]["unified"],
            "confirmation": o["source_contracts"]["confirmation"],
            "confirmation_parameters": o["source_contracts"]["confirmation_parameters"],
            "confirmation_families": o["source_contracts"]["confirmation_families"],
            "opportunity_parameters": o["parameters"]["version"],
            "ranking_parameters": r["parameters"]["version"],
        },
        "decision": copy.deepcopy(view["decision"]),
        "snapshot": copy.deepcopy(o["snapshot"]),
        "parameters": {
            "version": params.version,
            "detected_levels": list(params.detected_levels),
            "visible_levels": list(params.visible_levels),
            "experimental": True,
        },
        "checks": {
            "version": CHECKS_VERSION,
            "items": [
                {"check_id": i, "category": c, "scope": s, "condition": t} for i, c, s, t in CHECKS
            ],
            "results": [{"id": i, "meaning": m} for i, m in RESULTS],
            "invalidation_results": [{"id": i, "meaning": m} for i, m in INVALIDATION_RESULTS],
        },
        "evidence_dependence": {
            "single_snapshot": True,
            "inputs": [r["contract_version"], o["contract_version"], view["contract_version"]],
            "independent_confirmation": False,
            "note": (
                "The inputs are views of one stored snapshot. Agreement between them is not "
                "independent confirmation and lowers no risk."
            ),
        },
        "gates": copy.deepcopy(gates),
        "assessment": {"performed": not gated, "gate_reasons": gate_reasons},
        "integrity": {"findings": _integrity(o, gate_reasons)},
        "market_risks": {"applies_to": list(_SCOPES), "findings": market},
        "unavailable_checks": [
            {
                "check_id": i,
                "category": c,
                "result": "unavailable",
                "reason_ids": [reason],
                "note": note,
            }
            for i, c, reason, note in DECLARED_UNAVAILABLE
        ],
        "assets": assets,
        "data_quality": copy.deepcopy(o["data_quality"]),
        "notice": {"id": NOTICE[0], "text": NOTICE[1]},
        "limitations": [{"id": i, "text": t} for i, t in LIMITATIONS],
    }
