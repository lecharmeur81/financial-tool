/**
 * Market-data API client (server side) and presentation helpers.
 *
 * Every value comes from FastAPI with its evidence category, source and freshness (R2, R3).
 * Prices and volumes arrive as exact decimal strings; they are converted to numbers only for
 * drawing the chart, never for display text.
 */

import { apiBaseUrl } from "@/lib/api";

export type Freshness = "fresh" | "stale" | "no_data";

export type Source = {
  provider_id: string;
  provider_name: string;
  original_source: string;
  enabled: boolean;
  attribution: { text: string; url: string } | null;
};

export type Catalog = {
  assets: { symbol: string; name: string }[];
  timeframes: string[];
  venues: {
    venue_id: string;
    display_name: string;
    quote: string;
    instruments: Record<string, string>;
    timeframes: { timeframe: string; source: "native" | "derived"; derived_from: string | null }[];
    source: Source;
  }[];
  market_cap_source: Source;
};

export type Bar = {
  time: string;
  open: string | null;
  high: string | null;
  low: string | null;
  close: string | null;
  volume_base: string | null;
  volume_quote: string | null;
  trade_count: number | null;
  quality_status: string;
  quality_note: string | null;
  revision: number;
};

export type BarsResponse = {
  evidence_category: "observed";
  as_of: string;
  asset: string;
  timeframe: string;
  instrument: {
    venue_id: string;
    venue_name: string;
    instrument_id: string;
    price_unit: string;
    volume_unit: string;
    quote_volume_unit: string;
  };
  source: Source;
  derivation: { from_timeframe: string; bars_per_bucket: number; method: string } | null;
  range: { start: string; end: string };
  bars: Bar[];
  quality: {
    expected: number;
    present: number;
    missing: number;
    missing_times: string[];
    not_loaded: number;
    coverage_start: string | null;
    suspect: number;
    conflicting: number;
    revised: number;
  };
  freshness: {
    status: Freshness;
    latest_bar_time: string | null;
    age_seconds: number | null;
    limit_seconds: number;
    last_ingested_at: string | null;
  };
  ingestion: {
    last_run: {
      job_run_id: number;
      status: string;
      started_at: string;
      finished_at: string | null;
      error_code: string | null;
      error_detail: string | null;
    } | null;
    backfill: {
      covered_from: string;
      target_start: string;
      complete: boolean;
      note: string | null;
    } | null;
  };
  warnings: string[];
};

export type ScalarValue = {
  value: string | null;
  unit: string | null;
  time: string | null;
  ingested_at: string | null;
  quality_status: string | null;
  quality_note: string | null;
  instrument_id: string | null;
  freshness: Freshness;
  age_seconds: number | null;
  limit_seconds: number;
  source: Source;
};

export type AssetOverview = {
  symbol: string;
  name: string;
  last_trade: ScalarValue;
  latest_bars: {
    venue_id: string;
    venue_name: string;
    instrument_id: string;
    timeframe: string;
    bar_time: string | null;
    close: string | null;
    unit: string;
    quality_status: string | null;
    freshness: Freshness;
    age_seconds: number | null;
    source: Source;
  }[];
  market_cap: ScalarValue;
};

export type Overview = { evidence_category: "observed"; as_of: string; assets: AssetOverview[] };

export type ApiResult<T> =
  { ok: true; data: T } | { ok: false; status: number | null; reason: string };

const TIMEOUT_MS = 8000;

