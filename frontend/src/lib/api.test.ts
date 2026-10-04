import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchIngestionRuns, fetchMeta, fetchProviderHealth, fetchReadiness } from "./api";

const body = { status: "ready", checked_at: "2026-09-23T00:00:00Z", components: {} };

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("fetchReadiness", () => {
  it("reports a missing API URL instead of guessing one", async () => {
    vi.stubEnv("API_INTERNAL_URL", "");
    const result = await fetchReadiness(vi.fn());
    expect(result).toEqual({ reachable: false, reason: "API_INTERNAL_URL is not set" });
  });

  it("calls the readiness endpoint without caching", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000/");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
    const result = await fetchReadiness(fetchMock);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api:8000/health/ready",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(result).toEqual({ reachable: true, httpStatus: 200, readiness: body });
  });

  it("keeps the body of a 503 so the failing component is visible", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const degraded = { ...body, status: "not_ready" };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(degraded), { status: 503 }));
    const result = await fetchReadiness(fetchMock);
    expect(result).toMatchObject({ reachable: true, httpStatus: 503 });
  });

  it("reports network failures as unreachable", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const result = await fetchReadiness(vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    expect(result).toEqual({ reachable: false, reason: "Unreachable" });
  });

  it("reports unexpected statuses", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const result = await fetchReadiness(
      vi.fn().mockResolvedValue(new Response("x", { status: 500 })),
    );
    expect(result).toEqual({ reachable: false, reason: "Unexpected HTTP 500" });
  });
});

describe("fetchMeta", () => {
  it("returns representative service metadata on success", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const meta = {
      name: "cfi-api",
      version: "0.36.0",
      environment: "development",
      api_version: "v1",
      server_time_utc: "2026-09-23T00:00:00Z",
      evidence_categories: ["observed", "calculated"],
      data_sources_connected: 12,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(meta), { status: 200 }));
    const result = await fetchMeta(fetchMock);
    expect(result).toEqual({ ok: true, data: meta });
  });

  it("reports API errors instead of hiding them", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ detail: "boom" }), { status: 500 }));
    const result = await fetchMeta(fetchMock);
    expect(result).toEqual({ ok: false, status: 500, reason: "boom" });
  });
});

describe("fetchProviderHealth", () => {
  it("returns representative provider rows on success", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const data = {
      window_hours: 24,
      generated_at: "2026-09-23T00:00:00Z",
      providers: [
        {
          provider_id: "coinbase",
          display_name: "Coinbase",
          requests: 100,
          successes: 98,
          success_rate: 0.98,
          consecutive_failures: 0,
          last_success_at: "2026-09-23T00:00:00Z",
          last_failure_at: null,
          last_error: null,
          last_job_status: "ok",
        },
      ],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(data), { status: 200 }));
    const result = await fetchProviderHealth(fetchMock);
    expect(result).toEqual({ ok: true, data });
  });

  it("reports an unreachable API", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const result = await fetchProviderHealth(
      vi.fn().mockRejectedValue(new TypeError("fetch failed")),
    );
    expect(result).toEqual({ ok: false, status: null, reason: "Unreachable" });
  });
});

describe("fetchIngestionRuns", () => {
  it("defaults the limit and returns representative rows", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const runs = [
      {
        job_run_id: 1,
        job_type: "ingest",
        dataset_id: "market.ohlcv.btc.1d",
        provider_id: "coinbase",
        subject: null,
        status: "ok",
        window_start: "2026-09-22T00:00:00Z",
        window_end: "2026-09-23T00:00:00Z",
        started_at: "2026-09-23T00:00:00Z",
        finished_at: "2026-09-23T00:00:05Z",
        pages: 1,
        records_received: 288,
        inserted: 288,
        duplicates: 0,
        revisions: 0,
        missing: 0,
        conflicts: 0,
        rejected: 0,
        skipped: 0,
        suspect: 0,
        stale: false,
        error_code: null,
        error_detail: null,
      },
    ];
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(runs), { status: 200 }));
    const result = await fetchIngestionRuns(undefined, fetchMock);
    expect(result).toEqual({ ok: true, data: runs });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api:8000/api/v1/ingestion/runs?limit=20",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("reports API errors instead of hiding them", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ detail: "boom" }), { status: 500 }));
    const result = await fetchIngestionRuns(20, fetchMock);
    expect(result).toEqual({ ok: false, status: 500, reason: "boom" });
  });
});
