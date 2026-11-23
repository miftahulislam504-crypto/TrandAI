// ড্যাশবোর্ড রেন্ডার-যাচাই (আসল Supabase ছাড়া): নকল PostgREST সার্ভার দিয়ে প্রতিটা পেজ খুলে
// ১) HTTP 200, ২) HTML-এ ইমোজি নেই (পুরনো ডেটার ⚠️ ঢোকানো থাকে, ছেঁকে যায় কি না), ৩) নতুন ক্লাসগুলো আছে কি না দেখে।
// ব্যবহার: cd dashboard && npm ci && npx next build && cd .. && node tools/dashboard_render_check.mjs
import http from "node:http";
import { spawn } from "node:child_process";

const WARN = "\u26A0\uFE0F", MEGA = "\u{1F4E2}";
const listing = {
  id: 1, canonical_product_id: 10, url: "https://www.daraz.com.bd/products/x-i1.html", title_raw: "Air Fryer 5L", brand_raw: "Acme", seller_name: "Acme Store",
  category: "kitchen", first_seen_at: "2026-11-01T00:00:00Z", captured_on: "2026-11-19", price: 5200, original_price: 6500, rating_avg: 4.6, rating_count: 120,
  review_count: 80, sold_count: 900, sold_delta_7d: 40, review_delta_7d: 6, price_delta_7d: -100, seller_name2: null, score: 78, tier: "best", confidence: "medium",
  provisional_tier: null, scored_on: "2026-11-19", is_active: true,
  reasons: {
    summary: [`${WARN} নকল/ডুপ্লিকেট অভিযোগ: ১০টি রিভিউয়ের মধ্যে ৩টায়`, `${MEGA} বিজ্ঞাপনে ভিড়: 'air fryer' শব্দে ১২০টা সক্রিয় বিজ্ঞাপন`],
    notes: ["ইতিহাস ১৪ দিনের কম"],
    factors: { demand: 80, trend: 60, review_quality: 70, bad_review: 30, ads_signal: 55, margin: null, competition: null },
    weights: { demand: 30, trend: 25, review_quality: 20, bad_review: 15, ads_signal: 0, margin: 0, competition: 0 },
    detail: { ads: { keyword: "air fryer", level: "segment", status: "ok", observed_on: "2026-11-18", active_ads: 120, advertisers: 14, oldest_start: "2026-09-03", new_30d: 30, longest_days: 76, crowded: true, growth_basis: "new_share" } },
  },
};
const T = {
  listing_scored: [listing], listing_overview: [{ id: 1, canonical_product_id: 10, title_raw: "Air Fryer 5L" }],
  categories: [{ slug: "kitchen", name: "Kitchen" }],
  match_queue: [{ id: 5, score: 0.82, created_at: "2026-11-19", status: "pending",
    evidence: { title_sim: 0.9, price_ratio: 0.95, shared: ["air", "fryer"], code_match: true, same_source: true, image_dist: 4, note: "cluster_conflict" },
    a_id: 1, a_source: "daraz", a_title: "Air Fryer 5L", a_url: "https://example.com/a", a_price: 5200, a_rating: 4.6, a_rating_count: 120, a_sold: 900, a_canonical: 10, a_image: null,
    b_id: 2, b_source: "daraz", b_title: "Air Fryer 5 Litre", b_url: null, b_price: 5000, b_rating: 4.4, b_rating_count: 30, b_sold: 100, b_canonical: 11, b_image: null }],
  alerts: [
    { id: 1, canonical_product_id: 10, kind: "redflag", created_on: "2026-11-19", watched: true, severity: "warn", title: `Air Fryer: ${WARN} নকল/ফেক অভিযোগ (৩টা রিভিউয়ে)`, seen_at: null },
    { id: 2, canonical_product_id: 10, kind: "tier_change", created_on: "2026-11-18", watched: false, severity: "good", title: "Air Fryer: Mid → Best", seen_at: "2026-11-19T00:00:00Z" },
  ],
  watchlist: [{ canonical_product_id: 10, note: "ঈদের আগে দেখব", added_at: "2026-11-19" }],
  listing_snapshots: [1, 2, 3].map((i) => ({ captured_on: `2026-11-1${i}`, price: 5000 + i * 100, rating_count: 100 + i, sold_count: 800 + i * 30, review_count: 70 + i })),
  reviews: [{ stars: 5, body: "খুব ভালো", reviewed_at: "2026-11-15", lang: "bn", suspected_fake: false, flags: ["counterfeit"], sentiment: 1, topics: ["quality", "price"] }],
  product_costs: [], trend_keywords: [], trend_points: [],
  manual_signals: [
    { id: 1, source: "infoneen", keyword: "air fryer", canonical_product_id: null, observed_on: "2026-11-20", value: 12000, unit: "সার্চ/মাস", link: "https://www.infoneen.com/x", note: `${WARN} সিজন ঈদের আগে` },
    { id: 2, source: "tiktok_creative_center", keyword: "smart watch", canonical_product_id: null, observed_on: "2026-11-19", value: null, unit: null, link: null, note: "টপ ১০-এ ট্রেন্ডিং" },
  ],
  ad_checks: [{ id: 1, keyword: "air fryer", canonical_product_id: 10, observed_on: "2026-11-18", active_ads: 120, advertisers: 14, oldest_start: "2026-09-03", new_30d: 30, note: `${WARN} হাতে-দেখা`, source: "manual" }],
};
const HEALTH = {
  today: "2026-11-20",
  sources: [{ slug: "daraz", name: "Daraz", runs_14d: 2, ok_14d: 1, partial_14d: 0, failed_14d: 1, unfinished_14d: 0, items_ok_14d: 400, items_failed_14d: 5, last_run_at: "2026-11-19T20:00:00Z", last_ok_at: "2026-11-19T20:00:00Z", last_error: `${WARN} timeout` }],
  snapshots: { first_on: "2026-11-19", latest_on: "2026-11-19", days_with_data_30d: 1, streak_days: 1, active_listings: 449, fresh_listings: 449, fresh_with_sold: 417, listings_by_category: { kitchen: 150, home: 150, fashion: 149 } },
  scores: { latest_on: null, scored_latest: 0, tiers_latest: {}, confidence_latest: {}, products_14d: 0, tier_changes_14d: 0 },
  trends: { latest_week: null, keywords_total: 0, keywords_fresh: 0 }, reviews: { total: 1, with_sentiment: 1, suspected_fake: 0 },
  ads: { last_on: "2026-11-18", checks_45d: 1 }, matching: { pending: 1 }, alerts: { unseen: 1, last_on: "2026-11-19" }, watchlist: 1,
};

