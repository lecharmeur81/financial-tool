import type { NextConfig } from "next";

// No Content-Security-Policy is sent. This is a personal, local-only tool, and a strict
// `script-src 'self'` CSP breaks the Next.js App Router: it streams RSC flight data and the
// Suspense fallback swap (`loading.tsx`) as inline <script> tags, which that policy blocks —
// hydration fails (React error #412) and every page stays on "Loading". Do not re-add a CSP here
// without a nonce-based setup (or an HTTPS reverse proxy that supplies one).

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
