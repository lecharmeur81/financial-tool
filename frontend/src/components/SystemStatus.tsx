import type { ReadinessResult } from "@/lib/api";

/** Presents API readiness exactly as reported — unknown or failed states are shown, never hidden. */
export function SystemStatus({ result }: { result: ReadinessResult }) {
  if (!result.reachable) {
    return (
      <div className="status-card">
        <h2>System status</h2>
        <p>
          <span className="badge badge-error">API unavailable</span> {result.reason}
        </p>
        <p className="muted">
          Database and Redis status cannot be determined while the API is unavailable.
        </p>
      </div>
    );
  }

  const { readiness } = result;
  const overallOk = readiness.status === "ready";
  return (
    <div className="status-card">
      <h2>System status</h2>
      <p>
        <span className={overallOk ? "badge badge-ok" : "badge badge-error"}>
          {overallOk ? "All systems ready" : "Degraded"}
        </span>{" "}
        <span className="muted">Checked at {readiness.checked_at} (UTC)</span>
      </p>
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Component</th>
            <th scope="col">Status</th>
            <th scope="col">Latency</th>
            <th scope="col">Details</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(readiness.components).map(([name, report]) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              <td>
                <span className={report.status === "ok" ? "badge badge-ok" : "badge badge-error"}>
                  {report.status === "ok" ? "OK" : `Error: ${report.error ?? "unknown"}`}
                </span>
              </td>
              <td>{report.latency_ms} ms</td>
              <td>
                {Object.entries(report.detail)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(" · ") || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        This is system health. Data freshness and quality will be reported separately once data
        sources are connected.
      </p>
    </div>
  );
}
