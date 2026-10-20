/**
 * A read-only stand-in for the CFI API, used only by the Phase 56 end-to-end suite.
 *
 * It serves hand-written fixtures for the endpoints the Dashboard, Advisor Brief, Portfolio
 * Exposure, Alerts and Paper Trading pages call, and answers 404 for every other path (so the
 * pages' "unavailable" handling is exercised too). It holds no data, touches no database and
 * accepts no write: any non-GET request is recorded and refused with 405.
 */
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { setTimeout as sleep } from "node:timers/promises";

import { candidateRaw, insufficientRaw } from "@/components/advisor/advisor-fixtures";
import { bullishDecision, forAsset } from "@/components/decision/decision-fixtures";
import { emptyRaw, populatedRaw } from "@/components/portfolio/portfolio-fixtures";
import type { DecisionAsset } from "@/lib/decision";

export type Scenario = {
  advisor: "candidate" | "insufficient" | "404" | "503" | "malformed";
  portfolio: "populated" | "empty" | "503" | "malformed" | "slow";
  decision: "bullish" | "503";
  alerts: "one" | "503";
  paper: "empty" | "503";
};

export const DEFAULT_SCENARIO: Scenario = {
  advisor: "candidate",
  portfolio: "empty",
  decision: "bullish",
  alerts: "one",
  paper: "empty",
};

export type RecordedRequest = { method: string; path: string; query: string };

const ALERT = {
  alert_id: "e2e-alert-1",
  alert_type: "metric_threshold",
  severity: "high",
  domain: "derivatives",
  trigger_condition: "funding_rate > 0.01",
  observed_value: "0.012",
  reference_value: "0.01",
  evidence_field_ids: ["f1"],
  snapshot_id: 1,
  source_tool_id: "get_derivatives",
  component_status: "ok",
  data_quality_state: "ok",
  status: "active",
  acknowledged_at: null,
  resolved_at: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const PERFORMANCE = {
  total_trades: 0,
  open_trades: 0,
  closed_trades: 0,
  cancelled_trades: 0,
  winning_trades: 0,
  losing_trades: 0,
  win_rate: null,
  gross_pnl: "0",
  net_pnl: "0",
  average_win: null,
  average_loss: null,
  profit_factor: null,
  expectancy: null,
  max_drawdown: null,
  disclaimer: "E2E fixture: simulated trades only, not real execution.",
};

export type MockApi = {
  url: string;
  scenario: Scenario;
  requests: RecordedRequest[];
  reset: () => void;
  close: () => Promise<void>;
};

export async function startMockApi(): Promise<MockApi> {
  const state = { scenario: { ...DEFAULT_SCENARIO }, requests: [] as RecordedRequest[] };

  const server: Server = createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", "http://mock.invalid");
    const method = req.method ?? "GET";
    state.requests.push({ method, path: url.pathname, query: url.search });
    const send = (status: number, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (method !== "GET") return send(405, { detail: "The E2E mock API is read-only." });

    const s = state.scenario;
    switch (url.pathname) {
      case "/api/v1/advisor/brief": {
        const asset = url.searchParams.get("asset") ?? "BTC";
        if (s.advisor === "404") return send(404, { detail: "No stored snapshot exists." });
        if (s.advisor === "503") return send(503, { detail: "Snapshot cannot be used." });
        if (s.advisor === "malformed") return send(200, { contract_version: "something_else" });
        return send(200, s.advisor === "candidate" ? candidateRaw(asset) : insufficientRaw(asset));
      }
      case "/api/v1/portfolio/exposure": {
        if (s.portfolio === "503") return send(503, { detail: "Paper trades cannot be read." });
        if (s.portfolio === "malformed")
          return send(200, { contract_version: "portfolio_exposure.v0" });
        if (s.portfolio === "slow") await sleep(1500);
        return send(200, s.portfolio === "empty" ? emptyRaw() : populatedRaw());
      }
      case "/api/v1/decision/current": {
        if (s.decision === "503") return send(503, { detail: "Decision unavailable." });
        const asset = (url.searchParams.get("asset") ?? "BTC") as DecisionAsset;
        return send(200, forAsset(bullishDecision(), asset));
      }
      case "/api/v1/alerts/":
        return s.alerts === "503"
          ? send(503, { detail: "Alerts unavailable." })
          : send(200, [ALERT]);
      case "/api/v1/paper/trades":
      case "/api/v1/paper/positions":
        return s.paper === "503" ? send(503, { detail: "Paper unavailable." }) : send(200, []);
      case "/api/v1/paper/performance":
        return s.paper === "503"
          ? send(503, { detail: "Paper unavailable." })
          : send(200, PERFORMANCE);
      default:
        return send(404, { detail: "Not mocked in the E2E suite." });
    }
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as AddressInfo).port;

  return {
    url: `http://127.0.0.1:${port}`,
    get scenario() {
      return state.scenario;
    },
    set scenario(value: Scenario) {
      state.scenario = value;
    },
    get requests() {
      return state.requests;
    },
    reset() {
      state.scenario = { ...DEFAULT_SCENARIO };
      state.requests = [];
    },
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}
