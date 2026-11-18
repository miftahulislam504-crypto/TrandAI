// Data Health: get_data_health() SQL ফাংশনের কাঁচা সংখ্যা থেকে ভালো/সতর্ক/খারাপের বিচার।
// সীমাগুলো অনুমান-ভিত্তিক (Phase 1 লক্ষ্য "সফলতা ≥ ৯৫%" ও টানা ৭ দিন ছাড়া); আসল চালানোর পর বদলান।
export type Status = "ok" | "warn" | "fail" | "na";
export type Check = { group: string; label: string; status: Status; value: string; hint?: string };

type Src = {
  slug: string; name: string; runs_14d: number; ok_14d: number; partial_14d: number; failed_14d: number;
  unfinished_14d: number; items_ok_14d: number; items_failed_14d: number; last_run_at: string | null;
  last_ok_at: string | null; last_error: string | null;
};
export type Raw = {
  today: string;
  sources: Src[];
  snapshots: { first_on: string | null; latest_on: string | null; days_with_data_30d: number; streak_days: number;
    active_listings: number; fresh_listings: number; fresh_with_sold: number; listings_by_category: Record<string, number> };
  scores: { latest_on: string | null; scored_latest: number; tiers_latest: Record<string, number>;
    confidence_latest: Record<string, number>; products_14d: number; tier_changes_14d: number };
  trends: { latest_week: string | null; keywords_total: number; keywords_fresh: number };
  reviews: { total: number; with_sentiment: number; suspected_fake: number };
  ads: { last_on: string | null; checks_45d: number } | null;
  matching: { pending: number } | null;
  alerts: { unseen: number; last_on: string | null };
  watchlist: number;
};

export const TH = {
  runSuccessOk: 95, runSuccessWarn: 80,
  lastOkWarnDays: 2, lastOkFailDays: 4,
  dataAgeWarnDays: 2, dataAgeFailDays: 3,
  freshOk: 90, freshWarn: 70,
  soldOk: 80, soldWarn: 50,
  streakGoal: 7,
  flipWarn: 0.5, flipFail: 1,
  trendsWarnDays: 14, trendsFailDays: 28,
  trendsKwOk: 70, trendsKwWarn: 40,
  adsStaleDays: 45,
};

const DAY = 86400000;
const toDay = (s: string) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
export const ageDays = (today: string, d: string | null): number | null => (d ? Math.round((toDay(today) - toDay(d)) / DAY) : null);
const pct = (a: number, b: number): number | null => (b > 0 ? Math.round((100 * a) / b) : null);
const fmt = (n: number | null, suffix = "%") => (n === null ? "–" : `${n}${suffix}`);

function worst(...s: Status[]): Status {
  return s.includes("fail") ? "fail" : s.includes("warn") ? "warn" : s.every((x) => x === "na") ? "na" : "ok";
}
const high = (v: number | null, ok: number, warn: number): Status => (v === null ? "na" : v >= ok ? "ok" : v >= warn ? "warn" : "fail");

