import { SourceText } from "@/components/flows/MetricFacts";
import { formatUtc } from "@/lib/market";
import { DIRECTION_LABEL, formatCoins, shortAddress, type Transfers } from "@/lib/whales";

import { ClassificationCell } from "./ClassificationCell";

/** Large transfers (newest first) with the classification of both sides. */
export function TransfersPanel({ transfers }: { transfers: Transfers }) {
  const t = transfers;
  return (
    <section className="status-card" aria-labelledby="transfers-title">
      <h2 id="transfers-title">
        Large transfers · {t.asset} (≥ {formatCoins(t.threshold, t.unit, 0)})
      </h2>
      <p className="muted">
        {t.definition} Range {formatUtc(t.range.start)} … {formatUtc(t.range.end)}. Source:{" "}
        <SourceText source={t.source} />
      </p>
      <table className="status-table">
        <caption>
          {t.summary.transfers} transfers, {formatCoins(t.summary.total, t.unit, 0)} in total.{" "}
          {t.summary.note}
        </caption>
        <thead>
          <tr>
            <th scope="col">Direction</th>
            <th scope="col">Transfers</th>
            <th scope="col">Total</th>
          </tr>
        </thead>
        <tbody>
          {t.summary.by_direction.map((d) => (
            <tr key={d.direction}>
              <th scope="row">{DIRECTION_LABEL[d.direction] ?? d.direction}</th>
              <td>{d.transfers}</td>
              <td>{formatCoins(d.total, t.unit, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {t.transfers.length ? (
        <table className="status-table">
          <thead>
            <tr>
              <th scope="col">Block time (UTC)</th>
              <th scope="col">Amount</th>
              <th scope="col">From</th>
              <th scope="col">To</th>
              <th scope="col">Transaction</th>
            </tr>
          </thead>
          <tbody>
            {t.transfers.map((x) => (
              <tr key={`${x.tx_hash}:${x.output_index ?? ""}`}>
                <td>{formatUtc(x.time)}</td>
                <td>
                  {formatCoins(x.value, t.unit, 2)}
                  {x.quality_status !== "ok" ? (
                    <>
                      {" "}
                      <span className="badge badge-warn" title={x.quality_note ?? ""}>
                        {x.quality_status}
                      </span>
                    </>
                  ) : null}
                </td>
                <td>
                  {x.sender ? (
                    <ClassificationCell c={x.sender} />
                  ) : (
                    <span className="muted">not part of an output record</span>
                  )}
                </td>
                <td>
                  <ClassificationCell c={x.recipient} />
                </td>
                <td>
                  <code>{shortAddress(x.tx_hash)}</code>
                  {x.output_index !== null ? `:${x.output_index}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty-chart" role="status">
          No large transfers stored for this range.
        </p>
      )}
      {t.truncated ? <p className="muted">Only the newest transfers are listed.</p> : null}
    </section>
  );
}
