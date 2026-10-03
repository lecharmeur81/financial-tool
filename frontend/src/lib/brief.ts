/**
 * Daily Market Brief API client (server side) — Phase 22, read-only.
 *
 * Reads the latest completed AI Analyst brief. `response` follows the 12-section schema the
 * AI Analyst always produces (`cfi.analyst.schema.AnalystResponse`, Phase 21 R6): summary,
 * evidence, contradicting evidence, market regime, key changes (by domain), participant
 * behavior (institutional/whale/retail, kept distinct), derivatives/liquidity context,
 * historical context, risks, scenarios, invalidation conditions, data quality. The dashboard
 * and the full brief page both display this unchanged — never a second interpretation of it
 * (Phase 26 constraint).
 */

import { type ApiResult, getJson } from "@/lib/market";

export type EvidenceItem = { text: string; field_ids: string[] };

export type Scenario = {
  label: string;
  description: string;
  supporting_evidence: EvidenceItem[];
  contradicting_evidence: EvidenceItem[];
  strengthening_conditions: string[];
  invalidation_conditions: string[];
};

export type AnalystResponse = {
  summary: string;
  evidence: EvidenceItem[];
  contradicting_evidence: EvidenceItem[];
  market_regime: string;
  key_changes: {
    macro: EvidenceItem[];
    market_structure: EvidenceItem[];
    divergences: EvidenceItem[];
    anomalies: EvidenceItem[];
    capital_rotation: EvidenceItem[];
  };
  capital_participant_behavior: {
    institutional: EvidenceItem[];
    whale: EvidenceItem[];
    retail: EvidenceItem[];
  };
  derivatives_liquidity_context: { derivatives: EvidenceItem[]; liquidity: EvidenceItem[] };
  historical_context: EvidenceItem[];
  risks_uncertainties: string[];
  scenarios: Scenario[];
  invalidation_conditions: string[];
  data_quality: string;
};

export type BriefStatus = {
  brief_id: string;
  status: string;
  reporting_period_start: string;
  reporting_period_end: string;
  prompt_version: string | null;
  analyst_version: string | null;
  model: string | null;
  response: AnalystResponse | null;
  validation_status: string | null;
  validation_errors: string[] | null;
  attempt_count: number;
  tools_called: string[] | null;
  data_quality_state: string | null;
  changes: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export const fetchLatestBrief = (f?: typeof fetch): Promise<ApiResult<BriefStatus>> =>
  getJson<BriefStatus>("/api/v1/brief/latest", {}, f);
