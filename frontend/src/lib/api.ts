/**
 * Server-side API access. The browser never talks to the database; everything goes through FastAPI
 * (ADR-0015). `API_INTERNAL_URL` is read at request time (server only), so one image works in
 * every environment.
 */

import { type ApiResult, getJson } from "@/lib/market";

export type ComponentReport = {
  status: "ok" | "error";
  latency_ms: number;
  detail: Record<string, string>;
  error: string | null;
};

export type Readiness = {
  status: "ready" | "not_ready";
  checked_at: string;
  components: Record<string, ComponentReport>;
};

export type ReadinessResult =
  | { reachable: true; httpStatus: number; readiness: Readiness }
  | { reachable: false; reason: string };

const DEFAULT_TIMEOUT_MS = 3000;

export function apiBaseUrl(): string {
  const url = process.env.API_INTERNAL_URL;
  if (!url) {
    throw new Error("API_INTERNAL_URL is not set");
  }
  return url.replace(/\/+$/, "");
}

export async function fetchReadiness(
  fetchImpl: typeof fetch = fetch,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<ReadinessResult> {
  let base: string;
  try {
    base = apiBaseUrl();
  } catch (error) {
    return { reachable: false, reason: (error as Error).message };
  }
  try {
    const response = await fetchImpl(`${base}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
      headers: { Accept: "application/json" },
    });
    // 503 still carries a readiness body describing which component failed.
    if (response.status !== 200 && response.status !== 503) {
      return { reachable: false, reason: `Unexpected HTTP ${response.status}` };
    }
    const readiness = (await response.json()) as Readiness;
    return { reachable: true, httpStatus: response.status, readiness };
  } catch (error) {
    const name = error instanceof Error ? error.name : "Error";
    return { reachable: false, reason: name === "TimeoutError" ? "Timed out" : "Unreachable" };
  }
}

// ------------------------------------------------------------------ operational endpoints (Phase 36)
// These describe the ingestion pipeline, not the market — kept on /settings, never on a market page
// (Phase 36 constraint: operational/system information stays clearly separated from market intelligence).

export type Meta = {
  name: string;
  version: string;
  environment: string;
  api_version: string;
  server_time_utc: string;
  evidence_categories: string[];
  data_sources_connected: number;
};

export const fetchMeta = (f?: typeof fetch): Promise<ApiResult<Meta>> =>
  getJson<Meta>("/api/v1/meta", {}, f);

export type ProviderHealth = {
  provider_id: string;
  display_name: string;
  requests: number;
  successes: number;
  success_rate: number | null;
  consecutive_failures: number;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  last_job_status: string | null;
};

export type ProviderHealthResponse = {
  window_hours: number;
  generated_at: string;
  providers: ProviderHealth[];
};

export const fetchProviderHealth = (f?: typeof fetch): Promise<ApiResult<ProviderHealthResponse>> =>
  getJson<ProviderHealthResponse>("/api/v1/providers/health", {}, f);

export type IngestionJobRun = {
  job_run_id: number;
  job_type: string;
  dataset_id: string;
  provider_id: string;
  subject: string | null;
  status: string;
  window_start: string;
  window_end: string;
  started_at: string;
  finished_at: string | null;
  pages: number;
  records_received: number;
  inserted: number;
  duplicates: number;
  revisions: number;
  missing: number;
  conflicts: number;
  rejected: number;
  skipped: number;
  suspect: number;
  stale: boolean | null;
  error_code: string | null;
  error_detail: string | null;
};

export const fetchIngestionRuns = (
  limit = 20,
  f?: typeof fetch,
): Promise<ApiResult<IngestionJobRun[]>> =>
  getJson<IngestionJobRun[]>("/api/v1/ingestion/runs", { limit: String(limit) }, f);
