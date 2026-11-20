// ড্যাশবোর্ডের কোডে ইমোজি বা ইমোজি-সদৃশ চিহ্ন থাকতে পারবে না (Phase 12 নিয়ম)।
// Phase 12 শেষ: সব পেজ রিডিজাইন-করা, তাই PENDING ফাঁকা। নতুন ফাইলে ইমোজি বা অজানা CSS ভ্যারিয়েবল ঢুকলে টেস্ট ফেল করবে।
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const PENDING = new Set<string>([]);
// Extended_Pictographic (সব ইমোজি) + যেসব চিহ্ন ফোনে ইমোজি হয়ে দেখায় + ভ্যারিয়েশন সিলেক্টর/জয়নার
const EMOJI = /[\p{Extended_Pictographic}\u2605\u2606\u2713\u2714\u2717\u2718\u2715\u2716\u26AA\u26AB\u25B2\u25BC\uFE0F\u200D]/u;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx?|css)$/.test(name) && !/\.test\./.test(name)) out.push(p);
  }
  return out;
}

test("ড্যাশবোর্ডের রিডিজাইন-করা ফাইলে কোনো ইমোজি নেই", () => {
  const bad: string[] = [];
  for (const f of [...walk(join(ROOT, "app")), ...walk(join(ROOT, "lib"))]) {
    const rel = relative(ROOT, f).split(sep).join("/");
    if (PENDING.has(rel)) continue;
    const m = readFileSync(f, "utf-8").match(EMOJI);
    if (m) bad.push(`${rel}: ${m[0]}`);
  }
  assert.deepEqual(bad, []);
});

test("PENDING-এর প্রতিটা ফাইল আসলেই আছে (মুছে-যাওয়া নাম থাকলে তালিকা পরিষ্কার করুন)", () => {
  for (const rel of PENDING) assert.ok(statSync(join(ROOT, rel)).isFile(), rel);
});

test("ডার্ক মোড নেই", () => {
  const css = readFileSync(join(ROOT, "app/globals.css"), "utf-8");
  assert.ok(!/prefers-color-scheme:\s*dark/.test(css));
  assert.match(css, /color-scheme:\s*light/);
});

// var(--x) ব্যবহার হলে globals.css-এ --x ঠিকঠাক থাকতে হবে (আগে --accent ছাড়া পড়ে ছিল)
test("ব্যবহৃত প্রতিটা CSS ভ্যারিয়েবল globals.css-এ আছে", () => {
  const css = readFileSync(join(ROOT, "app/globals.css"), "utf-8");
  const defined = new Set([...css.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
  const missing: string[] = [];
  for (const f of walk(join(ROOT, "app"))) {
    for (const m of readFileSync(f, "utf-8").matchAll(/var\((--[a-z0-9-]+)/g)) {
      if (!defined.has(m[1])) missing.push(`${relative(ROOT, f).split(sep).join("/")}: ${m[1]}`);
    }
  }
  assert.deepEqual(missing, []);
});
