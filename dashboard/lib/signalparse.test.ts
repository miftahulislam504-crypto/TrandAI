import test from "node:test";
import assert from "node:assert/strict";
import { buildSignal, parseLink, parseValue, sourceLabel, SIGNAL_SOURCES } from "./signalparse.ts";

const TODAY = "2026-11-22";

test("parseValue: সাধারণ সংখ্যা, হাজারের কমা, বাংলা অঙ্ক, ~, %", () => {
  assert.equal(parseValue("120"), 120);
  assert.equal(parseValue("1,200"), 1200);
  assert.equal(parseValue("১২০"), 120);
  assert.equal(parseValue("~500"), 500);
  assert.equal(parseValue("25%"), 25);
  assert.equal(parseValue("-3.5"), -3.5);
  assert.equal(parseValue("0"), 0);
});

test("parseValue: K ও M সংক্ষেপ", () => {
  assert.equal(parseValue("12K"), 12000);
  assert.equal(parseValue("12k"), 12000);
  assert.equal(parseValue("1.2M"), 1200000);
  assert.equal(parseValue("৫K"), 5000);
});

test("parseValue: ফাঁকা বা - হলে null, ভুল হলে Error", () => {
  assert.equal(parseValue(""), null);
  assert.equal(parseValue("  "), null);
  assert.equal(parseValue("-"), null);
  assert.throws(() => parseValue("abc"), /সংখ্যা/);
  assert.throws(() => parseValue("12 লাখ"), /সংখ্যা/);
  assert.throws(() => parseValue("1.2.3"), /সংখ্যা/);
  assert.throws(() => parseValue("9999999999999"), /বড়/);
});

test("parseLink: শুধু http/https", () => {
  assert.equal(parseLink(""), null);
  assert.equal(parseLink(" https://trends.pinterest.com/x?y=1 "), "https://trends.pinterest.com/x?y=1");
  assert.equal(parseLink("http://example.com"), "http://example.com");
  assert.throws(() => parseLink("javascript:alert(1)"), /http/);
  assert.throws(() => parseLink("ftp://example.com"), /http/);
  assert.throws(() => parseLink("example.com"), /http/);
  assert.throws(() => parseLink("https://exa mple.com"), /http/);
  assert.throws(() => parseLink("https://example.com/" + "a".repeat(500)), /৫০০/);
});

test("buildSignal: পূর্ণ ও ন্যূনতম ইনপুট", () => {
  const r = buildSignal({ source: "infoneen", keyword: "  air   fryer ", value: "12K", unit: " সার্চ/মাস ", link: "https://infoneen.com/x", note: "সিজন ঈদের আগে", observed: "3 Nov 2026" }, TODAY);
  assert.deepEqual(r, { ok: true, input: { source: "infoneen", keyword: "air fryer", value: 12000, unit: "সার্চ/মাস", link: "https://infoneen.com/x", note: "সিজন ঈদের আগে", observed_on: "2026-11-03" } });
  const min = buildSignal({ source: "youtube", keyword: "পাঞ্জাবি", value: "৫০০" }, TODAY);
  assert.deepEqual(min, { ok: true, input: { source: "youtube", keyword: "পাঞ্জাবি", value: 500, unit: null, link: null, note: null, observed_on: null } });
});

test("buildSignal: শুধু নোট দিলেও চলে (যেমন TikTok-এ ট্রেন্ডিং দেখা গেছে)", () => {
  const r = buildSignal({ source: "tiktok_creative_center", keyword: "smart watch", note: "টপ ১০ হ্যাশট্যাগে" }, TODAY);
  assert.ok(r.ok && r.input.value === null && r.input.note === "টপ ১০ হ্যাশট্যাগে");
});

test("buildSignal: ভুল ইনপুটে বাংলা কারণ", () => {
  const err = (f: Parameters<typeof buildSignal>[0]) => {
    const r = buildSignal(f, TODAY);
    assert.ok(!r.ok);
    return (r as { ok: false; error: string }).error;
  };
  assert.match(err({ source: "", keyword: "x", value: "1" }), /সোর্স/);
  assert.match(err({ source: "meta_ads", keyword: "x", value: "1" }), /সোর্স/); // Meta Ads /ads দিয়ে যায়
  assert.match(err({ source: "other", keyword: "   ", value: "1" }), /শব্দ/);
  assert.match(err({ source: "other", keyword: "a".repeat(81), value: "1" }), /শব্দ/);
  assert.match(err({ source: "other", keyword: "x" }), /মান বা নোট/);
  assert.match(err({ source: "other", keyword: "x", value: "abc" }), /সংখ্যা/);
  assert.match(err({ source: "other", keyword: "x", value: "1", unit: "u".repeat(25) }), /একক/);
  assert.match(err({ source: "other", keyword: "x", value: "1", link: "javascript:alert(1)" }), /লিংক/);
  assert.match(err({ source: "other", keyword: "x", value: "1", observed: "2026-12-01" }), /ভবিষ্যতের/);
  assert.match(err({ source: "other", keyword: "x", value: "1", observed: "kal" }), /তারিখ/);
});

test("নোট ২০০ অক্ষরে কাটা হয়, সোর্স-তালিকা SQL-এর সাথে মেলে", () => {
  const r = buildSignal({ source: "other", keyword: "x", note: "n".repeat(300) }, TODAY);
  assert.ok(r.ok && r.input.note?.length === 200);
  assert.deepEqual(SIGNAL_SOURCES.map((s) => s.slug), ["tiktok_creative_center", "pinterest_trends", "infoneen", "similarweb", "youtube", "other"]);
  assert.equal(sourceLabel("pinterest_trends"), "Pinterest Trends");
  assert.equal(sourceLabel("unknown_x"), "unknown_x");
});