export function evaluateHealth(r: Raw): { checks: Check[]; overall: Status } {
  const c: Check[] = [];
  const t = r.today;

  // ---- সোর্স রান
  if (r.sources.length === 0) c.push({ group: "স্ক্র্যাপ", label: "কোনো রান নেই", status: "na", value: "–", hint: "Daraz Daily বা Smoke Test এখনও চলেনি" });
  for (const s of r.sources) {
    const ok = pct(s.ok_14d, s.runs_14d);
    const rate: Status = high(ok, TH.runSuccessOk, TH.runSuccessWarn);
    c.push({ group: "স্ক্র্যাপ", label: `${s.name}: সফল রান (১৪ দিন)`, status: rate,
      value: `${fmt(ok)} (${s.ok_14d}/${s.runs_14d}; আংশিক ${s.partial_14d}, ব্যর্থ ${s.failed_14d}${s.unfinished_14d ? `, শেষ হয়নি ${s.unfinished_14d}` : ""})`,
      hint: s.last_error ? `সর্বশেষ ত্রুটি: ${s.last_error.slice(0, 160)}` : undefined });
    const age = ageDays(t, s.last_ok_at ? s.last_ok_at.slice(0, 10) : null);
    c.push({ group: "স্ক্র্যাপ", label: `${s.name}: শেষ সফল রান`, status: age === null ? "fail" : age >= TH.lastOkFailDays ? "fail" : age >= TH.lastOkWarnDays ? "warn" : "ok",
      value: age === null ? "১৪ দিনে একটাও সফল নয়" : age === 0 ? "আজ" : `${age} দিন আগে` });
  }

  // ---- স্ন্যাপশট
  const sn = r.snapshots;
  const snapAge = ageDays(t, sn.latest_on);
  c.push({ group: "ডেটা", label: "সর্বশেষ স্ন্যাপশট", status: snapAge === null ? "fail" : snapAge >= TH.dataAgeFailDays ? "fail" : snapAge >= TH.dataAgeWarnDays ? "warn" : "ok",
    value: snapAge === null ? "কোনো স্ন্যাপশট নেই" : `${sn.latest_on} (${snapAge === 0 ? "আজ" : snapAge + " দিন আগে"})` });
  c.push({ group: "ডেটা", label: `টানা দিন (লক্ষ্য ${TH.streakGoal})`, status: sn.streak_days >= TH.streakGoal ? "ok" : sn.streak_days >= 1 ? "warn" : "na",
    value: `${sn.streak_days} দিন; শেষ ৩০ দিনে ${sn.days_with_data_30d} দিনে ডেটা`,
    hint: sn.streak_days < TH.streakGoal ? "স্কোরের বিক্রির গতি ১৪ দিনের ইতিহাস চায়, তাই এখনও বেশিরভাগ ট্যাগে '?' থাকবে" : undefined });
  const fresh = pct(sn.fresh_listings, sn.active_listings);
  c.push({ group: "ডেটা", label: "সক্রিয় listing-এ আজ-গতকালের ডেটা", status: high(fresh, TH.freshOk, TH.freshWarn),
    value: `${fmt(fresh)} (${sn.fresh_listings}/${sn.active_listings})`, hint: "কম হলে স্ক্র্যাপার সব listing ধরতে পারছে না" });
  const sold = pct(sn.fresh_with_sold, sn.fresh_listings);
  c.push({ group: "ডেটা", label: "বিক্রির সংখ্যা (sold_count) আছে", status: high(sold, TH.soldOk, TH.soldWarn),
    value: `${fmt(sold)} (${sn.fresh_with_sold}/${sn.fresh_listings})`, hint: "না থাকলে ডিমান্ড রিভিউ-বৃদ্ধি থেকে আন্দাজ হয়, কনফিডেন্স কমে" });

  // ---- স্কোর
  const sc = r.scores;
  const scAge = ageDays(t, sc.latest_on);
  c.push({ group: "স্কোর", label: "সর্বশেষ স্কোরিং", status: scAge === null ? "na" : scAge >= TH.dataAgeFailDays ? "fail" : scAge >= TH.dataAgeWarnDays ? "warn" : "ok",
    value: scAge === null ? "এখনও স্কোর হয়নি" : `${sc.latest_on}; ${sc.scored_latest}টা প্রোডাক্ট` });
  const flip = sc.products_14d > 0 ? sc.tier_changes_14d / sc.products_14d : null;   // বিচার অকাটা মানে, দেখানো গোল করে
  c.push({ group: "স্কোর", label: "ট্যাগ-বদল (প্রতি প্রোডাক্টে ১৪ দিনে)", status: flip === null ? "na" : flip > TH.flipFail ? "fail" : flip > TH.flipWarn ? "warn" : "ok",
    value: flip === null ? "–" : `${flip.toFixed(2)} (${sc.tier_changes_14d} বদল, ${sc.products_14d}টা প্রোডাক্ট)`, hint: "বেশি হলে tier_change_days বাড়ান" });
  const low = sc.confidence_latest["low"] ?? 0;
  const lowPct = pct(low, sc.scored_latest);
  c.push({ group: "স্কোর", label: "কম কনফিডেন্স", status: lowPct === null ? "na" : "ok", value: lowPct === null ? "–" : `${fmt(lowPct)} (${low}টা)`,
    hint: "শুধু তথ্য: প্রথম ২ সপ্তাহে বেশি থাকাই স্বাভাবিক" });

  // ---- Google Trends
  const tr = r.trends;
  const trAge = ageDays(t, tr.latest_week);
  const kw = pct(tr.keywords_fresh, tr.keywords_total);
  c.push({ group: "Google Trends", label: "সর্বশেষ সপ্তাহের ডেটা", status: trAge === null ? "na" : trAge >= TH.trendsFailDays ? "fail" : trAge >= TH.trendsWarnDays ? "warn" : "ok",
    value: trAge === null ? "এখনও ডেটা আসেনি" : `সপ্তাহ ${tr.latest_week} (${trAge} দিন আগে)`,
    hint: trAge === null ? "Trends Weekly চালু করেননি, বা Google ব্লক করছে (৪২৯)" : undefined });
  c.push({ group: "Google Trends", label: "টাটকা ডেটাসহ কীওয়ার্ড", status: tr.keywords_total === 0 ? "na" : high(kw, TH.trendsKwOk, TH.trendsKwWarn),
    value: tr.keywords_total === 0 ? "–" : `${fmt(kw)} (${tr.keywords_fresh}/${tr.keywords_total})` });

  // ---- রিভিউ, Ads, ম্যাচিং, অ্যালার্ট
  const sentiment = pct(r.reviews.with_sentiment, r.reviews.total);
  c.push({ group: "অন্যান্য", label: "রিভিউ", status: r.reviews.total === 0 ? "na" : "ok",
    value: `${r.reviews.total}টা; সেন্টিমেন্ট বিশ্লেষণ ${fmt(sentiment)}; সন্দেহজনক ${r.reviews.suspected_fake}টা` });
  if (r.ads) {
    const a = ageDays(t, r.ads.last_on);
    c.push({ group: "অন্যান্য", label: "Facebook Ads Library চেক", status: a === null ? "na" : a > TH.adsStaleDays ? "warn" : "ok",
      value: a === null ? "কোনো চেক নেই" : `শেষ ${r.ads.last_on} (${a} দিন আগে); ৪৫ দিনে ${r.ads.checks_45d}টা`,
      hint: a !== null && a > TH.adsStaleDays ? "পুরনো চেক স্কোরে ধরা হয় না" : undefined });
  }
  if (r.matching) c.push({ group: "অন্যান্য", label: "ম্যাচিং রিভিউ কিউ", status: "ok", value: `${r.matching.pending}টা অপেক্ষায়` });
  c.push({ group: "অন্যান্য", label: "ওয়াচলিস্ট ও অ্যালার্ট", status: "ok", value: `ওয়াচলিস্টে ${r.watchlist}টা; না-দেখা অ্যালার্ট ${r.alerts.unseen}টা` });

  return { checks: c, overall: worst(...c.map((x) => x.status)) };
}
