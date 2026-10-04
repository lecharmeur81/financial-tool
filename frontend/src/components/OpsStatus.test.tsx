import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { IngestionJobRun, Meta, ProviderHealthResponse } from "@/lib/api";

import { OpsStatus } from "./OpsStatus";

afterEach(cleanup);

const meta: Meta = {
  name: "cfi-api",
  version: "0.36.0",
  environment: "development",
  api_version: "v1",
  server_time_utc: "2026-10-01T00:00:00Z",
  evidence_categories: ["observed", "calculated"],
  data_sources_connected: 12,
};

const providerHealth: ProviderHealthResponse = {
  window_hours: 24,
  generated_at: "2026-10-01T00:00:00Z",
  providers: [
    {
      provider_id: "coinbase",
      display_name: "Coinbase",
      requests: 100,
      successes: 98,
      success_rate: 0.98,
      consecutive_failures: 0,
      last_success_at: "2026-10-01T00:00:00Z",
      last_failure_at: null,
      last_error: null,
      last_job_status: "ok",
    },
  ],
};

const ingestionRuns: IngestionJobRun[] = [
  {
    job_run_id: 1,
    job_type: "ingest",
    dataset_id: "market.ohlcv.btc.1d",
    provider_id: "coinbase",
    subject: null,
    status: "ok",
    window_start: "2026-09-30T00:00:00Z",
    window_end: "2026-10-01T00:00:00Z",
    started_at: "2026-10-01T00:00:00Z",
    finished_at: "2026-10-01T00:00:05Z",
    pages: 1,
    records_received: 288,
    inserted: 288,
    duplicates: 0,
    revisions: 0,
    missing: 0,
    conflicts: 0,
    rejected: 0,
    skipped: 0,
    suspect: 0,
    stale: false,
    error_code: null,
    error_detail: null,
  },
];

describe("OpsStatus", () => {
  it("shows service metadata, provider health, and ingestion runs on success", () => {
    render(
      <OpsStatus
        meta={{ ok: true, data: meta }}
        providerHealth={{ ok: true, data: providerHealth }}
        ingestionRuns={{ ok: true, data: ingestionRuns }}
      />,
    );
    expect(screen.getByText(/cfi-api v0.36.0/)).toBeTruthy();
    expect(screen.getByText("Coinbase")).toBeTruthy();
    expect(screen.getByText("market.ohlcv.btc.1d")).toBeTruthy();
  });

  it("reports each panel's own failure independently, never hiding it", () => {
    render(
      <OpsStatus
        meta={{ ok: false, status: 500, reason: "boom" }}
        providerHealth={{ ok: false, status: null, reason: "Unreachable" }}
        ingestionRuns={{ ok: false, status: null, reason: "Unreachable" }}
      />,
    );
    expect(screen.getByText("Service metadata unavailable")).toBeTruthy();
    expect(screen.getByText("Provider health unavailable")).toBeTruthy();
    expect(screen.getByText("Ingestion runs unavailable")).toBeTruthy();
  });

  it("shows an empty state rather than fabricating rows", () => {
    render(
      <OpsStatus
        meta={{ ok: true, data: meta }}
        providerHealth={{ ok: true, data: { ...providerHealth, providers: [] } }}
        ingestionRuns={{ ok: true, data: [] }}
      />,
    );
    expect(screen.getByText("No provider activity recorded in this window.")).toBeTruthy();
    expect(screen.getByText("No ingestion runs recorded.")).toBeTruthy();
  });
});
