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