export async function getJson<T>(
  path: string,
  params: Record<string, string> = {},
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<T>> {
  let base: string;
  try {
    base = apiBaseUrl();
  } catch (error) {
    return { ok: false, status: null, reason: (error as Error).message };
  }
  const query = new URLSearchParams(params).toString();
  try {
    const response = await fetchImpl(`${base}${path}${query ? `?${query}` : ""}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      let reason = `HTTP ${response.status}`;
      try {
        const problem = (await response.json()) as { detail?: string };
        if (problem.detail) reason = problem.detail;
      } catch {
        // body was not JSON; keep the status text
      }
      return { ok: false, status: response.status, reason };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch (error) {
    const name = error instanceof Error ? error.name : "Error";
    return {
      ok: false,
      status: null,
      reason: name === "TimeoutError" ? "Timed out" : "Unreachable",
    };
  }
}

export const fetchCatalog = (f?: typeof fetch) => getJson<Catalog>("/api/v1/market/catalog", {}, f);

export const fetchOverview = (f?: typeof fetch) =>
  getJson<Overview>("/api/v1/market/overview", {}, f);

export const fetchBars = (
  params: { asset: string; timeframe: string; venue: string; limit?: number },
  f?: typeof fetch,
) =>
  getJson<BarsResponse>(
    "/api/v1/market/bars",
    {
      asset: params.asset,
      timeframe: params.timeframe,
      venue: params.venue,
      limit: String(params.limit ?? 300),
    },
    f,
  );

// --------------------------------------------------------------------------- selection

export type Selection = { asset: string; timeframe: string; venue: string };

const first = (value: string | string[] | undefined): string | undefined =>
  Array.isArray(value) ? value[0] : value;

/** Resolve the URL's choice against the catalog; unknown values fall back to the defaults. */
export function resolveSelection(
  catalog: Catalog,
  query: Record<string, string | string[] | undefined>,
): Selection {
  const asset = first(query.asset)?.toUpperCase();
  const venue = first(query.venue);
  const timeframe = first(query.tf);
  const venueEntry = catalog.venues.find((v) => v.venue_id === venue) ?? catalog.venues[0];
  const timeframes = venueEntry?.timeframes.map((t) => t.timeframe) ?? catalog.timeframes;
  return {
    asset: catalog.assets.some((a) => a.symbol === asset)
      ? asset!
      : (catalog.assets[0]?.symbol ?? "BTC"),
    venue: venueEntry?.venue_id ?? "coinbase",
    timeframe: timeframe && timeframes.includes(timeframe) ? timeframe : "1h",
  };
}

export function selectionHref(selection: Selection, change: Partial<Selection>): string {
  const next = { ...selection, ...change };
  const params = new URLSearchParams({ asset: next.asset, tf: next.timeframe, venue: next.venue });
  return `/market?${params.toString()}`;
}

// --------------------------------------------------------------------------- formatting

/** Group digits without converting through a float (keeps every reported digit). */
export function formatDecimal(value: string | null, maxFraction = 8): string {
  if (value === null) return "—";
  const negative = value.startsWith("-");
  const [intPart, fracPart = ""] = (negative ? value.slice(1) : value).split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const trimmed = fracPart.slice(0, maxFraction).replace(/0+$/, "");
  return `${negative ? "-" : ""}${grouped}${trimmed ? `.${trimmed}` : ""}`;
}

export function formatUnit(unit: string | null): string {
  return unit ? unit.toUpperCase() : "";
}

/** Large values (market cap) as e.g. "1.69 T USD", keeping the exact value for the tooltip. */
export function formatCompact(value: string | null, unit: string | null): string {
  if (value === null) return "—";
  const n = Number(value);
  const scales: [number, string][] = [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
  ];
  for (const [scale, suffix] of scales) {
    if (Math.abs(n) >= scale) return `${(n / scale).toFixed(2)} ${suffix} ${formatUnit(unit)}`;
  }
  return `${formatDecimal(value, 2)} ${formatUnit(unit)}`;
}

export function formatAge(seconds: number | null): string {
  if (seconds === null) return "never";
  if (seconds < 90) return `${seconds} s ago`;
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 48 * 3600) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

/** UTC timestamp for display; the UI states the time zone explicitly. */
export function formatUtc(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export const FRESHNESS_LABEL: Record<Freshness, string> = {
  fresh: "Fresh",
  stale: "Stale",
  no_data: "No data",
};

export const FRESHNESS_CLASS: Record<Freshness, string> = {
  fresh: "badge badge-ok",
  stale: "badge badge-warn",
  no_data: "badge badge-error",
};

// --------------------------------------------------------------------------- chart data

export type Candle = { time: number; open: number; high: number; low: number; close: number };
export type VolumePoint = { time: number; value: number };
export type Gap = { time: number };

/**
 * Convert bars for the chart. Missing bars become whitespace points (a visible hole — never
 * a zero or an interpolated value). Suspect/conflicting bars are drawn but listed separately.
 */
export function toChartData(bars: Bar[]): {
  candles: (Candle | Gap)[];
  volumes: (VolumePoint | Gap)[];
  flagged: { time: number; status: string; note: string | null }[];
} {
  const candles: (Candle | Gap)[] = [];
  const volumes: (VolumePoint | Gap)[] = [];
  const flagged: { time: number; status: string; note: string | null }[] = [];
  for (const bar of bars) {
    const time = Math.floor(new Date(bar.time).getTime() / 1000);
    if (bar.close === null || bar.open === null || bar.high === null || bar.low === null) {
      candles.push({ time });
      volumes.push({ time });
      continue;
    }
    candles.push({
      time,
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    });
    volumes.push(bar.volume_base === null ? { time } : { time, value: Number(bar.volume_base) });
    if (bar.quality_status !== "ok")
      flagged.push({ time, status: bar.quality_status, note: bar.quality_note });
  }
  return { candles, volumes, flagged };
}
