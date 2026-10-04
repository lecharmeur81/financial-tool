import { describe, expect, it, vi } from "vitest";

import { fetchSimilarityCatalog, fetchSimilarityCurrent } from "./similarity";

describe("fetchSimilarityCurrent", () => {
  it("returns representative data on success", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const body = {
      asset: "BTC",
      as_of: "2026-09-23T00:00:00Z",
      knowledge_time: "2026-09-23T00:00:00Z",
      evidence_note: "Historical context only, never a prediction.",
      not_tracked: [],
      status: "ok",
      query_available_weight: "0.9",
      analogues: [
        {
          date: "2021-04-01T00:00:00Z",
          similarity_score: "0.87",
          available_weight: "0.9",
          regime: { regime_id: "r1", label: "risk-on", confidence: "0.7", status: "ok" },
          forward_returns: [{ horizon_days: 7, status: "ok", value_pct: "4.2", reason: null }],
          max_drawdown: {
            window_days: 30,
            status: "ok",
            value_pct: "-12.1",
            partial: false,
            reason: null,
          },
          volatility_annualized_pct: "55.0",
          compared_features: [],
        },
      ],
      distribution: [
        {
          horizon_days: 7,
          status: "ok",
          count: 5,
          min_pct: "-2",
          p25_pct: "0",
          median_pct: "3",
          p75_pct: "6",
          max_pct: "9",
          reason: null,
        },
      ],
      candidates_evaluated: 20,
      candidates_selected_for_distribution: 5,
    };
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify(body), { status: 200 }),
    ) as unknown as typeof fetch;
    const result = await fetchSimilarityCurrent(fetchMock);
    expect(result).toEqual({ ok: true, data: body });
  });

  it("passes through an insufficient_data response unchanged", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const body = {
      asset: "BTC",
      as_of: "2026-09-23T00:00:00Z",
      knowledge_time: "2026-09-23T00:00:00Z",
      evidence_note: "note",
      not_tracked: [],
      status: "insufficient_data",
      reason: "only 0.3 of the required 0.6 feature weight was available",
      analogues: [],
      distribution: [],
    };
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify(body), { status: 200 }),
    ) as unknown as typeof fetch;
    const result = await fetchSimilarityCurrent(fetchMock);
    expect(result).toEqual({ ok: true, data: body });
  });

  it("reports API errors instead of hiding them", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Database connection is not available." }), {
          status: 503,
        }),
    ) as unknown as typeof fetch;
    const result = await fetchSimilarityCurrent(fetchMock);
    expect(result).toEqual({
      ok: false,
      status: 503,
      reason: "Database connection is not available.",
    });
  });

  it("reports an unreachable API", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    const result = await fetchSimilarityCurrent(down);
    expect(result).toEqual({ ok: false, status: null, reason: "Unreachable" });
  });
});

describe("fetchSimilarityCatalog", () => {
  it("calls the catalog endpoint", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const body = {
      version: "v1",
      evidence_note: "note",
      benchmark_asset: "BTC",
      parameters: {},
      features: [],
      not_tracked: [],
    };
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify(body), { status: 200 }),
    ) as unknown as typeof fetch;
    const result = await fetchSimilarityCatalog(fetchMock);
    expect(result).toEqual({ ok: true, data: body });
    const call = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(call[0])).toBe("http://api.test/api/v1/similarity/catalog");
  });
});
