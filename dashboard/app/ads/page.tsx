import Link from "next/link";
import { rest } from "@/lib/supabase";
import { num, day } from "@/lib/format";
import { stripEmoji } from "@/lib/clean";
import { saveAdChecks, deleteAdCheck } from "./actions";
import { Icon } from "../components/icons";

export const dynamic = "force-dynamic";

type Check = {
  id: number; keyword: string; canonical_product_id: number | null; observed_on: string; active_ads: number;
  advertisers: number | null; oldest_start: string | null; new_30d: number | null; note: string | null; source: string;
};
type Lst = { id: number; canonical_product_id: number | null; title_raw: string | null };

// config/scoring.json-এর ads.max_age_days (৪৫)-এর সাথে মিল রাখুন: এর পুরনো চেক স্কোরে ধরা হয় না
const MAX_AGE = 45;
const daysBetween = (a: string, b: string) => Math.round((Date.parse(b.slice(0, 10)) - Date.parse(a.slice(0, 10))) / 86400000);

export default async function Ads({ searchParams }: { searchParams: Record<string, string | undefined> }) {
  const today = new Date(Date.now() + 6 * 3600 * 1000).toISOString().slice(0, 10);
  let checks: Check[] | null = [];
  try {
    checks = await rest<Check[]>("ad_checks", { select: "id,keyword,canonical_product_id,observed_on,active_ads,advertisers,oldest_start,new_30d,note,source", order: "observed_on.desc,id.desc", limit: "100" });
  } catch {
    checks = null; // Phase 6 migration চলেনি
  }
  const cids = [...new Set((checks ?? []).map((c) => c.canonical_product_id).filter((x): x is number => x !== null))];
  const titles = new Map<number, Lst>();
  if (cids.length) {
    const ls = await rest<Lst[]>("listing_overview", { canonical_product_id: `in.(${cids.join(",")})`, select: "id,canonical_product_id,title_raw", order: "id.asc" }).catch(() => []);
    for (const l of ls) if (l.canonical_product_id !== null && !titles.has(l.canonical_product_id)) titles.set(l.canonical_product_id, l);
  }
  const ok = Number(searchParams.ads_ok) || 0;
  const err = (searchParams.ads_err ?? "").slice(0, 700);

  return (
    <>
      <Link href="/" className="back"><Icon name="left" size={16} />প্রোডাক্ট তালিকা</Link>
      <h1>Facebook Ads Library চেক</h1>
      <p className="lede">
        Facebook-এ কতজন, কতদিন ধরে বিজ্ঞাপন চালাচ্ছে তা হাতে দেখে এখানে দিন। এটা &quot;বাজার-সমর্থন&quot;-এর একটা সংকেত, বিক্রির প্রমাণ নয়
        (Ads Library-তে খরচ বা ইম্প্রেশন নেই)। স্কোরে ওজন ডিফল্টে ০, তাই এখন শুধু কারণ ও ব্যাজে দেখায়।
      </p>

      {ok > 0 && <div className="msg ok" role="status"><Icon name="check" size={18} /><span>{num(ok)}টা চেক সেভ হয়েছে। পরের Score Daily রানে (বা হাতে চালালে এখনই) প্রোডাক্টে দেখাবে।</span></div>}
      {err && <div className="msg err" role="alert"><Icon name="alert" size={18} /><span>সেভ হয়নি:{"\n"}{err}</span></div>}

      <details className="box" style={{ marginBottom: 12 }}>
        <summary>কীভাবে চেক করবেন (ফোনেই হয়)</summary>
        <ol className="steps">
          <li>facebook.com/ads/library খুলুন। দেশ <b>Bangladesh</b>, ধরন <b>All ads</b> (সব বিজ্ঞাপন), স্ট্যাটাস <b>Active</b> বেছে নিন।</li>
          <li>প্রোডাক্টের ধরনের শব্দ লিখে খুঁজুন, যেমন <code>air fryer</code>। ইংরেজি আর বাংলা শব্দ আলাদা আলাদা চেক করা যায়।</li>
          <li><b>বিজ্ঞাপন সংখ্যা</b> = ফলাফলের সংখ্যা (উপরে যেমন &quot;~120 results&quot; দেখায়)। এটাই একমাত্র আবশ্যক ঘর।</li>
          <li><b>বিজ্ঞাপনদাতা</b> = স্ক্রল করে যে কার্ডগুলো দেখলেন তাদের আলাদা পেজের সংখ্যা (আসলে এর চেয়ে বেশি থাকতে পারে, তাই এটা সর্বনিম্ন)।</li>
          <li><b>সবচেয়ে পুরনো</b> = কার্ডগুলোর &quot;Started running on&quot; তারিখের সবচেয়ে আগেরটা (দিন/মাস/বছর বা 3 Oct 2026 লিখলেও চলে)।</li>
          <li><b>গত ৩০ দিনে নতুন</b> = ঐচ্ছিক, ফাঁকা রাখা যায়।</li>
        </ol>
        <p className="hint">
          Ads Library-র পেজের ভাষা ও লেআউট Facebook বদলায়, আমি আসল পেজ দেখে এই ধাপগুলো লিখিনি। কোনো ধাপ না মিললে জানান। শব্দ যত নির্দিষ্ট,
          সংকেত তত কাজের (&quot;air fryer&quot; ভালো, &quot;kitchen&quot; নয়)। একই শব্দ আবার চেক করলে (১৪ দিন বা বেশি পরে) বিজ্ঞাপন বাড়ছে কি কমছে তাও ধরা পড়ে।
        </p>
      </details>

      {checks === null ? (
        <div className="msg"><Icon name="info" size={18} /><span>চেক রাখতে Phase 6 migration (<code>20261116000000_phase6.sql</code>) চালান।</span></div>
      ) : (
        <>
          <div className="stack">
            <section className="box">
              <h3>একটা চেক দিন (প্রোডাক্টের ধরনের শব্দ)</h3>
              <form action={saveAdChecks} className="formrow ads">
                <input type="hidden" name="back" value="/ads" />
                <label className="field wide"><span>শব্দ</span><input name="keyword" type="text" required maxLength={80} placeholder="air fryer" /></label>
                <label className="field"><span>বিজ্ঞাপন সংখ্যা</span><input name="ads" type="text" inputMode="numeric" required /></label>
                <label className="field"><span>বিজ্ঞাপনদাতা</span><input name="advertisers" type="text" inputMode="numeric" /></label>
                <label className="field"><span>সবচেয়ে পুরনো</span><input name="oldest" type="text" placeholder="3 Oct 2026" /></label>
                <label className="field"><span>নতুন (৩০ দিন)</span><input name="new30" type="text" inputMode="numeric" /></label>
                <button type="submit">সেভ</button>
              </form>
            </section>

            <section className="box">
              <h3>অনেকগুলো একসাথে (প্রতি লাইনে একটা)</h3>
              <form action={saveAdChecks}>
                <input type="hidden" name="back" value="/ads" />
                <textarea name="bulk" rows={5} aria-label="অনেকগুলো চেক, প্রতি লাইনে একটা" placeholder={"air fryer | 120 | 14 | 3 Sep 2026 | 30\nপাঞ্জাবি | 85 | 20\nsaree | 25"} />
                <p className="hint">
                  ক্রম: শব্দ | বিজ্ঞাপন | বিজ্ঞাপনদাতা | সবচেয়ে পুরনোর তারিখ | নতুন-৩০ দিন। প্রথম দুটো আবশ্যক, বাকিগুলো বাদ দেওয়া বা &quot;-&quot; দেওয়া যায়।
                  বাংলা অঙ্ক চলে। একবারে সর্বোচ্চ ৬০ লাইন।
                </p>
                <div className="actions"><button type="submit">সব সেভ</button></div>
              </form>
            </section>
          </div>

          <h2>সাম্প্রতিক চেক ({num(checks.length)}টা)</h2>
          {checks.length === 0 && <div className="empty">এখনও কোনো চেক নেই।</div>}
          {checks.length > 0 && (
            <div className="scroll tablewrap">
              <table className="cards">
                <thead><tr><th>শব্দ</th><th>তারিখ</th><th>বিজ্ঞাপন</th><th>দাতা</th><th>পুরনো (দিন)</th><th>নতুন-৩০</th><th /></tr></thead>
                <tbody>
                  {checks.map((c) => {
                    const age = daysBetween(c.observed_on, today);
                    const t = c.canonical_product_id !== null ? titles.get(c.canonical_product_id) : undefined;
                    return (
                      <tr key={c.id}>
                        <td>
                          {c.keyword}
                          {c.canonical_product_id !== null && (
                            <span className="sub">
                              শুধু এই প্রোডাক্টের: {t ? <Link href={`/products/${t.id}`}>{(t.title_raw ?? "").slice(0, 40) || `#${c.canonical_product_id}`}</Link> : `#${c.canonical_product_id}`}
                            </span>
                          )}
                          {c.note && <span className="sub">{stripEmoji(c.note)}</span>}
                        </td>
                        <td data-label="তারিখ">{day(c.observed_on)}{age > MAX_AGE ? <span className="sub">পুরনো, স্কোরে ধরা হয় না</span> : null}</td>
                        <td data-label="বিজ্ঞাপন">{num(c.active_ads)}</td>
                        <td data-label="দাতা">{num(c.advertisers)}</td>
                        <td data-label="পুরনো (দিন)">{c.oldest_start ? num(daysBetween(c.oldest_start, c.observed_on)) : "–"}</td>
                        <td data-label="নতুন-৩০">{num(c.new_30d)}</td>
                        <td className="act">
                          <form action={deleteAdCheck}>
                            <input type="hidden" name="back" value="/ads" /><input type="hidden" name="id" value={c.id} />
                            <button type="submit" className="iconbtn" aria-label={`মুছুন: ${c.keyword}`}><Icon name="close" size={18} /></button>
                          </form>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
