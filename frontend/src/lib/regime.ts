/**
 * Market Regime API client (server side) — Phase 14, read-only.
 *
 * Confidence means confidence that current conditions satisfy the regime's own definition. It is
 * NOT a probability that price will rise or fall, and the dashboard must say so wherever the
 * number appears (`confidence_semantic_note` carries the backend's own wording verbatim).
 */

import { type ApiResult, getJson } from "@/lib/market";

export type RegimeOutcome = {
  condition_id: string;
  label: string;
  metric_key: string;
  weight: string | null;
  rationale: string;
  value: string | null;
  condition: string | null;
};

export type RegimeCurrent = {
  asset: string;
  as_of: string;
  knowledge_time: string;
  evidence_note: string;
  regime_id: string | null;
  label: string | null;
  confidence: string | null;
  confidence_semantic_note: string;
  status: "ok" | "insufficient_data";
  reason: string | null;
  held_by_hysteresis: boolean;
  regime_start_date: string | null;
  regime_duration_days: number;
  regime_duration_capped: boolean;
  contributing_metrics: RegimeOutcome[];
  contradicting_metrics: RegimeOutcome[];
  not_tracked: string[];
};

export const fetchCurrentRegime = (f?: typeof fetch): Promise<ApiResult<RegimeCurrent>> =>
  getJson<RegimeCurrent>("/api/v1/regime/current", {}, f);