const mock = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  const name = u.pathname.replace("/rest/v1/", "");
  res.setHeader("Content-Type", "application/json");
  if (name === "rpc/get_data_health") return res.end(JSON.stringify(HEALTH));
  if (name.startsWith("rpc/")) return res.end("null");
  const rows = T[name];
  if (!rows) { res.statusCode = 404; return res.end(JSON.stringify({ message: "PGRST205" })); }
  res.setHeader("Content-Range", `0-${Math.max(rows.length - 1, 0)}/${rows.length}`);
  res.end(JSON.stringify(rows));
});

const EMOJI = /[\p{Extended_Pictographic}\u2605\u2606\u2713\u2714\u2717\u2718\u2715\u2716\u26AA\u26AB\uFE0F]/u;
const PAGES = ["/", "/products/1", "/watchlist", "/alerts", "/ads", "/signals", "/matches", "/health"];
const MUST = { "/products/1": ["scorehead", "bar-top", "dist"], "/alerts": ["card unseen", "chip danger"], "/health": ["status ok", "check-top"], "/ads": ['class="cards"'], "/signals": ['class="cards"', "Infoneen", "air fryer", "infoneen.com", "formrow signals"], "/matches": ["pair", "evidence"] };

await new Promise((r) => mock.listen(0, r));
const mockPort = mock.address().port, port = 3457;
const env = { ...process.env, SUPABASE_URL: `http://127.0.0.1:${mockPort}`, SUPABASE_SERVICE_KEY: "k", DASHBOARD_PASSWORD: "pw", PORT: String(port) };
const next = spawn("npx", ["next", "start", "-p", String(port)], { cwd: new URL("../dashboard", import.meta.url).pathname, env, stdio: "ignore" });
let bad = 0;
try {
  for (let i = 0; i < 60; i++) { try { await fetch(`http://127.0.0.1:${port}/`); break; } catch { await new Promise((r) => setTimeout(r, 500)); } }
  const auth = "Basic " + Buffer.from("admin:pw").toString("base64");
  for (const p of PAGES) {
    const r = await fetch(`http://127.0.0.1:${port}${p}`, { headers: { Authorization: auth } });
    const html = await r.text();
    const problems = [];
    if (r.status !== 200) problems.push(`HTTP ${r.status}`);
    const m = html.match(EMOJI); if (m) problems.push(`ইমোজি: U+${m[0].codePointAt(0).toString(16)}`);
    for (const c of MUST[p] ?? []) if (!html.includes(c)) problems.push(`নেই: ${c}`);
    if (problems.length) bad++;
    console.log(`${problems.length ? "ফেল" : "ঠিক"}  ${p}  ${problems.join("; ")}`);
  }
} finally { next.kill(); mock.close(); }
process.exit(bad ? 1 : 0);
