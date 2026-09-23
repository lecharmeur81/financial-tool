import {
  type AssetOverview,
  FRESHNESS_CLASS,
  FRESHNESS_LABEL,
  formatAge,
  formatCompact,
  formatDecimal,
  formatUnit,
  formatUtc,
} from "@/lib/market";

/** Latest observed values for one asset, each with its own source, time and freshness. */
export function AssetSummary({ asset }: { asset: AssetOverview }) {
  const trade = asset.last_trade;
  const cap = asset.market_cap;
  return (
    <section className="summary-grid" aria-label={`${asset.name} latest values`}>
      <article className="tile">
        <h3>Last trade</h3>
        <p className="tile-value">
          {trade.value ? `${formatDecimal(trade.value)} ${formatUnit(trade.unit)}` : "—"}
        </p>
        <p className="muted">
          <span className={FRESHNESS_CLASS[trade.freshness]}>
            {FRESHNESS_LABEL[trade.freshness]}
          </span>{" "}
          {formatUtc(trade.time)} · {formatAge(trade.age_seconds)}
        </p>
        <p className="muted">
          {trade.source.provider_name}
          {trade.instrument_id ? ` · ${trade.instrument_id}` : ""}
        </p>
      </article>
      <article className="tile">
        <h3>Market capitalisation</h3>
        <p className="tile-value" title={cap.value ? `${cap.value} ${formatUnit(cap.unit)}` : ""}>
          {formatCompact(cap.value, cap.unit)}
        </p>
        <p className="muted">
          <span className={FRESHNESS_CLASS[cap.freshness]}>{FRESHNESS_LABEL[cap.freshness]}</span>{" "}
          {formatUtc(cap.time)} · {formatAge(cap.age_seconds)}
        </p>
        <p className="muted">
          {cap.source.attribution ? (
            <a
              href={cap.source.attribution.url}
              target="_blank"
              rel="noopener noreferrer"
              className="attribution"
            >
              {cap.source.attribution.text}
            </a>
          ) : (
            cap.source.provider_name
          )}
        </p>
      </article>
      <article className="tile">
        <h3>Latest 1m close by venue</h3>
        <ul className="venue-list">
          {asset.latest_bars.map((b) => (
            <li key={b.venue_id}>
              <span>{b.venue_name}</span>{" "}
              <strong>{b.close ? `${formatDecimal(b.close)} ${formatUnit(b.unit)}` : "—"}</strong>{" "}
              <span className={FRESHNESS_CLASS[b.freshness]}>{FRESHNESS_LABEL[b.freshness]}</span>
              <span className="muted"> {formatAge(b.age_seconds)}</span>
            </li>
          ))}
        </ul>
        <p className="muted">USD and USDT prices are different units and are not combined.</p>
      </article>
    </section>
  );
}
