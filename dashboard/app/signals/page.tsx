import Link from "next/link";
import { rest } from "@/lib/supabase";
import { num, day } from "@/lib/format";
import { stripEmoji } from "@/lib/clean";
import { SIGNAL_SOURCES, sourceLabel } from "@/lib/signalparse";
import { saveSignal, deleteSignal } from "./actions";
import { Icon } from "../components/icons";

export const dynamic = "force-dynamic";

type Signal = {
  id: number; source: string; keyword: string | null; canonical_product_id: number | null; observed_on: string;
  value: number | null; unit: string | null; link: string | null; note: string | null;
};

const host = (u: string): string => {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return "লিংক"; }
};

export default async function Signals({ searchParams }: { searchParams: Record<string, string | undefined> }) {
  let rows: Signal[] | null = [];
  try {
    rows = await rest<Signal[]>("manual_signals", {
      select: "id,source,keyword,canonical_product_id,observed_on,value,unit,link,note", order: "observed_on.desc,id.desc", limit: "100",
    });
  } catch {
    rows = null; // Phase 11 migration চলেনি
  }
  const ok = Number(searchParams.sig_ok) || 0;
  const err = (searchParams.sig_err ?? "").slice(0, 700);

  return (
    <>
      <Link href="/" className="back"><Icon name="left" size={16} />প্রোডাক্ট তালিকা</Link>
      <h1>সিগন্যাল (হাতে দেওয়া)</h1>
      <p className="lede">
        TikTok Creative Center, Pinterest Trends, Infoneen, Similarweb বা YouTube-এ হাতে যা দেখলেন তা এখানে রাখুন: কোন শব্দে কত ভলিউম, ভিউ বা ট্রাফিক।
        এখন এগুলো শুধু জমা থাকে ও এখানে দেখা যায়, স্কোরে ধরা হয় না। Facebook Ads Library-র চেক আগের মতো <Link href="/ads">Ads</Link> পেজে যাবে।
      </p>

      {ok > 0 && <div className="msg ok" role="status"><Icon name="check" size={18} /><span>সিগন্যাল সেভ হয়েছে।</span></div>}
      {err && <div className="msg err" role="alert"><Icon name="alert" size={18} /><span>সেভ হয়নি:{"\n"}{err}</span></div>}

      <details className="box" style={{ marginBottom: 12 }}>
        <summary>কীভাবে দেবেন (ফোনেই হয়)</summary>
        <ol className="steps">
          <li><b>সোর্স</b> বেছে নিন, <b>শব্দ</b> লিখুন (যেমন <code>air fryer</code>)। বাংলা শব্দও চলে।</li>
          <li><b>মান</b>-এ সংখ্যা: <code>1200</code>, <code>1,200</code>, <code>12K</code>, <code>1.2M</code> বা <code>25%</code> চলে, বাংলা অঙ্কও। কমে-যাওয়া বোঝাতে <code>-15</code>।</li>
          <li><b>একক</b> ঐচ্ছিক, মানটা কীসের তা বোঝাতে (ভিউ, সার্চ/মাস, ভিজিট, %)।</li>
          <li><b>তারিখ</b> ফাঁকা রাখলে আজকের। অন্যদিনের দেখা হলে <code>3 Nov 2026</code> বা <code>3/11/2026</code> লিখুন।</li>
          <li><b>লিংক</b> ঐচ্ছিক (পেজের ঠিকানা), পরে মিলিয়ে দেখতে কাজে লাগে। <b>মান বা নোট</b>, অন্তত একটা দিতে হবে (শুধু &quot;টপ ১০-এ ট্রেন্ডিং&quot; লিখলেও চলে)।</li>
        </ol>
        <p className="hint">একই সোর্স, শব্দ, তারিখ ও একক আবার দিলে আগেরটা বদলে যায়, তাই ভুল হলে আবার দিলেই ঠিক হয়ে যায়।</p>
      </details>

      {rows === null ? (
        <div className="msg"><Icon name="info" size={18} /><span>সিগন্যাল রাখতে Phase 11 migration (<code>20261122000000_phase11.sql</code>) চালান।</span></div>
      ) : (
        <>
          <section className="box">
            <h3>একটা সিগন্যাল দিন</h3>
            <form action={saveSignal} className="formrow signals">
              <label className="field wide src"><span>সোর্স</span>
                <select name="source" required defaultValue="">
                  <option value="" disabled>বেছে নিন</option>
                  {SIGNAL_SOURCES.map((s) => <option key={s.slug} value={s.slug}>{s.label}</option>)}
                </select>
              </label>
              <label className="field wide kw"><span>শব্দ</span><input name="keyword" type="text" required maxLength={80} placeholder="air fryer" /></label>
              <label className="field val"><span>মান</span><input name="value" type="text" inputMode="decimal" placeholder="12K" /></label>
              <label className="field unit"><span>একক</span><input name="unit" type="text" maxLength={24} placeholder="সার্চ/মাস" /></label>
              <label className="field wide date"><span>তারিখ (ফাঁকা = আজ)</span><input name="observed" type="text" placeholder="3 Nov 2026" /></label>
              <label className="field wide lnk"><span>লিংক</span><input name="link" type="url" inputMode="url" maxLength={500} placeholder="https://" /></label>
              <label className="field wide nt"><span>নোট</span><input name="note" type="text" maxLength={200} placeholder="যেমন সিজন ঈদের আগে" /></label>
              <button type="submit">সেভ</button>
            </form>
          </section>

          <h2>সাম্প্রতিক সিগন্যাল ({num(rows.length)}টা)</h2>
          {rows.length === 0 && <div className="empty">এখনও কোনো সিগন্যাল নেই।</div>}
          {rows.length > 0 && (
            <div className="scroll tablewrap">
              <table className="cards">
                <thead><tr><th>শব্দ</th><th>সোর্স</th><th>তারিখ</th><th>মান</th><th>লিংক</th><th /></tr></thead>
                <tbody>
                  {rows.map((s) => {
                    const kw = stripEmoji(s.keyword) || (s.canonical_product_id !== null ? `প্রোডাক্ট #${s.canonical_product_id}` : "–");
                    return (
                      <tr key={s.id}>
                        <td>
                          {kw}
                          {s.note && <span className="sub">{stripEmoji(s.note)}</span>}
                        </td>
                        <td data-label="সোর্স">{sourceLabel(s.source)}</td>
                        <td data-label="তারিখ">{day(s.observed_on)}</td>
                        <td data-label="মান">{s.value === null ? "–" : num(s.value)}{s.unit ? ` ${stripEmoji(s.unit)}` : ""}</td>
                        <td data-label="লিংক">
                          {s.link && /^https?:\/\//i.test(s.link)
                            ? <a href={s.link} target="_blank" rel="noopener noreferrer">{host(s.link)}</a>
                            : "–"}
                        </td>
                        <td className="act">
                          <form action={deleteSignal}>
                            <input type="hidden" name="id" value={s.id} />
                            <button type="submit" className="iconbtn" aria-label={`মুছুন: ${kw}`}><Icon name="close" size={18} /></button>
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
