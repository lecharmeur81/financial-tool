/**
 * Real-Time Intelligence Events API client (server side) — Phase 35, read-only.
 *
 * A minimal view over `sig.intelligence_event`: change-detected events across the same evidence
 * domains the AI Analyst snapshot already covers, each carrying the detection method, data-quality
 * state and component status it was computed under. Read-only — this client never acknowledges,
 * resolves, or otherwise mutates an event (Phase 36 constraint: frontend stays read-only).
 */

import { type ApiResult, getJson } from "@/lib/market";

export type IntelligenceEvent = {
  event_id: string;
  created_at: string;
  observed_at: string;
  domain: string;
  event_type: string;
  severity: string;
  previous_value: string | null;
  current_value: string;
  change_magnitude: string | null;
  detection_method: string;
  data_quality_state: string;
  component_status: string;
  dedup_key: string;
  correlation_key: string;
  snapshot_id: number | null;
  status: string;
  ai_interpretation_id: number | null;
};

export type FetchIntelligenceEventsParams = {
  domain?: string;
  severity?: string;
  event_type?: string;
  since?: string;
  limit?: number;
};

export const fetchIntelligenceEvents = (
  params: FetchIntelligenceEventsParams = {},
  f?: typeof fetch,
): Promise<ApiResult<IntelligenceEvent[]>> => {
  const query: Record<string, string> = {};
  if (params.domain) query.domain = params.domain;
  if (params.severity) query.severity = params.severity;
  if (params.event_type) query.event_type = params.event_type;
  if (params.since) query.since = params.since;
  query.limit = String(params.limit ?? 50);
  return getJson<IntelligenceEvent[]>("/api/v1/intelligence-events/", query, f);
};

export const fetchIntelligenceEvent = (
  eventId: string,
  f?: typeof fetch,
): Promise<ApiResult<IntelligenceEvent>> =>
  getJson<IntelligenceEvent>(`/api/v1/intelligence-events/${eventId}`, {}, f);
