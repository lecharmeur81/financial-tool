/**
 * Decision Center API client (server side) — Phase 39, read-only.
 *
 * `GET /api/v1/decision/current` serves the deterministic Decision Intelligence (Phase 38) built
 * from the latest *stored* analyst snapshot. This client never triggers a snapshot build and never
 * recalculates a stance, confidence, posture or CAP-U: every label shown comes from the response.
 */

import { type ApiResult, getJson } from "@/lib/market";

export const DECISION_ASSETS = ["BTC", "ETH", "SOL", "XRP"] as const;
export type DecisionAsset = (typeof DECISION_ASSETS)[number];

export type ScopeLabel = { code: string; text: string };
export type TextItem = { id: string; text: string | null };

export type Stance = {
  final: string;
  raw: string;
  confidence: string;
  posture: string;
  differs_from_raw: boolean;
  cap_u_applied: boolean;
  headline: string | null;
};

export type CapU = {
  rule_id: string;
  cap_source: string;
  source_field_id: string;
  binding: boolean;
  raw_stance: string;
  applied_ceiling: string;
  final_stance: string;
  final_posture: string;
  text: string | null;
  template_id: string;
};

export type EvidenceItem = {
  side: "supportive" | "adverse" | "neutral";
  domain: string;
  scope_label: ScopeLabel | null;
  strength: string;
  band: string | null;
  text: string | null;
  template_id: string | null;
  quality_flags: string[];
  field_ids: string[];
};

export type Reason = { kind: string; text: string; path: string };

export type DomainReading = {
  domain: string;
  component: string;
  role: string;
  scope_label: ScopeLabel | null;
  status: string;
  freshness: string;
  evidence_state: string;
  quality_flags: string[];
  direction: string | null;
  strength: string | null;
  band: string | null;
  freshness_info: {
    status_counts: Record<string, number>;
    latest: string | null;
    expected_latest: string | null;
    rule: string | null;
    note: string | null;
  };
  reasons: Reason[];
};

export type DecisionCurrent = {
  contract_version: string;
  asset: DecisionAsset;
  stance: Stance;
  why: { directional: TextItem[]; limits: TextItem[]; missing_context: TextItem[] };
  cap_u: CapU[];
  observed_caps: { rule_id: string; ceiling: string; binding: boolean; text: string | null }[];
  evidence: { supportive: EvidenceItem[]; adverse: EvidenceItem[]; neutral: EvidenceItem[] };
  conflict: { directional: boolean; contradictions: string[]; conflicting_tools: string[] };
  risks: { dimension: string; level: string; text: string | null }[];
  max_risk: string;
  coverage: { available: number; expected: number; missing: string[]; missing_context: string[] };
  domains: DomainReading[];
  scope_notes: string[];
  limitations: TextItem[];
  data_quality: {
    unavailable_components: string[];
    stale_components: string[];
    partial_components: string[];
    not_assessed_components: string[];
    unavailable_tools: string[];
    degraded_tools: string[];
    look_ahead_violations: string[];
    platform_limits: string[];
  };
  snapshot: {
    row_id: number | null;
    uuid: string | null;
    row_created_at: string | null;
    as_of: string;
    knowledge_time: string;
    snapshot_version: string;
    producer_payload_hash: string | null;
    producer_hash_check: "verified" | "mismatch" | "unverified";
    decision_input_hash: string;
  };
  methodology: {
    methodology_version: string;
    parameter_version: string;
    template_version: string;
    fired_rule_ids: string[];
    confidence_rule_ids: string[];
    posture_rule_id: string;
  };
  technical: {
    fields: {
      field_id: string;
      display: string;
      evidence_category: string | null;
      quality_status: string | null;
      unit: string | null;
      source: string | null;
    }[];
    fields_without_display: number;
  };
};

export const fetchDecisionCurrent = (
  asset: DecisionAsset = "BTC",
  f?: typeof fetch,
): Promise<ApiResult<DecisionCurrent>> =>
  getJson<DecisionCurrent>("/api/v1/decision/current", { asset }, f);

// --------------------------------------------------------------------------- selection

export function resolveDecisionAsset(
  query: Record<string, string | string[] | undefined>,
): DecisionAsset {
  const raw = Array.isArray(query.asset) ? query.asset[0] : query.asset;
  const asset = raw?.toUpperCase() ?? "";
  return (DECISION_ASSETS as readonly string[]).includes(asset) ? (asset as DecisionAsset) : "BTC";
}

// --------------------------------------------------------------------------- wording

/** Plain-language names for the evidence areas the engine reads. */
export const DOMAIN_LABEL: Record<string, string> = {
  institutional: "Institutional flows (US spot ETFs)",
  whale: "Large-wallet (whale) activity",
  liquidity: "Stablecoin liquidity",
  macro: "Macroeconomic backdrop",
  market_structure: "Market structure (price trend and momentum)",
  regime: "Market regime",
  derivatives: "Derivatives (leverage and funding)",
  anomaly: "Unusual-move scan",
  retail: "Retail activity",
  similarity: "Historical similarity",
  divergence: "Participant divergence",
  rotation: "Capital rotation",
  market_data: "Market data",
};

export const domainLabel = (domain: string): string => DOMAIN_LABEL[domain] ?? domain;

/** How the engine's availability state is worded. Never "zero": a missing source is not a value. */
export const EVIDENCE_STATE_LABEL: Record<string, string> = {
  available: "Data available",
  available_freshness_not_assessed: "Data available (freshness not assessed)",
  insufficient_data: "Insufficient data",
  unavailable: "Unavailable",
  stale: "Stale",
  not_applicable: "Not applicable",
  not_tracked: "Not tracked",
};

export const evidenceStateLabel = (state: string): string =>
  EVIDENCE_STATE_LABEL[state] ?? state.replace(/_/g, " ");

export const isAvailableState = (state: string): boolean =>
  state === "available" || state === "available_freshness_not_assessed";

export const REASON_KIND_LABEL: Record<string, string> = {
  score_reason: "Score note",
  freshness_note: "Freshness note",
  component_reason: "Source note",
};

/** The engine's own label for "not enough reliable evidence" (a valid outcome, not an error). */
export const INSUFFICIENT_STANCE = "Insufficient Evidence";

export const DIRECTION_LABEL: Record<string, string> = {
  S: "Supportive",
  A: "Adverse",
  N: "Neutral",
  U: "No usable reading",
};

export const CONTRADICTION_LABEL: Record<string, string> = {
  regime_disagrees: "The market regime disagrees with the direction of the other evidence.",
};

export const RISK_DIMENSION_LABEL: Record<string, string> = {
  market: "Market",
  liquidity: "Liquidity",
  leverage: "Leverage",
  volatility: "Volatility",
  narrative: "Narrative",
  data_quality: "Data quality",
};
