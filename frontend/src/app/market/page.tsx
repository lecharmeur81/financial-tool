import type { Metadata } from "next";

import { AssetSummary } from "@/components/market/AssetSummary";
import { AutoRefresh } from "@/components/market/AutoRefresh";
import { DataStatus } from "@/components/market/DataStatus";
import { MarketControls } from "@/components/market/MarketControls";
import { PriceChart } from "@/components/market/PriceChart";
import { fetchBars, fetchCatalog, fetchOverview, formatUnit, resolveSelection } from "@/lib/market";
import { navItem } from "@/lib/navigation";

const item = navItem("/market");

export const metadata: Metadata = { title: item.label };

function Unavailable({ what, reason }: { what: string; reason: string }) {
  return (
    <div className="status-card" role="alert">
      <span className="badge badge-error">{what} unavailable</span> <span>{reason}</span>
      <p className="muted">Nothing is shown in its place — no cached or estimated values.</p>
    </div>
  );
}

export default async function MarketPage(props: PageProps<"/market">) {
  const query = await props.searchParams;
  const catalog = await fetchCatalog();
  if (!catalog.ok) {
    return (
      <section className="page">
        <header className="page-header">
          <h1>{item.label}</h1>
        </header>
        <Unavailable what="Market data API" reason={catalog.reason} />
      </section>
    );
  }
  const selection = resolveSelection(catalog.data, query);
  const [bars, overview] = await Promise.all([
    fetchBars({ ...selection, limit: 300 }),
    fetchOverview(),
  ]);
  const assetName =
    catalog.data.assets.find((a) => a.symbol === selection.asset)?.name ?? selection.asset;
  const assetOverview = overview.ok
    ? overview.data.assets.find((a) => a.symbol === selection.asset)
    : undefined;

  return (
    <section className="page">
      <header className="page-header">
        <h1>
          {item.label} · {assetName}
        </h1>
        <p className="page-description">
          Observed spot market data: prices, candles, volume and market capitalisation, each with
          its source, time and freshness. No signals, forecasts or recommendations — not financial
          advice.
        </p>
      </header>

      <MarketControls catalog={catalog.data} selection={selection} />

      {assetOverview ? (
        <AssetSummary asset={assetOverview} />
      ) : (
        <Unavailable
          what="Latest values"
          reason={overview.ok ? "asset not found" : overview.reason}
        />
      )}

      {bars.ok ? (
        <>
          <div className="status-card chart-card">
            <h2>
              {bars.data.instrument.instrument_id} · {selection.timeframe} ·{" "}
              {formatUnit(bars.data.instrument.price_unit)}
            </h2>
            {bars.data.bars.length ? (
              <PriceChart
                bars={bars.data.bars}
                priceUnit={bars.data.instrument.price_unit}
                volumeUnit={bars.data.instrument.volume_unit}
                label={`${selection.asset} ${selection.timeframe}`}
              />
            ) : (
              <p className="empty-chart" role="status">
                No bars stored for this selection yet. The ingestion workers fill this in once they
                run (see Data status below).
              </p>
            )}
            <p className="muted">
              Times in UTC. Candles show completed bars only; gaps are missing bars, never filled
              in. Charting by{" "}
              <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
                TradingView Lightweight Charts™
              </a>{" "}
              (Copyright © 2025 TradingView, Inc.).
            </p>
          </div>
          <DataStatus data={bars.data} />
        </>
      ) : (
        <Unavailable what="Bars" reason={bars.reason} />
      )}

      <AutoRefresh renderedAt={new Date().toISOString()} />
    </section>
  );
}
