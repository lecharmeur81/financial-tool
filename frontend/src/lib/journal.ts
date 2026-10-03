/**
 * Decision Journal API client (server side) — Phase 25, read-only here.
 *
 * The user's own recorded decisions — thesis, decision-time evidence, and later outcomes.
 * Descriptive review only, never a ranking, never automatic decision generation. The dashboard
 * links to the full journal views rather than duplicating them (Phase 26 constraint).
 */

import { type ApiResult, getJson } from "@/lib/market";

export type DecisionStatus = {
  decision_id: string;
  decision_time: string;
  asset: string;
  decision_type: string;
  thesis: string;
  confidence: string | null;
  status: string;
  outcome: string | null;
  market_regime_label: string | null;
  created_at: string;
  updated_at: string;
};

export type DecisionStats = {
  total_decisions: number;
  open_decisions: number;
  resolved_decisions: number;
  invalidated_decisions: number;
  cancelled_decisions: number;
  thesis_supported_count: number;
  thesis_contradicted_count: number;
  invalidation_occurred_count: number;
  average_time_to_resolution_hours: string | null;
  disclaimer: string;
};

export const fetchRecentDecisions = (
  limit = 5,
  f?: typeof fetch,
): Promise<ApiResult<DecisionStatus[]>> =>
  getJson<DecisionStatus[]>("/api/v1/journal/decisions", { limit: String(limit) }, f);

export const fetchDecisionStats = (f?: typeof fetch): Promise<ApiResult<DecisionStats>> =>
  getJson<DecisionStats>("/api/v1/journal/stats", {}, f);
