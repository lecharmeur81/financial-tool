/**
 * Institutional capital API client (server side) and presentation helpers (Phase 6).
 *
 * Every metric arrives with its evidence category, evidence class, source, timestamp, unit,
 * calculation, freshness and data quality. Amounts are exact decimal strings; they become numbers
 * only for drawing the chart.
 */

import { type ApiResult, type Freshness, getJson } from "@/lib/market";

export const ETF_ASSETS = ["BTC", "ETH", "SOL", "XRP"] as const;
export const INTERVALS = ["1d", "1w", "1mo"] as const;
export type Interval = (typeof INTERVALS)[number];

export const INTERVAL_LABEL: Record<Interval, string> = {
  "1d": "Daily",
  "1w": "Weekly",
  "1mo": "Monthly",
};

export type Source = {
  provider_id: string;
  provider_name: string;
  original_source: string;
  dataset_id: string;
  enabled: boolean;
  terms_verified: boolean;
  attribution: { text: string; url: string } | null;
};

export type FreshnessInfo = {
  status: Freshness;
  latest: string | null;
  expected_latest: string | null;
  age_seconds: number | null;
  rule: string;
  note: string;
};

export type Quality = {
  status: string;
  days_expected: number | null;
  days_present: number | null;
  flagged: number;
  revised: number;
  backfilled: number;
  estimated_availability: number;
  notes: string[];
  missing_days?: string[];
  not_loaded?: number | null;
  not_due?: number | null;
};

export type Metric = {
  metric_id: string;
  label: string;
  evidence_category: "observed" | "metric";
  evidence_class: string | null;
  value: string | null;
  unit: string;
  timestamp: string | null;
  calculation: string;
  source: Source;
  freshness: FreshnessInfo;
  quality: Quality;
};

export type LastRun = {
  job_run_id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  error_code: string | null;
  error_detail: string | null;
} | null;

export type EtfBucket = {
  start: string;
  end: string;
  net_flow_usd: string | null;
  net_assets_usd: string | null;
  net_assets_date: string | null;
  value_traded_usd: string | null;
  inflow_days: number;
  outflow_days: number;
  status: "complete" | "partial" | "in_progress" | "not_due" | "not_loaded" | "no_data";
  quality: Quality;
  reconciliation: {
    funds_reporting: number;
    funds_total_usd: string | null;
    difference_usd: string | null;
    reconciles: boolean;
    tolerance_usd: string;
  } | null;
};

export type EtfFlows = {
  asset: string;
  interval: Interval;
  as_of: string;
  knowledge_time: string;
  range: { start: string; end: string };
  evidence_category: "observed" | "metric";
  evidence_class: string;
  definition: {
    metric_id: string;
    label: string;
    unit: string;
    calculation: string;
    sign: string;
    event_time: string;
  };
  source: Source;
  buckets: EtfBucket[];
  latest_day: string | null;
  coverage_start: string | null;
  freshness: FreshnessInfo;
  ingestion: { last_run: LastRun };
  warnings: string[];
};

export type Fund = {
  ticker: string;
  name: string | null;
  latest_day: string;
  net_assets_usd: string | null;
  share_of_net_assets_pct: string | null;
  premium_discount: string | null;
  cum_flow_usd: string | null;
  range_flow_usd: string | null;
  days_present: number;
  freshness: FreshnessInfo;
  quality: Quality;
};

export type EtfFunds = {
  asset: string;
  range: { start: string; end: string };
  definition: Record<string, string>;
  source: Source;
  funds: Fund[];
  total_net_assets_usd: string | null;
  ingestion: { last_run: LastRun };
  warnings: string[];
};

export type ScoreComponent = {
  component_id: string;
  status: "ok" | "unavailable";
  reason: string | null;
  definition: string;
  evidence: string;
  weight: string;
  effective_weight: string | null;
  reference_scale: string | null;
  sub_score: string | null;
  contribution: string | null;
  window: { start: string | null; end: string | null };
  inputs: Record<string, string | number | null>;
  metric: Metric;
};

