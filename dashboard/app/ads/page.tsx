import Link from "next/link";
import { rest } from "@/lib/supabase";
import { num, day } from "@/lib/format";
import { saveAdChecks, deleteAdCheck } from "./actions";

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
      <p><Link href="/">← প্রোডাক্ট তালিকা</Link></p>
      <h1>Facebook Ads Library চেক</h1>
      <p className="muted">
        Facebook-এ কতজন, কতদিন ধরে বিজ্ঞাপন চালাচ্ছে তা হাতে দেখে এখানে দিন। এটা &quot;বাজার-সমর্থন&quot;-এর একটা সংকেত, বিক্রির প্রমাণ নয়
        (Ads Library-তে খরচ বা ইম্প্রেশন নেই)। স্কোরে ওজন ডিফল্টে ০, তাই এখন শুধু কারণ ও ব্যাজে দেখায়।
      </p>

      {ok > 0 && <div className="box" style={{ marginBottom: 12 }}>✅ {ok}টা চেক সেভ হয়েছে। পরের Score Daily রানে (বা হাতে চালালে এখনই) প্রোডাক্টে দেখাবে।</div>}
      {err && <div className="box" style={{ marginBottom: 12, whiteSpace: "pre-wrap" }}>⚠️ সেভ হয়নি:{"\n"}{err}</div>}

      <details className="box" style={{ marginBottom: 12 }}>
        <summary>কীভাবে চেক করবেন (ফোনেই হয়)</summary>
        <ol style={{ paddingLeft: 20, margin: "8px 0" }}>
          <li>facebook.com/ads/library খুলুন। দেশ <b>Bangladesh</b>, ধরন <b>All ads</b> (সব বিজ্ঞাপন), স্ট্যাটাস <b>Active</b> বেছে নিন।</li>
          <li>প্রোডাক্টের ধরনের শব্দ লিখে খুঁজুন, যেমন <code>air fryer</code>। ইংরেজি আর বাংলা শব্দ আলাদা আলাদা চেক করা যায়।</li>
          <li><b>বিজ্ঞাপন সংখ্যা</b> = ফলাফলের সংখ্যা (উপরে যেমন &quot;~120 results&quot; দেখায়)। এটাই একমাত্র আবশ্যক ঘর।</li>
          <li><b>বিজ্ঞাপনদাতা</b> = স্ক্রল করে যে কার্ডগুলো দেখলেন তাদের আলাদা পেজের সংখ্যা (আসলে এর চেয়ে বেশি থাকতে পারে, তাই এটা সর্বনিম্ন)।</li>
          <li><b>সবচেয়ে পুরনো</b> = কার্ডগুলোর &quot;Started running on&quot; তারিখের সবচেয়ে আগেরটা (দিন/মাস/বছর বা 3 Oct 2026 লিখলেও চলে)।</li>
          <li><b>গত ৩০ দিনে নতুন</b> = ঐচ্ছিক, ফাঁকা রাখা যায়।</li>
        </ol>
        <div className="muted" style={{ fontSize: 12 }}>
          Ads Library-র পেজের ভাষা ও লেআউট Facebook বদলায়, আমি আসল পেজ দেখে এই ধাপগুলো লিখিনি। কোনো ধাপ না মিললে জানান। শব্দ যত নির্দিষ্ট,
          সংকেত তত কাজের (&quot;air fryer&quot; ভালো, &quot;kitchen&quot; নয়)। একই শব্দ আবার চেক করলে (১৪ দিন বা বেশি পরে) বিজ্ঞাপন বাড়ছে কি কমছে তাও ধরা পড়ে।
        </div>
      </details>

      {checks === null ? (
        <p className="muted">চেক রাখতে Phase 6 migration (<code>20261116000000_phase6.sql</code>) চালান।</p>
      ) : (
        <>
          <div className="box" style={{ marginBottom: 12 }}>
            <h3>একটা চেক দিন (প্রোডাক্টের ধরনের শব্দ)</h3>
            <form action={saveAdChecks} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
              <input type="hidden" name="back" value="/ads" />
              <label>শব্দ<br /><input name="keyword" type="text" required maxLength={80} placeholder="air fryer" style={{ width: 150 }} /></label>
              <label>বিজ্ঞাপন সংখ্যা<br /><input name="ads" type="text" inputMode="numeric" required style={{ width: 90 }} /></label>
              <label>বিজ্ঞাপনদাতা<br /><input name="advertisers" type="text" inputMode="numeric" style={{ width: 90 }} /></label>
              <label>সবচেয়ে পুরনো<br /><input name="oldest" type="text" placeholder="3 Oct 2026" style={{ width: 110 }} /></label>
              <label>নতুন (৩০ দিন)<br /><input name="new30" type="text" inputMode="numeric" style={{ width: 90 }} /></label>
              <button type="submit">সেভ</button>
            </form>
          </div>

          <div className="box" style={{ marginBottom: 12 }}>
            <h3>অনেকগুলো একসাথে (প্রতি লাইনে একটা)</h3>
            <form action={saveAdChecks}>
              <input type="hidden" name="back" value="/ads" />
              <textarea name="bulk" rows={5} placeholder={"air fryer | 120 | 14 | 3 Sep 2026 | 30\nপাঞ্জাবি | 85 | 20\nsaree | 25"} style={{ width: "100%", font: "inherit", padding: 8 }} />
              <div className="muted" style={{ fontSize: 12, margin: "4px 0 8px" }}>
                ক্রম: শব্দ | বিজ্ঞাপন | বিজ্ঞাপনদাতা | সবচেয়ে পুরনোর তারিখ | নতুন-৩০ দিন। প্রথম দুটো আবশ্যক, বাকিগুলো বাদ দেওয়া বা &quot;-&quot; দেওয়া যায়।
                বাংলা অঙ্ক চলে। একবারে সর্বোচ্চ ৬০ লাইন।
              </div>
              <button type="submit">সব সেভ</button>
            </form>
          </div>

          <h2 style={{ fontSize: 16 }}>সাম্প্রতিক চেক ({checks.length}টা)</h2>
          {checks.length === 0 && <p className="muted">এখনও কোনো চেক নেই।</p>}
          <div className="scroll">
            <table>
              <thead><tr><th>শব্দ</th><th>তারিখ</th><th>বিজ্ঞাপন</th><th>দাতা</th><th>পুরনো (দিন)</th><th>নতুন-৩০</th><th></th></tr></thead>
              <tbody>
                {checks.map((c) => {
                  const age = daysBetween(c.observed_on, today);
                  const t = c.canonical_product_id !== null ? titles.get(c.canonical_product_id) : undefined;
                  return (
                    <tr key={c.id}>
                      <td>
                        {c.keyword}
                        {c.canonical_product_id !== null && (
                          <div className="muted" style={{ fontSize: 11 }}>
                            শুধু এই প্রোডাক্টের: {t ? <Link href={`/products/${t.id}`}>{(t.title_raw ?? "").slice(0, 40) || `#${c.canonical_product_id}`}</Link> : `#${c.canonical_product_id}`}
                          </div>
                        )}
                        {c.note && <div className="muted" style={{ fontSize: 11 }}>{c.note}</div>}
                      </td>
                      <td>{day(c.observed_on)}{age > MAX_AGE ? <div className="muted" style={{ fontSize: 11 }}>পুরনো, স্কোরে ধরা হয় না</div> : null}</td>
                      <td>{num(c.active_ads)}</td>
                      <td>{num(c.advertisers)}</td>
                      <td>{c.oldest_start ? num(daysBetween(c.oldest_start, c.observed_on)) : "–"}</td>
                      <td>{num(c.new_30d)}</td>
                      <td>
                        <form action={deleteAdCheck}>
                          <input type="hidden" name="back" value="/ads" /><input type="hidden" name="id" value={c.id} />
                          <button type="submit" aria-label="মুছুন">✕</button>
                        </form>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
