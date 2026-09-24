import { FreshnessText, SourceText } from "@/components/flows/MetricFacts";
import { formatSigned, formatSignedGrouped } from "@/lib/institutional";
import { formatUtc } from "@/lib/market";
import { formatCoins, type Holders } from "@/lib/whales";

import { ClassificationCell } from "./ClassificationCell";

/** Wallet balance changes: cohorts by class, then the top-100 list with every classification. */
export function HoldersPanel({ holders }: { holders: Holders }) {
  const unit = holders.unit.toUpperCase();
  return (
    <section className="status-card" aria-labelledby="holders-title">
      <h2 id="holders-title">Largest addresses · {holders.asset}</h2>
      <p className="muted">
        {holders.definition} Snapshot {formatUtc(holders.snapshot)}; compared with{" "}
        {holders.compared_with ? formatUtc(holders.compared_with) : "—"}.{" "}
        {holders.compared_note ?? ""}
      </p>
      <dl className="facts compact">
        <div>
          <dt>Source</dt>
          <dd>
            <SourceText source={holders.source} /> · labels:{" "}
            {holders.label_sources.length ? holders.label_sources.join(", ") : "none stored"}
          </dd>
        </div>
        <div>
          <dt>Freshness</dt>
          <dd>
            <FreshnessText freshness={holders.freshness} />
          </dd>
        </div>
      </dl>
      {holders.cohorts.length ? (
        <table className="status-table">
          <caption>
            Balances by class (7-day change over addresses listed in both snapshots)
          </caption>
          <thead>
            <tr>
              <th scope="col">Class</th>
              <th scope="col">Addresses</th>
              <th scope="col">Balance ({unit})</th>
              <th scope="col">7-day change ({unit})</th>
              <th scope="col">7-day change (%)</th>
            </tr>
          </thead>
          <tbody>
            {holders.cohorts.map((c) => (
              <tr key={c.actor_class}>
                <th scope="row">{c.label}</th>
                <td>{c.addresses}</td>
                <td>{formatCoins(c.balance, "", 0)}</td>
                <td>{formatSignedGrouped(c.change_7d, 2)}</td>
                <td>
                  {formatSigned(c.change_7d_pct, 4, " %")}
                  {c.change_7d_addresses_left ? (
                    <span className="muted"> ({c.change_7d_addresses_left} left the list)</span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {holders.holders.length ? (
        <table className="status-table">
          <thead>
            <tr>
              <th scope="col">Rank</th>
              <th scope="col">Address and classification</th>
              <th scope="col">Balance ({unit})</th>
              <th scope="col">7-day change</th>
            </tr>
          </thead>
          <tbody>
            {holders.holders.map((h) => (
              <tr key={h.classification.address}>
                <td>{h.rank}</td>
                <td>
                  <ClassificationCell c={h.classification} />
                </td>
                <td>{formatCoins(h.balance, "", 2)}</td>
                <td>
                  {h.change_7d === null
                    ? (h.change_7d_note ?? "—")
                    : formatSignedGrouped(h.change_7d, 2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty-chart" role="status">
          No top-100 snapshot stored yet.
        </p>
      )}
    </section>
  );
}
