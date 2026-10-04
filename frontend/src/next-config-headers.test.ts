import { afterEach, describe, expect, it, vi } from "vitest";

import nextConfig from "../next.config";

/**
 * Phase 28 (ADR-0028): verifies the security headers `next.config.ts` sends — in particular that
 * the CSP/Permissions-Policy added this phase are present alongside the pre-existing baseline
 * headers, and that HSTS is gated to production only (sending it on a plain-HTTP dev response is
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

  it("sends a self-only Content-Security-Policy with no unsafe-eval/unsafe-inline for scripts", async () => {
    const headers = await headerMap();
    const csp = headers["Content-Security-Policy"];
    expect(csp).toBeTruthy();
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("script-src 'self'");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/);
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
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
