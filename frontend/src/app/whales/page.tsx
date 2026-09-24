import type { Metadata } from "next";
import Link from "next/link";

import { AutoRefresh } from "@/components/market/AutoRefresh";
import { ContradictionPanel } from "@/components/whales/ContradictionPanel";
import { DailyFlowsPanel } from "@/components/whales/DailyFlowsPanel";
import { HoldersPanel } from "@/components/whales/HoldersPanel";
import { TransfersPanel } from "@/components/whales/TransfersPanel";
import { WhaleScoreCard } from "@/components/whales/WhaleScoreCard";
import { navItem } from "@/lib/navigation";
import {
  fetchHolders,
  fetchTransfers,
  fetchWhaleCatalog,
  fetchWhaleFlows,
  fetchWhaleScore,
  resolveWhaleAsset,
  WHALE_ASSETS,
} from "@/lib/whales";

const item = navItem("/whales");

export const metadata: Metadata = { title: item.label };

function Unavailable({ what, reason }: { what: string; reason: string }) {
  return (
    <div className="status-card" role="alert">
      <span className="badge badge-error">{what} unavailable</span> <span>{reason}</span>
      <p className="muted">Nothing is shown in its place — no cached or estimated values.</p>
    </div>
  );
}

export default async function WhalesPage(props: PageProps<"/whales">) {
  const asset = resolveWhaleAsset(await props.searchParams);
  const [score, flows, holders, transfers, catalog] = await Promise.all([
    fetchWhaleScore(asset),
    fetchWhaleFlows(asset),
    fetchHolders(asset),
    fetchTransfers(asset),
    fetchWhaleCatalog(),
  ]);

  return (
    <section className="page">
      <header className="page-header">
        <h1>Whale intelligence · {asset}</h1>
        <p className="page-description">
          Exchange flows, large holders, large transfers and coin-age activity, with the source,
          time, unit, calculation, freshness and data quality of every number, and the evidence,
          source and confidence of every address label. A large address is never called an
          institution. Descriptive only: no forecasts, no trading signals, not financial advice.
        </p>
      </header>

      <div className="market-controls">
        <nav aria-label="Asset" className="segmented">
          {WHALE_ASSETS.map((a) => (
            <Link
              key={a}
              href={`/whales?asset=${a}`}
              className={a === asset ? "segment active" : "segment"}
              aria-current={a === asset ? "page" : undefined}
            >
              {a}
            </Link>
          ))}
        </nav>
      </div>

      {score.ok ? (
        <>
          <WhaleScoreCard score={score.data} />
          <ContradictionPanel
            items={score.data.contradictions}
            rule={catalog.ok ? catalog.data.score.contradiction_rule : null}
          />
        </>
      ) : (
        <Unavailable what="Whale Flow Score" reason={score.reason} />
      )}

      {flows.ok ? (
        <DailyFlowsPanel flows={flows.data} />
      ) : (
        <Unavailable what="Exchange flows" reason={flows.reason} />
      )}

      {holders.ok ? (
        <HoldersPanel holders={holders.data} />
      ) : (
        <Unavailable what="Largest addresses" reason={holders.reason} />
      )}

      {transfers.ok ? (
        <TransfersPanel transfers={transfers.data} />
      ) : (
        <Unavailable what="Large transfers" reason={transfers.reason} />
      )}

      {catalog.ok ? (
        <section className="status-card" aria-labelledby="whale-coverage-title">
          <h2 id="whale-coverage-title">Classification rules, coverage and limits</h2>
          <ul className="note-list">
            {catalog.data.classification_rules.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <p className="muted">
            Thresholds ({catalog.data.thresholds.note}): large transfer{" "}
            {Object.entries(catalog.data.thresholds.large_transfer)
              .map(([a, v]) => `${Number(v).toLocaleString("en-US")} ${a}`)
              .join(", ")}
            ; unknown large holder{" "}
            {Object.entries(catalog.data.thresholds.unknown_large_holder_balance)
              .map(([a, v]) => `${Number(v).toLocaleString("en-US")} ${a}`)
              .join(", ")}
            . {catalog.data.score.parameters_note}
          </p>
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
                {p.attribution ? (
                  <>
                    {" "}
                    <a href={p.attribution.url} target="_blank" rel="noopener noreferrer">
                      {p.attribution.text}
                    </a>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* daily data and a 3-hourly transfer feed: refresh every 5 minutes is plenty */}
      <AutoRefresh seconds={300} renderedAt={new Date().toISOString()} />
    </section>
  );
}
