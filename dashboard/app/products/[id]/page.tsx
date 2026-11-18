import Link from "next/link";
import { revalidatePath } from "next/cache";
import { notFound } from "next/navigation";
import { rest, rpc } from "@/lib/supabase";
import { num, taka, delta, rating, day } from "@/lib/format";
import { FACTOR_LABEL, FACTOR_WEIGHT, OPTIONAL_FACTORS, TOPIC_BN, tierText } from "@/lib/tier";
import { saveAdChecks, deleteAdCheck } from "@/app/ads/actions";
import { toggleWatch } from "@/app/watch/actions";

export const dynamic = "force-dynamic";

type Overview = {
  id: number; canonical_product_id: number | null; url: string; title_raw: string | null; brand_raw: string | null; seller_name: string | null;
  category: string | null; first_seen_at: string; captured_on: string | null; price: number | null;
  original_price: number | null; rating_avg: number | null; rating_count: number | null;
  review_count: number | null; sold_count: number | null; sold_delta_7d: number | null; review_delta_7d: number | null;
  score: number | null; tier: string | null; confidence: string | null; provisional_tier: string | null; scored_on: string | null;
  reasons: {
    summary?: string[]; notes?: string[]; factors?: Record<string, number | null>; weights?: Record<string, number>;
    detail?: { google?: GoogleDetail; margin?: MarginDetail; competition?: { sellers: number; listings: number; by: string }; ads?: AdsDetail };
  } | null;
};
type GoogleDetail = {
  group: string; label: string; status: string; score?: number; momentum_pct?: number; position_pct?: number;
  yoy_pct?: number | null; seasonal?: boolean; recent_weeks?: number; prior_weeks?: number;
};
type MarginDetail = {
  price: number; unit_cost: number; extra_cost: number; profit: number; margin_pct: number; roi_pct: number | null;
  break_even_price: number | null; fee_pct: number; return_rate_pct: number;
};
type AdsDetail = {
  keyword: string; level: "product" | "segment"; status: string; observed_on: string; active_ads: number; advertisers: number | null;
  oldest_start: string | null; new_30d: number | null; score?: number; longest_days?: number | null; growth_pct?: number | null;
  growth_basis?: string | null; crowded?: boolean; age_days?: number;
};
type AdCheck = { id: number; keyword: string; observed_on: string; active_ads: number; advertisers: number | null; oldest_start: string | null; new_30d: number | null };
type Cost = { unit_cost: number; extra_cost: number; note: string | null; updated_at: string };
type TrendKw = { id: number; keyword: string; lang: string };
type TrendPt = { keyword_id: number; week_start: string; value: number | null };
type Snap = { captured_on: string; price: number | null; rating_count: number | null; sold_count: number | null; review_count: number | null };
type Review = { stars: number; body: string | null; reviewed_at: string | null; lang: string | null; suspected_fake: boolean; flags?: string[] | null; sentiment?: number | null; topics?: string[] | null };

// কেনা দাম সেভ: শুধু SQL ফাংশন set_product_cost ডাকে (Phase 5 migration লাগে)। মার্জিন পরের স্কোরিং রানে হিসাব হয়
async function saveCost(formData: FormData) {
  "use server";
  const cid = Number(formData.get("cid"));
  const listing = Number(formData.get("id"));
  const unit = Number(formData.get("unit"));
  const extra = Number(formData.get("extra") || 0);
  if (!Number.isInteger(cid) || cid <= 0 || !Number.isInteger(listing) || listing <= 0) return;
  if (!Number.isFinite(unit) || unit < 0 || !Number.isFinite(extra) || extra < 0) return;
  await rpc("set_product_cost", { p_canonical: cid, p_unit_cost: unit, p_extra_cost: extra, p_note: String(formData.get("note") ?? "").slice(0, 200) });
  revalidatePath(`/products/${listing}`);
}

async function clearCost(formData: FormData) {
  "use server";
  const cid = Number(formData.get("cid"));
  const listing = Number(formData.get("id"));
  if (!Number.isInteger(cid) || cid <= 0 || !Number.isInteger(listing) || listing <= 0) return;
  await rpc("clear_product_cost", { p_canonical: cid });
  revalidatePath(`/products/${listing}`);
}

