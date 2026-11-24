"""Othoba/Bagdoom কার্ড-পার্সার (অডিটের আসল হোমপেজ-নমুনা থেকে কাটা ফিক্সচারে) ও adapter probe-এর সহায়ক।"""
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scrapers.audit import adapter_probe as probe
from scrapers.bagdoom.parse import parse_cards as bagdoom_cards
from scrapers.othoba.parse import money, parse_cards as othoba_cards

FX = Path(__file__).parent / "fixtures"
OTHOBA = (FX / "othoba_home_cards.html").read_text(encoding="utf-8")
BAGDOOM = (FX / "bagdoom_home_cards.html").read_text(encoding="utf-8")
ITEM_KEYS = {"brand", "category_ids", "external_id", "image_url", "in_stock", "original_price", "price", "rating_avg",
             "rating_count", "review_count", "seller_name", "sold_count", "title", "url"}


class OthobaTests(unittest.TestCase):
    def setUp(self):
        self.items = {i["external_id"]: i for i in othoba_cards(OTHOBA)}

    def test_cards_found_with_pipeline_item_shape(self):
        self.assertGreaterEqual(len(self.items), 5)
        for it in self.items.values():
            self.assertEqual(set(it), ITEM_KEYS)
            self.assertTrue(it["url"].startswith("https://www.othoba.com/"))
            self.assertGreater(it["price"], 0)
            self.assertIsNone(it["sold_count"])          # সাইটে সোল্ড নেই

    def test_discounted_card_with_reviews(self):
        c = self.items["818728"]
        self.assertEqual((c["title"], c["price"], c["original_price"], c["review_count"]), ("Cargo Box 30L (Lid Assorted)", 604.0, 800.0, 5))
        self.assertEqual(c["rating_avg"], 4.4)           # তারার চওড়া 88% ÷ 20
        self.assertTrue(c["image_url"].startswith("https://images.othoba.com/"))

    def test_list_card_with_zero_reviews_has_no_rating(self):
        c = self.items["886216"]
        self.assertEqual((c["price"], c["original_price"], c["review_count"], c["rating_avg"]), (2805.0, 3300.0, 0, None))

    def test_ids_unique_and_empty_input(self):
        ids = [i["external_id"] for i in othoba_cards(OTHOBA)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(othoba_cards(""), [])
        self.assertEqual(othoba_cards("<div class=\"product\"><h4 class=product-name><a href=/x>No price</a></h4></div>"), [])

    def test_money(self):
        self.assertEqual(money("Tk 2,805"), 2805.0)
        self.assertEqual(money("৳427.50"), 427.5)
        self.assertEqual(money("৳১,২৩৪"), 1234.0)
        self.assertIsNone(money("Free"))
        self.assertIsNone(money(None))


class BagdoomTests(unittest.TestCase):
    def setUp(self):
        self.items = {i["external_id"]: i for i in bagdoom_cards(BAGDOOM)}

    def test_cards(self):
        self.assertGreaterEqual(len(self.items), 3)
        for it in self.items.values():
            self.assertEqual(set(it), ITEM_KEYS)
            self.assertTrue(it["url"].startswith("https://www.bagdoom.com/product/"))
            self.assertTrue(it["image_url"])
            self.assertIsNone(it["rating_avg"])           # হোমপেজ-কার্ডে রেটিং/সোল্ড নেই

    def test_prices_and_bengali_title(self):
        bbq = self.items["instant-bbq-instzant-bbq-gril"]
        self.assertEqual((bbq["price"], bbq["original_price"]), (427.5, 450.0))
        self.assertIn("ইন্সট্যান্ট", bbq["title"])
        intel = self.items["intel-core-i3-12100-12th-gen-alder-lake-processor-tray"]
        self.assertEqual((intel["price"], intel["original_price"]), (9300.0, None))

    def test_empty(self):
        self.assertEqual(bagdoom_cards(""), [])


class ProbeHelperTests(unittest.TestCase):
    def test_jsonld_and_next_chunks(self):
        html = ('<script type="application/ld+json">{"@type":"Product","name":"X"}</script>'
                '<script type="application/ld+json">not json</script>'
                '<script>self.__next_f.push([1,"abc {\\"price\\":250,\\"discountedPrice\\":200} xyz"])</script>')
        ld = probe.extract_jsonld(html)
        self.assertEqual(ld[0]["name"], "X")
        self.assertIn("_unparsed", ld[1])
        ch = probe.next_chunks(html, '"price"')
        self.assertEqual(len(ch), 1)
        self.assertIn('"discountedPrice":200', ch[0])
        self.assertEqual(probe.next_chunks(html, "nothing-here"), [])

    def test_pagination_sitemap_title_around(self):
        h = '<title> A  B </title><a href="/c?page=2">2</a><a href=/c?pagenumber=3>3</a><a href="/c?page=2">dup</a>'
        self.assertEqual(probe.pagination_links(h, "page"), ["/c?page=2", "/c?pagenumber=3"])
        self.assertEqual(probe.title_of(h), "A B")
        self.assertEqual(probe.sitemap_urls("<urlset><url><loc>https://a/1</loc></url><url><loc> https://a/2 </loc></url></urlset>"), ["https://a/1", "https://a/2"])
        self.assertEqual(len(probe.around("xxNEEDLEyyNEEDLEzz", "NEEDLE", 2, 5, 2)), 2)


class R:
    def __init__(self, url, text="", status=200):
        self.url, self.text, self.status_code, self.content = url, text, status, text.encode()


class FakeClient:
    """আসল সাইট নয়: রুট ধরে কাছাকাছি-আসল পেজ ফেরত দেয় (Othoba/Bagdoom ফিক্সচার, Cartup সাইটম্যাপ)।"""
    def __init__(self):
        self.seen = []

    def get(self, url, params=None, headers=None):
        self.seen.append(url)
        if "othoba.com" in url and "pagenumber=2" in url:
            return R(url, OTHOBA.replace("818728", "999999"))
        if "othoba.com" in url:
            return R(url, "<title>Kitchen</title>" + OTHOBA)
        if "bagdoom.com/category" in url:
            return R(url, "<title>Cat</title>" + BAGDOOM + '<a href="/category/x?page=2">2</a>')
        if "bagdoom.com/product" in url or "othoba.com" in url:
            return R(url, "<title>P</title>৳100")
        if url.endswith("sitemap.xml"):
            return R(url, "<sitemapindex><sitemap><loc>https://www.cartup.com/sitemap-product-all.xml.gz</loc></sitemap>"
                          "<sitemap><loc>https://www.cartup.com/sitemap-category-all.xml.gz</loc></sitemap></sitemapindex>")
        return R(url, "<title>Cartup</title><script type=\"application/ld+json\">{\"@type\":\"Product\"}</script>")

    def get_bytes(self, url, max_bytes=0, headers=None):
        urls = "".join(f"<url><loc>https://cartup.com/product/p{i}</loc></url>" for i in range(1200))
        return gzip.compress(f"<urlset>{urls}</urlset>".encode())


class ProbeRunTests(unittest.TestCase):
    def test_full_run_offline(self):
        with tempfile.TemporaryDirectory() as d:
            rep = probe.run(FakeClient(), Path(d))
            self.assertGreaterEqual(rep["requests"], 15)
            ot = rep["othoba"]["listings"]["/kitchen-dining-4"]
            self.assertGreaterEqual(ot[0]["parsed_items"], 5)
            self.assertTrue(ot[1]["page2_differs_from_page1"])
            self.assertEqual(rep["othoba"]["product"]["status"], 200)
            self.assertTrue(rep["bagdoom"]["listings"]["/category/groceries"][0]["pagination"])
            self.assertEqual(rep["cartup"]["product_sitemap"]["urls_in_first_3MB"], 1200)
            self.assertEqual(len(rep["cartup"]["products"]), 3)
            self.assertEqual(len(rep["cartup"]["products"][0]["jsonld"]), 1)
            self.assertTrue((Path(d) / "adapter-probe.md").exists())
            self.assertTrue(any((Path(d) / "adapter-probe").iterdir()))
            json.loads((Path(d) / "adapter-probe.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
