import type { Metadata } from "next";
import { connection } from "next/server";

import { PagePlaceholder } from "@/components/PagePlaceholder";
import { SystemStatus } from "@/components/SystemStatus";
import { fetchReadiness } from "@/lib/api";
import { navItem } from "@/lib/navigation";

const item = navItem("/settings");

export const metadata: Metadata = { title: item.label };

export default async function SettingsPage() {
  // Render at request time so the status is live and API_INTERNAL_URL is read at runtime.
  await connection();
  const result = await fetchReadiness();
  return (
    <>
      <PagePlaceholder item={item} />
      <SystemStatus result={result} />
    </>
  );
}
