"""``assess`` — the pure, deterministic L4.5 Evidence Synthesis function.

``assess(snapshot_payload, scope, parameters) -> AssessmentResult``

* deterministic: same payload + scope + methodology version + parameter version -> equal result
  (no clock, randomness, network, database, Redis, Celery, HTTP or model call is made here);
* it consumes only evidence present in the supplied stored snapshot payload and never rebuilds a
  snapshot, fetches data, or invents a missing value;
* Claude never determines any output (stance, confidence, posture, risk, tally, coverage, conflict).

Pipeline (methodology sections 4-10): normalise -> directional tally (DS-01..09) -> observed caps
and CAP-U ceilings -> confidence (CN) -> six risk dimensions (RK) -> posture (PO) -> explanation.
Raw directional stance (``directional_stance_before_limits``) is preserved separately from the
final stance for auditability.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from cfi.decision.evidence import EvidenceReading, ExtractedEvidence, extract_evidence
from cfi.decision.result import (
    AssessmentResult,
    CapUApplication,
    EvidenceItem,
    Explanation,
)
from cfi.decision.rules import (
    LimitOutcome,
    apply_limits,
    classify_raw_stance,
    compute_confidence,
    compute_posture,
    compute_risks,
    compute_tally,
)
from cfi.decision.universe import (
    BULLISH_FAMILY,
    PARAMETERS_V0,
    SCOPE_DOMAINS,
    DecisionParameters,
    Direction,
    Freshness,
    Posture,
    RiskLevel,
    Stance,
)

__all__ = ["assess", "assess_extracted", "risk_by_dimension", "snapshot_hash"]


def snapshot_hash(payload: dict[str, Any]) -> str:
    """Deterministic content hash of the supplied payload (provenance; not a database id)."""
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _item(r: EvidenceReading) -> EvidenceItem:
    if r.direction is None or r.strength is None:  # pragma: no cover - directional only
        raise ValueError(f"{r.domain} is not a directional reading")
    return EvidenceItem(
        domain=r.domain,
        direction=r.direction,
        strength=r.strength,
        band=r.band,
        template_id=r.template_id,
        field_ids=r.field_ids,
        raw_paths=r.raw_paths,
        reason_ids=r.reason_ids,
        quality_flags=r.quality_flags,
    )


def _cap_u_records(
    raw: Stance,
    limits: LimitOutcome,
    ev: ExtractedEvidence,
    final: Stance,
    posture: Posture,
    params: DecisionParameters,
) -> tuple[CapUApplication, ...]:
    """One traceability record per CAP-U rule that applies."""
    if raw not in BULLISH_FAMILY or limits.applied_ceiling is None:
        return ()
    entries = (
        (limits.cu01, "regime", "CU-01", Stance.NEUTRAL, ev.regime.source_ids[0], "CAPU.regime"),
        (
            limits.cu02,
            "derivatives",
            "CU-02",
            Stance.CAUTIOUSLY_BULLISH,
            ev.derivatives.source_ids[0],
            "CAPU.derivatives",
        ),
        (
            limits.cu03,
            "anomaly",
            "CU-03",
            Stance.CAUTIOUSLY_BULLISH,
            ev.anomaly_reading.source_ids[0],
            "CAPU.anomaly",
        ),
    )
    binding = dict(limits.cu_binding)
    return tuple(
        CapUApplication(
            cap_source=source,
            source_field_id=tool_id,
            source_status="not_evaluable",
            reason_id=f"{rule}:{source}=not_evaluable",
            rule_id=rule,
            rule_ceiling=ceiling,
            applied_ceiling=limits.applied_ceiling,
            binding=binding.get(rule, False),
            directional_stance_before_limits=raw,
            final_stance=final,
            final_posture=posture,
            methodology_version=params.methodology_version,
            parameter_version=params.version,
            template_id=template,
        )
        for applies, source, rule, ceiling, tool_id, template in entries
        if applies
    )


def _explanation(
    ev: ExtractedEvidence,
    raw: Stance,
    conflict: bool,
    limits: LimitOutcome,
    cap_u: tuple[CapUApplication, ...],
) -> tuple[Explanation, tuple[str, ...]]:
    directional: list[str] = [f"STANCE.{raw.value}"]
    for r in ev.directional:
        if r.template_id is not None:
            directional.append(r.template_id)
        if "stale" in r.quality_flags:
            directional.append("SUFFIX.stale")
        if "partial" in r.quality_flags or "flagged" in r.quality_flags:
            directional.append("SUFFIX.partial")
    if conflict:
        directional += ["CONFLICT.phrase", "CONFLICT.pair"]
    limits_ids: list[str] = [c.template_id for c in limits.observed_caps]
    if cap_u:
        limits_ids += ["CAPU.frame.directional", "CAPU.frame.limit", "CAPU.frame.missing"]
        limits_ids += [c.template_id for c in cap_u]
    missing_ids: list[str] = []
    if ev.regime.status != "ok":
        missing_ids.append("CTX.regime.missing")
    missing_ids += [
        r.template_id
        for r in ev.directional
        if r.direction is Direction.UNAVAILABLE and r.template_id is not None
    ]
    limitations: list[str] = []
    if ev.derivatives.status == "ok" and ev.derivatives.freshness is Freshness.NOT_ASSESSED:
        limitations.append("LIMIT.derivatives_freshness")
    missing_ids += limitations
    return Explanation(tuple(directional), tuple(limits_ids), tuple(missing_ids)), tuple(
        limitations
    )


def assess(
    snapshot_payload: dict[str, Any],
    scope: str,
    parameters: DecisionParameters = PARAMETERS_V0,
) -> AssessmentResult:
    """Assess one scope from one stored snapshot payload. Raises ``ValueError`` for an undefined
    scope; never raises for missing evidence (that is a first-class, explained state)."""
    ev = extract_evidence(snapshot_payload, scope)
    as_of = snapshot_payload.get("as_of")
    return assess_extracted(
        ev,
        parameters,
        input_hash=snapshot_hash(snapshot_payload),
        snapshot_as_of=as_of if isinstance(as_of, str) else None,
    )


def assess_extracted(
    ev: ExtractedEvidence,
    parameters: DecisionParameters = PARAMETERS_V0,
    *,
    input_hash: str = "",
    snapshot_as_of: str | None = None,
) -> AssessmentResult:
    """The synthesis proper, over already-normalised evidence (also the unit-test seam)."""
    scope = ev.scope
    tally = compute_tally(ev.directional)
    expected = len(SCOPE_DOMAINS[scope])
    if tally.d != expected:  # pragma: no cover - structural invariant
        raise AssertionError(f"tally D={tally.d} != scope definition {expected}")

    raw, ds_rule, conflict = classify_raw_stance(tally, parameters)
    limits = apply_limits(raw, ev)
    final = limits.final_stance
    conf = compute_confidence(final, tally, conflict, ev, parameters)
    risks = compute_risks(ev, tally)
    posture = compute_posture(final, conf.level, risks, limits, ev, parameters)
    cap_u = _cap_u_records(raw, limits, ev, final, posture.posture, parameters)

    missing_context_list: list[str] = []
    if ev.regime.status != "ok":
        missing_context_list.append("regime")
    if ev.derivatives.status != "ok":
        missing_context_list.append("derivatives")
    if not ev.anomaly.evaluable:
        missing_context_list.append("volatility_anomaly")
    missing_context = tuple(missing_context_list)
    explanation, limitations = _explanation(ev, raw, conflict, limits, cap_u)

    fired: list[str] = [ds_rule]
    fired += [c.rule_id for c in limits.observed_caps]
    fired += [c.rule_id for c in cap_u]
    fired += list(conf.rule_ids)
    fired.append(posture.rule_id)
    fired = list(dict.fromkeys(fired))

    supportive = tuple(_item(r) for r in ev.directional if r.direction is Direction.SUPPORTIVE)
    adverse = tuple(_item(r) for r in ev.directional if r.direction is Direction.ADVERSE)
    neutral = tuple(_item(r) for r in ev.directional if r.direction is Direction.NEUTRAL)
    readings = (
        *ev.directional,
        ev.regime,
        ev.derivatives,
        ev.anomaly_reading,
        ev.retail_activity,
        ev.retail_speculation,
        *ev.context,
    )
    return AssessmentResult(
        scope=scope,
        methodology_version=parameters.methodology_version,
        parameter_version=parameters.version,
        template_version=parameters.template_version,
        snapshot_hash=input_hash,
        snapshot_as_of=snapshot_as_of,
        assumed_domain_score_versions=parameters.assumed_domain_score_versions,
        observed_domain_score_versions=ev.observed_score_versions,
        tally=tally,
        expected_domains=expected,
        coverage_available=tally.n,
        directional_stance_before_limits=raw,
        final_stance=final,
        confidence=conf.level,
        posture=posture.posture,
        conflict=conflict,
        contradictions=limits.contradictions,
        supportive=supportive,
        adverse=adverse,
        neutral=neutral,
        missing=tuple(r.domain for r in ev.directional if r.direction is Direction.UNAVAILABLE),
        missing_context=missing_context,
        not_tracked=ev.not_tracked,
        readings=readings,
        risks=risks,
        max_risk=posture.max_risk,
        not_assessed_count=posture.not_assessed_count,
        observed_caps=limits.observed_caps,
        cap_u=cap_u,
        confidence_rule_ids=conf.rule_ids,
        posture_rule_id=posture.rule_id,
        fired_rule_ids=tuple(fired),
        limitations=limitations,
        explanation=explanation,
        snapshot_data_quality_state=ev.data_quality_state,
        snapshot_has_conflicts=ev.has_conflicts,
    )


def risk_by_dimension(result: AssessmentResult) -> dict[str, RiskLevel]:
    """Convenience map ``dimension -> level`` (used by tests and later consumers)."""
    return {r.dimension.value: r.level for r in result.risks}