export type Score = {
  score_id: string;
  version: string;
  asset: string;
  as_of: string;
  knowledge_time: string;
  evidence_category: "metric";
  status: "ok" | "insufficient_data";
  value: string | null;
  unit: string;
  band: string | null;
  reason: string | null;
  available_weight: string;
  calculation: string;
  etf_due_until: string;
  components: ScoreComponent[];
  interpretation_limits: string[];
  bands_note: string;
};

export type Treasury = {
  asset: string;
  interval: Interval;
  range: { start: string; end: string };
  evidence_class: string;
  evidence_note: string;
  purchases: {
    definition: { metric_id: string; label: string; calculation: string };
    source: Source;
    buckets: {
      start: string;
      end: string;
      btc_acquired: string | null;
      cost_usd: string | null;
      cost_known_events: number;
      events: number;
      companies: number;
      quality: Quality;
    }[];
    recent: {
      date: string;
      company: string | null;
      ticker: string;
      btc_acquired: string | null;
      cost_usd: string | null;
      unit_cost_usd: string | null;
      implied_cost_per_btc_usd: string | null;
      holdings_after_btc: string | null;
      available_at: string;
      available_at_estimated: boolean;
      pit_reliability: string;
      quality_status: string;
      quality_note: string | null;
    }[];
    top_holders: {
      ticker: string;
      company: string | null;
      holdings_btc: string | null;
      as_of_purchase_date: string;
      pit_reliability: string;
    }[];
    reported_holdings: Metric;
    companies_tracked: number;
    freshness: FreshnessInfo;
  } | null;
  holdings_totals: {
    holdings: Metric;
    value_usd: Metric;
    changes: {
      days: number;
      compared_with: string | null;
      change_native: string | null;
      change_pct: string | null;
      note: string | null;
    }[];
  } | null;
  warnings: string[];
};

export type Overview = {
  as_of: string;
  assets: {
    asset: string;
    score: {
      status: "ok" | "insufficient_data";
      value: string | null;
      band: string | null;
      reason: string | null;
      available_weight: string;
    };
    latest_day: {
      date: string | null;
      net_flow_usd: string | null;
      net_assets_usd: string | null;
      quality_status: string | null;
    };
    flow_5d: {
      status: "ok" | "unavailable";
      net_flow_usd: string | number | null;
      pct_of_net_assets: string | null;
      window: { start: string | null; end: string | null };
      reason: string | null;
    };
    freshness: FreshnessInfo;
  }[];
  source: Source;
  interpretation_limits: string[];
};

export type Catalog = {
  not_tracked: { item: string; reason: string }[];
  providers: {
    provider_id: string;
    display_name: string;
    enabled: boolean;
    requires_api_key: boolean;
    api_key_variable: string | null;
    terms_verified: boolean;
    notes: string;
  }[];
  score: { parameters_note: string; bands_note: string };
};

const BASE = "/api/v1/institutional";

export const fetchInstitutionalOverview = (f?: typeof fetch) =>
  getJson<Overview>(`${BASE}/overview`, {}, f);
export const fetchInstitutionalCatalog = (f?: typeof fetch) =>
  getJson<Catalog>(`${BASE}/catalog`, {}, f);
export const fetchScore = (asset: string, f?: typeof fetch) =>
  getJson<Score>(`${BASE}/score`, { asset }, f);
export const fetchEtfFlows = (asset: string, interval: Interval, f?: typeof fetch) =>
  getJson<EtfFlows>(`${BASE}/etf-flows`, { asset, interval }, f);
export const fetchEtfFunds = (asset: string, f?: typeof fetch) =>
  getJson<EtfFunds>(`${BASE}/etf-funds`, { asset }, f);
export const fetchTreasury = (asset: string, interval: Interval, f?: typeof fetch) =>
  getJson<Treasury>(`${BASE}/treasury`, { asset, interval }, f);

export type { ApiResult };

// --------------------------------------------------------------------------- selection

export type FlowSelection = { asset: string; interval: Interval };

const first = (value: string | string[] | undefined): string | undefined =>
  Array.isArray(value) ? value[0] : value;

