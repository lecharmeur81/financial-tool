/**
 * Liquidity / stablecoin API client (server side) — Phase 9, read-only.
 *
 * Stablecoin circulating supply, growth and market share, and the Liquidity Score. No reading
 * is labelled bullish or bearish, and no recommendation is produced.
 */

import { type ApiResult, getJson } from "@/lib/market";
import { type DomainScore } from "@/lib/retail";

export type { DomainScore };

export type SupplyGrowth = {
  subject: string;
  status: string;
  reason: string | null;
  value: string | null;
  time: string | null;
  change_24h_pct: string | null;
  change_7d_pct: string | null;
  change_30d_pct: string | null;
  condition: string | null;
};

export type MarketShare = {
  subject: string;
  status: string;
  reason: string | null;
  value: string | null;
  total: string | null;
  share_pct: string | null;
};

export type LiquidityOverview = {
  as_of: string;
  knowledge_time: string;
  evidence_note: string;
  score: DomainScore;
  supply: Record<string, SupplyGrowth>;
  market_share: Record<string, MarketShare>;
  growth_acceleration: {
    status: string;
    reason: string | null;
    subject: string;
    rate_now_7d_pct: string | null;
    rate_prior_7d_pct: string | null;
    change_pct_points: string | null;
  };
  exchange_liquidity_change: { status: string; reason: string | null };
  data_quality: { status: string; [key: string]: unknown };
  not_tracked: string[];
};

export const fetchLiquidityOverview = (f?: typeof fetch): Promise<ApiResult<LiquidityOverview>> =>
  getJson<LiquidityOverview>("/api/v1/liquidity/overview", {}, f);

// --------------------------------------------------------------------------- history (Phase 36)

export type SupplyHistoryPoint = { time: string; value: string | null; quality_status: string };

export type SupplyHistory = {
  subject: string;
  as_of: string;
  start: string;
  days: number;
  unit: string;
  points: SupplyHistoryPoint[];
};

export const fetchLiquidityHistory = (
  subject: string,
  days = 90,
  f?: typeof fetch,
): Promise<ApiResult<SupplyHistory>> =>
  getJson<SupplyHistory>("/api/v1/liquidity/history", { subject, days: String(days) }, f);

// --------------------------------------------------------------------------- chart data

export type LinePoint = { time: number; value: number } | { time: number };

function toSeconds(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 1000);
}

/** Daily circulating-supply line for one subject. Days without a value are holes, never zeros. */
export function toSupplyHistoryChart(history: SupplyHistory): LinePoint[] {
  return history.points.map((p) =>
    p.value === null
      ? { time: toSeconds(p.time) }
      : { time: toSeconds(p.time), value: Number(p.value) },
  );
}
