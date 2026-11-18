// চালান: cd dashboard && npm test   (Node 22+, কোনো বাড়তি প্যাকেজ লাগে না)
import test from "node:test";
import assert from "node:assert/strict";
import { buildCheck, normDigits, parseBulk, parseCount, parseDate, parseLine } from "./adsparse.ts";

const TODAY = "2026-11-17";

test("বাংলা অঙ্ক ইংরেজিতে", () => {
  assert.equal(normDigits("১২৩৪৫৬৭৮৯০"), "1234567890");
  assert.equal(parseCount("১,২০০", "x"), 1200);
});

test("সংখ্যার নানা রূপ", () => {
  assert.equal(parseCount("~120", "x"), 120);
  assert.equal(parseCount("50+", "x"), 50);
  assert.equal(parseCount(" 0 ", "x"), 0);
  assert.equal(parseCount("", "x"), null);
  assert.equal(parseCount("-", "x"), null);
  assert.throws(() => parseCount("-3", "x"), /পূর্ণসংখ্যা/);
  assert.throws(() => parseCount("3.5", "x"), /পূর্ণসংখ্যা/);
  assert.throws(() => parseCount("abc", "x"), /পূর্ণসংখ্যা/);
  assert.throws(() => parseCount("123456789", "x"), /পূর্ণসংখ্যা/);
});

test("তারিখের নানা রূপ", () => {
  assert.equal(parseDate("2026-10-03", TODAY), "2026-10-03");
  assert.equal(parseDate("3/10/2026", TODAY), "2026-10-03");       // দিন/মাস/বছর
  assert.equal(parseDate("03-10-2026", TODAY), "2026-10-03");
  assert.equal(parseDate("৩/১০/২০২৬", TODAY), "2026-10-03");
  assert.equal(parseDate("3 Oct 2026", TODAY), "2026-10-03");
  assert.equal(parseDate("3 October 2026", TODAY), "2026-10-03");
  assert.equal(parseDate("Oct 3, 2026", TODAY), "2026-10-03");
  assert.equal(parseDate("", TODAY), null);
  assert.equal(parseDate("-", TODAY), null);
  assert.equal(parseDate(TODAY, TODAY), TODAY);
});

test("ভুল তারিখ", () => {
  assert.throws(() => parseDate("2026-02-31", TODAY), /বোঝা যায়নি/);
  assert.throws(() => parseDate("31/13/2026", TODAY), /বোঝা যায়নি/);
  assert.throws(() => parseDate("someday", TODAY), /বোঝা যায়নি/);
  assert.throws(() => parseDate("2026-11-18", TODAY), /ভবিষ্যতের/);
  assert.throws(() => parseDate("2017-12-31", TODAY), /২০১৮/);
});

test("এক লাইন: | দিয়ে পুরো", () => {
  const r = parseLine("air fryer | 120 | 14 | 3 Sep 2026 | 30", TODAY);
  assert.deepEqual(r, { ok: true, input: { keyword: "air fryer", active_ads: 120, advertisers: 14, oldest_start: "2026-09-03", new_30d: 30 } });
});

test("এক লাইন: শুধু শব্দ ও সংখ্যা, কমা দিয়ে", () => {
  const r = parseLine("পাঞ্জাবি, ৪০", TODAY);
  assert.deepEqual(r, { ok: true, input: { keyword: "পাঞ্জাবি", active_ads: 40, advertisers: null, oldest_start: null, new_30d: null } });
});

test("এক লাইন: মাঝের ঘর বাদ দিতে '-'", () => {
  const r = parseLine("saree | 25 | - | - | 5", TODAY);
  assert.deepEqual(r, { ok: true, input: { keyword: "saree", active_ads: 25, advertisers: null, oldest_start: null, new_30d: 5 } });
});

test("ট্যাব দিয়ে (স্প্রেডশিট থেকে পেস্ট)", () => {
  const r = parseLine("saree\t25\t3", TODAY);
  assert.equal(r.ok && r.input.advertisers, 3);
});

test("যুক্তিসংগত নয় এমন সংখ্যা আটকায়", () => {
  const bad = (l: string) => { const r = parseLine(l, TODAY); assert.equal(r.ok, false, l); return r.ok ? "" : r.error; };
  assert.match(bad("x | 10 | 11"), /বিজ্ঞাপনদাতা সংখ্যা/);
  assert.match(bad("x | 10 | 3 | - | 11"), /নতুন বিজ্ঞাপন/);
  assert.match(bad("x | 0 | 2"), /বিজ্ঞাপনদাতা সংখ্যা/);   // ০ বিজ্ঞাপনে ২ জন হতে পারে না
  assert.match(bad("x | 0 | - | 3/10/2026"), /০ হলে/);
  assert.match(bad("x"), /কমপক্ষে/);
  assert.match(bad("x | 1 | 1 | - | 1 | 1"), /সর্বোচ্চ ৫/);
  assert.match(bad(" | 5"), /১–৮০/);
  assert.match(bad("x | -"), /দিতে হবে/);
  assert.match(bad("a".repeat(81) + " | 5"), /১–৮০/);
});

test("০ বিজ্ঞাপন বৈধ", () => {
  const r = parseLine("rare thing | 0", TODAY);
  assert.deepEqual(r, { ok: true, input: { keyword: "rare thing", active_ads: 0, advertisers: null, oldest_start: null, new_30d: null } });
});

test("buildCheck: শব্দের বাড়তি ফাঁকা ঠিক হয়", () => {
  const r = buildCheck({ keyword: "  air    fryer  ", ads: "5" }, TODAY);
  assert.equal(r.ok && r.input.keyword, "air fryer");
});

test("বাল্ক: ভালো ও খারাপ লাইন আলাদা, লাইন নম্বরসহ, মন্তব্য ও ফাঁকা বাদ", () => {
  const text = ["# মন্তব্য", "air fryer | 120 | 14", "", "bad line", "saree | 25 | 30", "pan | 5 | 2 | 2026-02-30"].join("\n");
  const r = parseBulk(text, TODAY);
  assert.equal(r.rows.length, 1);                       // saree-র advertisers 30 > 25 বাদ
  assert.deepEqual(r.rows.map((x) => x.line), [2]);
  assert.deepEqual(r.errors.map((e) => e.line), [4, 5, 6]);
});

test("বাল্ক: লাইন সীমা", () => {
  const text = Array.from({ length: 70 }, (_, i) => `kw${i} | ${i + 1}`).join("\n");
  const r = parseBulk(text, TODAY);
  assert.equal(r.rows.length, 60);
  assert.equal(r.errors.length, 1);
  assert.match(r.errors[0].message, /সর্বোচ্চ 60/);
});

test("বাল্ক: Windows লাইন-শেষ", () => {
  const r = parseBulk("a | 1\r\nb | 2\r\n", TODAY);
  assert.equal(r.rows.length, 2);
});
