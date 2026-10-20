import { tmpdir } from "node:os";
import { join } from "node:path";

import { defineConfig } from "@playwright/test";

// Phase 56 real-browser suite: Chromium against the BUILT Next.js server (run `pnpm build` first)
// and a read-only fixture API, both started by the tests themselves (e2e/harness.ts). Nothing else
// is started: no backend, database, Redis or scheduler. Not part of `pnpm test` (Vitest).
//
// PW_CHROMIUM_EXECUTABLE is optional: it points Playwright at an already-installed Chromium for
// environments where `playwright install` cannot download one. CI does not set it.
const executablePath = process.env.PW_CHROMIUM_EXECUTABLE;

export default defineConfig({
  testDir: "browser",
  // Each file starts its own server pair and mutates the mock API in-process, so run serially.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: [["list"]],
  outputDir: join(tmpdir(), "cfi-playwright-results"),
  use: {
    headless: true,
    actionTimeout: 5_000,
    navigationTimeout: 15_000,
    launchOptions: executablePath ? { executablePath } : {},
  },
});
