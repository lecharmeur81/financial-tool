/**
 * Market Anomaly Engine API client (server side) — Phase 19, read-only.
 *
 * Unusual behavior detected against each metric's own historical distribution and percentile
 * rank — never an arbitrary fixed threshold, never labelled bullish or bearish. The dashboard
 * displays this engine's own bands and magnitudes unchanged (Phase 26 constraint).
 */

import { type ApiResult, getJson } from "@/lib/market";

export const ACTIVE_BANDS = new Set(["extreme_high", "notable_high", "extreme_low", "notable_low"]);

export type Anomaly = {
  metric_id: string;
  category: string;
  label: string;
  asset: string | null;
  unit: string;
  source: string;
  evidence_class: string;
  proxy_caveat: string | null;
  timestamp: string | null;
  status: string;
  reason: string | null;
  current_value: string | null;
  historical_percentile: { status: string; percentile: string | null; sample_size: number };
  band: string | null;
  magnitude: { value: string | null; method: string | null };
  duration: { days: number | null; capped: boolean; since: string | null };
  possible_interpretations: string[];
  contradicting_evidence: unknown[];
  data_quality: { status: string; points_considered: number; flagged_points: number };
};

export type AnomalyScan = {
  asset: string;
  as_of: string;
  knowledge_time: string;
  bands_version: string;
  anomalies: Anomaly[];
  evidence_note: string;
  not_tracked: string[];
};

export const fetchAnomalyScan = (f?: typeof fetch): Promise<ApiResult<AnomalyScan>> =>
  getJson<AnomalyScan>("/api/v1/anomaly/scan", {}, f);
