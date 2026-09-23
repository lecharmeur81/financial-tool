import {
  type BarsResponse,
  FRESHNESS_CLASS,
  FRESHNESS_LABEL,
  formatAge,
  formatUnit,
  formatUtc,
} from "@/lib/market";

/**
 * Where the chart's data came from and how trustworthy it is right now: source, last update,
 * freshness, missing/suspect bars, derivation, and the last ingestion run. Nothing is hidden (R3).
 */
export function DataStatus({ data }: { data: BarsResponse }) {
  const { freshness, quality, instrument, source, ingestion } = data;
  const lastRun = ingestion.last_run;
  return (
    <section className="status-card data-status" aria-labelledby="data-status-title">
      <h2 id="data-status-title">Data status</h2>
      <dl className="facts">
        <div>
          <dt>Evidence</dt>
          <dd>
            <span className="badge badge-neutral">Observed data</span>
            {data.derivation ? (
              <span className="badge badge-warn" title={data.derivation.method}>
                Derived from {data.derivation.from_timeframe} bars
              </span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>
            {source.provider_name} ({instrument.instrument_id}) · original source:{" "}
            {source.original_source}
          </dd>
        </div>
        <div>
          <dt>Units</dt>
          <dd>
            Prices in {formatUnit(instrument.price_unit)} · volume in{" "}
            {formatUnit(instrument.volume_unit)}
          </dd>
        </div>
        <div>
          <dt>Freshness</dt>
          <dd>
            <span className={FRESHNESS_CLASS[freshness.status]}>
              {FRESHNESS_LABEL[freshness.status]}
            </span>{" "}
            newest bar {formatUtc(freshness.latest_bar_time)} ({formatAge(freshness.age_seconds)};
            limit {Math.round(freshness.limit_seconds / 60)} min)
          </dd>
        </div>
        <div>
          <dt>Last update</dt>
          <dd>{formatUtc(freshness.last_ingested_at)} (stored by our system)</dd>
        </div>
        <div>
          <dt>Completeness</dt>
          <dd>
            {quality.present} of {quality.expected} expected bars present
            {quality.missing ? ` · ${quality.missing} missing` : ""}
            {quality.suspect ? ` · ${quality.suspect} suspect` : ""}
            {quality.conflicting ? ` · ${quality.conflicting} conflicting` : ""}
            {quality.revised ? ` · ${quality.revised} revised` : ""}
            {quality.not_loaded ? ` · ${quality.not_loaded} not loaded` : ""}
          </dd>
        </div>
        <div>
          <dt>Last ingestion</dt>
          <dd>
            {lastRun ? (
              <>
                <span
                  className={
                    lastRun.status === "failed" ? "badge badge-error" : "badge badge-neutral"
                  }
                >
                  {lastRun.status}
                </span>{" "}
                {formatUtc(lastRun.finished_at ?? lastRun.started_at)}
                {lastRun.error_code ? ` — ${lastRun.error_code}: ${lastRun.error_detail}` : ""}
              </>
            ) : (
              "no ingestion run recorded yet"
            )}
          </dd>
        </div>
        {ingestion.backfill ? (
          <div>
            <dt>History</dt>
            <dd>
              {ingestion.backfill.complete ? "loaded" : "loading"} back to{" "}
              {formatUtc(ingestion.backfill.covered_from)}
              {ingestion.backfill.note ? ` — ${ingestion.backfill.note}` : ""}
            </dd>
          </div>
        ) : null}
      </dl>
      {data.warnings.length ? (
        <ul className="warnings" aria-label="Data warnings">
          {data.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">No data-quality warnings for this range.</p>
      )}
      {quality.missing_times.length ? (
        <details>
          <summary>Missing bars ({quality.missing})</summary>
          <p className="muted">{quality.missing_times.map(formatUtc).join(", ")}</p>
        </details>
      ) : null}
    </section>
  );
}
