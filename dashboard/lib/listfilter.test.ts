import test from "node:test";
import assert from "node:assert/strict";
import { listParams, parseListQuery } from "./listfilter.ts";

test("ডিফল্ট", () => {
  assert.deepEqual(parseListQuery({}), { sort: "score", tier: "", q: "", category: "", page: 1 });
});

test("অবৈধ মান বাদ", () => {
  const q = parseListQuery({ sort: "drop table", tier: "gold", category: "a b;c", page: "-4" });
  assert.deepEqual(q, { sort: "score", tier: "", q: "", category: "", page: 1 });
  assert.equal(parseListQuery({ page: "abc" }).page, 1);
  assert.equal(parseListQuery({ page: "3" }).page, 3);
});

test("সার্চ শব্দ থেকে PostgREST-এর বিশেষ চিহ্ন সরে", () => {
  assert.equal(parseListQuery({ q: "  a*b,c(d)  " }).q, "a b c d");
  assert.equal(parseListQuery({ q: "x".repeat(200) }).q.length, 60);
});

test("পরামিতি তৈরি", () => {
  const p = listParams(parseListQuery({ sort: "price", tier: "best?", category: "kitchen", q: "fry" }), "id", 30, 60);
  assert.equal(p.order, "price.asc.nullslast");
  assert.equal(p["reasons->>provisional_tier"], "eq.best");
  assert.equal(p.tier, undefined);
  assert.equal(p.category, "eq.kitchen");
  assert.equal(p.title_raw, "ilike.*fry*");
  assert.equal(p.offset, "60");
  assert.equal(listParams(parseListQuery({ tier: "dont" }), "id", 1, 0).tier, "eq.dont");
});
