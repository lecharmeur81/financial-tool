import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import {
  PortfolioExposureLoading,
  PortfolioExposureSection,
} from "@/components/portfolio/PortfolioExposureView";
import { navItem } from "@/lib/navigation";

const item = navItem("/portfolio");

export const metadata: Metadata = { title: item.label };

export default async function PortfolioPage() {
  // Render at request time so the exposure shown is never a build-time snapshot.
  await connection();

  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>
      <Suspense fallback={<PortfolioExposureLoading />}>
        <PortfolioExposureSection />
      </Suspense>
    </section>
  );
}
