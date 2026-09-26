/**
 * Derivatives API client (server side) and presentation helpers (Phase 8).
 *
 * Venue values are observed data; every change, ratio and flag is a calculated metric that
 * arrives with its formula and parameters. Amounts are exact decimal strings; percentages are
 * strings in percent. Nothing is labelled bullish or bearish.
 */

import { type ApiResult, getJson } from "@/lib/market";

export const DERIVATIVE_ASSETS = ["BTC", "ETH", "SOL", "XRP"] as const;
export type DerivativeAsset = (typeof DERIVATIVE_ASSETS)[number];

export type ScoreComponent = {
  component_id: string;
  metric_id: string;
  label: string;
  weight: string;
  scale: string;
  definition: string;
  status: "ok" | "unavailable" | "not_applicable";
  reason: string | null;
  value: string | null;
  value_unit: string;
  stress: string | null;
  effective_weight: string | null;
  contribution: string | null;
  calculation: string;
  context: string | null;
  inputs: Record<string, string | null>;
};

export type HealthScore = {
  score_id: string;
  version: string;
  evidence_category: string;
  status: "ok" | "insufficient_data";
  health: string | null;
  stress: string | null;
  band: string | null;
  band_note: string;
  available_weight: string;
  reason: string | null;
  components: ScoreComponent[];
};

export type Condition = {
  condition_id: string;
  label: string;
  state: "active" | "inactive" | "unknown" | "not_applicable";
  detail: string;
};

export type Unavailable = { status: "not_applicable" | "unavailable"; reason: string };

export type CurvePoint = {
  instrument: string;
  expiry: string | null;
  days_to_expiry: string | null;
  mark: string;
  index: string;
  premium_pct: string;
  annualised_pct: string | null;
  open_interest_usd: string | null;
};

export type Basis =
  | Unavailable
  | {
      status: "ok" | "unavailable";
      reason: string | null;
      venue: string;
      snapshot: string | null;
      shape: string | null;
      condition: string;
      headline: CurvePoint | null;
      perpetual_premium_pct: string | null;
      curve: CurvePoint[];
      calculation: string;
    };

export type Options =
  | Unavailable
  | {
      status: "ok" | "unavailable";
      reason: string | null;
      venue: string;
      snapshot: string | null;
      instruments: number;
      call_open_interest: string | null;
      put_open_interest: string | null;
      put_call_oi_ratio: string | null;
      call_volume_24h: string | null;
      put_volume_24h: string | null;
      put_call_volume_ratio: string | null;
      notional_open_interest_usd: string | null;
      index: string | null;
      expiry: string | null;
      expiry_days: string | null;
      forward: string | null;
      atm_strike: string | null;
      atm_iv_pct: string | null;
      skew_pct_points: string | null;
      skew_put: { strike: string; iv_pct: string } | null;
      skew_call: { strike: string; iv_pct: string } | null;
      skew_reason: string | null;
      skew_context: string | null;
      definitions: Record<string, string>;
    };

export type DerivativesAssetView = {
  asset: string;
  as_of: string;
  knowledge_time: string;
  evidence_note: string;
  score: HealthScore;
  conditions: Condition[];
  open_interest: {
    unit: string;
    total: string | null;
    total_usd: string | null;
    usd_note: string;
    change_24h_pct: string | null;
    change_7d_pct: string | null;
    venues_24h: string[];
    venues_7d: string[];
    condition: string;
    reason: string;
    calculation: string;
    venues: {
      venue: string;
      provider_id: string | null;
      open_interest: string | null;
      time: string | null;
      open_interest_usd: string | null;
      change_24h_pct: string | null;
      change_7d_pct: string | null;
      status: string;
    }[];
  };
  leverage: {
    status: string;
    reason: string | null;
    ratio_now_pct: string | null;
    ratio_week_ago_pct: string | null;
    change_7d_pct: string | null;
    condition: string;
    venues: string[];
    calculation: string;
    note: string;
  };
  funding: {
    annualised_7d_pct: string | null;
    weighting: string;
    condition: string;
    direction: string | null;
    calculation: string;
    venues: {
      venue: string;
      status: string;
      reason: string | null;
      settlements_7d: number;
      annualised_7d_pct: string | null;
      latest_rate_pct: string | null;
      latest_time: string | null;
      interval_hours: string | null;
      latest_annualised_pct: string | null;
    }[];
  };
  basis: Basis;
  liquidations: {
    status: string;
    reason: string | null;
    venue: string;
    unit: string;
    window_start: string | null;
    window_end: string | null;
    hours_expected: number;
    hours_present: number;
    long_24h: string | null;
    short_24h: string | null;
    total_24h: string | null;
    long_share_pct: string | null;
    share_of_oi_pct: string | null;
    open_interest: string | null;
    events: {
      hour: string;
      total: string;
      long: string;
      short: string;
      median_before: string;
      share_of_oi_pct: string;
    }[];
    events_note: string | null;
    note: string;
  };
  options: Options;
  volatility:
    | Unavailable
    | {
        status: "ok";
        index: string;
        dvol_pct: string;
        hour: string;
        change_7d_points: string | null;
      };
  positioning: {
    long_short_account_ratio: {
      venue: string;
      population: string | null;
      ratio: string | null;
      time: string | null;
      change_7d_pct: string | null;
    }[];
    note: string;
  };
  price_context: {
    source: string;
    price: string | null;
    time: string | null;
    change_24h_pct: string | null;
    change_7d_pct: string | null;
    oi_change_24h_pct: string | null;
    description: string | null;
    note: string;
  };
  data_quality: {
    sources: {
      provider_id: string;
      provider_name: string;
      dataset_id: string;
      enabled: boolean;
      latest_event_time: string | null;
      freshness: "fresh" | "stale" | "no_data";
      flagged_points: number;
      backfilled_points: number;
      missing_points: number;
      last_run: {
        status: string;
        started_at: string | null;
        error_code: string | null;
        error_detail: string | null;
      } | null;
    }[];
    price_source: string;
    note: string;
  };
  not_tracked: { item: string; reason: string }[];
};

