import { FreshnessText, SourceText } from "@/components/flows/MetricFacts";
import { formatSignedGrouped } from "@/lib/institutional";
import { formatCoins, type WhaleFlows } from "@/lib/whales";

import { NetflowChart } from "./NetflowChart";

const TABLE_DAYS = 14;

/** Exchange flows, supply, coin age and miner data per UTC day, with every dataset's source. */
export function DailyFlowsPanel({ flows }: { flows: WhaleFlows }) {
  const recent = flows.days.slice(-TABLE_DAYS).reverse();
  const cols = flows.datasets.map((d) => d.metric);
  return (
    <section className="status-card chart-card" aria-labelledby="daily-title">
      <h2 id="daily-title">Exchange flows and coin activity · {flows.asset}</h2>
      {flows.days.some((d) => d.netflow !== null) ? (
        <NetflowChart days={flows.days} unit={flows.unit} />
      ) : (
        <p className="empty-chart" role="status">
          No exchange flow data stored for this range yet.
        </p>
      )}
      <p className="muted">
        {flows.definitions.netflow}. {flows.definitions.event_time}. Days without data are holes,
        never zeros.
      </p>
      {recent.length ? (
        <div className="table-scroll">
          <table className="status-table">
            <caption>Last {recent.length} days with data (native units)</caption>
            <thead>
              <tr>
                <th scope="col">Day (UTC)</th>
                <th scope="col">Net flow to exchanges</th>
                {flows.datasets.map((d) => (
                  <th scope="col" key={d.metric}>
                    {d.label} ({d.unit})
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {recent.map((d) => (
                <tr key={d.date}>
                  <th scope="row">{d.date}</th>
                  <td>{formatSignedGrouped(d.netflow, 2)}</td>
                  {cols.map((m) => {
                    const cell = d.values[m];
                    return (
                      <td key={m}>
                        {cell ? formatCoins(cell.value, "", 2) : "—"}
                        {cell && cell.quality_status !== "ok" ? (
                          <span className="muted"> ({cell.quality_status})</span>
                        ) : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <details className="component-details">
        <summary>Datasets — source, evidence, freshness, quality, last ingestion</summary>
        <ul className="note-list">
          {flows.datasets.map((d) => (
            <li key={d.metric}>
              <strong>{d.label}</strong> ({d.unit}
              {d.evidence_class ? `, ${d.evidence_class} evidence` : ""}): {d.description} Source:{" "}
              <SourceText source={d.source} />. Freshness: <FreshnessText freshness={d.freshness} />
              . Quality: {d.quality.status}, {d.quality.days_present ?? 0} days in range
              {d.quality.flagged ? `, ${d.quality.flagged} flagged` : ""}
              {d.quality.revised ? `, ${d.quality.revised} revised` : ""}
              {d.quality.estimated_availability
                ? `, ${d.quality.estimated_availability} preliminary`
                : ""}
              . Last run:{" "}
              {d.last_run
                ? `${d.last_run.status}${d.last_run.error_code ? ` (${d.last_run.error_code})` : ""}`
                : "none yet"}
              .
            </li>
          ))}
        </ul>
      </details>
      <p className="muted">
        Charting by{" "}
        <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
          TradingView Lightweight Charts™
        </a>
        .
      </p>
    </section>
  );
}
