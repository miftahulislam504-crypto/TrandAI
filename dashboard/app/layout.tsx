import "@fontsource/hind-siliguri/bengali-400.css";
import "@fontsource/hind-siliguri/bengali-500.css";
import "@fontsource/hind-siliguri/bengali-600.css";
import "@fontsource/hind-siliguri/latin-400.css";
import "@fontsource/hind-siliguri/latin-500.css";
import "@fontsource/hind-siliguri/latin-600.css";
import "./globals.css";
import type { Metadata, Viewport } from "next";
import Link from "next/link";
import Nav from "./components/Nav";

export const metadata: Metadata = { title: "Market Research", robots: { index: false, follow: false } };
// সবসময় হালকা (সাদা) থিম, ডার্ক মোড নেই
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#ffffff", colorScheme: "light" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="bn">
      <body>
        <header className="topbar">
          <div className="topbar-in">
            <Link href="/" className="brand">Market Research</Link>
            <Nav />
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
