import test from "node:test";
import assert from "node:assert/strict";
import { ageDays, evaluateHealth, type Raw } from "./health.ts";

const base = (): Raw => ({
  today: "2026-11-20",
  sources: [{ slug: "daraz", name: "Daraz", runs_14d: 14, ok_14d: 14, partial_14d: 0, failed_14d: 0, unfinished_14d: 0,
    items_ok_14d: 6000, items_failed_14d: 0, last_run_at: "2026-11-19T20:30:00+00:00", last_ok_at: "2026-11-19T20:30:00+00:00", last_error: null }],
  snapshots: { first_on: "2026-11-01", latest_on: "2026-11-20", days_with_data_30d: 20, streak_days: 20, active_listings: 450,
    fresh_listings: 440, fresh_with_sold: 400, listings_by_category: { fashion: 170 } },
  scores: { latest_on: "2026-11-20", scored_latest: 450, tiers_latest: { best: 40, mid: 300, dont: 110 }, confidence_latest: { high: 400, low: 50 },
    products_14d: 450, tier_changes_14d: 90 },
  trends: { latest_week: "2026-11-16", keywords_total: 78, keywords_fresh: 70 },
  reviews: { total: 1000, with_sentiment: 500, suspected_fake: 12 },
  ads: { last_on: "2026-11-10", checks_45d: 10 },
  matching: { pending: 3 },
  alerts: { unseen: 2, last_on: "2026-11-20" },
  watchlist: 5,
});
const find = (r: Raw, label: string) => evaluateHealth(r).checks.find((c) => c.label.includes(label))!;

test("ageDays", () => {
  assert.equal(ageDays("2026-11-20", "2026-11-20"), 0);
  assert.equal(ageDays("2026-11-20", "2026-11-18"), 2);
  assert.equal(ageDays("2026-03-01", "2026-02-27"), 2);     // মাস পেরোনো
  assert.equal(ageDays("2026-11-20", null), null);
});

test("সব ঠিক থাকলে overall ok", () => {
  assert.equal(evaluateHealth(base()).overall, "ok");
});

test("রান সফলতার সীমা: ৯৫ ok, ৮০ warn, নিচে fail", () => {
  const r = base();
  r.sources[0] = { ...r.sources[0], runs_14d: 20, ok_14d: 19 };           // ৯৫%
  assert.equal(find(r, "সফল রান").status, "ok");
  r.sources[0] = { ...r.sources[0], ok_14d: 16 };                          // ৮০%
  assert.equal(find(r, "সফল রান").status, "warn");
  r.sources[0] = { ...r.sources[0], ok_14d: 15 };                          // ৭৫%
  assert.equal(find(r, "সফল রান").status, "fail");
});

test("শেষ সফল রান: আজ ok, ২ দিন warn, ৪ দিন fail, নেই fail", () => {
  const r = base();
  const at = (d: string | null) => { r.sources[0] = { ...r.sources[0], last_ok_at: d }; return find(r, "শেষ সফল রান").status; };
  assert.equal(at("2026-11-20T01:00:00+00:00"), "ok");
  assert.equal(at("2026-11-18T01:00:00+00:00"), "warn");
  assert.equal(at("2026-11-16T01:00:00+00:00"), "fail");
  assert.equal(at(null), "fail");
});

test("কোনো সোর্সে রান না থাকলে na, overall fail নয়", () => {
  const r = base();
  r.sources = [];
  assert.equal(find(r, "কোনো রান নেই").status, "na");
  assert.notEqual(evaluateHealth(r).overall, "fail");
});

test("স্ন্যাপশট পুরনো হলে fail", () => {
  const r = base();
  r.snapshots.latest_on = "2026-11-15";
  assert.equal(find(r, "সর্বশেষ স্ন্যাপশট").status, "fail");
  assert.equal(evaluateHealth(r).overall, "fail");
  r.snapshots.latest_on = null;
  assert.equal(find(r, "সর্বশেষ স্ন্যাপশট").status, "fail");
});

test("টানা দিন ৭-এর নিচে warn ও ব্যাখ্যা", () => {
  const r = base();
  r.snapshots.streak_days = 3;
  const c = find(r, "টানা দিন");
  assert.equal(c.status, "warn");
  assert.match(c.hint ?? "", /১৪ দিনের ইতিহাস/);
  r.snapshots.streak_days = 0;
  assert.equal(find(r, "টানা দিন").status, "na");
});

test("fresh ও sold কভারেজ", () => {
  const r = base();
  r.snapshots.fresh_listings = 300;                    // ৬৭% < ৭০
  assert.equal(find(r, "আজ-গতকালের").status, "fail");
  r.snapshots.fresh_listings = 450; r.snapshots.fresh_with_sold = 200;   // ৪৪% < ৫০
  assert.equal(find(r, "sold_count").status, "fail");
  r.snapshots.active_listings = 0; r.snapshots.fresh_listings = 0; r.snapshots.fresh_with_sold = 0;
  assert.equal(find(r, "আজ-গতকালের").status, "na");   // ০ দিয়ে ভাগ নয়
});

test("flip rate: ০.৫ পর্যন্ত ok, বেশি warn, ১-এর বেশি fail", () => {
  const r = base();
  r.scores.tier_changes_14d = 225; assert.equal(find(r, "ট্যাগ-বদল").status, "ok");     // ০.৫
  r.scores.tier_changes_14d = 226; assert.equal(find(r, "ট্যাগ-বদল").status, "warn");
  r.scores.tier_changes_14d = 460; assert.equal(find(r, "ট্যাগ-বদল").status, "fail");
  r.scores.products_14d = 0; assert.equal(find(r, "ট্যাগ-বদল").status, "na");
});

test("Trends: ডেটা না আসা na + কারণের ইঙ্গিত, পুরনো হলে fail", () => {
  const r = base();
  r.trends = { latest_week: null, keywords_total: 0, keywords_fresh: 0 };
  const c = find(r, "সর্বশেষ সপ্তাহ");
  assert.equal(c.status, "na");
  assert.match(c.hint ?? "", /৪২৯/);
  r.trends = { latest_week: "2026-10-12", keywords_total: 78, keywords_fresh: 0 };
  assert.equal(find(r, "সর্বশেষ সপ্তাহ").status, "fail");
  assert.equal(find(r, "টাটকা").status, "fail");
});

test("ঐচ্ছিক টেবিল না থাকলে (null) সারি বাদ", () => {
  const r = base();
  r.ads = null; r.matching = null;
  const labels = evaluateHealth(r).checks.map((c) => c.label);
  assert.ok(!labels.some((l) => l.includes("Ads Library")));
  assert.ok(!labels.some((l) => l.includes("ম্যাচিং")));
});

test("পুরনো Ads চেক warn", () => {
  const r = base();
  r.ads = { last_on: "2026-09-01", checks_45d: 0 };
  assert.equal(find(r, "Ads Library").status, "warn");
});

test("ব্যর্থ রানের ত্রুটি hint-এ ছোট করে দেখায়", () => {
  const r = base();
  r.sources[0] = { ...r.sources[0], runs_14d: 10, ok_14d: 2, failed_14d: 8, last_error: "x".repeat(500) };
  const c = find(r, "সফল রান");
  assert.equal(c.status, "fail");
  assert.ok((c.hint ?? "").length < 200);
});
