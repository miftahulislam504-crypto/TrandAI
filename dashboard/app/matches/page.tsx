import Link from "next/link";
import { revalidatePath } from "next/cache";
import { rest, rpc } from "@/lib/supabase";
import { num, taka, rating } from "@/lib/format";
import { stripEmoji } from "@/lib/clean";
import { Icon } from "../components/icons";

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
    <div className="side">
      {p.image && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={p.image} alt="" width={96} height={96} loading="lazy" referrerPolicy="no-referrer" className="thumb" />
      )}
      <div className="side-body">
        <div className="muted" style={{ fontSize: 12 }}>{p.label} · {p.source} · প্রোডাক্ট #{p.canonical ?? "–"}</div>
        <div className="ttl">
          {p.url
            ? <a href={p.url} target="_blank" rel="noreferrer noopener" className="extlink">{p.title ?? "(নাম নেই)"}<Icon name="external" size={14} /></a>
            : p.title ?? "(নাম নেই)"}
        </div>
        <div className="muted">{taka(p.price)} · রেটিং {rating(p.rating)} ({num(p.rc)}) · বিক্রি {num(p.sold)}</div>
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
      <Link href="/" className="back"><Icon name="left" size={16} />প্রোডাক্ট তালিকা</Link>
      <h1>একই প্রোডাক্ট কি না?</h1>
      <p className="lede">
        রিভিউ কিউ: সিস্টেম নিশ্চিত হতে পারেনি, এমন জোড়া। <b>এক প্রোডাক্ট</b> চাপলে দুটোর বিক্রি ও রিভিউ যোগ হয়ে একটা প্রোডাক্ট হবে।
        <b> আলাদা</b> চাপলে জোড়াটা চিরতরে বাদ, সিস্টেম আর নিজে মেলাবে না। মাপ, ওজন, সংখ্যা বা ব্র্যান্ড আলাদা হলে &quot;আলাদা&quot; দিন।
        রঙ বা সাইজ আলাদা হলে ফ্যাশনে তা একই প্রোডাক্টের ভ্যারিয়েন্ট ধরা হয়।
      </p>
      {shown.length === 0 && <div className="empty">কিউ খালি। সব জোড়ার সিদ্ধান্ত হয়ে গেছে।</div>}
      {shown.map((r) => {
        const img = imageNote(r.evidence?.image_dist);
        const note = r.evidence?.note ? NOTES[r.evidence.note] ?? stripEmoji(r.evidence.note) : null;
        return (
          <div key={r.id} className="card">
            <div className="item-top">
              <div className="pair" style={{ flex: 1, minWidth: 0 }}>
                <Side label="ক" source={r.a_source} title={r.a_title} url={r.a_url} price={r.a_price} rating={r.a_rating} rc={r.a_rating_count} sold={r.a_sold} canonical={r.a_canonical} image={r.a_image} />
                <Side label="খ" source={r.b_source} title={r.b_title} url={r.b_url} price={r.b_price} rating={r.b_rating} rc={r.b_rating_count} sold={r.b_sold} canonical={r.b_canonical} image={r.b_image} />
              </div>
              <div className="score"><b>{Math.round(r.score * 100)}%</b><span>মিল</span></div>
            </div>
            <div className="evidence">
              <div className="chips">
                {r.evidence?.title_sim !== undefined && <span className="chip">নামের মিল {Math.round(r.evidence.title_sim * 100)}%</span>}
                {r.evidence?.price_ratio != null && <span className="chip">দামের অনুপাত {Math.round(r.evidence.price_ratio * 100)}%</span>}
                {r.evidence?.code_match && <span className="chip">মডেল কোড মিলেছে</span>}
                {img && <span className="chip">{img}</span>}
                {r.evidence?.same_source && <span className="chip">একই সাইট (ভিন্ন সেলার হতে পারে)</span>}
                {r.evidence?.shared && r.evidence.shared.length > 0 && <span className="chip">মিলে যাওয়া শব্দ: {r.evidence.shared.slice(0, 6).join(", ")}</span>}
                {note && <span className="chip danger">{note}</span>}
              </div>
            </div>
            <form action={decide} className="actions">
              <input type="hidden" name="id" value={r.id} />
              <button type="submit" name="accept" value="1">এক প্রোডাক্ট</button>
              <button type="submit" name="accept" value="0" className="linkbtn">আলাদা</button>
            </form>
          </div>
        );
      })}
      <nav className="pager" aria-label="পেজ">
        {page > 1 ? <Link href={`/matches?page=${page - 1}`}><Icon name="left" size={16} />আগের</Link> : <span />}
        <span className="muted">পেজ {page}</span>
        {more ? <Link href={`/matches?page=${page + 1}`}>পরের<Icon name="right" size={16} /></Link> : <span />}
      </nav>
    </>
  );
}