type Series = { time: string; value: string | null; quality_status?: string }[];

export type DerivativesHistory = {
  asset: string;
  as_of: string;
  days: number;
  open_interest: {
    unit: string;
    venues: Record<string, Series>;
    aggregate: { time: string; value: string | null }[];
    aggregate_venues: string[];
  };
  price: { unit: string; source: string; points: { time: string; value: string | null }[] };
};

export type DerivativesCatalog = {
  providers: {
    provider_id: string;
    display_name: string;
    enabled: boolean;
    terms_verified: boolean;
    notes: string;
    attribution: { text: string; url: string } | null;
  }[];
  parameters: Record<string, string>;
  score: { parameters_note: string; method: string[] };
  not_tracked: { item: string; reason: string }[];
};

const API = "/api/v1/derivatives";

export function fetchDerivativesAsset(asset: string): Promise<ApiResult<DerivativesAssetView>> {
  return getJson<DerivativesAssetView>(`${API}/asset`, { asset });
}

export function fetchDerivativesHistory(
  asset: string,
  days = 14,
): Promise<ApiResult<DerivativesHistory>> {
  return getJson<DerivativesHistory>(`${API}/history`, { asset, days: String(days) });
}

export function fetchDerivativesCatalog(): Promise<ApiResult<DerivativesCatalog>> {
  return getJson<DerivativesCatalog>(`${API}/catalog`);
}

// --------------------------------------------------------------------------- selection

export function resolveDerivativeAsset(
  query: Record<string, string | string[] | undefined>,
): DerivativeAsset {
  const raw = Array.isArray(query.asset) ? query.asset[0] : query.asset;
  const asset = raw?.toUpperCase() ?? "";
  return (DERIVATIVE_ASSETS as readonly string[]).includes(asset)
    ? (asset as DerivativeAsset)
    : "BTC";
}

// --------------------------------------------------------------------------- formatting

/** A percentage string with sign, e.g. "+12.00 %" / "−3.10 %"; "—" when missing. */
export function formatPct(value: string | null, digits = 2): string {
  if (value === null) return "—";
  const n = Number(value);
  const sign = n < 0 ? "−" : n > 0 ? "+" : "";
  return `${sign}${Math.abs(n).toFixed(digits)} %`;
}

/** A signed difference in percentage points, e.g. "+8.00 pts". */
export function formatPoints(value: string | null, digits = 2): string {
  return value === null ? "—" : `${formatPct(value, digits).replace(" %", "")} pts`;
}

/** Stress bands: calm is neutral-good, stress is a warning — never a direction colour. */
export function stressBandClass(band: string | null): string {
  if (!band) return "badge badge-neutral";
  if (band === "low stress") return "badge badge-ok";
  if (band === "moderate stress") return "badge badge-neutral";
  return "badge badge-warn";
}

export const CONDITION_LABEL: Record<Condition["state"], string> = {
  active: "Active",
  inactive: "Not active",
  unknown: "Insufficient data",
  not_applicable: "Not applicable",
};

export function conditionClass(state: Condition["state"]): string {
  return state === "active" ? "badge badge-warn" : "badge badge-neutral";
}

/** Basis and options sections carry their details (a venue) unless the asset has none. */
export function hasDetail<T extends { venue: string }>(section: T | Unavailable): section is T {
  return "venue" in section;
}

// --------------------------------------------------------------------------- chart data

export type LinePoint = { time: number; value: number } | { time: number };

function toSeconds(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 1000);
}

/**
 * Aggregate open interest (coins; hours where every venue reported) and the Coinbase USD price
 * as two hourly lines. Hours without a value are holes, never zeros.
 */
export function toOpenInterestChart(history: DerivativesHistory): {
  openInterest: LinePoint[];
  price: LinePoint[];
} {
  const line = (points: { time: string; value: string | null }[]): LinePoint[] =>
    points.map((p) =>
      p.value === null
        ? { time: toSeconds(p.time) }
        : { time: toSeconds(p.time), value: Number(p.value) },
    );
  return {
    openInterest: line(history.open_interest.aggregate),
    price: line(history.price.points),
  };
}
