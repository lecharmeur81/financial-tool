import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import { AlertsSection } from "@/components/dashboard/AlertsSection";
import { AnomalySection } from "@/components/dashboard/AnomalySection";
import { BriefSection } from "@/components/dashboard/BriefSection";
import { DecisionCenterLoading, DecisionCenterSection } from "@/components/decision/DecisionCenter";
import { DerivativesLiquiditySection } from "@/components/dashboard/DerivativesLiquiditySection";
import { DivergenceSection } from "@/components/dashboard/DivergenceSection";
import { IntelligenceEventsSection } from "@/components/dashboard/IntelligenceEventsSection";
import { IntelligenceOverviewSection } from "@/components/dashboard/IntelligenceOverviewSection";
import { JournalPaperSection } from "@/components/dashboard/JournalPaperSection";
import { MacroSection } from "@/components/dashboard/MacroSection";
import { MarketOverviewSection } from "@/components/dashboard/MarketOverviewSection";
import { ParticipantsSection } from "@/components/dashboard/ParticipantsSection";
import { RegimeSection } from "@/components/dashboard/RegimeSection";
import { RotationSection } from "@/components/dashboard/RotationSection";
import { Unavailable } from "@/components/dashboard/Unavailable";
import { AutoRefresh } from "@/components/market/AutoRefresh";
import { fetchAlerts } from "@/lib/alerts";
import { fetchAnomalyScan } from "@/lib/anomaly";
import { fetchLatestBrief } from "@/lib/brief";
import { resolveDecisionAsset } from "@/lib/decision";
import { fetchDerivativesAsset } from "@/lib/derivatives";
import { fetchDivergenceMatrix } from "@/lib/divergence";
import { fetchInstitutionalOverview } from "@/lib/institutional";
import { fetchIntelligenceEvents } from "@/lib/intelligence";
import { fetchRecentDecisions } from "@/lib/journal";
import { fetchLiquidityOverview } from "@/lib/liquidity";
import { fetchMacroOverview } from "@/lib/macro";
import { fetchOverview, fetchSummary } from "@/lib/market";
import { fetchMarketStructureOverview } from "@/lib/market-structure";
import { navItem } from "@/lib/navigation";
import { fetchOpenPositions, fetchPaperPerformance, fetchRecentTrades } from "@/lib/paper";
import { fetchCurrentRegime } from "@/lib/regime";
import { fetchRetailOverview } from "@/lib/retail";
import { fetchRotationMatrix } from "@/lib/rotation";
import { fetchWhaleScore } from "@/lib/whales";

const item = navItem("/");

export const metadata: Metadata = { title: item.label };

/**
 * Every analytics section below the Decision Center. It is fetched on its own (and streamed) so the
 * Decision Center never waits on these requests — in particular the slow market-regime call.
 */
async function DashboardAnalytics() {
  const [
    regime,
    summary,
    structure,
    marketOverview,
    institutional,
    whaleScore,
    retail,
    liquidity,
    derivatives,
    rotation,
    divergence,
    anomaly,
    macro,
    alerts,
    brief,
    trades,
    positions,
    performance,
    decisions,
    intelligenceEvents,
  ] = await Promise.all([
    fetchCurrentRegime(),
    fetchSummary(),
    fetchMarketStructureOverview(),
    fetchOverview(),
    fetchInstitutionalOverview(),
    fetchWhaleScore("BTC"),
    fetchRetailOverview(),
    fetchLiquidityOverview(),
    fetchDerivativesAsset("BTC"),
    fetchRotationMatrix(),
    fetchDivergenceMatrix(),
    fetchAnomalyScan(),
    fetchMacroOverview(),
    fetchAlerts({ limit: 10 }),
    fetchLatestBrief(),
    fetchRecentTrades(5),
    fetchOpenPositions(),
    fetchPaperPerformance(),
    fetchRecentDecisions(5),
    fetchIntelligenceEvents({ limit: 5 }),
  ]);

  return (
    <>
      {regime.ok ? (
        <RegimeSection regime={regime.data} />
      ) : (
        <Unavailable what="Market regime" reason={regime.reason} />
      )}

      {summary.ok ? (
        <MarketOverviewSection
          summary={summary.data}
          structure={structure.ok ? structure.data : null}
          overview={marketOverview.ok ? marketOverview.data : null}
        />
      ) : (
        <Unavailable what="Market overview" reason={summary.reason} />
      )}

      <IntelligenceOverviewSection
        institutional={institutional.ok ? institutional.data : null}
        whaleScore={whaleScore.ok ? whaleScore.data : null}
        retail={retail.ok ? retail.data : null}
        liquidity={liquidity.ok ? liquidity.data : null}
        derivatives={derivatives.ok ? derivatives.data : null}
        rotation={rotation.ok ? rotation.data : null}
      />

      <IntelligenceEventsSection events={intelligenceEvents} />

      <DivergenceSection matrix={divergence} />

      <AnomalySection scan={anomaly} />

      <RotationSection matrix={rotation} />

      <ParticipantsSection
        institutional={institutional.ok ? institutional.data : null}
        whaleScore={whaleScore.ok ? whaleScore.data : null}
        retail={retail.ok ? retail.data : null}
      />

      <DerivativesLiquiditySection
        derivatives={derivatives.ok ? derivatives.data : null}
        liquidity={liquidity.ok ? liquidity.data : null}
      />

      <MacroSection macro={macro} />

      <AlertsSection alerts={alerts} />

      <BriefSection brief={brief} />

      <JournalPaperSection
        trades={trades}
        positions={positions}
        performance={performance}
        decisions={decisions}
      />
    </>
  );
}

export default async function DashboardPage(props: PageProps<"/">) {
  // Render at request time so every section's freshness is live, never a build-time snapshot.
  await connection();
  const asset = resolveDecisionAsset(await props.searchParams);

  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>

      <Suspense fallback={<DecisionCenterLoading />}>
        <DecisionCenterSection asset={asset} />
      </Suspense>

      <Suspense
        fallback={
          <div className="placeholder" role="status">
            Loading the rest of the dashboard…
          </div>
        }
      >
        <DashboardAnalytics />
      </Suspense>

      {/* intelligence data refreshes on backend schedules measured in minutes/hours */}
      <AutoRefresh seconds={300} renderedAt={new Date().toISOString()} />
    </section>
  );
}
