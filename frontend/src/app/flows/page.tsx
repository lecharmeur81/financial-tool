import type { Metadata } from "next";

import { AutoRefresh } from "@/components/market/AutoRefresh";
import { FlowChart } from "@/components/flows/FlowChart";
import { FlowControls } from "@/components/flows/FlowControls";
import { FlowTable } from "@/components/flows/FlowTable";
import { FundsTable } from "@/components/flows/FundsTable";
import { FreshnessText, SourceText } from "@/components/flows/MetricFacts";
import { OverviewTiles } from "@/components/flows/OverviewTiles";
import { ScoreCard } from "@/components/flows/ScoreCard";
import { TreasuryPanel } from "@/components/flows/TreasuryPanel";
import {
  fetchEtfFlows,
  fetchEtfFunds,
  fetchInstitutionalCatalog,
  fetchInstitutionalOverview,
  fetchScore,
  fetchTreasury,
  INTERVAL_LABEL,
  resolveFlowSelection,
} from "@/lib/institutional";
import { formatUtc } from "@/lib/market";
import { navItem } from "@/lib/navigation";

const item = navItem("/flows");

export const metadata: Metadata = { title: item.label };

function Unavailable({ what, reason }: { what: string; reason: string }) {
  return (
    <div className="status-card" role="alert">
      <span className="badge badge-error">{what} unavailable</span> <span>{reason}</span>
      <p className="muted">Nothing is shown in its place — no cached or estimated values.</p>
    </div>
  );
}

export default async function FlowsPage(props: PageProps<"/flows">) {
  const selection = resolveFlowSelection(await props.searchParams);
  const { asset, interval } = selection;
  const [overview, score, flows, funds, treasury, catalog] = await Promise.all([
    fetchInstitutionalOverview(),
    fetchScore(asset),
    fetchEtfFlows(asset, interval),
    fetchEtfFunds(asset),
    fetchTreasury(asset, interval === "1d" ? "1w" : interval),
    fetchInstitutionalCatalog(),
  ]);

  return (
    <section className="page">
      <header className="page-header">
        <h1>Institutional capital · {asset}</h1>
        <p className="page-description">
          Flows through institutional channels — US spot ETFs and listed-company treasuries — with
          the source, time, unit, calculation, freshness and data quality of every number.
          Descriptive only: no forecasts, no trading signals, not financial advice.
        </p>
      </header>

      <FlowControls selection={selection} />

      {overview.ok ? (
        <OverviewTiles overview={overview.data} selection={selection} />
      ) : (
        <Unavailable what="Overview" reason={overview.reason} />
      )}

      {score.ok ? (
        <ScoreCard score={score.data} />
      ) : (
        <Unavailable what="Score" reason={score.reason} />
      )}

      {flows.ok ? (
        <section className="status-card chart-card" aria-labelledby="flows-title">
          <h2 id="flows-title">
            {flows.data.definition.label} · {INTERVAL_LABEL[interval]}
          </h2>
          {flows.data.warnings.length ? (
            <ul className="warnings">
              {flows.data.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
          {flows.data.buckets.some((b) => b.net_flow_usd !== null) ? (
            <FlowChart buckets={flows.data.buckets} label={`${asset} ETF net flow`} />
          ) : (
            <p className="empty-chart" role="status">
              No ETF flow data stored for this range yet.
            </p>
          )}
          <dl className="facts">
            <div>
              <dt>Evidence</dt>
              <dd>
                <span className="badge badge-neutral">
                  {flows.data.evidence_category === "observed"
                    ? "Observed data"
                    : "Calculated metric"}
                </span>
                <span className="badge badge-neutral">{flows.data.evidence_class} evidence</span>
              </dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>
                <SourceText source={flows.data.source} />
              </dd>
            </div>
            <div>
              <dt>Unit / sign</dt>
              <dd>
                {flows.data.definition.unit.toUpperCase()} · {flows.data.definition.sign}
              </dd>
            </div>
            <div>
              <dt>Calculation</dt>
              <dd>{flows.data.definition.calculation}</dd>
            </div>
            <div>
              <dt>Timestamp</dt>
              <dd>
                {flows.data.definition.event_time} · newest day {flows.data.latest_day ?? "—"} ·
                stored history from {flows.data.coverage_start ?? "—"}
              </dd>
            </div>
            <div>
              <dt>Freshness</dt>
              <dd>
                <FreshnessText freshness={flows.data.freshness} />
              </dd>
            </div>
            <div>
              <dt>Last ingestion</dt>
              <dd>
                {flows.data.ingestion.last_run
                  ? `${flows.data.ingestion.last_run.status} · ${formatUtc(flows.data.ingestion.last_run.started_at)}${
                      flows.data.ingestion.last_run.error_code
                        ? ` · ${flows.data.ingestion.last_run.error_code}: ${flows.data.ingestion.last_run.error_detail}`
                        : ""
                    }`
                  : "no run yet"}
              </dd>
            </div>
          </dl>
          <FlowTable flows={flows.data} />
          <p className="muted">
            Dates are US trading dates. Missing days are shown as holes, never filled. Charting by{" "}
            <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
              TradingView Lightweight Charts™
            </a>
            .
          </p>
        </section>
      ) : (
        <Unavailable what="ETF flows" reason={flows.reason} />
      )}

      {funds.ok ? (
        <section className="status-card" aria-labelledby="funds-title">
          <h2 id="funds-title">Flows by fund · {asset}</h2>
          {funds.data.warnings.length ? (
            <ul className="warnings">
              {funds.data.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
          <FundsTable funds={funds.data} />
        </section>
      ) : (
        <Unavailable what="Per-fund flows" reason={funds.reason} />
      )}

      {treasury.ok ? (
        <TreasuryPanel treasury={treasury.data} />
      ) : (
        <Unavailable what="Treasuries" reason={treasury.reason} />
      )}

      {catalog.ok ? (
        <section className="status-card" aria-labelledby="coverage-title">
          <h2 id="coverage-title">Coverage and limits</h2>
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
                {p.enabled ? "" : " (disabled)"}
                {p.requires_api_key ? ` · needs API key ${p.api_key_variable}` : ""}
                {p.terms_verified ? "" : " · terms not verified"} — {p.notes}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* daily data: refresh every 5 minutes is plenty */}
      <AutoRefresh seconds={300} renderedAt={new Date().toISOString()} />
    </section>
  );
}
