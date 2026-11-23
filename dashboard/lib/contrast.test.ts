// অ্যাক্সেসিবিলিটি (Phase 12): লেখার রঙ ও পটভূমির কনট্রাস্ট WCAG AA (≥ 4.5:1) এবং ফোকাস রিং আছে কি না।
// রঙের মান `app/globals.css`-এর টোকেন থেকে পড়া হয়, তাই টোকেন বদলালে এই টেস্ট নিজে ধরবে।
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const CSS = readFileSync(join(ROOT, "app/globals.css"), "utf-8");

function token(name: string): string {
  const m = CSS.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`));
  assert.ok(m, `--${name} টোকেন globals.css-এ হেক্স রঙে থাকতে হবে`);
  return m![1];
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const WHITE = "#ffffff";
// (লেখার রং, পটভূমি, কোথায় ব্যবহার হয়)
const TEXT_PAIRS: [string, string, string][] = [
  [token("ink"), token("bg"), "সাধারণ লেখা"],
  [token("ink-2"), token("bg"), "দ্বিতীয় স্তরের লেখা, ব্যাজ, চিপ"],
  [token("muted"), token("bg"), "ছোট/হালকা লেখা সাদা পটভূমিতে"],
  [token("muted"), token("subtle"), "হালকা লেখা `.card.seen`, `.msg`, `.notice`-এর ধূসর পটভূমিতে"],
  [token("danger"), token("bg"), "সতর্কতা (নকল-অভিযোগ, ব্যর্থতা)"],
  [token("danger"), token("subtle"), "সতর্কতা ধূসর পটভূমিতে"],
  [WHITE, token("ink"), "Best ট্যাগ, বাটন, বর্তমান পেজ"],
  [WHITE, "#262626", "বাটনের hover"],
  [token("ink-2"), "#ececec", "Don't ট্যাগ"],
  [token("muted"), "#ececec", "হালকা লেখা `.badge.dont`-এর পটভূমিতে গেলেও"],
  ["#bdbdbd", token("ink"), "কালো স্ট্যাট-টাইলের ছোট লেখা"],
];

test("লেখার কনট্রাস্ট ≥ 4.5:1 (WCAG AA)", () => {
  const low = TEXT_PAIRS
    .map(([fg, bg, where]) => ({ fg, bg, where, ratio: contrast(fg, bg) }))
    .filter((p) => p.ratio < 4.5)
    .map((p) => `${p.where}: ${p.fg} on ${p.bg} = ${p.ratio.toFixed(2)}`);
  assert.deepEqual(low, []);
});

test("কনট্রাস্ট হিসাবের নিজের সঠিকতা (কালো-সাদা ২১:১, একই রং ১:১)", () => {
  assert.ok(Math.abs(contrast("#000000", "#ffffff") - 21) < 1e-9);
  assert.ok(Math.abs(contrast("#767676", "#767676") - 1) < 1e-9);
});

test("কীবোর্ড ফোকাস রিং আছে: :focus-visible-এ ≥ 2px আউটলাইন, রং পটভূমির সাথে ≥ 3:1", () => {
  const m = CSS.match(/:focus-visible\s*\{([^}]*)\}/);
  assert.ok(m, ":focus-visible নিয়ম লাগবে");
  const px = m![1].match(/outline:\s*(\d+)px\s+solid\s+var\(--ink\)/);
  assert.ok(px && Number(px[1]) >= 2, "outline কমপক্ষে 2px solid var(--ink) হতে হবে");
  assert.ok(contrast(token("ink"), token("bg")) >= 3);
});

test("ফর্ম ঘরে `outline: none` থাকলে ফোকাসে বর্ডার কালো হতে হবে (ফোকাস চিহ্ন হারায় না)", () => {
  const m = CSS.match(/input:focus,\s*select:focus,\s*textarea:focus\s*\{([^}]*)\}/);
  assert.ok(m, "ইনপুট ফোকাস নিয়ম লাগবে");
  if (/outline:\s*none/.test(m![1])) {
    assert.ok(/border-color:\s*var\(--ink\)/.test(m![1]), "outline বন্ধ হলে border-color: var(--ink) লাগবে");
    assert.ok(contrast(token("ink"), token("line-strong")) >= 3, "ফোকাসের বর্ডার আগের বর্ডার থেকে স্পষ্ট আলাদা হতে হবে");
  }
});

test("ডার্ক মোড বা শুধু-রঙে-অর্থ: ট্যাগে লেখা সবসময় থাকে (রং ছাড়াও অর্থ বোঝা যায়)", () => {
  // Best/Mid/Don't ভরাট/বর্ডার/ধূসর দিয়ে আলাদা, আর লেখা TSX-এ আছে
  const tier = readFileSync(join(ROOT, "lib/tier.ts"), "utf-8");
  assert.ok(/Best/.test(tier) && /Mid/.test(tier) && /Don/.test(tier));
  assert.ok(/\.badge\.best[^}]*background:\s*var\(--ink\)/.test(CSS));
  assert.ok(/\.badge\.mid[^}]*border-color:\s*var\(--ink\)/.test(CSS));
  assert.ok(/\.badge\.dont[^}]*background:\s*#ececec/.test(CSS));
});
