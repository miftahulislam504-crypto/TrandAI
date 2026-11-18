"""DarazAdapter-এর টেস্ট: কৌশল ফলব্যাক, পেজিং, ত্রুটি। নকল ক্লায়েন্ট, নেটওয়ার্ক ছাড়া।"""
import json
import unittest

from scrapers.common.http import BlockedError, CircuitOpen, FetchError, RobotsDisallowed
from scrapers.daraz.adapter import DarazAdapter


def listing(ids):
    return {"mainInfo": {"totalResults": "99", "pageSize": "3"},
            "mods": {"listItems": [{"itemId": str(i), "name": f"n{i}", "price": "10", "itemUrl": f"/products/p-i{i}.html"} for i in ids]}}


class FakeResp:
    def __init__(self, text):
        self.text = text


class FakeClient:
    """script: {(kind, page): ফলাফল বা Exception}; kind = 'ajax' | 'html'"""

    def __init__(self, script):
        self.script, self.calls = script, []
        self.stats = {}

    def _run(self, kind, params):
        key = (kind, params["page"])
        self.calls.append(key)
        res = self.script.get(key, listing([]))
        if isinstance(res, Exception):
            raise res
        return res

    def get_json(self, url, params=None, headers=None):
        assert params.get("ajax") == "true"
        return self._run("ajax", params)

    def get(self, url, params=None, headers=None):
        if "getReviewList" in url or "/products/" in url:
            return FakeResp(self.script["product_html"])
        assert "ajax" not in params
        return FakeResp("<script>window.pageData = " + json.dumps(self._run("html", params)) + ";</script>")


SEED = {"type": "keyword", "q": "saree"}


class AdapterTests(unittest.TestCase):
    def test_ajax_works_and_is_sticky(self):
        c = FakeClient({("ajax", 1): listing([1, 2, 3]), ("ajax", 2): listing([4, 5, 6])})
        a = DarazAdapter(c)
        items, diag = a.discover(SEED, limit=10, max_pages=5)
        self.assertEqual([i["external_id"] for i in items], ["1", "2", "3", "4", "5", "6"])
        self.assertEqual(diag["strategy"], "ajax")
        self.assertEqual(diag["total_results"], 99)
        self.assertEqual(a.strategy_order, ["ajax"])
        self.assertNotIn(("html", 1), c.calls)  # সফল কৌশলের পর html চেষ্টাই হয়নি

    def test_falls_back_to_html_when_ajax_disallowed(self):
        c = FakeClient({("ajax", 1): RobotsDisallowed("x"), ("html", 1): listing([7, 8])})
        items, diag = DarazAdapter(c).discover(SEED, limit=10, max_pages=1)
        self.assertEqual([i["external_id"] for i in items], ["7", "8"])
        self.assertEqual(diag["strategy"], "html")
        self.assertTrue(any("robots" in n for n in diag["notes"]))

    def test_falls_back_when_ajax_blocked_or_empty(self):
        c = FakeClient({("ajax", 1): BlockedError("403"), ("html", 1): listing([1])})
        items, diag = DarazAdapter(c).discover(SEED, 5, 1)
        self.assertEqual(len(items), 1)
        c2 = FakeClient({("ajax", 1): listing([]), ("html", 1): listing([2])})
        items2, _ = DarazAdapter(c2).discover(SEED, 5, 1)
        self.assertEqual(items2[0]["external_id"], "2")

    def test_all_strategies_fail(self):
        c = FakeClient({("ajax", 1): FetchError("boom"), ("html", 1): RobotsDisallowed("y")})
        items, diag = DarazAdapter(c).discover(SEED, 5, 3)
        self.assertEqual(items, [])
        self.assertIsNone(diag["strategy"])
        self.assertEqual(len(diag["notes"]), 2)

    def test_circuit_open_propagates(self):
        c = FakeClient({("ajax", 1): CircuitOpen("stop")})
        with self.assertRaises(CircuitOpen):
            DarazAdapter(c).discover(SEED, 5, 3)

    def test_limit_and_no_new_items_stop(self):
        c = FakeClient({("ajax", 1): listing([1, 2, 3]), ("ajax", 2): listing([4, 5, 6]), ("ajax", 3): listing([7, 8, 9])})
        items, diag = DarazAdapter(c).discover(SEED, limit=4, max_pages=5)
        self.assertEqual(len(items), 4)
        self.assertEqual(diag["pages"], 2)
        same = FakeClient({("ajax", 1): listing([1, 2]), ("ajax", 2): listing([1, 2]), ("ajax", 3): listing([9])})
        items2, _ = DarazAdapter(same).discover(SEED, 50, 5)
        self.assertEqual(len(items2), 2)  # ২য় পেজে নতুন কিছু নেই বলে থেমেছে

    def test_listing_params(self):
        a = DarazAdapter(FakeClient({}), sort="popularity")
        url, params = a._listing_target({"type": "category", "url": "https://x.test/kitchen"}, 2, ajax=True)
        self.assertEqual(url, "https://x.test/kitchen/")
        self.assertEqual(params, {"ajax": "true", "page": 2, "sort": "popularity"})
        url, params = a._listing_target(SEED, 1, ajax=False)
        self.assertTrue(url.endswith("/catalog/"))
        self.assertEqual(params, {"q": "saree", "page": 1, "sort": "popularity"})

    def test_fetch_product_ids(self):
        c = FakeClient({"product_html": "<html><title>A | Daraz</title>Ratings 3 ৳ 50</html>"})
        p = DarazAdapter(c).fetch_product("https://www.daraz.com.bd/products/a-i555-s9.html?x=1")
        self.assertEqual((p["external_id"], p["price"], p["rating_count"]), ("555", 50.0, 3))
        self.assertEqual(p["url"], "https://www.daraz.com.bd/products/a-i555-s9.html")


if __name__ == "__main__":
    unittest.main()
