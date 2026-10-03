/**
 * Retail activity API client (server side) — Phase 10, read-only.
 *
 * Two scores (Activity, Speculation), each a Calculated Metric over proxy data (small on-chain
 * transactions, meme-coin trending, derivatives turnover) — never a sentiment poll, never a
 * trading signal.
 */

import { type ApiResult, getJson } from "@/lib/market";

export type DomainScore = {
  score_id: string;
  version: string;
  calculated_at: string;
  evidence_category: string;
  status: "ok" | "insufficient_data";
  score: string | null;
  band: string | null;
  semantic_note: string;
  reason: string | null;
};

export type RetailOverview = {
  as_of: string;
  knowledge_time: string;
  evidence_note: string;
  activity_score: DomainScore;
  speculation_score: DomainScore;
  not_tracked: string[];
};

export const fetchRetailOverview = (f?: typeof fetch): Promise<ApiResult<RetailOverview>> =>
  getJson<RetailOverview>("/api/v1/retail/overview", {}, f);
