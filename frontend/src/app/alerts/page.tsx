import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/PagePlaceholder";
import { navItem } from "@/lib/navigation";

const item = navItem("/alerts");

export const metadata: Metadata = { title: item.label };

export default function AlertsPage() {
  return <PagePlaceholder item={item} />;
}
