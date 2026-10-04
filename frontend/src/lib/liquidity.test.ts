import { describe, expect, it, vi } from "vitest";

import { fetchLiquidityHistory, toSupplyHistoryChart } from "./liquidity";

describe("fetchLiquidityHistory", () => {
  it("returns representative daily supply points on success", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const body = {
      subject: "TOTAL",
      as_of: "2026-10-01T00:00:00Z",
      start: "2026-07-03T00:00:00Z",
      days: 90,
      unit: "usd",
      points: [
        { time: "2026-09-30T00:00:00Z", value: "150000000000", quality_status: "ok" },
        { time: "2026-10-01T00:00:00Z", value: null, quality_status: "missing" },
      ],
    };
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify(body), { status: 200 }),
    ) as unknown as typeof fetch;
    const result = await fetchLiquidityHistory("TOTAL", 90, fetchMock);
    expect(result).toEqual({ ok: true, data: body });
    const call = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(call[0])).toBe("http://api.test/api/v1/liquidity/history?subject=TOTAL&days=90");
  });

  it("reports API errors instead of hiding them", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "No liquidity data is tracked for 'XYZ'." }), {
          status: 404,
        }),
    ) as unknown as typeof fetch;
    const result = await fetchLiquidityHistory("XYZ", 90, fetchMock);
    expect(result).toEqual({
      ok: false,
      status: 404,
      reason: "No liquidity data is tracked for 'XYZ'.",
    });
  });
});

describe("toSupplyHistoryChart", () => {
  it("builds a line with holes for missing days, never a fabricated zero", () => {
    const line = toSupplyHistoryChart({
      subject: "TOTAL",
      as_of: "2026-10-01T00:00:00Z",
      start: "2026-09-30T00:00:00Z",
      days: 2,
      unit: "usd",
      points: [
        { time: "2026-09-30T00:00:00Z", value: "150000000000", quality_status: "ok" },
        { time: "2026-10-01T00:00:00Z", value: null, quality_status: "missing" },
      ],
    });
    expect(line).toEqual([
      { time: Math.floor(new Date("2026-09-30T00:00:00Z").getTime() / 1000), value: 150000000000 },
      { time: Math.floor(new Date("2026-10-01T00:00:00Z").getTime() / 1000) },
    ]);
  });
});
