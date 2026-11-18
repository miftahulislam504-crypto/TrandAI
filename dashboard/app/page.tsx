import Link from "next/link";
import { restWithCount, rest } from "@/lib/supabase";
import { num, taka, delta, rating } from "@/lib/format";
import { tierText } from "@/lib/tier";
import { SORTS, TIERS, listParams, parseListQuery } from "@/lib/listfilter";

export const dynamic = "force-dynamic";

type Row = {
  id: number; title_raw: string | null; category: string | null; price: number | null;
  rating_avg: number | null; rating_count: number | null; sold_count: number | null;
  sold_delta_7d: number | null; review_delta_7d: number | null; price_delta_7d: number | null;
  seller_name: string | null; captured_on: string | null;
  score: number | null; tier: string | null; confidence: string | null; provisional_tier: string | null;
  reasons: { summary?: string[]; detail?: { ads?: { status?: string; crowded?: boolean } } } | null;
};
type Cat = { slug: string; name: string };

const PAGE = 30;
const SELECT = "id,title_raw,category,price,rating_avg,rating_count,sold_count,sold_delta_7d,review_delta_7d,price_delta_7d,seller_name,captured_on,score,tier,confidence,provisional_tier,reasons";

export default async function Home({ searchParams }: { searchParams: Record<string, string | undefined> }) {
  const { sort, tier, page, q, category } = parseListQuery(searchParams);
  const params = listParams({ sort, tier, page, q, category }, SELECT, PAGE, (page - 1) * PAGE);

  const [{ rows, total }, cats] = await Promise.all([
    restWithCount<Row[]>("listing_scored", params),
    rest<Cat[]>("categories", { select: "slug,name", order: "name" }),
  ]);
  // ট্যাগ অনুযায়ী মোট সংখ্যা (বর্তমান ক্যাটাগরি ফিল্টারে)
  const counts = await Promise.all(
    ["best", "mid", "dont"].map(async (t) => {
      const p: Record<string, string> = { select: "id", is_active: "eq.true", tier: `eq.${t}`, limit: "1" };
      if (category) p.category = `eq.${category}`;
      return (await restWithCount<unknown[]>("listing_scored", p)).total ?? 0;
    })
  );
  const pages = total ? Math.ceil(total / PAGE) : 1;
  const link = (p: number) => {
    const u = new URLSearchParams({ ...(category && { category }), ...(tier && { tier }), ...(q && { q }), sort, page: String(p) });
    return `/?${u.toString()}`;
  };

  // migration ৪ না চললে match_queue নেই, তখন লিংকটা শুধু দেখায় না
  const pending = await restWithCount<unknown[]>("match_queue", { select: "id", status: "eq.pending", limit: "1" })
    .then((r) => r.total ?? 0).catch(() => 0);

  // Phase 7 migration না চললে alerts টেবিল নেই; তখন ব্যানার দেখায় না
  const unseenAlerts = await restWithCount<unknown[]>("alerts", { select: "id", seen_at: "is.null", limit: "1" })
    .then((r) => r.total ?? 0).catch(() => 0);
  const exportHref = `/export?${new URLSearchParams({ kind: "products", ...(category && { category }), ...(tier && { tier }), ...(q && { q }), sort }).toString()}`;

  return (
    <>
      <h1>প্রোডাক্ট তালিকা</h1>
      {pending > 0 && <p><Link href="/matches">🔗 রিভিউ কিউ: {pending}টা জোড়া একই প্রোডাক্ট কি না দেখুন</Link></p>}
      {unseenAlerts > 0 && <p><Link href="/alerts">🔔 {unseenAlerts}টা নতুন অ্যালার্ট</Link></p>}
      <p><Link href="/ads">📢 Facebook Ads Library চেক</Link></p>
      <form className="filters" method="get">
        <input name="q" placeholder="নাম দিয়ে খুঁজুন" defaultValue={q} />
        <select name="category" defaultValue={category}>
          <option value="">সব ক্যাটাগরি</option>
          {cats.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
        </select>
        <select name="tier" defaultValue={tier}>
          <option value="">সব ট্যাগ</option>
          {Object.entries(TIERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select name="sort" defaultValue={sort}>
          {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <button type="submit">দেখান</button>
      </form>
      <div className="chips">
        <span className="chip best">Best {counts[0]}</span>
        <span className="chip mid">Mid {counts[1]}</span>
        <span className="chip dont">Don&apos;t {counts[2]}</span>
      </div>
      <p className="muted">মোট {num(total)}টা প্রোডাক্ট · <a href={exportHref}>⬇ CSV (এই ফিল্টারে)</a></p>

      {rows.length === 0 && <p className="muted">এখনও কোনো ডেটা নেই। প্রথম দৈনিক রান শেষ হলে এখানে দেখা যাবে।</p>}
      {rows.map((r) => (
        <Link key={r.id} href={`/products/${r.id}`} className="card">
          <div className="title">
            {r.tier && <span className={`badge ${r.tier}`}>{tierText(r.tier, r.confidence, r.provisional_tier)}</span>}{" "}
            {r.title_raw || "(নাম নেই)"}
            {r.reasons?.detail?.ads?.status === "ok" && r.reasons.detail.ads.crowded ? <>{" "}<span className="chip" title="Facebook-এ অনেকে বিজ্ঞাপন চালাচ্ছে">📢 ভিড়</span></> : null}
          </div>
          {r.score !== null && (
            <div className="muted">স্কোর {Math.round(r.score)} · কনফিডেন্স {r.confidence}{r.reasons?.summary?.[0] ? ` · ${r.reasons.summary[0]}` : ""}</div>
          )}
          <div className="metrics">
            <div><span>দাম</span>{taka(r.price)} <small className={(r.price_delta_7d || 0) > 0 ? "up" : "down"}>{r.price_delta_7d ? delta(r.price_delta_7d) : ""}</small></div>
            <div><span>রেটিং</span>{rating(r.rating_avg)} ({num(r.rating_count)})</div>
            <div><span>মোট বিক্রি</span>{num(r.sold_count)}</div>
            <div><span>৭ দিনে বিক্রি</span><b className={(r.sold_delta_7d || 0) > 0 ? "up" : ""}>{delta(r.sold_delta_7d)}</b></div>
            <div><span>৭ দিনে রিভিউ</span>{delta(r.review_delta_7d)}</div>
            <div><span>ক্যাটাগরি</span>{r.category || "–"}</div>
          </div>
        </Link>
      ))}

      <div className="pager">
        {page > 1 ? <Link href={link(page - 1)}>← আগের</Link> : <span />}
        <span className="muted">{page} / {pages}</span>
        {page < pages ? <Link href={link(page + 1)}>পরের →</Link> : <span />}
      </div>
    </>
  );
}
