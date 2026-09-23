import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchReadiness } from "./api";

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
