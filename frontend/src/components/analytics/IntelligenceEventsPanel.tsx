import type { IntelligenceEvent } from "@/lib/intelligence";
import { formatUtc } from "@/lib/market";
import { Unavailable } from "@/components/dashboard/Unavailable";

const SEVERITY_BADGE: Record<string, string> = {
  critical: "badge badge-error",
  elevated: "badge badge-warn",
  notable: "badge badge-neutral",
};

function severityBadge(severity: string): string {
  return SEVERITY_BADGE[severity] ?? "badge badge-neutral";
}

/**
 * Full Intelligence Events view (Phase 35 backend, surfaced on /analytics in Phase 36). A
 * read-only list over `sig.intelligence_event` — detection, not interpretation: each row is the
 * deterministic rule engine's own output, never re-derived here. Per-row `<details>` disclosure is
 * the "navigation to event details" (same pattern as the dashboard's AlertsSection, Phase 26) —
 * no new route, and no acknowledge/resolve control (events are read-only, Phase 36 constraint).
 */
export function IntelligenceEventsPanel({
  events,
}: {
  events: { ok: true; data: IntelligenceEvent[] } | { ok: false; reason: string };
}) {
  if (!events.ok) return <Unavailable what="Intelligence events" reason={events.reason} />;

  return (
    <section className="status-card" aria-labelledby="intel-events-title">
      <h2 id="intel-events-title">Intelligence Events</h2>
      <p className="muted">
        Recent change-detected events across every intelligence domain — detection only, never an
        interpretation or a recommendation.
      </p>
      {events.data.length ? (
        <div className="table-scroll">
          <table className="status-table">
            <thead>
              <tr>
                <th scope="col">Observed</th>
                <th scope="col">Domain</th>
                <th scope="col">Event type</th>
                <th scope="col">Severity</th>
                <th scope="col">Current value</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {events.data.map((e) => (
                <tr key={e.event_id}>
                  <th scope="row">{formatUtc(e.observed_at)}</th>
                  <td>{e.domain}</td>
                  <td>{e.event_type}</td>
                  <td>
                    <span className={severityBadge(e.severity)}>{e.severity}</span>
                  </td>
                  <td>
                    {e.current_value}
                    {e.change_magnitude !== null ? ` (Δ ${e.change_magnitude})` : ""}
                  </td>
                  <td>{e.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No intelligence events recorded.</p>
      )}
      <details className="component-details">
        <summary>Event detail (first {Math.min(events.data.length, 10)} shown)</summary>
        <ul className="note-list">
          {events.data.slice(0, 10).map((e) => (
            <li key={e.event_id}>
              {e.domain}/{e.event_type}: {e.previous_value ?? "—"} → {e.current_value} · detected
              via {e.detection_method} · data quality {e.data_quality_state} (component{" "}
              {e.component_status}) · created {formatUtc(e.created_at)}
              {e.ai_interpretation_id !== null
                ? ` · AI interpretation #${e.ai_interpretation_id}`
                : ""}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
