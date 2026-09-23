import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/PagePlaceholder";
import { navItem } from "@/lib/navigation";

const item = navItem("/liquidity");

export const metadata: Metadata = { title: item.label };

export default function LiquidityPage() {
  return <PagePlaceholder item={item} />;
}
