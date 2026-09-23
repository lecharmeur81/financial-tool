import {
  BUCKET_STATUS_LABEL,
  type EtfFlows,
  formatUsdCompact,
  formatUsdMillions,
  periodLabel,
  qualityClass,
} from "@/lib/institutional";

/** Short per-row flags; the full explanation is given once, below the table. */
function QualityTags({ quality }: { quality: EtfFlows["buckets"][number]["quality"] }) {
  const gaps = quality.notes.filter((n) => /missing|not loaded|not reported/.test(n));
  return (
    <>
      {quality.backfilled ? (
        <span className="badge badge-neutral" title="pit_reliability = backfilled_latest">
          loaded later
        </span>
      ) : null}
      {quality.flagged ? <span className="badge badge-warn">{quality.flagged} flagged</span> : null}
      {quality.revised ? <span className="badge badge-warn">{quality.revised} revised</span> : null}
      {gaps.length ? (
        <ul className="note-list">
          {gaps.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

/** Every bucket with its completeness — present, missing, not loaded, not due — newest first. */
export function FlowTable({ flows }: { flows: EtfFlows }) {
  const daily = flows.interval === "1d";
  const rows = [...flows.buckets].reverse().filter((b) => b.status !== "not_loaded");
  const hidden = flows.buckets.length - rows.length;
  return (
    <>
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">{daily ? "Trading day" : "Period"}</th>
            <th scope="col">Net flow</th>
            <th scope="col">Net assets (end)</th>
            <th scope="col">Days with data</th>
            <th scope="col">Status</th>
            {daily ? <th scope="col">Sum of funds</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr key={b.start}>
              <th scope="row">{periodLabel(b.start, b.end)}</th>
              <td title={b.net_flow_usd ?? undefined}>{formatUsdMillions(b.net_flow_usd)}</td>
              <td title={b.net_assets_usd ?? undefined}>{formatUsdCompact(b.net_assets_usd)}</td>
              <td>
                {b.quality.days_present ?? 0} of {b.quality.days_expected ?? 0}
              </td>
              <td>
                <span className={qualityClass(b.status)}>{BUCKET_STATUS_LABEL[b.status]}</span>
                <QualityTags quality={b.quality} />
              </td>
              {daily ? (
                <td>
                  {b.reconciliation ? (
                    <>
                      {formatUsdMillions(b.reconciliation.funds_total_usd)} (
                      {b.reconciliation.funds_reporting} funds){" "}
                      <span
                        className={
                          b.reconciliation.reconciles ? "badge badge-ok" : "badge badge-warn"
                        }
                      >
                        {b.reconciliation.reconciles
                          ? "matches total"
                          : `differs by ${formatUsdMillions(b.reconciliation.difference_usd)}`}
                      </span>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
      {hidden ? (
        <p className="muted">
          {hidden} earlier period(s) fall before the stored history (
          {flows.coverage_start ?? "none"}) and are not listed — not loaded, which is different from
          missing.
        </p>
      ) : null}
      <p className="muted">
        “Loaded later”: stored more than 5 days after it became public (history as the provider
        shows it today; may include later corrections). Publication times of ETF figures are
        estimated (next US trading day 18:00 New York time) unless the value was received earlier.
        “Sum of funds” cross-checks the total against the per-fund figures.
      </p>
    </>
  );
}
