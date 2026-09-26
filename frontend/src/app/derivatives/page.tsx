import type { Metadata } from "next";
import Link from "next/link";

import { ConditionsPanel } from "@/components/derivatives/ConditionsPanel";
import { CurveOptionsPanel } from "@/components/derivatives/CurveOptionsPanel";
import { DataQualityPanel } from "@/components/derivatives/DataQualityPanel";
import { HealthScoreCard } from "@/components/derivatives/HealthScoreCard";
import { LiquidationsPanel } from "@/components/derivatives/LiquidationsPanel";
import { OpenInterestChart } from "@/components/derivatives/OpenInterestChart";
import { PositioningPanel } from "@/components/derivatives/PositioningPanel";
import { AutoRefresh } from "@/components/market/AutoRefresh";
import {
  DERIVATIVE_ASSETS,
  fetchDerivativesAsset,
  fetchDerivativesCatalog,
  fetchDerivativesHistory,
  resolveDerivativeAsset,
} from "@/lib/derivatives";
import { navItem } from "@/lib/navigation";

const item = navItem("/derivatives");

export const metadata: Metadata = { title: item.label };

function Unavailable({ what, reason }: { what: string; reason: string }) {
  return (
    <div className="status-card" role="alert">
      <span className="badge badge-error">{what} unavailable</span> <span>{reason}</span>
      <p className="muted">Nothing is shown in its place — no cached or estimated values.</p>
    </div>
  );
}

export default async function DerivativesPage(props: PageProps<"/derivatives">) {
  const asset = resolveDerivativeAsset(await props.searchParams);
  const [view, history, catalog] = await Promise.all([
    fetchDerivativesAsset(asset),
    fetchDerivativesHistory(asset),
    fetchDerivativesCatalog(),
  ]);

  return (
    <section className="page">
      <header className="page-header">
        <h1>Derivatives · {asset}</h1>
        <p className="page-description">
          Open interest, leverage, funding, futures basis, liquidations and options positioning,
          with the formula and parameters of every calculation and the Derivatives Health Score
          broken into its components. Leverage, funding and skew are shown with their direction as
          context — never as bullish or bearish. Descriptive only: no forecasts, no trading signals,
          not financial advice.
        </p>
      </header>

      <div className="market-controls">
        <nav aria-label="Asset" className="segmented">
          {DERIVATIVE_ASSETS.map((a) => (
            <Link
              key={a}
              href={`/derivatives?asset=${a}`}
              className={a === asset ? "segment active" : "segment"}
              aria-current={a === asset ? "page" : undefined}
            >
              {a}
            </Link>
          ))}
        </nav>
      </div>

      {view.ok ? (
        <>
          <p className="muted">{view.data.evidence_note}</p>
          <HealthScoreCard score={view.data.score} asset={asset} />
          <ConditionsPanel conditions={view.data.conditions} />
          <PositioningPanel view={view.data} />
        </>
      ) : (
        <Unavailable what="Derivatives data" reason={view.reason} />
      )}

      {history.ok ? (
        history.data.open_interest.aggregate.length ? (
          <section className="status-card" aria-labelledby="deriv-chart-title">
            <h2 id="deriv-chart-title">Open interest and price, {history.data.days} days</h2>
            <OpenInterestChart history={history.data} />
            <p className="muted">
              Aggregate of {history.data.open_interest.aggregate_venues.join(" + ") || "—"}; only
              hours at which every venue reported are drawn. Price: {history.data.price.source}.
            </p>
          </section>
        ) : null
      ) : (
        <Unavailable what="Open interest history" reason={history.reason} />
      )}

      {view.ok ? (
        <>
          <CurveOptionsPanel view={view.data} />
          <LiquidationsPanel liq={view.data.liquidations} />
          <DataQualityPanel quality={view.data.data_quality} />
        </>
      ) : null}

      {catalog.ok ? (
        <section className="status-card" aria-labelledby="deriv-coverage-title">
          <h2 id="deriv-coverage-title">Method, coverage and limits</h2>
          <ul className="note-list">
            {catalog.data.score.method.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
          <h3>Thresholds</h3>
          <ul className="note-list">
            {Object.entries(catalog.data.parameters).map(([k, v]) => (
              <li key={k}>
                {k.replaceAll("_", " ")}: {v}
              </li>
            ))}
          </ul>
          <p className="muted">{catalog.data.score.parameters_note}</p>
          <h3>Not tracked</h3>
          <ul className="note-list">
            {catalog.data.not_tracked.map((n) => (
              <li key={n.item}>
                {n.item}: {n.reason}
              </li>
            ))}
          </ul>
          <h3>Providers</h3>
          <ul className="note-list">
            {catalog.data.providers.map((p) => (
              <li key={p.provider_id}>
                {p.display_name}
                {p.enabled ? "" : " (disabled)"} — {p.notes}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* hourly data: refresh every 5 minutes */}
      <AutoRefresh seconds={300} renderedAt={new Date().toISOString()} />
    </section>
  );
}
