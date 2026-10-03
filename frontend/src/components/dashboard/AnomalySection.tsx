import { ACTIVE_BANDS, type AnomalyScan } from "@/lib/anomaly";
import { Unavailable } from "@/components/dashboard/Unavailable";

/**
 * Section 5 — Anomalies. Reuses the Anomaly Engine's own percentile-band readings unchanged
 * (`/anomaly/scan`) — bands and magnitudes are never reinterpreted here (Phase 26 constraint).
 * Only active (notable/extreme) bands surface by default, to avoid overloading the first screen.
 */
export function AnomalySection({
  scan,
}: {
  scan: { ok: true; data: AnomalyScan } | { ok: false; reason: string };
}) {
  if (!scan.ok) return <Unavailable what="Anomalies" reason={scan.reason} />;
  const active = scan.data.anomalies.filter((a) => a.band && ACTIVE_BANDS.has(a.band));
  return (
    <section className="status-card" aria-labelledby="anomaly-title">
      <h2 id="anomaly-title">Anomalies · {scan.data.asset}</h2>
      {active.length ? (
        <table className="status-table">
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col">Band</th>
              <th scope="col">Value</th>
              <th scope="col">Percentile</th>
              <th scope="col">Since</th>
            </tr>
          </thead>
          <tbody>
            {active.map((a) => (
              <tr key={a.metric_id}>
                <th scope="row">{a.label}</th>
                <td>
                  <span className="badge badge-warn">{a.band}</span>
                </td>
                <td>
                  {a.current_value ?? "—"} {a.unit}
                </td>
                <td>{a.historical_percentile.percentile ?? "—"}</td>
                <td>
                  {a.duration.since ?? "—"}
                  {a.duration.capped ? " (capped)" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">No metric is currently in a notable or extreme band.</p>
      )}
      <details className="component-details">
        <summary>All {scan.data.anomalies.length} tracked categories</summary>
        <ul className="note-list">
          {scan.data.anomalies.map((a) => (
            <li key={a.metric_id}>
              {a.label}: {a.band ?? a.reason ?? "insufficient data"}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
