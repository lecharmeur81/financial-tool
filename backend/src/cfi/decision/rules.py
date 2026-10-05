"""The v0 rule functions of L4.5 (methodology sections 4-10). Every function is pure and uses exact
integer arithmetic; ``r`` and ``c`` are never computed in floating point (methodology X6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cfi.decision.evidence import EvidenceReading, ExtractedEvidence
from cfi.decision.result import CapRecord, RiskReading, Tally
from cfi.decision.universe import (
    BULLISH_BY_STRENGTH,
    BULLISH_FAMILY,
    CONFIDENCE_ORDER,
    DERIVATIVES_RISK,
    KEY_CONFIRMATION_DOMAINS,
    REGIME_MARKET_RISK,
    RETAIL_ACTIVITY_RISK,
    RETAIL_ELEVATED_ACTIVITY_BAND,
    RETAIL_SPECULATION_RISK,
    RETAIL_STRONG_LONG_BAND,
    RISK_BY_ORDER,
    RISK_ORDER,
    STANCE_STRENGTH,
    VOLATILITY_RISK,
    Confidence,
    DecisionParameters,
    Direction,
    Freshness,
    Posture,
    RiskDimension,
    RiskLevel,
    Stance,
    Strength,
)

__all__ = [
    "ConfidenceOutcome",
    "LimitOutcome",
    "PostureOutcome",
    "apply_limits",
    "classify_raw_stance",
    "compute_confidence",
    "compute_posture",
    "compute_risks",
    "compute_tally",
    "is_conflict",
]


def _ge(numerator: int, fraction: tuple[int, int], denominator: int) -> bool:
    """``numerator / denominator >= fraction`` in exact integer arithmetic."""
    return numerator * fraction[1] >= fraction[0] * denominator


# --------------------------------------------------------------------------- directional
def compute_tally(readings: Sequence[EvidenceReading]) -> Tally:
    """Count the Directional readings. Unavailable readings are U: they stay in D, are never
    counted as neutral, and never enter S, A, N or n (INV-1)."""
    s = a = n_neutral = u = s_strong = a_strong = 0
    for r in readings:
        if r.direction is Direction.SUPPORTIVE:
            s += 1
            s_strong += r.strength is Strength.STRONG
        elif r.direction is Direction.ADVERSE:
            a += 1
            a_strong += r.strength is Strength.STRONG
        elif r.direction is Direction.NEUTRAL:
            n_neutral += 1
        else:
            u += 1
    return Tally(s, a, n_neutral, u, s_strong, a_strong)


def is_conflict(t: Tally, params: DecisionParameters) -> bool:
    """DS-02: at least two supportive and two adverse readings, or one strong reading on each
    side (a reading is strong only if it is a strong band and fresh and complete, RD-04)."""
    k = params.conflict_min_each_side
    return (t.s >= k and t.a >= k) or (t.s_strong >= 1 and t.a_strong >= 1)


def classify_raw_stance(t: Tally, params: DecisionParameters) -> tuple[Stance, str, bool]:
    """Rules DS-01..DS-09 in order; returns ``(raw_stance, rule_id, conflict)``."""
    d, n = t.d, t.n
    if not _ge(n, params.coverage_floor, d):  # 2n < D  (c < 1/2)
        return Stance.INSUFFICIENT, "DS-01", False
    if is_conflict(t, params):
        return Stance.NEUTRAL, "DS-02", True
    bull = _ge(t.s - t.a, params.ratio_plain, d)
    bear = _ge(t.a - t.s, params.ratio_plain, d)
    wide = _ge(n, params.strongly_coverage, d)
    if bull and t.a == 0 and wide and t.s_strong >= 1:
        return Stance.STRONGLY_BULLISH, "DS-03", False
    if bear and t.s == 0 and wide and t.a_strong >= 1:
        return Stance.STRONGLY_BEARISH, "DS-09", False
    if bull:
        return Stance.BULLISH, "DS-04", False
    if bear:
        return Stance.BEARISH, "DS-08", False
    if _ge(t.s - t.a, params.ratio_cautious, d):
        return Stance.CAUTIOUSLY_BULLISH, "DS-05", False
    if _ge(t.a - t.s, params.ratio_cautious, d):
        return Stance.CAUTIOUSLY_BEARISH, "DS-07", False
    return Stance.NEUTRAL, "DS-06", False


# --------------------------------------------------------------------------- caps and CAP-U
@dataclass(frozen=True, slots=True)
class LimitOutcome:
    final_stance: Stance
    observed_caps: tuple[CapRecord, ...]
    contradictions: tuple[str, ...]
    regime_not_evaluable: bool
    derivatives_not_evaluable: bool
    anomaly_not_evaluable: bool
    cu01: bool  # CAP-U rules that APPLY (source not evaluable AND raw stance is bullish-family)
    cu02: bool
    cu03: bool
    cu_binding: tuple[tuple[str, bool], ...]
    applied_ceiling: Stance | None  # least-permissive ceiling among all that apply, or None


def _ceiling_stance(strength: int) -> Stance:
    return BULLISH_BY_STRENGTH[strength]


def apply_limits(raw: Stance, ev: ExtractedEvidence) -> LimitOutcome:
    """Observed caps RC-01..RC-04 and the CAP-U safety ceilings CU-01..CU-03.

    Applies to a bullish-family raw stance only (decision D-D). A cap source that cannot be
    evaluated is NOT treated as "no cap": it imposes the ceiling its worst possible value would
    impose. The least-permissive applicable ceiling wins and ceilings never compound (INV-11).
    """
    regime_ne = ev.regime.status != "ok"
    deriv_ne = ev.derivatives.status != "ok"
    anomaly_ne = not ev.anomaly.evaluable
    if raw not in BULLISH_FAMILY:
        return LimitOutcome(
            raw, (), (), regime_ne, deriv_ne, anomaly_ne, False, False, False, (), None
        )

    raw_strength = STANCE_STRENGTH[raw]
    observed: list[tuple[str, int, tuple[str, ...], str]] = []  # rule, ceiling, fields, reason
    contradictions: list[str] = []
    if ev.derivatives.status == "ok" and ev.derivatives.band == "high stress":
        observed.append(("RC-01", 1, ev.derivatives.field_ids, "RC-01:derivatives=high stress"))
    if ev.anomaly.any_critical:
        observed.append(("RC-02", 1, ev.anomaly.critical_field_ids, "RC-02:anomaly=critical"))
    if ev.regime.status == "ok" and ev.regime.band == "euphoria":
        observed.append(("RC-03", 1, ev.regime.field_ids, "RC-03:regime=euphoria"))
    if ev.regime.status == "ok" and ev.regime.band in ("distribution", "capitulation"):
        observed.append(("RC-04", 0, ev.regime.field_ids, f"RC-04:regime={ev.regime.band}"))
        contradictions.append("regime_disagrees")

    cu: list[tuple[str, int]] = []
    if regime_ne:
        cu.append(("CU-01", 0))
    if deriv_ne:
        cu.append(("CU-02", 1))
    if anomaly_ne:
        cu.append(("CU-03", 1))

    ceilings = [c for _, c, _, _ in observed] + [c for _, c in cu]
    applied = min([raw_strength, *ceilings])
    final = raw if applied == raw_strength else _ceiling_stance(applied)
    records = tuple(
        CapRecord(
            rule_id=rule,
            ceiling=_ceiling_stance(ceiling),
            binding=ceiling < raw_strength and ceiling == min(ceilings),
            source_field_ids=fields,
            reason_id=reason,
            template_id=f"CAP.{rule}",
        )
        for rule, ceiling, fields, reason in observed
    )
    return LimitOutcome(
        final_stance=final,
        observed_caps=records,
        contradictions=tuple(contradictions),
        regime_not_evaluable=regime_ne,
        derivatives_not_evaluable=deriv_ne,
        anomaly_not_evaluable=anomaly_ne,
        cu01=regime_ne,
        cu02=deriv_ne,
        cu03=anomaly_ne,
        cu_binding=tuple((rule, ceiling < raw_strength) for rule, ceiling in cu),
        applied_ceiling=_ceiling_stance(min(ceilings)) if ceilings else None,
    )


# --------------------------------------------------------------------------- confidence
@dataclass(frozen=True, slots=True)
class ConfidenceOutcome:
    level: Confidence
    rule_ids: tuple[str, ...]


def _lower(level: Confidence) -> Confidence:
    """One downgrade step, floored at Low (CN-07)."""
    return Confidence.MODERATE if level is Confidence.HIGH else Confidence.LOW


def compute_confidence(
    stance: Stance,
    t: Tally,
    conflict: bool,
    ev: ExtractedEvidence,
    params: DecisionParameters,
) -> ConfidenceOutcome:
    """CN-01..CN-07. Confidence is one of four words and never a percentage."""
    if stance is Stance.INSUFFICIENT:
        return ConfidenceOutcome(Confidence.INSUFFICIENT, ("CN-01",))
    d, n = t.d, t.n
    if _ge(n, params.confidence_high, d):
        level = Confidence.HIGH
    elif _ge(n, params.confidence_moderate, d):
        level = Confidence.MODERATE
    else:
        level = Confidence.LOW
    rules = ["CN-01"]
    voting = [r for r in ev.directional if r.direction not in (None, Direction.UNAVAILABLE)]
    stale = (
        any("stale" in r.quality_flags for r in voting)
        or ev.derivatives.freshness is Freshness.STALE
    )
    degraded = (
        any(("partial" in r.quality_flags) or ("flagged" in r.quality_flags) for r in voting)
        or ev.has_conflicts
    )
    downgrades = (
        ("CN-02", conflict),
        ("CN-03", stale),
        ("CN-04", degraded),
        ("CN-05", ev.regime.status != "ok"),
    )
    for rule, applies in downgrades:
        if applies:
            rules.append(rule)
            level = _lower(level)  # floored at Low (CN-07)
    key = KEY_CONFIRMATION_DOMAINS[ev.scope]
    key_missing = any(
        r.domain in key and r.direction is Direction.UNAVAILABLE for r in ev.directional
    )
    if key_missing:
        rules.append("CN-06")  # recorded when triggered; cap at Moderate
        if CONFIDENCE_ORDER[level] > CONFIDENCE_ORDER[Confidence.MODERATE]:
            level = Confidence.MODERATE
    return ConfidenceOutcome(level, tuple(rules))


# --------------------------------------------------------------------------- risk
def _max_level(levels: Sequence[RiskLevel]) -> RiskLevel:
    return RISK_BY_ORDER[max(RISK_ORDER[lv] for lv in levels)]


def _floor_moderate(level: RiskLevel, degraded: bool) -> tuple[RiskLevel, bool]:
    if degraded and RISK_ORDER[level] < RISK_ORDER[RiskLevel.MODERATE]:
        return RiskLevel.MODERATE, True
    return level, False


def _reading_by_domain(ev: ExtractedEvidence, domain: str) -> EvidenceReading | None:
    for r in ev.directional:
        if r.domain == domain:
            return r
    return None


def _direction_risk(r: EvidenceReading | None) -> RiskLevel | None:
    """Directional reading -> risk level for the market and liquidity inputs (RK-01, RK-02):
    S2/S1 Low, N Moderate, A1 Elevated, A2 High. Unavailable -> None (never Low)."""
    if r is None or r.direction in (None, Direction.UNAVAILABLE):
        return None
    if r.direction is Direction.SUPPORTIVE:
        return RiskLevel.LOW
    if r.direction is Direction.NEUTRAL:
        return RiskLevel.MODERATE
    return RiskLevel.HIGH if r.strong_band else RiskLevel.ELEVATED


def _risk(
    dim: RiskDimension,
    level: RiskLevel,
    reasons: list[str],
    field_ids: tuple[str, ...],
) -> RiskReading:
    template = f"RISK.{dim.value}.{level.value}"
    return RiskReading(dim, level, tuple(reasons), field_ids, template)


def compute_risks(ev: ExtractedEvidence, t: Tally) -> tuple[RiskReading, ...]:
    """The six risk dimensions (RK-01..RK-06). Risk is never a directional vote: nothing here feeds
    S, A, N, U or n (INV-6)."""
    out: list[RiskReading] = []

    # RK-01 market risk: max(regime, market structure, macro); all unavailable -> Not assessed.
    inputs: list[tuple[str, RiskLevel, tuple[str, ...], bool]] = []
    if ev.regime.status == "ok" and ev.regime.band in REGIME_MARKET_RISK:
        inputs.append(
            (
                f"regime={ev.regime.band}",
                REGIME_MARKET_RISK[str(ev.regime.band)],
                ev.regime.field_ids,
                False,
            )
        )
    for domain in ("market_structure", "macro"):
        r = _reading_by_domain(ev, domain)
        lvl = _direction_risk(r)
        if r is not None and lvl is not None:
            inputs.append((f"{domain}={r.band}", lvl, r.field_ids, bool(r.quality_flags)))
    if inputs:
        level = _max_level([lv for _, lv, _, _ in inputs])
        level, floored = _floor_moderate(level, any(f for _, _, _, f in inputs))
        reasons = [f"RK-01:{name}" for name, _, _, _ in inputs] + (["RK-F"] if floored else [])
        out.append(
            _risk(
                RiskDimension.MARKET, level, reasons, tuple(i for _, _, f, _ in inputs for i in f)
            )
        )
    else:
        out.append(_risk(RiskDimension.MARKET, RiskLevel.NOT_ASSESSED, ["RK-01:not_assessed"], ()))

    # RK-02 liquidity risk
    liq = _reading_by_domain(ev, "liquidity")
    liq_level = _direction_risk(liq)
    if liq is not None and liq_level is not None:
        if liq_level is RiskLevel.MODERATE:  # a neutral band is "stable": Low (not Moderate)
            liq_level = RiskLevel.LOW
        liq_level, floored = _floor_moderate(liq_level, bool(liq.quality_flags))
        out.append(
            _risk(
                RiskDimension.LIQUIDITY,
                liq_level,
                [f"RK-02:liquidity={liq.band}"] + (["RK-F"] if floored else []),
                liq.field_ids,
            )
        )
    else:
        out.append(
            _risk(RiskDimension.LIQUIDITY, RiskLevel.NOT_ASSESSED, ["RK-02:not_assessed"], ())
        )

    # RK-03 leverage / derivatives
    dv = ev.derivatives
    if dv.status == "ok" and dv.band in DERIVATIVES_RISK:
        lvl = DERIVATIVES_RISK[str(dv.band)]
        reasons = [f"RK-03:derivatives={dv.band}"]
        if (
            ev.derivatives_has_active_conditions
            and RISK_ORDER[lvl] < RISK_ORDER[RiskLevel.MODERATE]
        ):
            lvl = RiskLevel.MODERATE
            reasons.append("RK-03:active_conditions")
        lvl, floored = _floor_moderate(lvl, "stale" in dv.quality_flags)
        if floored:
            reasons.append("RK-F")
        out.append(_risk(RiskDimension.LEVERAGE, lvl, reasons, dv.field_ids))
    else:
        out.append(
            _risk(RiskDimension.LEVERAGE, RiskLevel.NOT_ASSESSED, ["RK-03:not_assessed"], ())
        )

    # RK-04 volatility
    vb = ev.anomaly.volatility_band
    if vb is not None and vb in VOLATILITY_RISK:
        out.append(
            _risk(
                RiskDimension.VOLATILITY,
                VOLATILITY_RISK[vb],
                [f"RK-04:volatility={vb}"],
                ev.anomaly.volatility_field_ids,
            )
        )
    else:
        out.append(
            _risk(RiskDimension.VOLATILITY, RiskLevel.NOT_ASSESSED, ["RK-04:not_assessed"], ())
        )

    # RK-05 narrative / speculation
    act, spec = ev.retail_activity, ev.retail_speculation
    levels: list[RiskLevel] = []
    reasons5: list[str] = []
    fields5: tuple[str, ...] = ()
    if act.status == "ok" and act.band in RETAIL_ACTIVITY_RISK:
        levels.append(RETAIL_ACTIVITY_RISK[str(act.band)])
        reasons5.append(f"RK-05:activity={act.band}")
        fields5 += act.field_ids
    if spec.status == "ok" and spec.band in RETAIL_SPECULATION_RISK:
        levels.append(RETAIL_SPECULATION_RISK[str(spec.band)])
        reasons5.append(f"RK-05:speculation={spec.band}")
        fields5 += spec.field_ids
    if levels:
        lvl5 = _max_level(levels)
        if (
            len(levels) == 2
            and act.band == RETAIL_ELEVATED_ACTIVITY_BAND
            and spec.band == RETAIL_STRONG_LONG_BAND
        ):
            lvl5 = RiskLevel.HIGH  # High only when both inputs are at their extremes
        lvl5, floored = _floor_moderate(lvl5, bool(act.quality_flags) or bool(spec.quality_flags))
        if floored:
            reasons5.append("RK-F")
        out.append(_risk(RiskDimension.NARRATIVE, lvl5, reasons5, fields5))
    else:
        out.append(
            _risk(RiskDimension.NARRATIVE, RiskLevel.NOT_ASSESSED, ["RK-05:not_assessed"], ())
        )

    # RK-06 data quality (never Not assessed)
    u = t.d - t.n
    base = RiskLevel.HIGH if u >= 3 else (RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.ELEVATED)[u]
    reasons6 = [f"RK-06:unavailable={u}"]
    voting = [r for r in ev.directional if r.direction not in (None, Direction.UNAVAILABLE)]
    degraded = (
        any(r.quality_flags for r in voting)
        or ev.has_conflicts
        or "stale" in ev.derivatives.quality_flags
    )
    level6 = base
    if degraded:
        level6 = RISK_BY_ORDER[min(RISK_ORDER[base] + 1, RISK_ORDER[RiskLevel.HIGH])]
        reasons6.append("RK-06:degraded")
    out.append(_risk(RiskDimension.DATA_QUALITY, level6, reasons6, ()))
    return tuple(out)


# --------------------------------------------------------------------------- posture
@dataclass(frozen=True, slots=True)
class PostureOutcome:
    posture: Posture
    rule_id: str
    max_risk: RiskLevel
    not_assessed_count: int


def compute_posture(
    final_stance: Stance,
    confidence: Confidence,
    risks: Sequence[RiskReading],
    limits: LimitOutcome,
    ev: ExtractedEvidence,
    params: DecisionParameters,
) -> PostureOutcome:
    """PO-01..PO-08 (first match wins). The six postures are general, non-personalized context:
    none depends on a presumed holding, entry, size, horizon or risk tolerance."""
    assessed = [r.level for r in risks if r.level is not RiskLevel.NOT_ASSESSED]
    max_risk = _max_level(assessed) if assessed else RiskLevel.LOW
    n_na = sum(1 for r in risks if r.level is RiskLevel.NOT_ASSESSED)

    def out(posture: Posture, rule_id: str) -> PostureOutcome:
        return PostureOutcome(posture, rule_id, max_risk, n_na)

    if final_stance is Stance.INSUFFICIENT:
        return out(Posture.INVESTIGATE_FURTHER, "PO-01")
    if final_stance is Stance.NEUTRAL:
        return out(Posture.WAIT_FOR_CONFIRMATION, "PO-02")
    if final_stance in (Stance.STRONGLY_BEARISH, Stance.BEARISH):
        return out(Posture.REASSESS_REDUCE_RISK, "PO-07")
    if final_stance is Stance.CAUTIOUSLY_BEARISH:
        return out(Posture.AVOID_ADDING_HIGH_RISK, "PO-08")
    key = KEY_CONFIRMATION_DOMAINS[ev.scope]
    key_missing = any(
        r.domain in key and r.direction is Direction.UNAVAILABLE for r in ev.directional
    )
    if max_risk is RiskLevel.HIGH or key_missing or limits.cu02 or limits.cu03:
        return out(Posture.AVOID_ADDING_HIGH_RISK, "PO-04")
    any_cap_source_missing = (
        limits.regime_not_evaluable
        or limits.derivatives_not_evaluable
        or limits.anomaly_not_evaluable
    )
    if (
        final_stance in (Stance.BULLISH, Stance.STRONGLY_BULLISH)
        and confidence is Confidence.HIGH
        and RISK_ORDER[max_risk] <= RISK_ORDER[RiskLevel.MODERATE]
        and n_na <= params.constructive_max_not_assessed
        and not any_cap_source_missing
    ):
        return out(Posture.MONITOR_CONSTRUCTIVE, "PO-05")
    return out(Posture.MONITOR_ELEVATED_CAUTION, "PO-06")
