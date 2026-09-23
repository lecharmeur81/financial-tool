import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/PagePlaceholder";
import { navItem } from "@/lib/navigation";

const item = navItem("/analytics");

export const metadata: Metadata = { title: item.label };

export default function AnalyticsPage() {
  return <PagePlaceholder item={item} />;
}
