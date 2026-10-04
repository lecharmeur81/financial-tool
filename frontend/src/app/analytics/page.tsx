import type { Metadata } from "next";
import { connection } from "next/server";

import { AnomalySection } from "@/components/dashboard/AnomalySection";
import { DivergenceSection } from "@/components/dashboard/DivergenceSection";
import { RegimeSection } from "@/components/dashboard/RegimeSection";
import { RotationSection } from "@/components/dashboard/RotationSection";
import { Unavailable } from "@/components/dashboard/Unavailable";
import { SimilaritySection } from "@/components/analytics/SimilaritySection";
import { IntelligenceEventsPanel } from "@/components/analytics/IntelligenceEventsPanel";
import { AutoRefresh } from "@/components/market/AutoRefresh";
import { fetchAnomalyScan } from "@/lib/anomaly";
import { fetchDivergenceMatrix } from "@/lib/divergence";
import { fetchIntelligenceEvents } from "@/lib/intelligence";
import { navItem } from "@/lib/navigation";
import { fetchCurrentRegime } from "@/lib/regime";
import { fetchRotationMatrix } from "@/lib/rotation";
import { fetchSimilarityCurrent } from "@/lib/similarity";

const item = navItem("/analytics");

export const metadata: Metadata = { title: item.label };

export default async function AnalyticsPage() {
  // Render at request time so every section's freshness is live, never a build-time snapshot.
  await connection();
  const [regime, divergence, anomaly, rotation, similarity, events] = await Promise.all([
    fetchCurrentRegime(),
    fetchDivergenceMatrix(),
    fetchAnomalyScan(),
    fetchRotationMatrix(),
    fetchSimilarityCurrent(),
    fetchIntelligenceEvents({ limit: 50 }),
  ]);

  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>

      {regime.ok ? (
        <RegimeSection regime={regime.data} />
      ) : (
        <Unavailable what="Market regime" reason={regime.reason} />
      )}

      <DivergenceSection matrix={divergence} />

      <AnomalySection scan={anomaly} />

      <RotationSection matrix={rotation} />

      <SimilaritySection similarity={similarity} />

      <IntelligenceEventsPanel events={events} />

      {/* intelligence data refreshes on backend schedules measured in minutes/hours */}
      <AutoRefresh seconds={300} renderedAt={new Date().toISOString()} />
    </section>
  );
}
