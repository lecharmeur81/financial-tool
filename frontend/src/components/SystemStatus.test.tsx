import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Readiness } from "@/lib/api";

import { SystemStatus } from "./SystemStatus";

afterEach(cleanup);

const readiness = (redisOk: boolean): Readiness => ({
  status: redisOk ? "ready" : "not_ready",
  checked_at: "2026-09-23T00:00:00Z",
  components: {
    database: {
      status: "ok",
      latency_ms: 3,
      detail: { timescaledb_version: "2.30.1", schema_revision: "0001" },
      error: null,
    },
    redis: redisOk
      ? { status: "ok", latency_ms: 1, detail: { ping: "PONG" }, error: null }
      : { status: "error", latency_ms: 1, detail: {}, error: "ConnectionError" },
  },
});

describe("SystemStatus", () => {
  it("shows ready components", () => {
    render(
      <SystemStatus result={{ reachable: true, httpStatus: 200, readiness: readiness(true) }} />,
    );
    expect(screen.getByText("All systems ready")).toBeDefined();
    expect(screen.getByText(/timescaledb_version: 2.30.1/)).toBeDefined();
  });

  it("shows a degraded component with its error", () => {
    render(
      <SystemStatus result={{ reachable: true, httpStatus: 503, readiness: readiness(false) }} />,
    );
    expect(screen.getByText("Degraded")).toBeDefined();
    expect(screen.getByText("Error: ConnectionError")).toBeDefined();
  });

  it("shows an unreachable API honestly", () => {
    render(<SystemStatus result={{ reachable: false, reason: "Timed out" }} />);
    expect(screen.getByText("API unavailable")).toBeDefined();
    expect(screen.getByText(/cannot be determined/)).toBeDefined();
  });
});
