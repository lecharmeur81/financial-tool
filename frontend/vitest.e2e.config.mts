import { defineConfig } from "vitest/config";

// Phase 56 end-to-end suite: runs against the built app, so it is NOT part of `pnpm test`.
// Run `pnpm build` first, then `pnpm test:e2e`.
export default defineConfig({
  resolve: { tsconfigPaths: true },
  test: {
    environment: "node",
    include: ["e2e/**/*.e2e.test.ts"],
    fileParallelism: false,
    testTimeout: 60_000,
    hookTimeout: 120_000,
  },
});
