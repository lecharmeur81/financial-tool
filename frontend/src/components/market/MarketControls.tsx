import Link from "next/link";

import { type Catalog, type Selection, formatUnit, selectionHref } from "@/lib/market";

/** Asset, venue and timeframe switching. Plain links: the page re-renders on the server. */
export function MarketControls({ catalog, selection }: { catalog: Catalog; selection: Selection }) {
  const venue = catalog.venues.find((v) => v.venue_id === selection.venue) ?? catalog.venues[0];
  return (
    <div className="market-controls">
      <nav aria-label="Asset" className="segmented">
        {catalog.assets.map((a) => (
          <Link
            key={a.symbol}
            href={selectionHref(selection, { asset: a.symbol })}
            className={a.symbol === selection.asset ? "segment active" : "segment"}
            aria-current={a.symbol === selection.asset ? "page" : undefined}
            title={a.name}
          >
            {a.symbol}
          </Link>
        ))}
      </nav>
      <nav aria-label="Timeframe" className="segmented">
        {venue?.timeframes.map((t) => (
          <Link
            key={t.timeframe}
            href={selectionHref(selection, { timeframe: t.timeframe })}
            className={t.timeframe === selection.timeframe ? "segment active" : "segment"}
            aria-current={t.timeframe === selection.timeframe ? "page" : undefined}
            title={
              t.source === "derived"
                ? `Derived from ${t.derived_from} bars (the venue does not publish ${t.timeframe})`
                : `${t.timeframe} bars as published by the venue`
            }
          >
            {t.timeframe}
            {t.source === "derived" ? "*" : ""}
          </Link>
        ))}
      </nav>
      <nav aria-label="Venue" className="segmented">
        {catalog.venues.map((v) => (
          <Link
            key={v.venue_id}
            href={selectionHref(selection, {
              venue: v.venue_id,
              timeframe: v.timeframes.some((t) => t.timeframe === selection.timeframe)
                ? selection.timeframe
                : "1h",
            })}
            className={v.venue_id === selection.venue ? "segment active" : "segment"}
            aria-current={v.venue_id === selection.venue ? "page" : undefined}
          >
            {v.display_name} · {formatUnit(v.quote)}
            {v.source.enabled ? "" : " (disabled)"}
          </Link>
        ))}
      </nav>
    </div>
  );
}
