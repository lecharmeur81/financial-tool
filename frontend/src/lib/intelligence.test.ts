import { describe, expect, it, vi } from "vitest";

import { fetchIntelligenceEvent, fetchIntelligenceEvents } from "./intelligence";

const event = {
  event_id: "11111111-1111-1111-1111-111111111111",
  created_at: "2026-09-23T00:05:00Z",
  observed_at: "2026-09-23T00:00:00Z",
  domain: "regime",
  event_type: "regime_change",
  severity: "elevated",
  previous_value: "risk-off",
  current_value: "risk-on",
  change_magnitude: "1",
  detection_method: "rule_engine",
  data_quality_state: "ok",
  component_status: "ok",
  dedup_key: "regime:BTC",
  correlation_key: "regime:BTC:2026-09-23",
  snapshot_id: 42,
  status: "active",
  ai_interpretation_id: null,
};

describe("fetchIntelligenceEvents", () => {
  it("returns representative data on success and defaults limit to 50", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify([event]), { status: 200 }),
    ) as unknown as typeof fetch;
    const result = await fetchIntelligenceEvents({}, fetchMock);
    expect(result).toEqual({ ok: true, data: [event] });
    const call = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(call[0])).toBe("http://api.test/api/v1/intelligence-events/?limit=50");
  });

  it("passes through optional filters", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify([]), { status: 200 }),
    ) as unknown as typeof fetch;
    await fetchIntelligenceEvents({ domain: "regime", severity: "critical", limit: 10 }, fetchMock);
    const call = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const url = new URL(String(call[0]));
    expect(url.searchParams.get("domain")).toBe("regime");
    expect(url.searchParams.get("severity")).toBe("critical");
    expect(url.searchParams.get("limit")).toBe("10");
  });

  it("returns an empty list when no events are recorded (not fabricated rows)", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify([]), { status: 200 }),
    ) as unknown as typeof fetch;
    const result = await fetchIntelligenceEvents({}, fetchMock);
    expect(result).toEqual({ ok: true, data: [] });
  });

  it("reports API errors instead of hiding them", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Database connection is not available." }), {
          status: 503,
        }),
    ) as unknown as typeof fetch;
    const result = await fetchIntelligenceEvents({}, fetchMock);
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
    const result = await fetchIntelligenceEvents({}, down);
    expect(result).toEqual({ ok: false, status: null, reason: "Unreachable" });
  });
});

describe("fetchIntelligenceEvent", () => {
  it("calls the single-event endpoint by id", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify(event), { status: 200 }),
    ) as unknown as typeof fetch;
    const result = await fetchIntelligenceEvent(event.event_id, fetchMock);
    expect(result).toEqual({ ok: true, data: event });
    const call = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(call[0])).toBe(`http://api.test/api/v1/intelligence-events/${event.event_id}`);
  });

  it("reports a not-found event", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "No intelligence event found." }), { status: 404 }),
    ) as unknown as typeof fetch;
    const result = await fetchIntelligenceEvent("missing-id", fetchMock);
    expect(result).toEqual({ ok: false, status: 404, reason: "No intelligence event found." });
  });
});
