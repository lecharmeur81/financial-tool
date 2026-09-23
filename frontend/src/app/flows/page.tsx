import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/PagePlaceholder";
import { navItem } from "@/lib/navigation";

const item = navItem("/flows");

export const metadata: Metadata = { title: item.label };

export default function FlowsPage() {
  return <PagePlaceholder item={item} />;
}
