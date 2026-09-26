import type { DerivativesAssetView } from "@/lib/derivatives";

const FRESHNESS_CLASS = {
  fresh: "badge badge-ok",
  stale: "badge badge-warn",
  no_data: "badge badge-error",
};

/** Every source of this asset: freshness, last run, and flagged / backfilled / missing points. */
export function DataQualityPanel({ quality }: { quality: DerivativesAssetView["data_quality"] }) {
  return (
    <section className="status-card" aria-labelledby="deriv-quality-title">
      <h2 id="deriv-quality-title">Sources and data quality</h2>
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Dataset</th>
            <th scope="col">Provider</th>
            <th scope="col">Newest value (UTC)</th>
            <th scope="col">Freshness</th>
            <th scope="col">Last run</th>
            <th scope="col">Flagged / backfilled / missing</th>
          </tr>
        </thead>
        <tbody>
          {quality.sources.map((s) => (
            <tr key={`${s.provider_id}:${s.dataset_id}`}>
              <th scope="row">{s.dataset_id}</th>
              <td>
                {s.provider_name}
                {s.enabled ? "" : " (disabled)"}
              </td>
              <td>{s.latest_event_time ?? "—"}</td>
              <td>
                <span className={FRESHNESS_CLASS[s.freshness]}>
                  {s.freshness.replace("_", " ")}
                </span>
              </td>
              <td>
                {s.last_run
                  ? `${s.last_run.status}${s.last_run.error_code ? ` (${s.last_run.error_code})` : ""}`
                  : "never run"}
              </td>
              <td>
                {s.flagged_points} / {s.backfilled_points} / {s.missing_points}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        {quality.note} Price: {quality.price_source}.
      </p>
    </section>
  );
}
