import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/PagePlaceholder";
import { navItem } from "@/lib/navigation";

const item = navItem("/market");

export const metadata: Metadata = { title: item.label };

export default function MarketPage() {
  return <PagePlaceholder item={item} />;
}
