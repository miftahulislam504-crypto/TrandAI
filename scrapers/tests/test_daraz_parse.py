"""Daraz পার্সারের টেস্ট।

সতর্কতা: ফিক্সচারগুলো কৃত্রিম, Daraz-এর পরিচিত গঠনের আন্দাজে লেখা (আসল রেসপন্স নয়)।
আসল রেসপন্সের গঠন Phase 1 স্মোক টেস্টে যাচাই হবে। গঠন আলাদা হলে parse.KEYS বদলাতে হবে।
"""
import json
import unittest

from scrapers.daraz import parse

LISTING_JSON = {
    "mainInfo": {"totalResults": "312", "pageSize": "40"},
    "mods": {"listItems": [
        {"itemId": "542322850", "name": "Wooden Mixer", "itemUrl": "//www.daraz.com.bd/products/wooden-mixer-i542322850-s1.html?search=1",
         "price": "65", "priceShow": "৳ 65", "originalPrice": "180", "ratingScore": "4.7857", "review": "28",
         "itemSoldCntShow": "1.2K sold", "sellerName": "KhelnaGhor", "brandName": "No Brand", "inStock": True,
         "categories": ["1", "2"]},
        {"nid": "999", "title": "Pan", "productUrl": "/products/pan-i999.html", "priceShow": "৳ 1,250",
         "ratingScore": "", "review": "", "itemSoldCntShow": ""},
        {"name": "no id and no url"},
    ]},
}

PRODUCT_HTML = """
<html><head><title>Dhal Ghutni/ Wooden Mixer | Daraz.com.bd</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Dhal Ghutni","brand":{"@type":"Brand","name":"Acme"},
"aggregateRating":{"@type":"AggregateRating","ratingValue":"4.6","ratingCount":"25"},"offers":{"@type":"Offer","price":"65"}}</script>
</head><body>
<div>Ratings 25</div><div>৳ 65</div><div>৳ 180 -64%</div>
<div>Positive Seller Ratings 90%</div><div>Ship on Time 100%</div><div>1.2K sold</div>
<script>var d = {"itemSoldCntShow":"300 sold","soldCount":5};</script>
</body></html>
"""

PRODUCT_HTML_TEXT_ONLY = """<html><head><title>Plain Item | Daraz.com.bd</title></head>
<body>Ratings ১২ ৳ 99 ৳ 150 Positive Seller Ratings 80%</body></html>"""

REVIEWS_JSON = {"model": {"items": [
    {"reviewRateId": 1, "rating": 5, "reviewContent": "খুব ভালো প্রোডাক্ট", "reviewTime": "08 Nov 2026", "buyerName": "Rahim"},
    {"reviewRateId": 2, "rating": 2, "reviewContent": "Not good, broke fast", "reviewTime": "2026-11-01", "buyerName": "Karim"},
    {"reviewRateId": 3, "rating": 9, "reviewContent": "invalid stars"},
], "paging": {"totalPages": "3", "totalItems": "41"}}}


class NumberTests(unittest.TestCase):
    def test_price(self):
        self.assertEqual(parse.parse_price("৳ 1,250"), 1250.0)
        self.assertEqual(parse.parse_price("Tk. 65.50"), 65.5)
        self.assertEqual(parse.parse_price("৯৯"), 99.0)
        self.assertIsNone(parse.parse_price(""))
        self.assertIsNone(parse.parse_price(None))

    def test_sold(self):
        self.assertEqual(parse.parse_sold("1.2K sold"), 1200)
        self.assertEqual(parse.parse_sold("10 sold"), 10)
        self.assertEqual(parse.parse_sold("2M sold"), 2_000_000)
        self.assertEqual(parse.parse_sold("১২ বিক্রি"), 12)
        self.assertEqual(parse.parse_sold(7), 7)
        self.assertIsNone(parse.parse_sold(""))

    def test_rating_bounds(self):
        self.assertEqual(parse.parse_rating("4.7857"), 4.786)
        self.assertIsNone(parse.parse_rating("7"))
        self.assertIsNone(parse.parse_rating(""))

    def test_url(self):
        u = parse.normalize_url("//www.daraz.com.bd/products/x-i123-s4.html?search=1#a")
        self.assertEqual(u, "https://www.daraz.com.bd/products/x-i123-s4.html")
        self.assertEqual(parse.item_id_from_url(u), "123")
        self.assertEqual(parse.normalize_url("/products/y-i9.html"), "https://www.daraz.com.bd/products/y-i9.html")
        self.assertIsNone(parse.item_id_from_url("https://www.daraz.com.bd/cat/"))


