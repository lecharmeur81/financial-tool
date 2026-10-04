import type { ApiResult } from "@/lib/market";
import type { IngestionJobRun, Meta, ProviderHealthResponse } from "@/lib/api";

/**
 * Operational/system information for /settings (Phase 36) — service metadata, provider health and
 * recent ingestion runs. Describes the pipeline, never the market: kept entirely separate from any
 * market-intelligence reading (Phase 36 constraint). Nothing here is fabricated; a failed fetch
 * shows its own reason, never a cached or estimated value (R3).
 */
export function OpsStatus({
  meta,
  providerHealth,
  ingestionRuns,
}: {
  meta: ApiResult<Meta>;
  providerHealth: ApiResult<ProviderHealthResponse>;
  ingestionRuns: ApiResult<IngestionJobRun[]>;
}) {
  return (
    <div className="status-card">
      <h2>Operational status</h2>
      <p className="muted">
        Service metadata and the data-ingestion pipeline&apos;s own health — not market data.
      </p>

      {meta.ok ? (
        <dl className="facts compact">
          <div>
            <dt>Service</dt>
            <dd>
              {meta.data.name} v{meta.data.version} ({meta.data.environment})
            </dd>
          </div>
          <div>
            <dt>API version</dt>
            <dd>{meta.data.api_version}</dd>
          </div>
          <div>
            <dt>Server time (UTC)</dt>
            <dd>{meta.data.server_time_utc}</dd>
          </div>
          <div>
            <dt>Data sources connected</dt>
            <dd>{meta.data.data_sources_connected}</dd>
          </div>
        </dl>
      ) : (
        <p>
          <span className="badge badge-error">Service metadata unavailable</span> {meta.reason}
        </p>
      )}

      <h3>Provider health</h3>
      {providerHealth.ok ? (
        providerHealth.data.providers.length ? (
          <div className="table-scroll">
            <table className="status-table">
              <caption>Window: last {providerHealth.data.window_hours}h</caption>
              <thead>
                <tr>
                  <th scope="col">Provider</th>
                  <th scope="col">Requests</th>
                  <th scope="col">Success rate</th>
                  <th scope="col">Consecutive failures</th>
                  <th scope="col">Last status</th>
                  <th scope="col">Last error</th>
                </tr>
              </thead>
              <tbody>
                {providerHealth.data.providers.map((p) => (
                  <tr key={p.provider_id}>
                    <th scope="row">{p.display_name}</th>
                    <td>{p.requests}</td>
                    <td>
                      {p.success_rate !== null ? `${(p.success_rate * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td>
                      {p.consecutive_failures > 0 ? (
                        <span className="badge badge-warn">{p.consecutive_failures}</span>
                      ) : (
                        "0"
                      )}
                    </td>
                    <td>{p.last_job_status ?? "—"}</td>
                    <td>{p.last_error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No provider activity recorded in this window.</p>
        )
      ) : (
        <p>
          <span className="badge badge-error">Provider health unavailable</span>{" "}
          {providerHealth.reason}
        </p>
      )}

      <h3>Recent ingestion runs</h3>
      {ingestionRuns.ok ? (
        ingestionRuns.data.length ? (
          <div className="table-scroll">
            <table className="status-table">
              <thead>
                <tr>
                  <th scope="col">Dataset</th>
                  <th scope="col">Provider</th>
                  <th scope="col">Status</th>
                  <th scope="col">Started</th>
                  <th scope="col">Inserted</th>
                  <th scope="col">Rejected/Suspect</th>
                </tr>
              </thead>
              <tbody>
                {ingestionRuns.data.map((run) => (
                  <tr key={run.job_run_id}>
                    <th scope="row">{run.dataset_id}</th>
                    <td>{run.provider_id}</td>
                    <td>
                      <span
                        className={run.status === "ok" ? "badge badge-ok" : "badge badge-error"}
                      >
                        {run.status}
                      </span>
                    </td>
                    <td>{run.started_at}</td>
                    <td>{run.inserted}</td>
                    <td>
                      {run.rejected}/{run.suspect}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No ingestion runs recorded.</p>
        )
      ) : (
        <p>
          <span className="badge badge-error">Ingestion runs unavailable</span>{" "}
          {ingestionRuns.reason}
        </p>
      )}
    </div>
  );
}
