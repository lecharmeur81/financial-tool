/**
 * Alert API client (server side) — Phase 23, read-only.
 *
 * Rule-based alerts on metrics, signals, regimes, and data-quality events. Lifecycle:
 * active → acknowledged → resolved (or expired).
 */

import { type ApiResult, getJson } from "@/lib/market";

export type AlertStatus = {
  alert_id: string;
  alert_type: string;
  severity: string;
  domain: string;
  trigger_condition: string;
  observed_value: string;
  reference_value: string | null;
  evidence_field_ids: string[];
  snapshot_id: number | null;
  source_tool_id: string;
  component_status: string;
  data_quality_state: string;
  status: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
};

export const fetchAlerts = (
  params: { status?: string; limit?: number } = {},
  f?: typeof fetch,
): Promise<ApiResult<AlertStatus[]>> =>
  getJson<AlertStatus[]>(
    "/api/v1/alerts/",
    {
      ...(params.status ? { status: params.status } : {}),
      limit: String(params.limit ?? 50),
    },
    f,
  );
