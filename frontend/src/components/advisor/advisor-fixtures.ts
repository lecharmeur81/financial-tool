/** Raw `advisor_brief.v0` bodies (synthetic test data; not real market data). */
import { type AdvisorBrief, parseAdvisorBrief } from "@/lib/advisor";

type Raw = Record<string, unknown>;

const LAYERS = {
  observed_data: "A stored observation (price, volume), as recorded.",
  calculated_signal: "A metric or score the platform computed from observed data.",
  regime_assessment: "The platform's classified market regime; context, not a vote.",
  historical_analogue: "A description of similar past periods; never a prediction.",
  hypothesis: "An inferred, hedged explanation; never an observed fact.",
  risk_reading: "A risk or stress reading; not directional evidence.",
  context_reading: "Other context the platform reports.",
  deterministic_assessment: "A rule-based synthesis of the above (not a forecast).",
};

const NOT_CLAIMED = [
  { id: "ADV-NOT-ADVICE", text: "Not personalized financial advice." },
  { id: "ADV-NOT-PREDICTION", text: "Nothing here predicts a price or an outcome." },
  { id: "ADV-NO-TRADING", text: "This service places no orders." },
];

/** The current real-data state: Insufficient Evidence, with gaps and no usable invalidation. */
export function insufficientRaw(asset = "BTC"): Raw {
  return {
    contract_version: "advisor_brief.v0",
    asset,
    answered_from: {},
    snapshot: { as_of: "2026-10-19T08:00:00Z", row_id: 42 },
    layers: LAYERS,
    assessment: {
      layer: "deterministic_assessment",
      stance: {
        final: "Insufficient Evidence",
        raw: "Insufficient Evidence",
        confidence: "Insufficient Evidence",
        posture: "INVESTIGATE FURTHER",
        headline: null,
        differs_from_raw: false,
        cap_u_applied: false,
      },
      why: { directional: [], limits: ["Only 1 of 5 core evidence areas has usable data."] },
      investment_state: {
        status: "no_candidate",
        discovery_type: null,
        decision_state: "insufficient_evidence",
        decision_reasons: ["DI-INSUFFICIENT-EVIDENCE"],
        gated: false,
        gate_reasons: [],
      },
      state_notice: "Decision support only.",
    },
    signals: [],
    readings: [
      {
        layer: "calculated_signal",
        domain: "institutional",
        role: "Directional",
        evidence_state: "unavailable",
        status: "unavailable",
        freshness: "unknown",
        direction: null,
        strength: null,
        band: null,
        quality_flags: [],
      },
      {
        layer: "calculated_signal",
        domain: "whale",
        role: "Directional",
        evidence_state: "stale",
        status: "ok",
        freshness: "stale",
        direction: "supportive",
        strength: 2,
        band: "S2",
        quality_flags: ["stale"],
      },
      {
        layer: "regime_assessment",
        domain: "regime",
        role: "Context",
        evidence_state: "available",
        status: "ok",
        freshness: "fresh",
        direction: null,
        strength: null,
        band: null,
        quality_flags: [],
      },
    ],
    uncertainty: {
      confidence: "Insufficient Evidence",
      directional_conflict: false,
      contradictions: [],
      conflicting_tools: [],
      limited_by_caps: false,
      binding_caps: [],
      limitations: ["Formal confirmation is a future capability."],
      scope_notes: [],
      missing_context: ["Macro backdrop is not available."],
    },
    data_gaps: {
      has_gaps: true,
      items: [
        {
          kind: "reading_not_usable",
          domain: "institutional",
          evidence_state: "unavailable",
          reasons: ["ETF flow source returned nothing."],
        },
        { kind: "missing_directional_domain", domain: "macro" },
        { kind: "stale_component", ref: "whale.exchange_flows" },
        { kind: "partial_component", ref: "derivatives.options" },
        { kind: "not_assessed_component", ref: "retail.sentiment" },
        { kind: "investment_state_not_conclusive", reason_id: "DI-X", ref: "coverage_below_floor" },
      ],
    },
    risk: {
      decision_risks: [
        { dimension: "Market stress", level: "Moderate", text: "Volatility is elevated." },
      ],
      max_decision_risk: "Moderate",
      investment_risk_assessment: {},
      market_risks_detected: [],
      findings: null,
    },
    invalidation: null,
    reassessment: [
      {
        kind: "new_snapshot",
        ref: "RA-1",
        when: "When a newer snapshot is stored",
        evaluable: true,
        field_ids: [],
      },
      {
        kind: "missing_evidence_arrives",
        ref: "RA-2",
        when: "When ETF flows return",
        evaluable: false,
        field_ids: [],
      },
    ],
    field_trace: {},
    not_claimed: NOT_CLAIMED,
  };
}

/** A conclusive-looking brief: signals present, invalidation conditions with mixed results. */
export function candidateRaw(asset = "BTC"): Raw {
  const base = insufficientRaw(asset);
  return {
    ...base,
    assessment: {
      layer: "deterministic_assessment",
      stance: {
        final: "Bullish",
        raw: "Bullish",
        confidence: "Moderate",
        posture: "MONITOR WITH ELEVATED CAUTION",
        headline: "More of the available evidence leans supportive than adverse.",
        differs_from_raw: false,
        cap_u_applied: false,
      },
      why: { directional: ["Institutional flows lean supportive."], limits: [] },
      investment_state: {
        status: "candidate",
        discovery_type: "x",
        decision_state: "candidate_unresolved",
        decision_reasons: ["DI-UNRESOLVED"],
        gated: false,
        gate_reasons: [],
      },
      state_notice: "Decision support only.",
    },
    signals: [
      {
        layer: "calculated_signal",
        side: "supportive",
        domain: "institutional",
        scope: "asset_specific",
        strength: 2,
        band: "S2",
        text: "Spot ETF inflows are above their recent range.",
        quality_flags: [],
        field_ids: ["f1"],
      },
      {
        layer: "hypothesis",
        side: "neutral",
        domain: "rotation",
        scope: "market_wide",
        strength: 0,
        band: "N",
        text: "A rotation toward large caps is one possible reading.",
        quality_flags: ["partial"],
        field_ids: ["f2"],
      },
    ],
    invalidation: {
      summary: "cannot_evaluate",
      conditions: [
        {
          condition_id: "INV-1",
          name: "Flow reversal",
          meaning: "Flows turn adverse.",
          result: "not_triggered",
          monitor_field_ids: [],
        },
        {
          condition_id: "INV-2",
          name: "Funding spike",
          meaning: "Funding becomes extreme.",
          result: "cannot_evaluate",
          monitor_field_ids: [],
        },
      ],
    },
  };
}

export const parsed = (raw: Raw): AdvisorBrief => {
  const brief = parseAdvisorBrief(raw);
  if (!brief) throw new Error("fixture does not parse");
  return brief;
};