function Spark({ values, label }: { values: (number | null)[]; label: string }) {
  const pts = values.map((v, i) => ({ v, i })).filter((p): p is { v: number; i: number } => p.v !== null);
  if (pts.length < 2) return <div className="box"><h3>{label}</h3><span className="muted">ইতিহাস জমছে…</span></div>;
  const min = Math.min(...pts.map((p) => p.v));
  const max = Math.max(...pts.map((p) => p.v));
  const span = max - min || 1;
  const n = values.length - 1 || 1;
  const d = pts.map((p) => `${((p.i / n) * 100).toFixed(1)},${(44 - ((p.v - min) / span) * 40).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1].v;
  return (
    <div className="box">
      <h3>{label}</h3>
      <svg className="spark" viewBox="0 0 100 48" preserveAspectRatio="none" aria-label={label}>
        <polyline points={d} fill="none" stroke="var(--accent)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="muted">{num(min)} → {num(last)} (সর্বোচ্চ {num(max)})</div>
    </div>
  );
}

// en ও bn শব্দের সিরিজ একই সপ্তাহগুলোতে যোগ (স্কোরিংয়ের হিসাবের মতোই), যাতে গ্রাফ আর স্কোর একই জিনিস দেখায়
async function googleSeries(group: string): Promise<{ weeks: string[]; values: number[]; keywords: string[] }> {
  const kws = await rest<TrendKw[]>("trend_keywords", { group_key: `eq.${group}`, last_status: "eq.ok", select: "id,keyword,lang" });
  if (kws.length === 0) return { weeks: [], values: [], keywords: [] };
  const pts = await rest<TrendPt[]>("trend_points", {
    keyword_id: `in.(${kws.map((k) => k.id).join(",")})`, order: "week_start.asc", select: "keyword_id,week_start,value",
  });
  const by = new Map<number, Map<string, number>>();
  for (const p of pts) if (p.value !== null) (by.get(p.keyword_id) ?? by.set(p.keyword_id, new Map()).get(p.keyword_id)!).set(p.week_start, Number(p.value));
  const maps = kws.map((k) => by.get(k.id)).filter((m): m is Map<string, number> => !!m);
  if (maps.length === 0) return { weeks: [], values: [], keywords: [] };
  const weeks = [...maps[0].keys()].filter((w) => maps.every((m) => m.has(w))).sort();
  return { weeks, values: weeks.map((w) => maps.reduce((a, m) => a + (m.get(w) as number), 0)), keywords: kws.map((k) => k.keyword) };
}

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${v}%`);

export default async function Product({ params, searchParams }: { params: { id: string }; searchParams: Record<string, string | undefined> }) {
  const id = Number(params.id);
  if (!Number.isInteger(id) || id <= 0) notFound();

  const [ov, snaps, reviews] = await Promise.all([
    rest<Overview[]>("listing_scored", { id: `eq.${id}`, select: "*" }),
    rest<Snap[]>("listing_snapshots", { listing_id: `eq.${id}`, order: "captured_on.asc", select: "captured_on,price,rating_count,sold_count,review_count" }),
    rest<Review[]>("reviews", { listing_id: `eq.${id}`, order: "reviewed_at.desc.nullslast", limit: "30", select: "stars,body,reviewed_at,lang,suspected_fake,flags,sentiment,topics" })
      // Phase 5 migration চলেনি: flags কলাম নেই, আগের মতো দেখায়
      .catch(() => rest<Review[]>("reviews", { listing_id: `eq.${id}`, order: "reviewed_at.desc.nullslast", limit: "30", select: "stars,body,reviewed_at,lang,suspected_fake,sentiment,topics" })),
  ]);
  if (ov.length === 0) notFound();
  const p = ov[0];
  let costs: Cost[] | null = [];
  if (p.canonical_product_id) {
    costs = await rest<Cost[]>("product_costs", { canonical_product_id: `eq.${p.canonical_product_id}`, select: "unit_cost,extra_cost,note,updated_at" }).catch(() => null);
  }
  const cost = costs && costs.length ? costs[0] : null;
  // এই প্রোডাক্টের নিজস্ব Ads Library চেক (Phase 6 migration না চললে null)
  let ownAds: AdCheck[] | null = [];
  if (p.canonical_product_id) {
    ownAds = await rest<AdCheck[]>("ad_checks", { canonical_product_id: `eq.${p.canonical_product_id}`, order: "observed_on.desc,id.desc", limit: "5", select: "id,keyword,observed_on,active_ads,advertisers,oldest_start,new_30d" }).catch(() => null);
  }
  // নজরে রাখা ও এই প্রোডাক্টের সাম্প্রতিক অ্যালার্ট (Phase 7 migration না চললে null, তখন বোতাম দেখায় না)
  let watch: { note: string | null }[] | null = [];
  let prodAlerts: { id: number; created_on: string; severity: string; title: string }[] = [];
  if (p.canonical_product_id) {
    watch = await rest<{ note: string | null }[]>("watchlist", { canonical_product_id: `eq.${p.canonical_product_id}`, select: "note" }).catch(() => null);
    prodAlerts = await rest<typeof prodAlerts>("alerts", { canonical_product_id: `eq.${p.canonical_product_id}`, order: "created_on.desc,id.desc", limit: "5", select: "id,created_on,severity,title" }).catch(() => []);
  }
  const watched = !!(watch && watch.length);
  const watchErr = (searchParams.watch_err ?? "").slice(0, 300);
  const ad = p.reasons?.detail?.ads;
  const adsOk = Number(searchParams.ads_ok) || 0;
  const adsErr = (searchParams.ads_err ?? "").slice(0, 700);
  const mg = p.reasons?.detail?.margin;
  const wts = p.reasons?.weights ?? FACTOR_WEIGHT;
  const g = p.reasons?.detail?.google;
  const gs = g ? await googleSeries(g.group).catch(() => ({ weeks: [], values: [], keywords: [] })) : null;
  const dist = [5, 4, 3, 2, 1].map((s) => ({ s, c: reviews.filter((r) => r.stars === s).length }));

  return (
    <>
      <p><Link href="/">← তালিকায় ফিরুন</Link></p>
      <h1>{p.title_raw || "(নাম নেই)"}</h1>
      <p className="muted">
        {p.category || "–"} · ব্র্যান্ড: {p.brand_raw || "–"} · সেলার: {p.seller_name || "–"} ·{" "}
        <a href={p.url} target="_blank" rel="noopener noreferrer">Daraz-এ দেখুন ↗</a>
      </p>
      {p.canonical_product_id && watch !== null && (
        <form action={toggleWatch} style={{ marginBottom: 10 }}>
          <input type="hidden" name="cid" value={p.canonical_product_id} />
          <input type="hidden" name="on" value={watched ? "0" : "1"} />
          <input type="hidden" name="back" value={`/products/${id}`} />
          {!watched && <input name="note" placeholder="নোট (ঐচ্ছিক)" maxLength={200} style={{ marginRight: 6 }} />}
          <button type="submit" className="linkbtn">{watched ? "⭐ নজরে আছে, সরান" : "☆ নজরে রাখুন"}</button>
          {watched && watch![0].note && <span className="muted"> 📝 {watch![0].note}</span>}
        </form>
      )}
      {watchErr && <p className="down">{watchErr}</p>}
      {prodAlerts.length > 0 && (
        <div className="box" style={{ marginBottom: 10 }}>
          <h3>সাম্প্রতিক অ্যালার্ট</h3>
          {prodAlerts.map((a) => <div key={a.id} className="muted">{a.severity === "good" ? "🟢" : a.severity === "warn" ? "🔴" : "⚪"} {day(a.created_on)}: {a.title}</div>)}
        </div>
      )}

      {p.tier ? (
        <div className="box" style={{ marginBottom: 12 }}>
          <h3>স্কোর ({day(p.scored_on)})</h3>
          <div>
            <span className={`badge ${p.tier}`}>{tierText(p.tier, p.confidence, p.provisional_tier)}</span>{" "}
            <b>{Math.round(p.score ?? 0)}</b>/100 · কনফিডেন্স {p.confidence}
            {ad?.status === "ok" && ad.crowded ? <> · <span className="chip">📢 বিজ্ঞাপনে ভিড়</span></> : null}
          </div>
          {(p.reasons?.summary ?? []).map((s, i) => <div key={i}>• {s}</div>)}
          {(p.reasons?.notes ?? []).map((s, i) => <div key={i} className="muted">– {s}</div>)}
          <div style={{ marginTop: 8 }}>
            {Object.keys(FACTOR_LABEL).filter((k) => !OPTIONAL_FACTORS.includes(k) || p.reasons?.factors?.[k] != null).map((k) => {
              const v = p.reasons?.factors?.[k];
              return (
                <div key={k} className="bar">
                  <span>{FACTOR_LABEL[k]} · {(wts[k] ?? 0) > 0 ? `ওজন ${wts[k]}` : "শুধু তথ্য (স্কোরে ওজন ০)"}</span>
                  <div className="track"><div className="fill" style={{ width: `${v ?? 0}%`, opacity: v === null || v === undefined ? 0.15 : 1 }} /></div>
                  <small className="muted">{v === null || v === undefined ? "ডেটা নেই" : Math.round(v)}</small>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <p className="muted">এই প্রোডাক্টের স্কোর এখনও হয়নি (ডেটা জমছে)।</p>
      )}

      {p.canonical_product_id && (
        <div className="box" style={{ marginBottom: 12 }}>
          <h3>আপনার কেনা দাম ও মার্জিন</h3>
          {costs === null ? (
            <p className="muted">কেনা দাম রাখতে Phase 5 migration (<code>20261115000000_phase5.sql</code>) চালান।</p>
          ) : (
            <>
              {mg ? (
                <div style={{ marginBottom: 8 }}>
                  বাজারে সর্বনিম্ন ৳{mg.price} · খরচ ৳{mg.unit_cost + mg.extra_cost} → প্রতি পিসে প্রায় <b>৳{mg.profit}</b> লাভ,
                  মার্জিন <b>{mg.margin_pct}%</b>{mg.roi_pct !== null ? <> (খরচের উপর {mg.roi_pct}%)</> : null}
                  {mg.break_even_price !== null ? <> · ন্যূনতম বিক্রয়মূল্য ৳{mg.break_even_price}</> : null}
                  <div className="muted" style={{ fontSize: 12 }}>
                    ধরা হয়েছে: প্ল্যাটফর্ম ফি {mg.fee_pct}%, ফেরতের হার {mg.return_rate_pct}% (config/scoring.json-এ বদলানো যায়)।
                  </div>
                </div>
              ) : cost ? (
                <p className="muted">মার্জিন পরের স্কোরিং রানে হিসাব হবে (Score Daily হাতে চালালে এখনই)।</p>
              ) : (
                <p className="muted">কেনা দাম দিলে মার্জিন ও ন্যূনতম বিক্রয়মূল্য দেখাবে, আর লোকসানের প্রোডাক্ট Best হবে না।</p>
              )}
              <form action={saveCost} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
                <input type="hidden" name="cid" value={p.canonical_product_id} />
                <input type="hidden" name="id" value={p.id} />
                <label>কেনা দাম (৳)<br /><input name="unit" type="number" min="0" step="0.01" required defaultValue={cost?.unit_cost} style={{ width: 110 }} /></label>
                <label>বাড়তি খরচ (৳)<br /><input name="extra" type="number" min="0" step="0.01" defaultValue={cost?.extra_cost ?? 0} style={{ width: 110 }} /></label>
                <label>নোট<br /><input name="note" type="text" maxLength={200} defaultValue={cost?.note ?? ""} style={{ width: 160 }} /></label>
                <button type="submit">সেভ</button>
              </form>
              {cost && (
                <form action={clearCost} style={{ marginTop: 6 }}>
                  <input type="hidden" name="cid" value={p.canonical_product_id} />
                  <input type="hidden" name="id" value={p.id} />
                  <button type="submit">কেনা দাম মুছুন</button>
                </form>
              )}
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>বাড়তি খরচ = প্রতি পিসে প্যাকেজিং, ডেলিভারি ইত্যাদি।</div>
            </>
          )}
        </div>
      )}


      {p.canonical_product_id && (
        <div className="box" style={{ marginBottom: 12 }}>
          <h3>Facebook Ads Library (হাতে-দেওয়া চেক)</h3>
          {adsOk > 0 && <div style={{ marginBottom: 8 }}>✅ {adsOk}টা চেক সেভ হয়েছে। পরের Score Daily রানে স্কোরে দেখাবে।</div>}
          {adsErr && <div style={{ marginBottom: 8, whiteSpace: "pre-wrap" }}>⚠️ সেভ হয়নি:{"\n"}{adsErr}</div>}
          {ownAds === null ? (
            <p className="muted">চেক রাখতে Phase 6 migration (<code>20261116000000_phase6.sql</code>) চালান।</p>
          ) : (
            <>
              {ad?.status === "ok" ? (
                <div style={{ marginBottom: 8 }}>
                  &apos;{ad.keyword}&apos; শব্দে ({day(ad.observed_on)}, {ad.level === "product" ? "এই প্রোডাক্টের নিজস্ব চেক" : "প্রোডাক্টের ধরনের চেক, এই প্রোডাক্টের নিজস্ব নয়"}):{" "}
                  <b>{num(ad.active_ads)}</b>টা সক্রিয় বিজ্ঞাপন{ad.advertisers !== null ? <>, কমপক্ষে <b>{num(ad.advertisers)}</b>টা আলাদা পেজ</> : null}
                  {ad.longest_days !== null && ad.longest_days !== undefined ? <>, সবচেয়ে পুরনোটা <b>{ad.longest_days}</b> দিন ধরে চলছে</> : null}
                  {ad.growth_basis === "history" && ad.growth_pct !== null && ad.growth_pct !== undefined ? <>, আগের চেকের চেয়ে বিজ্ঞাপন {pct(ad.growth_pct)}</> : null}
                  {ad.growth_basis === "new_share" && ad.new_30d !== null ? <>, গত ৩০ দিনে নতুন {num(ad.new_30d)}টা</> : null}
                  {ad.crowded ? <> · <b>📢 বিজ্ঞাপনে ভিড়</b> (প্রতিযোগিতা বেশি হতে পারে)</> : null}
                </div>
              ) : ad?.status === "stale" ? (
                <p className="muted">শেষ চেক পুরনো ({day(ad.observed_on)}), স্কোরে ধরা হয়নি। নতুন চেক দিন।</p>
              ) : (
                <p className="muted">এই প্রোডাক্টে কোনো চেক লাগেনি। প্রোডাক্টের ধরনের শব্দ <Link href="/ads">/ads</Link>-এ দিলে মিলে গেলে লাগে, বা নিচে এই প্রোডাক্টের জন্যই সরাসরি দিন।</p>
              )}
              <form action={saveAdChecks} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
                <input type="hidden" name="back" value={`/products/${p.id}`} />
                <input type="hidden" name="cid" value={p.canonical_product_id} />
                <label>শব্দ<br /><input name="keyword" type="text" required maxLength={80} defaultValue={ownAds[0]?.keyword ?? ""} style={{ width: 150 }} /></label>
                <label>বিজ্ঞাপন সংখ্যা<br /><input name="ads" type="text" inputMode="numeric" required style={{ width: 90 }} /></label>
                <label>বিজ্ঞাপনদাতা<br /><input name="advertisers" type="text" inputMode="numeric" style={{ width: 90 }} /></label>
                <label>সবচেয়ে পুরনো<br /><input name="oldest" type="text" placeholder="3 Oct 2026" style={{ width: 110 }} /></label>
                <label>নতুন (৩০ দিন)<br /><input name="new30" type="text" inputMode="numeric" style={{ width: 90 }} /></label>
                <button type="submit">সেভ</button>
              </form>
              {ownAds.length > 0 && (
                <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                  এই প্রোডাক্টের নিজস্ব চেক:
                  {ownAds.map((c) => (
                    <form key={c.id} action={deleteAdCheck} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 2 }}>
                      <input type="hidden" name="back" value={`/products/${p.id}`} /><input type="hidden" name="id" value={c.id} />
                      <span>{day(c.observed_on)} · &apos;{c.keyword}&apos; · {num(c.active_ads)} বিজ্ঞাপন{c.advertisers !== null ? ` · ${num(c.advertisers)} পেজ` : ""}</span>
                      <button type="submit" aria-label="মুছুন">✕</button>
                    </form>
                  ))}
                </div>
              )}
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                কীভাবে চেক করবেন: <Link href="/ads">/ads</Link>-এর নির্দেশনা। &quot;বিজ্ঞাপনদাতা বেশি&quot; মানে বাজারের সমর্থনও, প্রতিযোগিতাও: তাই ভিড় ব্যাজ আলাদা, Best আটকায় না।
              </div>
            </>
          )}
        </div>
      )}

      <div className="grid2">
        <div className="box"><h3>দাম</h3><b>{taka(p.price)}</b> {p.original_price ? <s className="muted">{taka(p.original_price)}</s> : null}</div>
        <div className="box"><h3>রেটিং</h3><b>{rating(p.rating_avg)}</b> ({num(p.rating_count)} টি)</div>
        <div className="box"><h3>মোট বিক্রি</h3><b>{num(p.sold_count)}</b></div>
        <div className="box"><h3>৭ দিনে বিক্রি / রিভিউ</h3><b>{delta(p.sold_delta_7d)}</b> / {delta(p.review_delta_7d)}</div>
      </div>

      <div className="grid2">
        <Spark label="দামের ইতিহাস" values={snaps.map((s) => s.price)} />
        <Spark label="মোট বিক্রি" values={snaps.map((s) => s.sold_count)} />
        <Spark label="রিভিউ সংখ্যা" values={snaps.map((s) => s.review_count)} />
        {g && gs && (
          <div>
            <Spark label={`Google সার্চ: ${g.label} (সাপ্তাহিক)`} values={gs.values} />
            <div className="muted" style={{ fontSize: 12, padding: "0 4px" }}>
              {g.status === "ok"
                ? <>গত {g.recent_weeks} সপ্তাহ বনাম আগের {g.prior_weeks}: {pct(g.momentum_pct)} · ১২ মাসের গড়ের তুলনায় {pct(g.position_pct)}
                    {g.seasonal ? <> · মৌসুমি{g.yoy_pct !== null && g.yoy_pct !== undefined ? <>, গত বছরের তুলনায় {pct(g.yoy_pct)}</> : null}</> : null}</>
                : <>এই কীওয়ার্ডের ডেটা স্কোরে ধরা হয়নি ({g.status === "stale" ? "পুরনো" : g.status === "short" ? "ডেটা কম বা নেই" : g.status})</>}
              <br />প্রোডাক্টের ধরনের সার্চ, এই প্রোডাক্টের নিজস্ব নয়।
            </div>
          </div>
        )}
        <div className="box">
          <h3>সাম্প্রতিক রিভিউয়ের স্টার ({reviews.length}টা)</h3>
          {dist.map((d) => <div key={d.s}>{d.s}★ {"█".repeat(d.c)} {d.c}</div>)}
        </div>
      </div>

      <h2 style={{ fontSize: 16 }}>রিভিউ</h2>
      {reviews.length === 0 && <p className="muted">এখনও কোনো রিভিউ সংগ্রহ হয়নি।</p>}
      {reviews.map((r, i) => (
        <div className="review" key={i}>
          {r.stars}★ <span className="muted">{day(r.reviewed_at)}{r.suspected_fake ? " · সন্দেহজনক" : ""}{r.flags?.includes("counterfeit") ? " · ⚠️ নকল অভিযোগ" : ""}{r.sentiment != null ? ` · ${r.sentiment > 0 ? "🙂" : r.sentiment < 0 ? "🙁" : "😐"}` : ""}{r.topics && r.topics.length ? ` · ${r.topics.map((t) => TOPIC_BN[t] ?? t).join(", ")}` : ""}</span>
          <div>{r.body || ""}</div>
        </div>
      ))}

      <h2 style={{ fontSize: 16 }}>দৈনিক স্ন্যাপশট</h2>
      <div className="scroll">
        <table>
          <thead><tr><th>তারিখ</th><th>দাম</th><th>বিক্রি</th><th>রিভিউ</th></tr></thead>
          <tbody>
            {[...snaps].reverse().slice(0, 30).map((s) => (
              <tr key={s.captured_on}><td>{day(s.captured_on)}</td><td>{taka(s.price)}</td><td>{num(s.sold_count)}</td><td>{num(s.review_count)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