class ListingTests(unittest.TestCase):
    def test_items(self):
        raw = parse.find_listing_items(LISTING_JSON)
        items = [i for i in (parse.parse_listing_item(r) for r in raw) if i]
        self.assertEqual(len(raw), 3)
        self.assertEqual(len(items), 2)  # id-বিহীনটা বাদ
        a, b = items
        self.assertEqual(a["external_id"], "542322850")
        self.assertEqual(a["url"], "https://www.daraz.com.bd/products/wooden-mixer-i542322850-s1.html")
        self.assertEqual((a["price"], a["original_price"], a["rating_avg"]), (65.0, 180.0, 4.786))
        self.assertEqual((a["rating_count"], a["sold_count"], a["seller_name"], a["brand"]), (28, 1200, "KhelnaGhor", "No Brand"))
        self.assertIs(a["in_stock"], True)
        self.assertEqual(b["external_id"], "999")
        self.assertEqual(b["price"], 1250.0)
        self.assertIsNone(b["rating_avg"])
        self.assertIsNone(b["sold_count"])

    def test_meta(self):
        self.assertEqual(parse.listing_meta(LISTING_JSON), {"total_results": 312, "page_size": 40})

    def test_generic_list_fallback(self):
        obj = {"data": {"products": [{"itemId": "1", "name": "a"}, {"itemId": "2", "name": "b"}]}}
        self.assertEqual(len(parse.find_listing_items(obj)), 2)

    def test_page_data_extraction(self):
        html = "<script>window.pageData = " + json.dumps(LISTING_JSON) + ";</script><script>other()</script>"
        data = parse.extract_page_data(html)
        self.assertEqual(len(parse.find_listing_items(data)), 3)
        self.assertIsNone(parse.extract_page_data("<html>no data</html>"))
        self.assertIsNone(parse.extract_page_data("window.pageData = {broken: js, not: json};"))


class ProductTests(unittest.TestCase):
    def test_json_ld_wins(self):
        p = parse.parse_product_html(PRODUCT_HTML)
        self.assertEqual((p["title"], p["brand"]), ("Dhal Ghutni", "Acme"))
        self.assertEqual((p["rating_avg"], p["rating_count"], p["price"]), (4.6, 25, 65.0))
        self.assertEqual(p["found_by"]["rating_avg"], "json_ld")
        self.assertEqual(p["original_price"], 180.0)
        self.assertEqual((p["seller_positive_pct"], p["ship_on_time_pct"]), (90, 100))
        self.assertEqual(p["sold_count"], 300)  # inline JSON, টেক্সটের আগে
        self.assertTrue(p["found_by"]["sold_count"].startswith("inline_json"))

    def test_text_only_fallback(self):
        p = parse.parse_product_html(PRODUCT_HTML_TEXT_ONLY)
        self.assertEqual(p["title"], "Plain Item")
        self.assertEqual((p["rating_count"], p["price"], p["original_price"]), (12, 99.0, 150.0))
        self.assertEqual(p["seller_positive_pct"], 80)
        self.assertNotIn("rating_avg", p)
        self.assertEqual(p["found_by"]["price"], "text")


class ReviewTests(unittest.TestCase):
    def test_reviews(self):
        revs, meta = parse.parse_reviews_payload(REVIEWS_JSON)
        self.assertEqual(len(revs), 2)  # ৯ স্টারেরটা বাদ
        a, b = revs
        self.assertEqual((a["external_review_id"], a["stars"], a["lang"], a["reviewed_at"]), ("1", 5, "bn", "2026-11-08"))
        self.assertEqual((b["lang"], b["reviewed_at"]), ("en", "2026-11-01"))
        self.assertEqual(len(a["reviewer_hash"]), 16)
        self.assertNotIn("Rahim", json.dumps(revs))  # নাম সেভ হয় না
        self.assertEqual(meta, {"total_pages": 3, "total_items": 41})

    def test_empty(self):
        self.assertEqual(parse.parse_reviews_payload({"model": {"items": []}})[0], [])
        self.assertEqual(parse.parse_reviews_payload("junk")[0], [])


class ImageTests(unittest.TestCase):
    def test_listing_item_image_variants(self):
        raw = {"itemId": "1", "name": "x", "price": "10", "image": "//static-01.daraz.com.bd/p/a.jpg"}
        self.assertEqual(parse.parse_listing_item(raw)["image_url"], "https://static-01.daraz.com.bd/p/a.jpg")
        raw = {"itemId": "2", "name": "x", "thumbs": [{"image": "https://cdn/x.jpg"}, {"image": "https://cdn/y.jpg"}]}
        self.assertEqual(parse.parse_listing_item(raw)["image_url"], "https://cdn/x.jpg")
        raw = {"itemId": "3", "name": "x", "imageUrl": ["https://cdn/z.jpg"]}
        self.assertEqual(parse.parse_listing_item(raw)["image_url"], "https://cdn/z.jpg")

    def test_missing_or_bad_image_is_none(self):
        for bad in (None, "", "data:image/png;base64,AAAA", "javascript:alert(1)", "/relative/a.jpg", 5, "https://x/" + "a" * 1200):
            raw = {"itemId": "9", "name": "x", "image": bad}
            self.assertIsNone(parse.parse_listing_item(raw)["image_url"], repr(bad)[:40])

    def test_product_page_og_image_either_attribute_order(self):
        a = '<html><head><meta property="og:image" content="https://cdn/p/a.jpg?x=1&amp;y=2"></head></html>'
        b = '<html><head><meta content="//cdn/p/b.jpg" property="og:image"></head></html>'
        self.assertEqual(parse.parse_product_html(a)["image_url"], "https://cdn/p/a.jpg?x=1&y=2")
        self.assertEqual(parse.parse_product_html(b)["image_url"], "https://cdn/p/b.jpg")
        self.assertNotIn("image_url", parse.parse_product_html("<html></html>"))

    def test_json_ld_image_beats_og(self):
        html = ('<script type="application/ld+json">{"@type":"Product","name":"N","image":["https://cdn/ld.jpg"]}</script>'
                '<meta property="og:image" content="https://cdn/og.jpg">')
        out = parse.parse_product_html(html)
        self.assertEqual((out["image_url"], out["found_by"]["image_url"]), ("https://cdn/ld.jpg", "json_ld"))


if __name__ == "__main__":
    unittest.main()
