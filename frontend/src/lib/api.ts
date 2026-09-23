/**
 * Server-side API access. The browser never talks to the database; everything goes through FastAPI
 * (ADR-0015). `API_INTERNAL_URL` is read at request time (server only), so one image works in
 * every environment.
 */

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
