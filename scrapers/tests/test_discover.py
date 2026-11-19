import json
import unittest
from pathlib import Path

from scrapers.daraz.discover import propose, slug_of, summarize
from scrapers.run_discover import crawl

FIX = json.loads((Path(__file__).parent / "fixtures" / "daraz_category_ajax.json").read_text(encoding="utf-8"))


class FakeClient:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get_json(self, url, params=None):
        self.calls.append(url)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if slug in self.pages:
            return self.pages[slug]
        from scrapers.common.http import FetchError
        raise FetchError("404")


class DiscoverTests(unittest.TestCase):
    def test_slug_of(self):
        self.assertEqual(slug_of("/small-kitchen-appliances/"), "small-kitchen-appliances")
        self.assertEqual(slug_of("https://www.daraz.com.bd/home-appliances/"), "home-appliances")
        self.assertEqual(slug_of("https://www.daraz.com.bd"), None)
        self.assertEqual(slug_of("/kitchen-small-appliances"), "kitchen-small-appliances")

    def test_summarize_real_sample(self):
        s = summarize("small-kitchen-appliances", FIX)
        self.assertEqual(s["total_results"], 4080)
        self.assertEqual(s["items"], 6)
        self.assertGreaterEqual(s["sold_pct"], 80)
        self.assertEqual([b["slug"] for b in s["breadcrumb"]], ["home-appliances", "small-kitchen-appliances"])
        self.assertIn("blenders", [c["slug"] for c in s["children"]])
        self.assertEqual(s["title"], "Small Kitchen Appliances")

    def test_summarize_empty(self):
        self.assertIsNone(summarize("x", {"mods": {}}))
        self.assertIsNone(summarize("x", None))

    def test_crawl_follows_breadcrumb_and_children(self):
        client = FakeClient({"small-kitchen-appliances": FIX, "home-appliances": FIX, "blenders": FIX})
        found, log = crawl(client, {"start": ["small-kitchen-appliances", "nope"], "max_requests": 20})
        self.assertIn("home-appliances", found)       # ব্রেডক্রাম্ব থেকে
        self.assertIn("blenders", found)              # ফিল্টার থেকে
        self.assertTrue(any("✗ nope" in l for l in log))
        self.assertEqual(len(client.calls), len(set(client.calls)))   # একই slug দুবার নয়

    def test_crawl_respects_budget(self):
        client = FakeClient({"small-kitchen-appliances": FIX})
        crawl(client, {"start": ["small-kitchen-appliances"], "max_requests": 2})
        self.assertEqual(len(client.calls), 2)

    def test_propose_groups_and_threshold(self):
        found = {
            "blenders": {"title": "Blenders", "total_results": 900},
            "rice-cookers": {"title": "Rice Cookers", "total_results": 50},
            "womens-sarees": {"title": "Sarees", "total_results": 5000},
        }
        out = propose(found, {"kitchen": ["blender", "rice cooker"], "fashion": ["saree"]}, min_total=300)
        self.assertEqual([r["url"] for r in out["kitchen"]], ["https://www.daraz.com.bd/blenders/"])
        self.assertEqual(len(out["fashion"]), 1)


if __name__ == "__main__":
    unittest.main()
