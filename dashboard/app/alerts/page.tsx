import Link from "next/link";
import { rest } from "@/lib/supabase";
import { day } from "@/lib/format";
import { inList } from "@/lib/watch";
import { markAlertsSeen } from "@/app/watch/actions";

export const dynamic = "force-dynamic";

type A = {
  id: number; canonical_product_id: number; kind: string; created_on: string; watched: boolean; severity: string;
  title: string; seen_at: string | null;
};
const KIND: Record<string, string> = { tier_change: "ট্যাগ বদল", score_move: "স্কোর সরেছে", price_move: "বাজারদর বদল", redflag: "নকল অভিযোগ" };
const ICON: Record<string, string> = { good: "🟢", warn: "🔴", info: "⚪" };
const LIMIT = 100;

export default async function Alerts({ searchParams }: { searchParams: Record<string, string | undefined> }) {
  const err = (searchParams.watch_err ?? "").slice(0, 300);
  const alerts = await rest<A[]>("alerts", {
    select: "id,canonical_product_id,kind,created_on,watched,severity,title,seen_at", order: "created_on.desc,id.desc", limit: String(LIMIT),
  }).catch(() => null);
  if (alerts === null) {
    return (<><h1>🔔 অ্যালার্ট</h1><p className="muted">Phase 7 migration (<code>20261117000000_phase7.sql</code>) এখনও চালানো হয়নি।</p></>);
  }
  // অ্যালার্ট থেকে প্রোডাক্ট-পেজের লিংক (পেজ listing id ধরে): প্রতি canonical-এর ছোট id-র সক্রিয় listing
  const pids = [...new Set(alerts.map((a) => a.canonical_product_id))];
  const links = new Map<number, number>();
  if (pids.length) {
    const ls = await rest<{ id: number; canonical_product_id: number }[]>("listing_overview", {
      canonical_product_id: inList(pids), is_active: "eq.true", select: "id,canonical_product_id", order: "id.desc",
    }).catch(() => []);
    for (const l of ls) links.set(l.canonical_product_id, l.id);   // id.desc, তাই শেষে ছোটটা থাকে
  }
  const unseen = alerts.filter((a) => !a.seen_at);
  const dates = [...new Set(alerts.map((a) => a.created_on))];

  return (
    <>
      <h1>🔔 অ্যালার্ট</h1>
      {err && <p className="down">{err}</p>}
      <p className="muted">
        না-দেখা {unseen.length}টা · সর্বশেষ {alerts.length}টা দেখাচ্ছে · <Link href="/watchlist">⭐ ওয়াচলিস্ট</Link> · <a href="/export?kind=alerts">⬇ CSV</a>
      </p>
      {unseen.length > 0 && (
        <form action={markAlertsSeen}><button type="submit" className="linkbtn">✓ সব দেখা হয়েছে চিহ্নিত করুন</button></form>
      )}
      {alerts.length === 0 && <p className="muted">এখনও কোনো অ্যালার্ট নেই। Score Daily চলার পর, ট্যাগ বা স্কোর বদলালে এখানে আসবে।</p>}
      {dates.map((d) => (
        <div key={d}>
          <h3 className="muted" style={{ margin: "14px 0 6px" }}>{day(d)}</h3>
          {alerts.filter((a) => a.created_on === d).map((a) => {
            const lid = links.get(a.canonical_product_id);
            return (
              <div key={a.id} className="card" style={a.seen_at ? { opacity: 0.65 } : undefined}>
                <div className="title">
                  {ICON[a.severity] ?? "⚪"} {a.watched ? "⭐ " : ""}
                  {lid ? <Link href={`/products/${lid}`}>{a.title}</Link> : a.title}
                </div>
                <div className="muted">{KIND[a.kind] ?? a.kind}{a.seen_at ? "" : " · নতুন"}</div>
              </div>
            );
          })}
        </div>
      ))}
    </>
  );
}
