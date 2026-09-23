import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/PagePlaceholder";
import { navItem } from "@/lib/navigation";

const item = navItem("/");

export const metadata: Metadata = { title: item.label };

export default function DashboardPage() {
  return <PagePlaceholder item={item} />;
}
