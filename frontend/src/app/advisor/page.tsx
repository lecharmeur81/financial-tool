import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import { AdvisorBriefLoading, AdvisorBriefSection } from "@/components/advisor/AdvisorBriefView";
import { resolveAdvisorAsset } from "@/lib/advisor";
import { navItem } from "@/lib/navigation";

const item = navItem("/advisor");

export const metadata: Metadata = { title: item.label };

export default async function AdvisorPage(props: PageProps<"/advisor">) {
  // Render at request time so the brief shown is never a build-time snapshot.
  await connection();
  const asset = resolveAdvisorAsset(await props.searchParams);

  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>
      <Suspense fallback={<AdvisorBriefLoading />}>
        <AdvisorBriefSection asset={asset} />
      </Suspense>
    </section>
  );
}
