"""probe.py-এর অফলাইন টেস্ট। চালান: python -m unittest scrapers/audit/test_probe.py -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe  # noqa: E402

ROBOTS = """
User-agent: *
Disallow: /catalog/
Allow: /catalog/?q=
Disallow: /*?ajax=
Disallow: /cart$

User-agent: badbot
Disallow: /
"""

HTML = """
<html><head><title>Test &amp; Product | Shop</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"X",
 "aggregateRating":{"@type":"AggregateRating","ratingValue":"4.5","reviewCount":"12"},
 "offers":{"@type":"Offer","price":"65"}}
</script>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"product":{"id":1},"reviews":[]}}}
</script>
<script>var d = {"itemSoldCntShow":"10 sold","ratingScore":"4.8","soldOut":false};</script>
</head><body><div>Ratings 25</div><div>৳ 65</div><span>1.2K Sold</span></body></html>
"""


class RobotsTests(unittest.TestCase):
    def setUp(self):
        self.groups = probe.parse_robots(ROBOTS)

    def test_plain_path_allowed(self):
        self.assertTrue(probe.robots_allowed(self.groups, "/products/x.html"))

    def test_disallow_prefix(self):
        self.assertFalse(probe.robots_allowed(self.groups, "/catalog/?page=2"))

    def test_longer_allow_wins(self):
        self.assertTrue(probe.robots_allowed(self.groups, "/catalog/?q=abc"))

    def test_wildcard_disallow(self):
        self.assertFalse(probe.robots_allowed(self.groups, "/catalog/?ajax=true&q=1"))

    def test_end_anchor(self):
        self.assertFalse(probe.robots_allowed(self.groups, "/cart"))
        self.assertTrue(probe.robots_allowed(self.groups, "/cart/items"))

    def test_specific_agent_group(self):
        self.assertFalse(probe.robots_allowed(self.groups, "/anything", ua_token="badbot"))

    def test_empty_disallow_means_allow(self):
        g = probe.parse_robots("User-agent: *\nDisallow:\n")
        self.assertTrue(probe.robots_allowed(g, "/x"))

    def test_decision_by_status(self):
        self.assertEqual(probe.robots_decision({"status": 404, "groups": None}, "https://a/x"), "allowed")
        self.assertEqual(probe.robots_decision({"status": 500, "groups": None}, "https://a/x"), "unknown")
        self.assertEqual(probe.robots_decision({"status": None, "groups": None}, "https://a/x"), "unknown")
        ok = {"status": 200, "groups": self.groups}
        self.assertEqual(probe.robots_decision(ok, "https://a/catalog/?page=2"), "disallowed")
        self.assertEqual(probe.robots_decision(ok, "https://a/products/x"), "allowed")


class AnalyzeTests(unittest.TestCase):
    def test_html_signals(self):
        r = probe.analyze("text/html", HTML)
        self.assertEqual(r["kind"], "html")
        self.assertEqual(r["title"], "Test & Product | Shop")
        self.assertIn("__NEXT_DATA__", r["state_markers"])
        self.assertTrue(r["json_ld"][0]["has_aggregateRating"])
        self.assertEqual(r["next_data"]["page_props_keys"], ["product", "reviews"])
        self.assertIn("itemSoldCntShow", r["keys"]["sold"])
        self.assertNotIn("soldOut", r["keys"]["sold"])
        self.assertIn("ratingScore", r["keys"]["rating"])
        self.assertEqual(r["visible"]["rating_count_text"], "Ratings 25")
        self.assertTrue(r["visible"]["price_text"].startswith("৳"))
        self.assertIn("Sold", r["visible"]["sold_text"])

    def test_escaped_json_keys(self):
        text = r'<script>x = "{\"soldCount\":5,\"reviewCount\":2}"</script>'
        self.assertEqual(probe.find_keys(text, "sold"), ["soldCount"])
        self.assertEqual(probe.find_keys(text, "review"), ["reviewCount"])

    def test_json_summary(self):
        body = '{"mods":{"listItems":[{"name":"a","price":"1","ratingScore":"4","itemSoldCntShow":"3 sold"},' \
               '{"name":"b","price":"2"}]}}'
        r = probe.analyze("application/json", body)
        self.assertEqual(r["kind"], "json")
        self.assertEqual(r["json"]["item_list_path"], "$.mods.listItems")
        self.assertEqual(r["json"]["item_count"], 2)
        self.assertEqual(r["json"]["item_key_hits"]["sold"], ["itemSoldCntShow"])

    def test_json_without_content_type(self):
        r = probe.analyze("text/plain", '{"a": 1}')
        self.assertEqual(r["kind"], "json")

    def test_block_detection(self):
        self.assertEqual(probe.detect_block(403, "ok"), ["http_403"])
        self.assertIn("captcha", probe.detect_block(200, "<div>Please solve the CAPTCHA</div>"))
        self.assertEqual(probe.detect_block(200, "all good"), [])


class OriginTests(unittest.TestCase):
    def test_origin_of_separates_hosts(self):
        self.assertEqual(probe.origin_of("https://my.daraz.com.bd/pdp/review/getReviewList?itemId=1"), "https://my.daraz.com.bd")
        self.assertEqual(probe.origin_of("https://www.daraz.com.bd/x/"), "https://www.daraz.com.bd")
        self.assertNotEqual(probe.origin_of("https://my.daraz.com.bd/a"), probe.origin_of("https://www.daraz.com.bd/a"))


if __name__ == "__main__":
    unittest.main()
