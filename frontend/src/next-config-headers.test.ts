import { afterEach, describe, expect, it, vi } from "vitest";

import nextConfig from "../next.config";

/**
 * Phase 28 (ADR-0028): verifies the security headers `next.config.ts` sends — the baseline and
 * Permissions-Policy headers are present, no CSP is sent (it broke the local Next.js app), and
 * HSTS is gated to production only (sending it on a plain-HTTP dev response is
 * misleading even though browsers ignore it over HTTP).
 */
describe("next.config headers()", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  async function headerMap(): Promise<Record<string, string>> {
    const rules = await nextConfig.headers!();
    const rule = rules.find((r) => r.source === "/:path*");
    if (!rule) throw new Error("expected a /:path* header rule");
    return Object.fromEntries(rule.headers.map((h) => [h.key, h.value]));
  }

  it("keeps the pre-existing baseline headers", async () => {
    const headers = await headerMap();
    expect(headers["X-Content-Type-Options"]).toBe("nosniff");
    expect(headers["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(headers["X-Frame-Options"]).toBe("DENY");
  });

  it("sends no Content-Security-Policy (local-only app; a strict one blocks Next.js inline scripts)", async () => {
    const headers = await headerMap();
    expect(headers["Content-Security-Policy"]).toBeUndefined();
  });

  it("sends a restrictive Permissions-Policy", async () => {
    const headers = await headerMap();
    expect(headers["Permissions-Policy"]).toContain("camera=()");
    expect(headers["Permissions-Policy"]).toContain("geolocation=()");
  });

  describe("Strict-Transport-Security", () => {
    it("is absent outside production (e.g. local `pnpm dev`)", async () => {
      vi.stubEnv("NODE_ENV", "development");
      const headers = await headerMap();
      expect(headers["Strict-Transport-Security"]).toBeUndefined();
    });

    it("is present in production", async () => {
      vi.stubEnv("NODE_ENV", "production");
      const headers = await headerMap();
      expect(headers["Strict-Transport-Security"]).toContain("max-age=");
      expect(headers["Strict-Transport-Security"]).toContain("includeSubDomains");
    });
  });
});
