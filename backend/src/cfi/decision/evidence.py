"""Evidence normalisation: the stored snapshot payload -> ``EvidenceReading`` objects (L4.5 input).

Pure and DB-free. It reads only the already-stored payload it is handed (``tool_results`` under the
immutable snapshot, ADR-0041) and never rebuilds a snapshot, calls a provider, queries a database or
substitutes live data. It invents nothing: a missing tool, asset, score or field becomes an
**unavailable** reading (never neutral), and freshness is reported only when the payload actually
carries it. In v0 the derivatives overview carries no freshness, so its freshness is
``not_assessed`` (FD-01) — not fresh, not stale, no penalty, never treated as high risk.

Status distinctions preserved: fresh != stale; stale != unavailable; partial != unavailable;
not_assessed != stale; not_assessed != unavailable; unavailable != neutral.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from cfi.decision.universe import (
    ANOMALY_BANDS,
    ASSET_SPECIFIC_DOMAINS,
    DERIVATIVES_BANDS,
    DOMAIN_BANDS,
    DOMAIN_TOOL,
    EXTREME_ANOMALY_BANDS,
    REGIME_IDS,
    RETAIL_ACTIVITY_RISK,
    RETAIL_SPECULATION_RISK,
    SCOPE_DOMAINS,
    TOOL_ANOMALY,
    TOOL_DERIVATIVES,
    TOOL_DIVERGENCE,
    TOOL_MARKET_DATA,
    TOOL_REGIME,
    TOOL_RETAIL,
    TOOL_ROTATION,
    TOOL_SIMILARITY,
    Direction,
    Freshness,
    Role,
    Strength,
)

__all__ = ["AnomalyInputs", "EvidenceReading", "ExtractedEvidence", "extract_evidence"]

_NOT_OK_STATUSES = frozenset({"insufficient_data", "unavailable", "not_applicable", "not_tracked"})


@dataclass(frozen=True, slots=True)
class EvidenceReading:
    """One normalised, auditable reading (conceptual schema, methodology section 3)."""

    domain: str
    component: str
    scope: str
    role: Role
    direction: Direction | None  # Directional readings only
    strength: Strength | None  # Directional readings only
    band: str | None  # the source's own band / state id (exact string), when one was read
    status: str  # ok / unavailable / insufficient_data / not_applicable / not_tracked
    freshness: Freshness
    quality_flags: tuple[str, ...]  # subset of: stale, partial, flagged
    field_ids: tuple[str, ...]  # snapshot field ids the reading rests on
    raw_paths: tuple[str, ...]  # raw payload paths for values that are not citable field ids
    source_ids: tuple[str, ...]  # source tool ids
    evidence_category: str | None
    reason_ids: tuple[str, ...]
    template_id: str | None
    warnings: tuple[str, ...] = ()
    strong_band: bool = False  # the band itself is a "strong" band (before freshness/completeness)

    @property
    def available(self) -> bool:
        return self.status == "ok" and self.direction not in (None, Direction.UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class AnomalyInputs:
    """What the anomaly tool tells the cap/risk rules (CAP-U evaluability, section 7.3)."""

    tool_ok: bool
    volatility_band: str | None
    volatility_field_ids: tuple[str, ...]
    critical_field_ids: tuple[str, ...]  # entries whose band is extreme_high / extreme_low
    any_notable: bool

    @property
    def any_critical(self) -> bool:
        return bool(self.critical_field_ids)

    @property
    def evaluable(self) -> bool:
        # Evaluated and applies, or evaluated and does not apply (volatility entry readable).
        return self.any_critical or self.volatility_band is not None


@dataclass(frozen=True, slots=True)
class ExtractedEvidence:
    scope: str
    directional: tuple[EvidenceReading, ...]  # in the scope's domain order
    regime: EvidenceReading
    derivatives: EvidenceReading
    derivatives_has_active_conditions: bool
    anomaly: AnomalyInputs
    anomaly_reading: EvidenceReading
    retail_activity: EvidenceReading
    retail_speculation: EvidenceReading
    context: tuple[EvidenceReading, ...]
    has_conflicts: bool
    data_quality_state: str | None
    not_tracked: tuple[str, ...]
    observed_score_versions: tuple[tuple[str, str], ...] = field(default=())


# --------------------------------------------------------------------------- payload helpers
def _tool_data(payload: dict[str, Any], tool_id: str) -> dict[str, Any] | None:
    results = payload.get("tool_results")
    if not isinstance(results, dict):
        return None
    result = results.get(tool_id)
    if not isinstance(result, dict) or result.get("status") != "ok":
        return None
    data = result.get("data")
    return data if isinstance(data, dict) else None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _freshness_status(node: Any) -> str | None:
    """A freshness node is either ``{"status": ...}`` or a bare status string."""
    if isinstance(node, dict):
        status = node.get("status")
        return status if isinstance(status, str) else None
    return node if isinstance(node, str) else None


def _find_asset(items: Any, scope: str) -> tuple[int, dict[str, Any]] | None:
    """Locate the item for ``scope`` by key (never by position)."""
    if not isinstance(items, list):
        return None
    for i, item in enumerate(items):
        if isinstance(item, dict) and item.get("asset") == scope:
            return i, item
    return None


def _source_flags(data: dict[str, Any]) -> tuple[bool, bool, bool, tuple[str, ...]]:
    """(any enabled source stale, any enabled source flagged, any source info present, ids)."""
    sources = _as_dict(data.get("data_quality")).get("sources")
    if not isinstance(sources, list):
        return False, False, False, ()
    stale = False
    flagged = False
    present = False
    ids: list[str] = []
    for j, src in enumerate(sources):
        if not isinstance(src, dict) or src.get("enabled") is not True:
            continue
        present = True
        if _freshness_status(src.get("freshness")) == "stale":
            stale = True
            ids.append(f".data_quality.sources[{j}].freshness")
        flagged_points = _decimal(src.get("flagged_points"))
        if flagged_points is not None and flagged_points > 0:
            flagged = True
    return stale, flagged, present, tuple(ids)


def _unavailable(
    *,
    domain: str,
    component: str,
    scope: str,
    role: Role,
    tool_id: str,
    status: str = "unavailable",
    reason_ids: tuple[str, ...] = ("RD-01",),
    template_id: str | None = None,
    warnings: tuple[str, ...] = (),
    freshness: Freshness = Freshness.NO_DATA,
    band: str | None = None,
) -> EvidenceReading:
    return EvidenceReading(
        domain=domain,
        component=component,
        scope=scope,
        role=role,
        direction=Direction.UNAVAILABLE if role is Role.DIRECTIONAL else None,
        strength=Strength.MISSING if role is Role.DIRECTIONAL else None,
        band=band,
        status=status if status in _NOT_OK_STATUSES else "unavailable",
        freshness=freshness,
        quality_flags=(),
        field_ids=(),
        raw_paths=(),
        source_ids=(tool_id,),
        evidence_category=None,
        reason_ids=reason_ids,
        template_id=template_id,
        warnings=warnings,
    )


def _direction_code(direction: Direction, strong: bool) -> str:
    if direction is Direction.NEUTRAL:
        return "N"
    return f"{direction.value}{2 if strong else 1}"


# --------------------------------------------------------------------------- directional
def _directional_reading(domain: str, payload: dict[str, Any], scope: str) -> EvidenceReading:
    tool_id = DOMAIN_TOOL[domain]
    na = _unavailable(
        domain=domain,
        component=f"{domain}.score",
        scope=scope,
        role=Role.DIRECTIONAL,
        tool_id=tool_id,
        template_id=f"DIR.{domain}.U",
    )
    data = _tool_data(payload, tool_id)
    if data is None:
        return na

    asset_fresh: str | None = None
    asset_fresh_paths: tuple[str, ...] = ()
    raw_paths: tuple[str, ...] = ()
    stale_sources = False
    flagged = False
    sources_present = False
    source_stale_ids: tuple[str, ...] = ()
    if domain in ASSET_SPECIFIC_DOMAINS:
        found = _find_asset(data.get("assets"), scope)
        if found is None:
            return _replace_reasons(na, ("RD-01", "MD-01"))
        index, item = found
        base = f".assets[{index}]"
        score = _as_dict(item.get("score"))
        asset_fresh = _freshness_status(item.get("freshness"))
        if item.get("freshness") is not None:
            asset_fresh_paths = (f"{tool_id}{base}.freshness.status",)
        score_path = f"{base}.score"
        field_ids: tuple[str, ...] = (f"{tool_id}{score_path}", *asset_fresh_paths)
        # band is not a citable snapshot field for institutional / whale (the score object carries
        # a ``value`` key, so the flattener stores one envelope field): cite the raw path as well.
        raw_paths = (f"tool_results.{tool_id}.data{score_path}.band",)
    else:
        score = _as_dict(data.get("score"))
        stale_sources, flagged, sources_present, source_stale_ids = _source_flags(data)
        score_path = ".score"
        field_ids = (
            f"{tool_id}{score_path}.band",
            f"{tool_id}{score_path}.status",
            *(f"{tool_id}{p}" for p in source_stale_ids),
        )
        raw_paths = ()

    score_status = score.get("status")
    if not score or score_status != "ok":
        status = score_status if score_status in _NOT_OK_STATUSES else "unavailable"
        reasons = ("RD-01", "MD-02") if status == "insufficient_data" else ("RD-01",)
        return _replace_reasons(na, reasons, status=status)
    if asset_fresh == "no_data":
        return _replace_reasons(na, ("RD-01",))

    band = score.get("band")
    mapping = DOMAIN_BANDS[domain]
    if not isinstance(band, str) or band not in mapping:
        return _replace_reasons(
            na, ("RD-09",), warnings=(f"{domain}: unrecognised band {band!r} (data-contract)",)
        )
    direction, strong = mapping[band]

    flags: list[str] = []
    stale = asset_fresh == "stale" or stale_sources
    if stale:
        flags.append("stale")
    weight = _decimal(score.get("available_weight"))
    if weight is not None and weight < 1:
        flags.append("partial")
    if flagged:
        flags.append("flagged")
    reasons_list = ["RD-02"]
    if "stale" in flags:
        reasons_list.append("RD-06")
    if "partial" in flags:
        reasons_list.append("RD-07")
    if "flagged" in flags:
        reasons_list.append("RD-08")
    if flags:
        strength = Strength.WEAK
        reasons_list.append("RD-05" if strong else "RD-03")
    elif strong:
        strength = Strength.STRONG
        reasons_list.append("RD-04")
    else:
        strength = Strength.MODERATE
        reasons_list.append("RD-03")

    if stale:
        freshness = Freshness.STALE
    elif asset_fresh == "fresh" or (sources_present and domain not in ASSET_SPECIFIC_DOMAINS):
        freshness = Freshness.FRESH
    else:
        freshness = Freshness.NOT_ASSESSED
    return EvidenceReading(
        domain=domain,
        component=f"{domain}.score",
        scope=scope,
        role=Role.DIRECTIONAL,
        direction=direction,
        strength=strength,
        band=band,
        status="ok",
        freshness=freshness,
        quality_flags=tuple(flags),
        field_ids=field_ids,
        raw_paths=raw_paths,
        source_ids=(tool_id,),
        evidence_category=_category(score),
        reason_ids=tuple(reasons_list),
        template_id=f"DIR.{domain}.{_direction_code(direction, strong)}",
        strong_band=strong,
    )


def _category(score: dict[str, Any]) -> str | None:
    value = score.get("evidence_category")
    return value if isinstance(value, str) else None


def _replace_reasons(
    reading: EvidenceReading,
    reasons: tuple[str, ...],
    *,
    status: str | None = None,
    warnings: tuple[str, ...] | None = None,
) -> EvidenceReading:
    return EvidenceReading(
        domain=reading.domain,
        component=reading.component,
        scope=reading.scope,
        role=reading.role,
        direction=reading.direction,
        strength=reading.strength,
        band=reading.band,
        status=reading.status if status is None else status,
        freshness=reading.freshness,
        quality_flags=reading.quality_flags,
        field_ids=reading.field_ids,
        raw_paths=reading.raw_paths,
        source_ids=reading.source_ids,
        evidence_category=reading.evidence_category,
        reason_ids=reasons,
        template_id=reading.template_id,
        warnings=reading.warnings if warnings is None else warnings,
        strong_band=reading.strong_band,
    )


# --------------------------------------------------------------------------- risk / context
def _regime_reading(payload: dict[str, Any], scope: str) -> EvidenceReading:
    data = _tool_data(payload, TOOL_REGIME)
    na = _unavailable(
        domain="regime",
        component="regime.regime_id",
        scope=scope,
        role=Role.CONTEXT,
        tool_id=TOOL_REGIME,
        reason_ids=("CTX.regime.missing",),
        template_id="CTX.regime.U",
    )
    if data is None:
        return na
    regime_id = data.get("regime_id")
    if data.get("status") != "ok" or regime_id not in REGIME_IDS:
        status = data.get("status")
        return _replace_reasons(
            na, ("CTX.regime.missing",), status=status if isinstance(status, str) else None
        )
    return EvidenceReading(
        domain="regime",
        component="regime.regime_id",
        scope=scope,
        role=Role.CONTEXT,
        direction=None,
        strength=None,
        band=str(regime_id),
        status="ok",
        freshness=Freshness.NOT_ASSESSED,
        quality_flags=(),
        field_ids=(f"{TOOL_REGIME}.regime_id",),
        raw_paths=(),
        source_ids=(TOOL_REGIME,),
        evidence_category="Regime Classification",
        reason_ids=(),
        template_id=f"CTX.regime.{regime_id}",
    )


def _derivatives_reading(payload: dict[str, Any], scope: str) -> tuple[EvidenceReading, bool]:
    na = _unavailable(
        domain="derivatives",
        component="derivatives.band",
        scope=scope,
        role=Role.RISK,
        tool_id=TOOL_DERIVATIVES,
        reason_ids=("RD-01",),
        freshness=Freshness.NOT_ASSESSED,
    )
    data = _tool_data(payload, TOOL_DERIVATIVES)
    if data is None:
        return na, False
    found = _find_asset(data.get("assets"), scope)
    if found is None:
        return na, False
    index, item = found
    base = f".assets[{index}]"
    score_status = item.get("score_status")
    band = item.get("band")
    if score_status != "ok" or band not in DERIVATIVES_BANDS:
        status = score_status if score_status in _NOT_OK_STATUSES else "unavailable"
        return _replace_reasons(na, ("RD-01",), status=status), False
    # Freshness is read only if the payload actually carries it (v0: it does not).
    fresh_status = _freshness_status(item.get("freshness"))
    if fresh_status == "stale":
        freshness = Freshness.STALE
    elif fresh_status == "fresh":
        freshness = Freshness.FRESH
    elif fresh_status == "no_data":
        freshness = Freshness.NO_DATA
    else:
        freshness = Freshness.NOT_ASSESSED
    conditions = item.get("active_conditions")
    has_conditions = isinstance(conditions, list) and len(conditions) > 0
    flags = ("stale",) if freshness is Freshness.STALE else ()
    return (
        EvidenceReading(
            domain="derivatives",
            component="derivatives.band",
            scope=scope,
            role=Role.RISK,
            direction=None,
            strength=None,
            band=str(band),
            status="ok",
            freshness=freshness,
            quality_flags=flags,
            field_ids=(f"{TOOL_DERIVATIVES}{base}.band", f"{TOOL_DERIVATIVES}{base}.score_status"),
            raw_paths=(),
            source_ids=(TOOL_DERIVATIVES,),
            evidence_category="Calculated Metric",
            reason_ids=(),
            template_id=None,
        ),
        has_conditions,
    )


def _anomaly(payload: dict[str, Any], scope: str) -> tuple[AnomalyInputs, EvidenceReading]:
    data = _tool_data(payload, TOOL_ANOMALY)
    if data is None:
        return (
            AnomalyInputs(False, None, (), (), False),
            _unavailable(
                domain="anomaly",
                component="anomaly.volatility",
                scope=scope,
                role=Role.RISK,
                tool_id=TOOL_ANOMALY,
                template_id="CTX.anomaly.U",
            ),
        )
    entries = data.get("anomalies")
    critical: list[str] = []
    vol_band: str | None = None
    vol_ids: tuple[str, ...] = ()
    any_notable = False
    for i, entry in enumerate(entries if isinstance(entries, list) else []):
        if not isinstance(entry, dict):
            continue
        band = entry.get("band")
        if band in EXTREME_ANOMALY_BANDS:
            critical.append(f"{TOOL_ANOMALY}.anomalies[{i}].band")
        elif band in ("notable_high", "notable_low"):
            any_notable = True
        if vol_band is None and entry.get("metric_id") == "volatility" and band in ANOMALY_BANDS:
            vol_band = str(band)
            vol_ids = (f"{TOOL_ANOMALY}.anomalies[{i}].band",)
    inputs = AnomalyInputs(True, vol_band, vol_ids, tuple(critical), any_notable)
    if critical:
        template = "CTX.anomaly.extreme"
    elif any_notable:
        template = "CTX.anomaly.notable"
    else:
        template = "CTX.anomaly.none"
    reading = EvidenceReading(
        domain="anomaly",
        component="anomaly.volatility",
        scope=scope,
        role=Role.RISK,
        direction=None,
        strength=None,
        band=vol_band,
        status="ok" if inputs.evaluable else "unavailable",
        freshness=Freshness.NOT_ASSESSED,
        quality_flags=(),
        field_ids=vol_ids + tuple(critical),
        raw_paths=(),
        source_ids=(TOOL_ANOMALY,),
        evidence_category="Statistical Signal",
        reason_ids=(),
        template_id=template if inputs.evaluable else "CTX.anomaly.U",
    )
    return inputs, reading


def _retail(payload: dict[str, Any], scope: str) -> tuple[EvidenceReading, EvidenceReading]:
    data = _tool_data(payload, TOOL_RETAIL)
    stale = False
    if data is not None:
        stale, _, _, _ = _source_flags(data)
    out: list[EvidenceReading] = []
    for key, mapping, component in (
        ("activity_score", RETAIL_ACTIVITY_RISK, "retail.activity"),
        ("speculation_score", RETAIL_SPECULATION_RISK, "retail.speculation"),
    ):
        node = _as_dict(_as_dict(data).get(key)) if data is not None else {}
        band = node.get("band")
        if data is not None and node.get("status") == "ok" and band in mapping:
            out.append(
                EvidenceReading(
                    domain="retail",
                    component=component,
                    scope=scope,
                    role=Role.RISK,
                    direction=None,
                    strength=None,
                    band=str(band),
                    status="ok",
                    freshness=Freshness.STALE if stale else Freshness.NOT_ASSESSED,
                    quality_flags=("stale",) if stale else (),
                    field_ids=(f"{TOOL_RETAIL}.{key}.band", f"{TOOL_RETAIL}.{key}.status"),
                    raw_paths=(),
                    source_ids=(TOOL_RETAIL,),
                    evidence_category="Calculated Metric",
                    reason_ids=(),
                    template_id=None,
                )
            )
        else:
            out.append(
                _unavailable(
                    domain="retail",
                    component=component,
                    scope=scope,
                    role=Role.RISK,
                    tool_id=TOOL_RETAIL,
                )
            )
    return out[0], out[1]


def _context_readings(payload: dict[str, Any], scope: str) -> tuple[EvidenceReading, ...]:
    """Similarity, divergence, rotation and market data: displayed only (decision D-L). None of
    them is ever read by the tally, the caps, the risk dimensions or the confidence rules."""

    def reading(
        domain: str, tool_id: str, ok: bool, template: str | None, unavailable_template: str | None
    ) -> EvidenceReading:
        if not ok:
            return _unavailable(
                domain=domain,
                component=f"{domain}.context",
                scope=scope,
                role=Role.CONTEXT,
                tool_id=tool_id,
                template_id=unavailable_template,
            )
        return EvidenceReading(
            domain=domain,
            component=f"{domain}.context",
            scope=scope,
            role=Role.CONTEXT,
            direction=None,
            strength=None,
            band=None,
            status="ok",
            freshness=Freshness.NOT_ASSESSED,
            quality_flags=(),
            field_ids=(f"{tool_id}.status",),
            raw_paths=(f"tool_results.{tool_id}.status",),
            source_ids=(tool_id,),
            evidence_category=None,
            reason_ids=(),
            template_id=template,
        )

    out: list[EvidenceReading] = []
    sim = _tool_data(payload, TOOL_SIMILARITY)
    out.append(
        reading(
            "similarity",
            TOOL_SIMILARITY,
            sim is not None and sim.get("status") in (None, "ok"),
            "CTX.similarity.ok",
            "CTX.similarity.U",
        )
    )
    div = _tool_data(payload, TOOL_DIVERGENCE)
    comparisons = div.get("comparisons") if div is not None else None
    div_ok = isinstance(comparisons, list) and len(comparisons) > 0
    divergent = div_ok and any(
        isinstance(c, dict) and c.get("is_divergent") is True
        for c in (comparisons if isinstance(comparisons, list) else [])
    )
    out.append(
        reading(
            "divergence",
            TOOL_DIVERGENCE,
            div_ok,
            "CTX.divergence.true" if divergent else "CTX.divergence.false",
            "CTX.divergence.U",
        )
    )
    rot = _tool_data(payload, TOOL_ROTATION)
    pairs = rot.get("pairs") if rot is not None else None
    rot_ok = isinstance(pairs, list) and len(pairs) > 0
    possible = rot_ok and any(
        isinstance(p, dict)
        and _as_dict(p.get("inferred_capital_rotation")).get("status") == "possible_rotation"
        for p in (pairs if isinstance(pairs, list) else [])
    )
    out.append(
        reading(
            "rotation",
            TOOL_ROTATION,
            rot_ok,
            "CTX.rotation.possible" if possible else "CTX.rotation.none",
            "CTX.rotation.U",
        )
    )
    md = _tool_data(payload, TOOL_MARKET_DATA)
    out.append(reading("market_data", TOOL_MARKET_DATA, md is not None, None, None))
    return tuple(out)


def _observed_versions(payload: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for domain in ("liquidity", "macro", "market_structure"):
        data = _tool_data(payload, DOMAIN_TOOL[domain])
        version = _as_dict(_as_dict(data).get("score")).get("version") if data else None
        if isinstance(version, str):
            out.append((domain, version))
    return tuple(out)


# --------------------------------------------------------------------------- entry point
def extract_evidence(payload: dict[str, Any], scope: str) -> ExtractedEvidence:
    """Normalise ``payload`` for ``scope``. Raises ``ValueError`` for an undefined scope."""
    if scope not in SCOPE_DOMAINS:
        raise ValueError(f"unsupported scope {scope!r}; defined scopes: {sorted(SCOPE_DOMAINS)}")
    directional = tuple(_directional_reading(d, payload, scope) for d in SCOPE_DOMAINS[scope])
    derivatives, has_conditions = _derivatives_reading(payload, scope)
    anomaly_inputs, anomaly_reading = _anomaly(payload, scope)
    activity, speculation = _retail(payload, scope)
    not_tracked = payload.get("not_tracked")
    dq_state = payload.get("data_quality_state")
    return ExtractedEvidence(
        scope=scope,
        directional=directional,
        regime=_regime_reading(payload, scope),
        derivatives=derivatives,
        derivatives_has_active_conditions=has_conditions,
        anomaly=anomaly_inputs,
        anomaly_reading=anomaly_reading,
        retail_activity=activity,
        retail_speculation=speculation,
        context=_context_readings(payload, scope),
        has_conflicts=payload.get("has_conflicts") is True,
        data_quality_state=dq_state if isinstance(dq_state, str) else None,
        not_tracked=tuple(str(x) for x in not_tracked) if isinstance(not_tracked, list) else (),
        observed_score_versions=_observed_versions(payload),
    )
