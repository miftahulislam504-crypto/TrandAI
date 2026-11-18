import test from "node:test";
import assert from "node:assert/strict";
import { cell, toCsv } from "./csv.ts";

test("সাধারণ মান", () => {
  assert.equal(cell("abc"), "abc");
  assert.equal(cell(12), "12");
  assert.equal(cell(-5), "-5");           // সংখ্যা ঋণাত্মক হলেও আসল সংখ্যা
  assert.equal(cell(true), "true");
  assert.equal(cell(null), "");
  assert.equal(cell(undefined), "");
  assert.equal(cell(NaN), "");
  assert.equal(cell(Infinity), "");
});

test("কমা, উদ্ধৃতি, নতুন লাইন ঘেরা হয়", () => {
  assert.equal(cell("a,b"), '"a,b"');
  assert.equal(cell('say "hi"'), '"say ""hi"""');
  assert.equal(cell("l1\nl2"), '"l1\nl2"');
});

test("সূত্র-ইনজেকশন আটকানো", () => {
  assert.equal(cell("=SUM(A1)"), "'=SUM(A1)");
  assert.equal(cell("+1"), "'+1");
  assert.equal(cell("-1+1"), "'-1+1");
  assert.equal(cell("@cmd"), "'@cmd");
  assert.equal(cell("\tx"), "'\tx");
  assert.equal(cell('=HYPERLINK("http://x","y")'), `"'=HYPERLINK(""http://x"",""y"")"`);
  assert.equal(cell("a=b"), "a=b");        // মাঝে = ঠিক আছে
});

test("বাংলা অক্ষর অক্ষত", () => {
  assert.equal(cell("পাঞ্জাবি ৳৫০০"), "পাঞ্জাবি ৳৫০০");
});

test("toCsv: BOM, CRLF, শিরোনাম", () => {
  const out = toCsv(["নাম", "দাম"], [["A", 10], ["B,C", null]]);
  assert.ok(out.startsWith("\uFEFFনাম,দাম\r\n"));
  assert.equal(out.slice(1), "নাম,দাম\r\nA,10\r\n\"B,C\",\r\n");
});
