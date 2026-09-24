/**
 * Whale intelligence API client (server side) and presentation helpers (Phase 7).
 *
 * Every metric arrives with its evidence category, evidence class, source, timestamp, unit,
 * calculation, freshness and data quality; every address with its classification, evidence,
 * source and confidence. Amounts are exact decimal strings; they become numbers only for drawing.
 */

import type { FreshnessInfo, LastRun, Metric, Quality, Source } from "@/lib/institutional";
import { type ApiResult, getJson } from "@/lib/market";

export const WHALE_ASSETS = ["BTC", "ETH"] as const;
export type WhaleAsset = (typeof WHALE_ASSETS)[number];

export type Classification = {
  address: string;
  chain: string;
  actor_class: string;
  display: string;
  entity_id: string | null;
  entity_name: string | null;
  evidence_class: string | null;
  confidence: string | null;
  evidence: string;
  source: string | null;
  source_url: string | null;
  rule: string;
  conflicting_labels: {
    actor_class: string;
    entity_id: string | null;
    evidence_class: string;
    confidence: string;
    source: string;
  }[];
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

export type Reading = {
  label: string;
  value: string | null;
  unit: string;
  direction: "accumulation" | "distribution" | "neutral" | "unknown";
  source: string;
};

export type Contradiction = {
  indicator_id: string;
  label: string;
  status: "contradiction" | "consistent" | "no_clear_direction" | "insufficient_data";
  explanation: string;
  readings: Reading[];
  detail?: Record<string, unknown>;
};

export type WhaleScore = {
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
  window_end: string;
  components: ScoreComponent[];
  contradictions: Contradiction[];
  miner_spending: {
    metric_id: string;
    label: string;
    status: "ok" | "unavailable";
    value: string | null;
    unit: string;
    window: { start: string; end: string };
    numerator_btc: string | null;
    denominator_btc: string | null;
    reason: string | null;
    calculation: string;
    note: string;
  } | null;
  interpretation_limits: string[];
  bands_note: string;
};

export type DayCell = {
  value: string | null;
  quality_status: string;
  revision: number;
  pit_reliability: string;
} | null;

export type FlowDataset = {
  metric: string;
  label: string;
  dataset_id: string;
  unit: string;
  evidence_class: string | null;
  description: string;
  source: Source;
  freshness: FreshnessInfo;
  quality: Quality;
  last_run: LastRun;
};

export type WhaleFlows = {
  asset: string;
  unit: string;
  as_of: string;
  range: { start: string; end: string };
  evidence_category: "observed";
  definitions: Record<string, string>;
  datasets: FlowDataset[];
  days: { date: string; values: Record<string, DayCell>; netflow: string | null }[];
  interpretation_limits: string[];
};

export type Holders = {
  asset: string;
  unit: string;
  snapshot: string | null;
  compared_with: string | null;
  compared_note: string | null;
  definition: string;
  source: Source;
  label_sources: string[];
  freshness: FreshnessInfo;
  holders: {
    rank: number;
    balance: string;
    change_7d: string | null;
    change_7d_note: string | null;
    classification: Classification;
  }[];
  cohorts: {
    actor_class: string;
    label: string;
    addresses: number;
    balance: string;
    change_7d: string | null;
    change_7d_pct: string | null;
    change_7d_addresses_compared: number | null;
    change_7d_addresses_left: number | null;
    calculation: string;
  }[];
  last_run: LastRun;
};

export type Transfers = {
  asset: string;
  unit: string;
  range: { start: string; end: string };
  threshold: string;
  definition: string;
  source: Source;
  summary: {
    transfers: number;
    total: string;
    by_direction: { direction: string; transfers: number; total: string }[];
    note: string;
  };
  transfers: {
    time: string;
    tx_hash: string;
    output_index: number | null;
    value: string;
    value_usd: string | null;
    direction: string;
    sender: Classification | null;
    recipient: Classification | null;
    quality_status: string;
    quality_note: string | null;
  }[];
  truncated: boolean;
  last_run: LastRun;
};

export type WhaleCatalog = {
  thresholds: {
    large_transfer: Record<string, string>;
    unknown_large_holder_balance: Record<string, string>;
    rich_list_size: number;
    note: string;
  };
  classes: { actor_class: string; label: string }[];
  classification_rules: string[];
  providers: {
    provider_id: string;
    display_name: string;
    enabled: boolean;
    terms_verified: boolean;
    notes: string;
    attribution: { text: string; url: string } | null;
  }[];
  score: { parameters_note: string; contradiction_rule: string };
  not_tracked: { item: string; reason: string }[];
};

const API = "/api/v1/whales";

export function fetchWhaleScore(asset: string): Promise<ApiResult<WhaleScore>> {
  return getJson<WhaleScore>(`${API}/score`, { asset });
}

export function fetchWhaleFlows(asset: string): Promise<ApiResult<WhaleFlows>> {
  return getJson<WhaleFlows>(`${API}/flows`, { asset });
}

export function fetchHolders(asset: string): Promise<ApiResult<Holders>> {
  return getJson<Holders>(`${API}/holders`, { asset });
}

export function fetchTransfers(asset: string): Promise<ApiResult<Transfers>> {
  return getJson<Transfers>(`${API}/transfers`, { asset, limit: "50" });
}

export function fetchWhaleCatalog(): Promise<ApiResult<WhaleCatalog>> {
  return getJson<WhaleCatalog>(`${API}/catalog`);
}

// --------------------------------------------------------------------------- selection

export function resolveWhaleAsset(
  query: Record<string, string | string[] | undefined>,
): WhaleAsset {
  const raw = Array.isArray(query.asset) ? query.asset[0] : query.asset;
  const asset = raw?.toUpperCase() ?? "";
  return (WHALE_ASSETS as readonly string[]).includes(asset) ? (asset as WhaleAsset) : "BTC";
}

// --------------------------------------------------------------------------- formatting

/** Coin amount with thousands separators, e.g. "12,118.45 BTC". */
export function formatCoins(value: string | null, unit: string, digits = 2): string {
  if (value === null) return "—";
  return `${Number(value).toLocaleString("en-US", { maximumFractionDigits: digits })} ${unit.toUpperCase()}`;
}

export function whaleBandClass(band: string | null): string {
  if (!band) return "badge badge-neutral";
  if (band.includes("accumulation")) return "badge badge-ok";
  if (band.includes("distribution")) return "badge badge-error";
  return "badge badge-neutral";
}

export const CONTRADICTION_LABEL: Record<Contradiction["status"], string> = {
  contradiction: "Contradiction",
  consistent: "Consistent",
  no_clear_direction: "No clear direction",
  insufficient_data: "Insufficient data",
};

export function contradictionClass(status: Contradiction["status"]): string {
  if (status === "contradiction") return "badge badge-warn";
  if (status === "consistent") return "badge badge-ok";
  return "badge badge-neutral";
}

/** Known entities get a solid badge; size-only and unlabelled addresses a neutral one. */
export function classBadge(c: Classification): string {
  if (c.actor_class === "unlabelled") return "badge badge-neutral";
  if (c.evidence_class === "inferred") return "badge badge-neutral";
  return "badge badge-ok";
}

export function shortAddress(address: string): string {
  return address.length > 16 ? `${address.slice(0, 8)}…${address.slice(-6)}` : address;
}

export const DIRECTION_LABEL: Record<string, string> = {
  to_exchange: "To labelled exchange",
  from_exchange: "From labelled exchange",
  exchange_to_exchange: "Between labelled exchanges",
  other: "Other / unlabelled",
};

// --------------------------------------------------------------------------- chart data

export type NetflowPoint = { time: number; value: number; color: string } | { time: number };

/**
 * Daily net flow to exchanges (inflow − outflow) in coins. A day without both values is a
 * whitespace point (a hole — never a zero). Red = coins onto exchanges, green = off exchanges.
 */
export function toNetflowChart(days: WhaleFlows["days"]): NetflowPoint[] {
  return days.map((d) => {
    const time = Math.floor(new Date(`${d.date}T00:00:00Z`).getTime() / 1000);
    if (d.netflow === null) return { time };
    const value = Number(d.netflow);
    return { time, value, color: value > 0 ? "#b42318" : "#17803d" };
  });
}
