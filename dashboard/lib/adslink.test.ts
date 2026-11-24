// /ads-এর "Ads Library খুলুন" ফর্ম: সাধারণ GET ফর্ম (JS ছাড়া), Meta-র সাইটে যায়, নতুন ট্যাবে, শর্তের ধরন ঠিক রাখে।
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const PAGE = readFileSync(join(ROOT, "app/ads/page.tsx"), "utf-8");

test("Ads Library ফর্ম: GET, নতুন ট্যাব, Bangladesh + সক্রিয়, শব্দের ঘর আবশ্যক", () => {
  const m = PAGE.match(/<form action="https:\/\/www\.facebook\.com\/ads\/library\/" method="get" target="_blank"[^>]*>([\s\S]*?)<\/form>/);
  assert.ok(m, "Ads Library GET ফর্ম থাকতে হবে");
  const body = m![1];
  for (const [k, v] of [["active_status", "active"], ["ad_type", "all"], ["country", "BD"], ["media_type", "all"], ["search_type", "keyword_unordered"]]) {
    assert.ok(new RegExp(`<input type="hidden" name="${k}" value="${v}"`).test(body), `${k}=${v} লুকানো ঘর লাগবে`);
  }
  assert.ok(/<input name="q" type="text" required/.test(body), "শব্দের ঘর (q) আবশ্যক হতে হবে");
});

test("স্বয়ংক্রিয় সংগ্রহ নয়: পেজে Meta থেকে ডেটা আনার কোড নেই (শুধু ব্যবহারকারীর নিজের ট্যাবে খোলা)", () => {
  assert.ok(!/fetch\(\s*["'`]https:\/\/(www\.)?facebook\.com/.test(PAGE));
  assert.ok(!/graph\.facebook\.com/.test(PAGE));
});
