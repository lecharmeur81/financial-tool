import type { Metadata } from "next";
import { connection } from "next/server";

import { OpsStatus } from "@/components/OpsStatus";
import { SystemStatus } from "@/components/SystemStatus";
import { fetchIngestionRuns, fetchMeta, fetchProviderHealth, fetchReadiness } from "@/lib/api";
import { navItem } from "@/lib/navigation";

const item = navItem("/settings");

export const metadata: Metadata = { title: item.label };

export default async function SettingsPage() {
  // Render at request time so the status is live and API_INTERNAL_URL is read at runtime.
  await connection();
  const [result, meta, providerHealth, ingestionRuns] = await Promise.all([
    fetchReadiness(),
    fetchMeta(),
    fetchProviderHealth(),
    fetchIngestionRuns(20),
  ]);
  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>
      <SystemStatus result={result} />
      <OpsStatus meta={meta} providerHealth={providerHealth} ingestionRuns={ingestionRuns} />
      <div className="placeholder" role="status">
        <span className="badge badge-neutral">Account and security settings not yet built</span>
        <p>No authentication, account management, or settings mutations exist in this build.</p>
      </div>
    </section>
  );
}
