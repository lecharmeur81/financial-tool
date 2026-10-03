import type { Metadata } from "next";
import { connection } from "next/server";

import { AlertsSection } from "@/components/dashboard/AlertsSection";
import { AutoRefresh } from "@/components/market/AutoRefresh";
import { fetchAlerts } from "@/lib/alerts";
import { navItem } from "@/lib/navigation";

const item = navItem("/alerts");

export const metadata: Metadata = { title: item.label };

export default async function AlertsPage() {
  // Render at request time so alert status is live, never a build-time snapshot.
  await connection();
  const alerts = await fetchAlerts({ limit: 200 });

  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>
      <AlertsSection alerts={alerts} />
      <AutoRefresh seconds={60} renderedAt={new Date().toISOString()} />
    </section>
  );
}
