import type { NextConfig } from "next";

// Phase 28 (ADR-0028): the app has no inline <script>, no third-party script/style CDN, and no
// external image/font origins (`lightweight-charts` is bundled via npm, not loaded from a CDN —
// verified against package.json/pnpm-lock.yaml). That lets the CSP below be close to the
// strictest possible shape without `unsafe-inline`/`unsafe-eval` for scripts. `style-src` keeps
// `'unsafe-inline'` only because Next.js itself injects small inline <style> tags for its own
// runtime (route announcer, dev overlay) — there is no first-party inline-style usage to tighten
// further.
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  // Self-contained server output for the Docker image (see infra/docker/frontend.Dockerfile).
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    // Baseline security headers (Phase 28 / ADR-0028 closes out the CSP/HSTS/Permissions-Policy
    // gap the Phase 27 audit flagged). HSTS is only meaningful once the app is actually served
    // over HTTPS (typically terminated by a reverse proxy in front of this container, not by
    // Next.js itself) — sending it in plain-HTTP local development is harmless (browsers only
    // honor it on a response actually received over HTTPS) but it's still gated on
    // NODE_ENV==="production" so a local `pnpm dev` response never carries it.
    const headers = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
      {
        key: "Permissions-Policy",
        value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
      },
    ];
    if (process.env.NODE_ENV === "production") {
      headers.push({
        key: "Strict-Transport-Security",
        value: "max-age=63072000; includeSubDomains; preload",
      });
    }
    return [{ source: "/:path*", headers }];
  },
};

export default nextConfig;
