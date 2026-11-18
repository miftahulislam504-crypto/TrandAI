import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Market Research", robots: { index: false, follow: false } };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="bn">
      <body>
        <nav className="nav">
          <Link href="/">তালিকা</Link>
          <Link href="/watchlist">⭐ নজরে</Link>
          <Link href="/alerts">🔔 অ্যালার্ট</Link>
          <Link href="/ads">📢 Ads</Link>
          <Link href="/health">🩺 হেলথ</Link>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
