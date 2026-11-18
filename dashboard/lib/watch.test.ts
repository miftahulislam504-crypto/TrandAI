import test from "node:test";
import assert from "node:assert/strict";
import { inList, pickPerCanonical } from "./watch.ts";

test("বেশি বিক্রির listing বাছে, সমান হলে ছোট id", () => {
  const m = pickPerCanonical([
    { id: 5, canonical_product_id: 1, sold_count: 10 },
    { id: 3, canonical_product_id: 1, sold_count: 50 },
    { id: 9, canonical_product_id: 1, sold_count: 50 },
    { id: 7, canonical_product_id: 2, sold_count: null },
    { id: 6, canonical_product_id: 2, sold_count: null },
    { id: 8, canonical_product_id: null, sold_count: 99 },
  ]);
  assert.equal(m.get(1)!.id, 3);
  assert.equal(m.get(2)!.id, 6);
  assert.equal(m.size, 2);
});

test("sold_count null-ও না-থাকা listing-কে হারায় না", () => {
  const m = pickPerCanonical([{ id: 1, canonical_product_id: 4, sold_count: null }, { id: 2, canonical_product_id: 4, sold_count: 0 }]);
  assert.equal(m.get(4)!.id, 2);                 // ০ বিক্রি, null (অজানা)-এর চেয়ে বেশি তথ্য
});

test("inList", () => assert.equal(inList([1, 2, 3]), "in.(1,2,3)"));
