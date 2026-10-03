import type { AlertStatus } from "@/lib/alerts";
import { formatUtc } from "@/lib/market";
import { Unavailable } from "@/components/dashboard/Unavailable";

const SEVERITY_CLASS: Record<string, string> = {
  critical: "badge badge-error",
  high: "badge badge-error",
  medium: "badge badge-warn",
  low: "badge badge-neutral",
};

/**
 * Section 10 — Alerts. Reuses the Phase 23 alert list unchanged; "navigation to the alert
 * details" (Phase 26's explicit requirement) is an inline disclosure per row, reusing the same
 * `<details>` pattern already used for whale/institutional score components, rather than a new
 * route (Phase 26: do not create unnecessary duplicate pages).
 */
export function AlertsSection({
  alerts,
}: {
  alerts: { ok: true; data: AlertStatus[] } | { ok: false; reason: string };
}) {
  if (!alerts.ok) return <Unavailable what="Alerts" reason={alerts.reason} />;
  if (!alerts.data.length) {
    return (
      <section className="status-card" aria-labelledby="alerts-title">
        <h2 id="alerts-title">Alerts</h2>
        <p className="muted">No alerts recorded.</p>
      </section>
    );
  }
  return (
    <section className="status-card" aria-labelledby="alerts-title">
      <h2 id="alerts-title">Alerts</h2>
      {alerts.data.map((a) => (
        <details key={a.alert_id} className="component-details">
          <summary>
            <span className={SEVERITY_CLASS[a.severity] ?? "badge badge-neutral"}>
              {a.severity}
            </span>{" "}
            {a.alert_type} · {a.domain} · <span className="badge badge-neutral">{a.status}</span> ·{" "}
            {formatUtc(a.created_at)}
          </summary>
          <dl className="facts compact">
            <div>
              <dt>Trigger</dt>
              <dd>{a.trigger_condition}</dd>
            </div>
            <div>
              <dt>Observed value</dt>
              <dd>
                {a.observed_value}
                {a.reference_value ? ` (reference ${a.reference_value})` : ""}
              </dd>
            </div>
            <div>
              <dt>Data quality</dt>
              <dd>{a.data_quality_state}</dd>
            </div>
            <div>
              <dt>Lifecycle</dt>
              <dd>
                {a.status}
                {a.acknowledged_at ? ` · acknowledged ${formatUtc(a.acknowledged_at)}` : ""}
                {a.resolved_at ? ` · resolved ${formatUtc(a.resolved_at)}` : ""}
              </dd>
            </div>
          </dl>
        </details>
      ))}
    </section>
  );
}
