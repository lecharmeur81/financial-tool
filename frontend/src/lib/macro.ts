/**
 * Macro environment API client (server side) — Phase 11, read-only.
 *
 * US rates, inflation, growth and risk-appetite series; the dashboard shows the Macro
 * Environment Score plus the readings it is built from. No new macro providers, no
 * crypto-price prediction derived from macro data (Phase 26 constraint).
 */

import { type ApiResult, getJson } from "@/lib/market";
import { type DomainScore } from "@/lib/retail";

export type { DomainScore };

export type Trend = {
  status: string;
  reason: string | null;
  value: string | null;
  time: string | null;
  condition: string | null;
};

export type MacroOverview = {
  as_of: string;
  knowledge_time: string;
  evidence_note: string;
  score: DomainScore;
  yield_curve: {
    status: string;
    reason: string | null;
    ust_10y_pct: string | null;
    ust_2y_pct: string | null;
    slope_pp: string | null;
    time: string | null;
    condition: string | null;
    condition_reason: string | null;
  };
  real_policy_rate: {
    status: string;
    reason: string | null;
    value: string | null;
    time: string | null;
    condition: string | null;
  };
  cpi_year_over_year: Trend;
  vix: {
    status: string;
    reason: string | null;
    value: string | null;
    time: string | null;
    condition: string | null;
  };
  equity_trend: Trend;
  dollar_trend: Trend;
  oil_trend: Trend;
  us_net_liquidity: {
    status: string;
    reason: string | null;
    value: string | null;
    time: string | null;
  };
  us_net_liquidity_trend: Trend;
  data_quality: { status: string; [key: string]: unknown };
  not_tracked: string[];
};

export const fetchMacroOverview = (f?: typeof fetch): Promise<ApiResult<MacroOverview>> =>
  getJson<MacroOverview>("/api/v1/macro/overview", {}, f);
