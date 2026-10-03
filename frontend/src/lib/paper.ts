/**
 * Paper trading API client (server side) — Phase 24, read-only here.
 *
 * Simulated trades only — no real execution, no exchange order endpoint, no trading
 * credential anywhere in this router. The dashboard reads recent trades, open positions and
 * performance; it links to the full paper-trading views rather than duplicating them
 * (Phase 26 constraint).
 */

import { type ApiResult, getJson } from "@/lib/market";

export type TradeStatus = {
  trade_id: string;
  asset: string;
  direction: string;
  status: string;
  entry_time: string;
  entry_price_observed: string;
  notional: string;
  leverage: string;
  exit_time: string | null;
  realized_pnl: string | null;
  return_pct: string | null;
  strategy_tag: string | null;
  created_at: string;
  updated_at: string;
};

export type OpenPositionStatus = {
  trade: TradeStatus;
  current_price_observed: string | null;
  unrealized_gross_pnl: string | null;
  unrealized_net_pnl: string | null;
  unrealized_return_pct: string | null;
  data_quality_state: string;
};

export type PerformanceStats = {
  total_trades: number;
  open_trades: number;
  closed_trades: number;
  cancelled_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: string | null;
  gross_pnl: string;
  net_pnl: string;
  average_win: string | null;
  average_loss: string | null;
  profit_factor: string | null;
  expectancy: string | null;
  max_drawdown: string | null;
  disclaimer: string;
};

export const fetchRecentTrades = (limit = 5, f?: typeof fetch): Promise<ApiResult<TradeStatus[]>> =>
  getJson<TradeStatus[]>("/api/v1/paper/trades", { limit: String(limit) }, f);

export const fetchOpenPositions = (f?: typeof fetch): Promise<ApiResult<OpenPositionStatus[]>> =>
  getJson<OpenPositionStatus[]>("/api/v1/paper/positions", {}, f);

export const fetchPaperPerformance = (f?: typeof fetch): Promise<ApiResult<PerformanceStats>> =>
  getJson<PerformanceStats>("/api/v1/paper/performance", {}, f);
