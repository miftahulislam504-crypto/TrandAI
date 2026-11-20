import Link from "next/link";
import { rest } from "@/lib/supabase";
import { num, taka, delta, rating, day } from "@/lib/format";
import { tierText } from "@/lib/tier";
import { stripEmoji } from "@/lib/clean";
import { inList, pickPerCanonical } from "@/lib/watch";
import { toggleWatch } from "@/app/watch/actions";
import { Icon } from "../components/icons";

export const dynamic = "force-dynamic";

type W = { canonical_product_id: number; note: string | null; added_at: string };
type Row = {
  id: number; canonical_product_id: number | null; title_raw: string | null; category: string | null; price: number | null;
  price_delta_7d: number | null; rating_avg: number | null; rating_count: number | null; sold_count: number | null;
  sold_delta_7d: number | null; score: number | null; tier: string | null; confidence: string | null; provisional_tier: string | null;
  scored_on: string | null;
};

export default async function Watchlist({ searchParams }: { searchParams: Record<string, string | undefined> }) {
  const err = (searchParams.watch_err ?? "").slice(0, 300);
  const list = await rest<W[]>("watchlist", { select: "canonical_product_id,note,added_at", order: "added_at.desc" }).catch(() => null);
  if (list === null) {
    return (
      <>
        <h1>নজরে রাখা প্রোডাক্ট</h1>
        <div className="msg"><Icon name="info" size={18} /><span>Phase 7 migration (<code>20261117000000_phase7.sql</code>) এখনও চালানো হয়নি। Supabase SQL Editor-এ চালিয়ে আবার আসুন।</span></div>
      </>
    );
  }
  const rows = list.length
    ? await rest<Row[]>("listing_scored", {
        canonical_product_id: inList(list.map((w) => w.canonical_product_id)), is_active: "eq.true",
        select: "id,canonical_product_id,title_raw,category,price,price_delta_7d,rating_avg,rating_count,sold_count,sold_delta_7d,score,tier,confidence,provisional_tier,scored_on",
      })
    : [];
  const best = pickPerCanonical(rows);

  return (
    <>
      <h1>নজরে রাখা প্রোডাক্ট</h1>
      <p className="lede">
        {num(list.length)}টা প্রোডাক্ট। ট্যাগ বদল, স্কোর বড় সরা, বাজারদর বদল বা নকল-অভিযোগ এলে <Link href="/alerts">অ্যালার্ট</Link> আসে।
      </p>
      {err && <div className="msg err" role="alert"><Icon name="alert" size={18} /><span>{err}</span></div>}
      {list.length > 0 && (
        <div className="toolbar">
          <span className="muted">{num(list.length)}টা</span>
          <a href="/export?kind=watchlist"><Icon name="download" size={16} />CSV ডাউনলোড</a>
        </div>
      )}
      {list.length === 0 && <div className="empty">এখনও কিছু নেই। যেকোনো প্রোডাক্টের পেজে গিয়ে &quot;নজরে রাখুন&quot; চাপুন।</div>}
      {list.map((w) => {
        const r = best.get(w.canonical_product_id);
        return (
          <div key={w.canonical_product_id} className="card">
            <div className="item-top">
              <div className="item-main">
                {r?.tier && <div className="item-tags"><span className={`badge ${r.tier}`}>{tierText(r.tier, r.confidence, r.provisional_tier)}</span></div>}
                {r
                  ? <Link href={`/products/${r.id}`} className="title">{r.title_raw || "(নাম নেই)"}</Link>
                  : <span className="muted">প্রোডাক্ট #{w.canonical_product_id} (সক্রিয় listing নেই)</span>}
              </div>
              {r && r.score !== null && <div className="score"><b>{Math.round(r.score)}</b><span>স্কোর</span></div>}
            </div>
            {w.note && <p className="why">নোট: {stripEmoji(w.note)}</p>}
            {r && (
              <div className="metrics">
                <div><span>দাম</span>{taka(r.price)} <small className={(r.price_delta_7d || 0) > 0 ? "up" : "down"}>{r.price_delta_7d ? delta(r.price_delta_7d) : ""}</small></div>
                <div><span>রেটিং</span>{rating(r.rating_avg)} ({num(r.rating_count)})</div>
                <div><span>মোট বিক্রি</span>{num(r.sold_count)}</div>
                <div><span>৭ দিনে বিক্রি</span><b className={(r.sold_delta_7d || 0) > 0 ? "up" : ""}>{delta(r.sold_delta_7d)}</b></div>
                <div><span>স্কোরের তারিখ</span>{day(r.scored_on)}</div>
                <div><span>ক্যাটাগরি</span>{r.category || "–"}</div>
              </div>
            )}
            <form action={toggleWatch} className="btn-row" style={{ marginTop: 14 }}>
              <input type="hidden" name="cid" value={w.canonical_product_id} />
              <input type="hidden" name="on" value="0" />
              <input type="hidden" name="back" value="/watchlist" />
              <button type="submit" className="linkbtn"><Icon name="close" size={16} />নজর থেকে সরান</button>
            </form>
          </div>
        );
      })}
    </>
  );
}
