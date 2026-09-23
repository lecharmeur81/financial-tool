import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/PagePlaceholder";
import { navItem } from "@/lib/navigation";

const item = navItem("/derivatives");

export const metadata: Metadata = { title: item.label };

export default function DerivativesPage() {
  return <PagePlaceholder item={item} />;
}
