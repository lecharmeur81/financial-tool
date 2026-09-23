import type { Metadata } from "next";

import { Sidebar } from "@/components/Sidebar";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Capital Flow Intelligence",
    template: "%s · Capital Flow Intelligence",
  },
  description:
    "Where is money moving, who is moving it, and how is that behavior changing? Decision support — not financial advice.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <Sidebar />
          <main className="content">{children}</main>
        </div>
      </body>
    </html>
  );
}
