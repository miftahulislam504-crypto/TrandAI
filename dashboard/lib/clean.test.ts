import test from "node:test";
import assert from "node:assert/strict";
import { stripEmoji } from "./clean.ts";

test("ইমোজি ও ভ্যারিয়েশন সিলেক্টর সরে, লেখা থাকে", () => {
  assert.equal(stripEmoji("\u26A0\uFE0F নকল/ডুপ্লিকেট অভিযোগ: ৩টায়"), "নকল/ডুপ্লিকেট অভিযোগ: ৩টায়");
  assert.equal(stripEmoji("\u{1F4E2} বিজ্ঞাপনে ভিড়: 'air fryer'"), "বিজ্ঞাপনে ভিড়: 'air fryer'");
  assert.equal(stripEmoji("A: \u26AB\u{1F7E2} ঠিক"), "A: ঠিক");
});

test("জোড়া ইমোজি (ZWJ, স্কিন টোন, পতাকা, কিক্যাপ) সরে", () => {
  assert.equal(stripEmoji("\u{1F468}\u200D\u{1F469}\u200D\u{1F467} পরিবার"), "পরিবার");
  assert.equal(stripEmoji("\u{1F44D}\u{1F3FD} ভালো"), "ভালো");
  assert.equal(stripEmoji("\u{1F1E7}\u{1F1E9} দেশ"), "দেশ");
  assert.equal(stripEmoji("1\uFE0F\u20E3 প্রথম"), " প্রথম".trim());
});

test("বাংলা র-ফলা (ZWJ) ও সাধারণ চিহ্ন অক্ষত", () => {
  const s = "র\u200D্যাংক: ৳১,২০০ \u2192 ৳১,৫০০ (+২৫%)";
  assert.equal(stripEmoji(s), s);
});

test("ফাঁকা, null ও undefined সামলায়", () => {
  assert.equal(stripEmoji(null), "");
  assert.equal(stripEmoji(undefined), "");
  assert.equal(stripEmoji("  \u{1F514}  "), "");
});
