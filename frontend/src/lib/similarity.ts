/**
 * Historical Similarity Engine API client (server side) — Phase 15, read-only.
 *
 * Compares the current 9-feature market state against sampled historical dates. The similarity
 * score is a Statistical Signal (L3) over already-published Calculated Metrics — never a
 * prediction. Each analogue's regime label cites Phase 14's own classification for that date.
 * Forward returns and maximum drawdown are realized outcomes, shown only once genuinely knowable
 * as of the query's own `as_of` — never a forecast (backend `evidence_note`, carried through
 * unchanged). Phase 36 constraint: this is historical context only, not a prediction.
 */

import { type ApiResult, getJson } from "@/lib/market";

export type SimilarityFeatureComparison = {
  feature_id: string;
  weight: string | null;
  query_value: string | null;
  candidate_value: string | null;
  query_normalized: string | null;
  candidate_normalized: string | null;
  abs_diff_normalized: string | null;
};

export type SimilarityForwardReturn = {
  horizon_days: number;
  status: string;
  value_pct: string | null;
  reason: string | null;
};

export type SimilarityAnalogue = {
  date: string | null;
  similarity_score: string | null;
  available_weight: string | null;
  regime: {
    regime_id: string | null;
    label: string | null;
    confidence: string | null;
    status: string;
  };
  forward_returns: SimilarityForwardReturn[];
  max_drawdown: {
    window_days: number;
    status: string;
    value_pct: string | null;
    partial: boolean;
    reason: string | null;
  };
  volatility_annualized_pct: string | null;
  compared_features: SimilarityFeatureComparison[];
};

export type SimilarityDistributionPoint = {
  horizon_days: number;
  status: string;
  count: number;
  min_pct: string | null;
  p25_pct: string | null;
  median_pct: string | null;
  p75_pct: string | null;
  max_pct: string | null;
  reason: string | null;
};

export type SimilarityCurrent = {
  asset: string;
  as_of: string;
  knowledge_time: string;
  evidence_note: string;
  not_tracked: string[];
  status: "ok" | "insufficient_data";
  reason?: string | null;
  query_available_weight?: string | null;
  analogues: SimilarityAnalogue[];
  distribution: SimilarityDistributionPoint[];
  candidates_evaluated?: number;
  candidates_selected_for_distribution?: number;
};

export type SimilarityCatalog = {
  version: string;
  evidence_note: string;
  benchmark_asset: string;
  parameters: Record<string, unknown>;
  features: {
    feature_id: string;
    label: string;
    weight: string | null;
    normalization: string;
    unit: string;
    evidence: string;
    clamp_min: string | null;
    clamp_max: string | null;
  }[];
  not_tracked: string[];
};

export const fetchSimilarityCurrent = (f?: typeof fetch): Promise<ApiResult<SimilarityCurrent>> =>
  getJson<SimilarityCurrent>("/api/v1/similarity/current", {}, f);

export const fetchSimilarityCatalog = (f?: typeof fetch): Promise<ApiResult<SimilarityCatalog>> =>
  getJson<SimilarityCatalog>("/api/v1/similarity/catalog", {}, f);
