/**
 * Market structure API client (server side) — Phase 12, read-only.
 *
 * Per-asset technical readout (trend, moving averages, RSI, volatility, volume trend) for
 * BTC/ETH/SOL/XRP, market breadth, and the Market Structure Score. Nothing here is turned into
 * an automatic trading recommendation (Phase 26 constraint) — the dashboard reuses these
 * calculations as-is, never re-deriving them.
 */

import { type ApiResult, getJson } from "@/lib/market";
import { type DomainScore } from "@/lib/retail";

export type { DomainScore };

export type MovingAverages = {
  status: string;
  reason: string | null;
  close: string | null;
  sma20: string | null;
  sma50: string | null;
  sma200: string | null;
  time: string | null;
} | null;

export type TrendReading = {
  status: string;
  reason: string | null;
  close: string | null;
  sma50: string | null;
  sma200: string | null;
  condition: string | null;
  time: string | null;
} | null;

export type VolatilityReading = {
  status: string;
  reason: string | null;
  annualized_pct: string | null;
  percentile: string | null;
  condition: string | null;
  time: string | null;
} | null;

export type VolumeTrendReading = {
  status: string;
  reason: string | null;
  current_volume: string | null;
  average_volume: string | null;
  ratio: string | null;
  condition: string | null;
  time: string | null;
} | null;

export type AssetStructure = {
  moving_averages: MovingAverages;
  trend: TrendReading;
  volatility: VolatilityReading;
  volume_trend: VolumeTrendReading;
};

export type MarketStructureOverview = {
  as_of: string;
  knowledge_time: string;
  evidence_note: string;
  score: DomainScore;
  assets: Record<string, AssetStructure>;
  market_breadth: { status: string; reason: string | null; [key: string]: unknown };
  total_cap_family: { status: string; reason: string | null; [key: string]: unknown };
  eth_btc: { status: string; reason: string | null; [key: string]: unknown };
  data_quality: { status: string; [key: string]: unknown };
  not_tracked: string[];
};

export const fetchMarketStructureOverview = (
  f?: typeof fetch,
): Promise<ApiResult<MarketStructureOverview>> =>
  getJson<MarketStructureOverview>("/api/v1/market-structure/overview", {}, f);
