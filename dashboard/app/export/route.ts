import { NextRequest, NextResponse } from "next/server";
import { restWithCount } from "@/lib/supabase";
import { toCsv, type Cell } from "@/lib/csv";
import { listParams, parseListQuery } from "@/lib/listfilter";
import { tierText } from "@/lib/tier";
import { inList, pickPerCanonical } from "@/lib/watch";

export const dynamic = "force-dynamic";

const PAGE = 1000;
const MAX_ROWS = 5000;

// সব সারি পেজ করে আনে (PostgREST-এর ডিফল্ট সীমা ১০০০)। MAX_ROWS-এর বেশি হলে থামে ও truncated জানায়।
async function fetchAll<T>(path: string, params: Record<string, string>): Promise<{ rows: T[]; truncated: boolean }> {
  const rows: T[] = [];
  for (let off = 0; off < MAX_ROWS; off += PAGE) {
    const { rows: part } = await restWithCount<T[]>(path, { ...params, limit: String(PAGE), offset: String(off) }, false);
    rows.push(...part);
    if (part.length < PAGE) return { rows, truncated: false };
  }
  return { rows, truncated: true };
}

type L = {
  id: number; canonical_product_id: number | null; title_raw: string | null; category: string | null; tier: string | null;
  confidence: string | null; provisional_tier: string | null; score: number | null; price: number | null; price_delta_7d: number | null;
  rating_avg: number | null; rating_count: number | null; sold_count: number | null; sold_delta_7d: number | null;
  review_delta_7d: number | null; seller_name: string | null; scored_on: string | null; url: string; first_reason: string | null;
};
const LCOLS = "id,canonical_product_id,title_raw,category,tier,confidence,provisional_tier,score,price,price_delta_7d,rating_avg,rating_count,sold_count,sold_delta_7d,review_delta_7d,seller_name,scored_on,url,first_reason:reasons->summary->>0";
const LHEAD = ["listing_id", "product_id", "নাম", "ক্যাটাগরি", "ট্যাগ", "স্কোর", "কনফিডেন্স", "দাম", "৭ দিনে দাম বদল", "রেটিং", "রেটিং সংখ্যা",
  "মোট বিক্রি", "৭ দিনে বিক্রি", "৭ দিনে রিভিউ", "সেলার", "স্কোরের তারিখ", "লিংক", "প্রধান কারণ"];
const lrow = (r: L): Cell[] => [r.id, r.canonical_product_id, r.title_raw, r.category, r.tier ? tierText(r.tier, r.confidence, r.provisional_tier) : "স্কোর হয়নি",
  r.score === null ? null : Math.round(r.score), r.confidence, r.price, r.price_delta_7d, r.rating_avg, r.rating_count, r.sold_count, r.sold_delta_7d,
  r.review_delta_7d, r.seller_name, r.scored_on, r.url, r.first_reason];

const bdToday = () => new Date(Date.now() + 6 * 3600 * 1000).toISOString().slice(0, 10);

function csv(name: string, body: string, truncated: boolean): NextResponse {
  return new NextResponse(body, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${name}-${bdToday()}.csv"`,
      "Cache-Control": "no-store",
      ...(truncated ? { "X-Truncated": "true" } : {}),
    },
  });
}

// /export?kind=products|watchlist|alerts (products-এ হোম পেজের category/tier/q/sort ফিল্টার একই)
export async function GET(req: NextRequest) {
  const sp = Object.fromEntries(req.nextUrl.searchParams.entries());
  const kind = sp.kind;
  try {
    if (kind === "products") {
      const { rows, truncated } = await fetchAll<L>("listing_scored", listParams(parseListQuery(sp), LCOLS, PAGE, 0));
      return csv("products", toCsv(LHEAD, rows.map(lrow)), truncated);
    }
    if (kind === "watchlist") {
      const w = await fetchAll<{ canonical_product_id: number; note: string | null; added_at: string }>("watchlist", { select: "canonical_product_id,note,added_at", order: "added_at.desc" });
      const ids = w.rows.map((x) => x.canonical_product_id);
      const ls = ids.length ? (await fetchAll<L>("listing_scored", { canonical_product_id: inList(ids), is_active: "eq.true", select: LCOLS })).rows : [];
      const best = pickPerCanonical(ls);
      const rows = w.rows.map((x) => {
        const r = best.get(x.canonical_product_id);
        return [x.note, x.added_at.slice(0, 10), ...(r ? lrow(r) : [null, x.canonical_product_id, "(সক্রিয় listing নেই)"])];
      });
      return csv("watchlist", toCsv(["নোট", "যোগের তারিখ", ...LHEAD], rows), w.truncated);
    }
    if (kind === "alerts") {
      const { rows, truncated } = await fetchAll<{ created_on: string; kind: string; watched: boolean; severity: string; title: string; seen_at: string | null; canonical_product_id: number }>(
        "alerts", { select: "canonical_product_id,created_on,kind,watched,severity,title,seen_at", order: "created_on.desc,id.desc" });
      return csv("alerts", toCsv(["তারিখ", "ধরন", "ওয়াচলিস্ট", "গুরুত্ব", "বার্তা", "দেখা হয়েছে", "product_id"],
        rows.map((a) => [a.created_on, a.kind, a.watched, a.severity, a.title, !!a.seen_at, a.canonical_product_id])), truncated);
    }
  } catch (e) {
    const m = (e as Error).message;
    // ভিতরের বার্তা (URL ইত্যাদি) বাইরে যায় না; শুধু কোন টেবিল ও HTTP কোড
    return NextResponse.json({ error: "এক্সপোর্ট ব্যর্থ", detail: m.replace(/https?:\/\/\S+/g, "").slice(0, 160) }, { status: 502 });
  }
  return NextResponse.json({ error: "kind হবে products, watchlist বা alerts" }, { status: 400 });
}
