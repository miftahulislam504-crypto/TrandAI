"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "./icons";

const ITEMS: { href: string; label: string; icon: IconName; also?: string[] }[] = [
  { href: "/", label: "তালিকা", icon: "list", also: ["/products", "/matches"] },
  { href: "/watchlist", label: "নজরে", icon: "bookmark" },
  { href: "/alerts", label: "অ্যালার্ট", icon: "bell" },
  { href: "/ads", label: "Ads", icon: "megaphone" },
  { href: "/signals", label: "সিগন্যাল", icon: "bars" },
  { href: "/health", label: "হেলথ", icon: "pulse" },
];

export default function Nav() {
  const path = usePathname() || "/";
  const on = (it: (typeof ITEMS)[number]) =>
    it.href === "/" ? path === "/" || (it.also || []).some((p) => path.startsWith(p)) : path.startsWith(it.href);
  return (
    <nav className="nav" aria-label="প্রধান মেনু">
      {ITEMS.map((it) => (
        <Link key={it.href} href={it.href} aria-current={on(it) ? "page" : undefined}>
          <Icon name={it.icon} size={20} />
          <span>{it.label}</span>
        </Link>
      ))}
    </nav>
  );
}
