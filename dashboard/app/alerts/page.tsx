import Link from "next/link";
import { rest } from "@/lib/supabase";
import { num, day } from "@/lib/format";
import { stripEmoji } from "@/lib/clean";
import { inList } from "@/lib/watch";
import { markAlertsSeen } from "@/app/watch/actions";
import { Icon } from "../components/icons";

export const dynamic = "force-dynamic";

type A = {
  id: number; canonical_product_id: number; kind: string; created_on: string; watched: boolean; severity: string;
  title: string; seen_at: string | null;
};
const KIND: Record<string, string> = { tier_change: "ট্যাগ বদল", score_move: "স্কোর সরেছে", price_move: "বাজারদর বদল", redflag: "নকল অভিযোগ" };
// রং নয়, লেখা দিয়ে: সতর্কতা শুধু লাল বর্ডারে, বাকিগুলো সাধারণ
const SEV: Record<string, string> = { good: "ভালো খবর", warn: "সতর্কতা", info: "তথ্য" };
const LIMIT = 100;

export default async function Alerts({ searchParams }: { searchParams: Record<string, string | undefined> }) {
  const err = (searchParams.watch_err ?? "").slice(0, 300);
  const alerts = await rest<A[]>("alerts", {
    select: "id,canonical_product_id,kind,created_on,watched,severity,title,seen_at", order: "created_on.desc,id.desc", limit: String(LIMIT),
  }).catch(() => null);
  if (alerts === null) {
    return (
      <>
        <h1>অ্যালার্ট</h1>
        <div className="msg"><Icon name="info" size={18} /><span>Phase 7 migration (<code>20261117000000_phase7.sql</code>) এখনও চালানো হয়নি।</span></div>
      </>
    );
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
      <h1>অ্যালার্ট</h1>
      <p className="lede">
        না-দেখা {num(unseen.length)}টা · সর্বশেষ {num(alerts.length)}টা দেখানো হচ্ছে · <Link href="/watchlist">নজরে রাখা প্রোডাক্ট</Link>
      </p>
      {err && <div className="msg err" role="alert"><Icon name="alert" size={18} /><span>{err}</span></div>}
      <div className="toolbar">
        {unseen.length > 0
          ? <form action={markAlertsSeen}><button type="submit" className="linkbtn touch"><Icon name="check" size={16} />সব দেখা হয়েছে চিহ্নিত করুন</button></form>
          : <span className="muted">সব দেখা হয়েছে</span>}
        <a href="/export?kind=alerts"><Icon name="download" size={16} />CSV ডাউনলোড</a>
      </div>
      {alerts.length === 0 && <div className="empty">এখনও কোনো অ্যালার্ট নেই। Score Daily চলার পর, ট্যাগ বা স্কোর বদলালে এখানে আসবে।</div>}
      {dates.map((d) => (
        <section key={d}>
          <h2 className="dateh">{day(d)}</h2>
          {alerts.filter((a) => a.created_on === d).map((a) => {
            const lid = links.get(a.canonical_product_id);
            const title = stripEmoji(a.title);
            return (
              <div key={a.id} className={`card ${a.seen_at ? "seen" : "unseen"}`}>
                <div className="item-tags">
                  {!a.seen_at && <span className="badge best">নতুন</span>}
                  <span className={`chip${a.severity === "warn" ? " danger" : ""}`}>{SEV[a.severity] ?? "তথ্য"}</span>
                  {a.watched && <span className="chip">নজরে</span>}
                </div>
                <div className="title">{lid ? <Link href={`/products/${lid}`}>{title}</Link> : title}</div>
                <p className="why muted">{KIND[a.kind] ?? a.kind}</p>
              </div>
            );
          })}
        </section>
      ))}
    </>
  );
}
