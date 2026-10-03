/**
 * Capital Flow Divergence Engine API client (server side) — Phase 13, read-only.
 *
 * The 10 standardized comparisons (institutional/whale/retail flow vs. price, OI vs. price,
 * funding vs. price, liquidity vs. price, and more). Nothing here labels a divergence
 * "bullish"/"bearish" or forecasts a price — the dashboard must not calculate new divergence
 * logic itself (Phase 26 constraint); it only displays this engine's own output.
 */

import { type ApiResult, getJson } from "@/lib/market";

export type DivergenceLeg = {
  label: string;
  unit: string;
  status: string;
  reason: string | null;
  direction: string | null;
  last_value: string | null;
  change_pct: string | null;
  historical_percentile: { status: string; percentile: string | null; sample_size: number };
};

export type DivergencePair = {
  comparison_id: string;
  number: number;
  title: string;
  asset: string | null;
  window_days: number;
  as_of: string;
  knowledge_time: string;
  observed_quadrant: string | null;
  is_divergent: boolean | null;
  metric_a: DivergenceLeg;
  metric_b: DivergenceLeg;
  duration: { days: number | null; capped: boolean; since: string | null } | null;
  historical_examples: unknown[];
  supporting_evidence: string[];
  contradicting_evidence: string[];
  notes: string | null;
  evidence_note: string;
};

export type DivergenceMatrix = {
  as_of: string;
  knowledge_time: string;
  window_days: number;
  comparisons: DivergencePair[];
  evidence_note: string;
  not_tracked: string[];
};

export const fetchDivergenceMatrix = (f?: typeof fetch): Promise<ApiResult<DivergenceMatrix>> =>
  getJson<DivergenceMatrix>("/api/v1/divergence/matrix", {}, f);
