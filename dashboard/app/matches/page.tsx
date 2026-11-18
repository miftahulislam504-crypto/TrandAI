import Link from "next/link";
import { revalidatePath } from "next/cache";
import { rest, rpc } from "@/lib/supabase";
import { num, taka, rating } from "@/lib/format";

export const dynamic = "force-dynamic";

type Row = {
  id: number; score: number; created_at: string;
  evidence: { title_sim?: number; price_ratio?: number | null; shared?: string[]; code_match?: boolean; same_source?: boolean; note?: string | null; image_dist?: number | null; image_lift?: boolean } | null;
  a_id: number; a_source: string; a_title: string | null; a_url: string | null; a_price: number | null;
  a_rating: number | null; a_rating_count: number | null; a_sold: number | null; a_canonical: number | null; a_image: string | null;
  b_id: number; b_source: string; b_title: string | null; b_url: string | null; b_price: number | null;
  b_rating: number | null; b_rating_count: number | null; b_sold: number | null; b_canonical: number | null; b_image: string | null;
};

const PAGE = 20;
const NOTES: Record<string, string> = {
  cluster_conflict: "মার্জ করলে একই গ্রুপে সংঘাতের দুটো প্রোডাক্ট এসে যেত",
  cluster_too_big: "গ্রুপ খুব বড় হয়ে যেত",
  blocked_pair: "গ্রুপের কেউ আগে reject হয়েছে",
};

// সার্ভার অ্যাকশন: রেজাল্ট DB-তে decide_match ফাংশন চালায়। accept = দুই প্রোডাক্ট এক হবে (বিক্রি যোগ), reject = আর কখনও নিজে মার্জ হবে না।
async function decide(formData: FormData) {
  "use server";
  const id = Number(formData.get("id"));
  const accept = formData.get("accept") === "1";
  if (!Number.isInteger(id) || id <= 0) return;
  await rpc("decide_match", { p_id: id, p_accept: accept, p_by: "dashboard" });
  revalidatePath("/matches");
}

// ছবির হ্যাশের দূরত্ব (০ = একই ছবি, ৬৪ বিটের মধ্যে)। কাছাকাছি হলে সেলার বা সাইট একই ছবি কপি করেছে
function imageNote(d: number | null | undefined): string | null {
  if (d == null) return null;
  if (d <= 6) return `ছবি প্রায় একই (দূরত্ব ${d})`;
  if (d <= 10) return `ছবি কাছাকাছি (দূরত্ব ${d})`;
  return "ছবি আলাদা (এটা আলাদা প্রোডাক্ট বোঝায় না, ফটো ভিন্ন হতে পারে)";
}

function Side(p: { label: string; source: string; title: string | null; url: string | null; price: number | null; rating: number | null; rc: number | null; sold: number | null; canonical: number | null; image: string | null }) {
  return (
    <div style={{ flex: 1, minWidth: 240, display: "flex", gap: 10 }}>
      {p.image && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={p.image} alt="" width={96} height={96} loading="lazy" referrerPolicy="no-referrer"
          style={{ objectFit: "contain", background: "#f4f4f4", borderRadius: 6, flex: "none" }} />
      )}
      <div style={{ minWidth: 0 }}>
      <div className="muted" style={{ fontSize: 12 }}>{p.label} · {p.source} · প্রোডাক্ট #{p.canonical ?? "–"}</div>
      <div style={{ margin: "4px 0" }}>{p.url ? <a href={p.url} target="_blank" rel="noreferrer noopener">{p.title ?? "(নাম নেই)"}</a> : p.title ?? "(নাম নেই)"}</div>
      <div className="muted" style={{ fontSize: 13 }}>{taka(p.price)} · ★ {rating(p.rating)} ({num(p.rc)}) · বিক্রি {num(p.sold)}</div>
      </div>
    </div>
  );
}

export default async function Matches({ searchParams }: { searchParams: Record<string, string | undefined> }) {
  const page = Math.max(1, Number(searchParams.page) || 1);
  const rows = await rest<Row[]>("match_queue", {
    select: "*", status: "eq.pending", order: "score.desc,id.asc", limit: String(PAGE + 1), offset: String((page - 1) * PAGE),
  });
  const more = rows.length > PAGE;
  const shown = rows.slice(0, PAGE);

  return (
    <>
      <p><Link href="/">← প্রোডাক্ট তালিকা</Link></p>
      <h1>একই প্রোডাক্ট কি না? (রিভিউ কিউ)</h1>
      <p className="muted">
        সিস্টেম নিশ্চিত হতে পারেনি, এমন জোড়া। <b>এক প্রোডাক্ট</b> চাপলে দুটোর বিক্রি ও রিভিউ যোগ হয়ে একটা প্রোডাক্ট হবে।
        <b> আলাদা</b> চাপলে জোড়াটা চিরতরে বাদ, সিস্টেম আর নিজে মেলাবে না। মাপ, ওজন, সংখ্যা বা ব্র্যান্ড আলাদা হলে "আলাদা" দিন।
        রঙ বা সাইজ আলাদা হলে ফ্যাশনে তা একই প্রোডাক্টের ভ্যারিয়েন্ট ধরা হয়।
      </p>
      {shown.length === 0 && <p>কিউ খালি। 🎉</p>}
      {shown.map((r) => (
        <div key={r.id} className="card" style={{ margin: "12px 0", padding: 12, border: "1px solid #ddd", borderRadius: 8 }}>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <Side label="ক" source={r.a_source} title={r.a_title} url={r.a_url} price={r.a_price} rating={r.a_rating} rc={r.a_rating_count} sold={r.a_sold} canonical={r.a_canonical} image={r.a_image} />
            <Side label="খ" source={r.b_source} title={r.b_title} url={r.b_url} price={r.b_price} rating={r.b_rating} rc={r.b_rating_count} sold={r.b_sold} canonical={r.b_canonical} image={r.b_image} />
          </div>
          <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            মিল {Math.round(r.score * 100)}%
            {r.evidence?.title_sim !== undefined && <> · নামের মিল {Math.round(r.evidence.title_sim * 100)}%</>}
            {r.evidence?.price_ratio != null && <> · দামের অনুপাত {Math.round(r.evidence.price_ratio * 100)}%</>}
            {r.evidence?.code_match && <> · মডেল কোড মিলেছে</>}
            {imageNote(r.evidence?.image_dist) && <> · 🖼 {imageNote(r.evidence?.image_dist)}</>}
            {r.evidence?.same_source && <> · একই সাইট (ভিন্ন সেলার হতে পারে)</>}
            {r.evidence?.shared && r.evidence.shared.length > 0 && <> · মিলে যাওয়া শব্দ: {r.evidence.shared.slice(0, 6).join(", ")}</>}
            {r.evidence?.note && <> · ⚠️ {NOTES[r.evidence.note] ?? r.evidence.note}</>}
          </div>
          <form action={decide} style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <input type="hidden" name="id" value={r.id} />
            <button type="submit" name="accept" value="1">✓ এক প্রোডাক্ট</button>
            <button type="submit" name="accept" value="0">✗ আলাদা</button>
          </form>
        </div>
      ))}
      <p>
        {page > 1 && <Link href={`/matches?page=${page - 1}`}>← আগের</Link>}
        {page > 1 && more && " · "}
        {more && <Link href={`/matches?page=${page + 1}`}>পরের →</Link>}
      </p>
    </>
  );
}