export function resolveFlowSelection(
  query: Record<string, string | string[] | undefined>,
): FlowSelection {
  const asset = first(query.asset)?.toUpperCase();
  const interval = first(query.interval);
  return {
    asset: (ETF_ASSETS as readonly string[]).includes(asset ?? "") ? asset! : "BTC",
    interval: (INTERVALS as readonly string[]).includes(interval ?? "")
      ? (interval as Interval)
      : "1d",
  };
}

export function flowHref(selection: FlowSelection, change: Partial<FlowSelection>): string {
  const next = { ...selection, ...change };
  return `/flows?${new URLSearchParams({ asset: next.asset, interval: next.interval }).toString()}`;
}

// --------------------------------------------------------------------------- formatting

/** USD amount in millions with sign, e.g. "+1,234.5 M USD"; exact digits stay in the tooltip. */
export function formatUsdMillions(value: string | number | null, signed = true): string {
  if (value === null) return "—";
  const n = Number(value) / 1e6;
  const body = Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  const sign = n < 0 ? "−" : signed && n > 0 ? "+" : "";
  return `${sign}${body} M USD`;
}

/** Large USD values (net assets), e.g. "100.00 B USD". */
export function formatUsdCompact(value: string | null): string {
  if (value === null) return "—";
  const n = Number(value);
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)} B USD`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)} M USD`;
  return `${n.toLocaleString("en-US")} USD`;
}

export function formatSigned(value: string | null, digits = 2, suffix = ""): string {
  if (value === null) return "—";
  const n = Number(value);
  const sign = n < 0 ? "−" : n > 0 ? "+" : "";
  return `${sign}${Math.abs(n).toFixed(digits)}${suffix}`;
}

/** Signed with thousands separators, e.g. "+59,000" / "−300". */
export function formatSignedGrouped(value: string | null, digits = 0): string {
  if (value === null) return "—";
  const n = Number(value);
  const sign = n < 0 ? "−" : n > 0 ? "+" : "";
  return `${sign}${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: digits })}`;
}

export function formatNumber(value: string | null, digits = 0): string {
  if (value === null) return "—";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function bandClass(band: string | null): string {
  if (!band) return "badge badge-neutral";
  if (band.includes("inflow")) return "badge badge-ok";
  if (band.includes("outflow")) return "badge badge-error";
  return "badge badge-neutral";
}

export const BUCKET_STATUS_LABEL: Record<EtfBucket["status"], string> = {
  complete: "Complete",
  partial: "Partial",
  in_progress: "In progress",
  not_due: "Not reported yet",
  not_loaded: "Not loaded",
  no_data: "No data",
};

/** API ranges are half-open [start, end); display the last day included. */
export function inclusiveEnd(end: string): string {
  const d = new Date(`${end}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

/** Period label: one day for daily buckets, otherwise "first … last day". */
export function periodLabel(start: string, end: string): string {
  const last = inclusiveEnd(end);
  return last === start ? start : `${start} … ${last}`;
}

export function qualityClass(status: string): string {
  if (status === "ok" || status === "complete") return "badge badge-ok";
  if (status === "missing" || status === "no_data") return "badge badge-error";
  if (status === "not_due" || status === "in_progress" || status === "not_loaded")
    return "badge badge-neutral";
  return "badge badge-warn";
}

// --------------------------------------------------------------------------- chart data

export type FlowPoint = { time: number; value: number; color: string } | { time: number };

/**
 * Net flow per bucket in millions of USD for the histogram. A bucket without data is a
 * whitespace point (a visible hole — never a zero). Partial buckets are drawn lighter.
 */
export function toFlowChart(buckets: EtfBucket[]): FlowPoint[] {
  return buckets.map((b) => {
    const time = Math.floor(new Date(`${b.start}T00:00:00Z`).getTime() / 1000);
    if (b.net_flow_usd === null) return { time };
    const value = Number(b.net_flow_usd) / 1e6;
    const up = value >= 0;
    const partial = b.status === "partial";
    const color = up
      ? partial
        ? "rgba(23,128,61,0.45)"
        : "#17803d"
      : partial
        ? "rgba(180,35,24,0.45)"
        : "#b42318";
    return { time, value, color };
  });
}
