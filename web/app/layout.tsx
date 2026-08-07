import type { Metadata } from "next";
import "./globals.css";
import TabNav from "@/components/TabNav";

export const metadata: Metadata = {
  title: "House Search",
  description: "Singapore condo screener",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen" style={{ backgroundColor: "var(--bg-primary)" }}>
        <TabNav />
        <main className="max-w-content mx-auto px-6 lg:px-12 pt-8 pb-16">
          {children}
        </main>
      </body>
    </html>
  );
}
