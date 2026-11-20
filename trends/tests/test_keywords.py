import unittest

from trends.config import load_config
from trends.keywords import build_terms, match_entry, tokens

CFG = load_config()
E = CFG["entries"]


def m(title, cat=None):
    r = match_entry(title, cat, E)
    return r.entry_id if r else None


class TokenTests(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(tokens("Men's T-Shirt (Cotton)"), ["men", "s", "t", "shirt", "cotton"])
        self.assertEqual(tokens("Women Sandals"), ["women", "sandal"])
        self.assertEqual(tokens("Glass"), ["glass"])            # "ss"-এ শেষ হলে ছাঁটা হয় না
        self.assertEqual(tokens("পাঞ্জাবি ছেলেদের"), ["পাঞ্জাবি", "ছেলেদের"])
        self.assertEqual(tokens(""), [])
        self.assertEqual(tokens(None), [])


class MatchTests(unittest.TestCase):
    def test_english_and_bengali_titles(self):
        self.assertEqual(m("Men Premium Cotton Panjabi - Eid Collection"), "panjabi")
        self.assertEqual(m("ছেলেদের পাঞ্জাবি ঈদ কালেকশন"), "panjabi")
        self.assertEqual(m("Digital Air Fryer 5L"), "air-fryer")
        self.assertEqual(m("Stainless Steel Water Bottle 1L"), "water-bottle")
        self.assertEqual(m("Non-stick Frying Pan 28cm"), "non-stick-pan")

    def test_plural_and_spacing_variants(self):
        self.assertEqual(m("Ladies Sandals Flat"), "sandal")
        self.assertEqual(m("Cotton BedSheet King Size"), "bed-sheet")
        self.assertEqual(m("Round Neck TShirt"), "t-shirt")

    def test_more_specific_phrase_wins(self):
        # "kitchen organizer" (২ শব্দ) বনাম "rack": কিচেন র‍্যাক phrase ("kitchen rack") ২ শব্দ
        self.assertEqual(m("Kitchen Rack Organizer Shelf"), "kitchen-organizer")   # সমান নির্দিষ্টতা: তালিকায় আগেরটা
        self.assertEqual(m("Knife Set with Stand"), "knife-set")

    def test_bigger_phrase_beats_smaller(self):
        # "pillow" (১ শব্দ) বনাম "bed sheet" (২ শব্দ)
        self.assertEqual(m("Pillow Cover and Bed Sheet Combo"), "bed-sheet")

    def test_same_category_breaks_ties(self):
        entries = [{"id": "a", "category": "home", "q": "x", "match": ["mug"]},
                   {"id": "b", "category": "kitchen", "q": "y", "match": ["mug"]}]
        self.assertEqual(match_entry("ceramic mug", "kitchen", entries).entry_id, "b")
        self.assertEqual(match_entry("ceramic mug", "home", entries).entry_id, "a")
        self.assertEqual(match_entry("ceramic mug", None, entries).entry_id, "a")   # শেষ ভরসা: তালিকার ক্রম

    def test_no_match(self):
        self.assertIsNone(m("random thing"))
        self.assertIsNone(m(""))
        self.assertIsNone(m(None))

    def test_partial_phrase_does_not_match(self):
        self.assertIsNone(m("Air Cooler"))                      # "air fryer"-এর অর্ধেক

    def test_every_entry_matches_its_own_query(self):
        for e in E:
            got = match_entry(e["q"], e["category"], E)
            self.assertIsNotNone(got, e["id"])
            self.assertEqual(got.entry_id, e["id"], f"{e['q']!r} নিজের entry পায়নি")


class TermTests(unittest.TestCase):
    def test_build_terms_default(self):
        t = build_terms(CFG)
        self.assertEqual(len(t), 2 * len(E))                 # প্রতি entry-র ইংরেজি + বাংলা
        self.assertEqual(t[0], {"keyword": "panjabi", "lang": "en", "group_key": "panjabi", "category": "fashion"})
        self.assertEqual(t[1]["lang"], "bn")
        self.assertEqual({x["group_key"] for x in t}, {e["id"] for e in E})

    def test_enabled_categories_skip_disabled(self):
        t = build_terms(CFG, enabled_categories={"fashion", "home", "kitchen"})
        self.assertEqual(len(t), 78)                        # আগের ৩ ক্যাটাগরির ৩৯ entry × ২
        self.assertEqual({x["category"] for x in t}, {"fashion", "home", "kitchen"})
        self.assertEqual(build_terms(CFG, enabled_categories=set()), [])

    def test_named_category_overrides_enabled_filter(self):
        """বন্ধ ক্যাটাগরি নাম ধরে চালালে (স্মোক টেস্ট) শব্দ আসে।"""
        t = build_terms(CFG, only_category="islamic", enabled_categories={"fashion"})
        self.assertEqual({x["category"] for x in t}, {"islamic"})
        self.assertEqual(len(t), 10)                        # ৫ entry × ২

    def test_new_category_titles_match(self):
        self.assertEqual(m("Premium Muslin Prayer Mat Janamaz"), "prayer-mat")
        self.assertEqual(m("Fast Charger 20W Type-C"), "mobile-charger")
        self.assertEqual(m("Yoga Mat 6mm Non Slip"), "yoga-mat")
        self.assertEqual(m("Smart Watch Series 8"), "smart-watch")      # "watch"-এর চেয়ে নির্দিষ্ট
        self.assertEqual(m("Baby Diaper Pant Size L"), "baby-diaper")
        self.assertIsNone(m("Air Cooler"))

    def test_english_only_and_category_filter(self):
        t = build_terms(CFG, only_category="home", use_bengali=False)
        self.assertEqual(len(t), 12)
        self.assertEqual({x["category"] for x in t}, {"home"})
        self.assertEqual({x["lang"] for x in t}, {"en"})


if __name__ == "__main__":
    unittest.main()
