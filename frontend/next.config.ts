import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server output for the Docker image (see infra/docker/frontend.Dockerfile).
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    // Baseline security headers; a full Content-Security-Policy is planned for Phase 25 (ADR-0028).
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
