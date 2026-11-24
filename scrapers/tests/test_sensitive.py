import unittest
from datetime import date

from scoring import run_scoring
from scoring.config import load_config as load_scoring_config
from scrapers import run_daraz, sensitive

CFG = sensitive.load_rules()


def m(title, cat):
    return sensitive.match(title, cat, CFG)


class MatchTests(unittest.TestCase):
    def test_real_config_is_valid(self):
        self.assertTrue(CFG["enabled"])
        self.assertEqual({r["id"] for r in CFG["rules"]},
                         {"medicine", "supplement", "sexual-wellness", "infant-formula", "tobacco-alcohol", "skin-lightening"})

    def test_medicine(self):
        for t in ("Paracetamol 500mg Tablet", "Cough Syrup 100ml", "Omeprazole Capsules", "Napa Extra", "ডায়াবেটিসের ট্যাবলেট", "ওষুধ বক্স"):
            self.assertEqual(m(t, "health-wellness")["rule"], "medicine", t)
        self.assertEqual(m("Calcium 500 mg", "health-wellness")["rule"], "medicine")     # ডোজ regex

    def test_supplement_and_weight_loss(self):
        for t in ("Vitamin D3 Softgels", "Collagen Powder", "Fat Burner Slimming Tea", "ভিটামিন সি"):
            self.assertEqual(m(t, "health-wellness")["rule"], "supplement", t)

    def test_sexual_wellness_and_tobacco_apply_to_every_category(self):
        self.assertEqual(m("Ultra thin condom 12pcs", "electronics")["rule"], "sexual-wellness")
        self.assertEqual(m("Imported hookah shisha set", "gifts-lifestyle")["rule"], "tobacco-alcohol")
        self.assertEqual(m("সিগারেট কেস", "fashion")["rule"], "tobacco-alcohol")

    def test_infant_formula_and_skin_lightening(self):
        self.assertEqual(m("Aptamil Stage 1 Infant Formula 400g", "baby")["rule"], "infant-formula")
        self.assertEqual(m("Fairness Cream 50g", "beauty")["rule"], "skin-lightening")

    def test_allow_lists_cancel_false_positives(self):
        self.assertIsNone(m("Coffee Capsule Machine", "grocery"))
        self.assertIsNone(m("Vitamin C Serum 30ml", "beauty"))
        self.assertIsNone(m("Anti Dandruff Shampoo with Vitamin E", "beauty"))
        self.assertIsNone(m("Baby Feeding Bottle Sterilizer formula milk warmer", "baby"))
        self.assertIsNone(m("Tobacco Brown Leather Wallet", "bags-footwear"))

    def test_scope_limits_the_medicine_and_supplement_rules(self):
        self.assertIsNone(m("Samsung Galaxy Tab 10 inch Tablet", "electronics"))
        self.assertIsNone(m("Vitamin pack lunch box", "kitchen"))

    def test_whole_word_for_english_and_normal_products_pass(self):
        self.assertIsNone(m("Wooden tabletop organizer", "grocery"))
        for t in ("Pran Full Cream Milk Powder 500gm", "Fresh Fortified Soyabean Oil 5ltr", "Mr Noodles Ramen 85gm", "Panjabi Cotton Men"):
            self.assertIsNone(m(t, "grocery"), t)

    def test_empty_and_disabled(self):
        self.assertIsNone(m(None, "grocery"))
        self.assertIsNone(m("", "grocery"))
        off = {**CFG, "enabled": False}
        self.assertIsNone(sensitive.match("Paracetamol Tablet", "health-wellness", off))

    def test_split_and_summary(self):
        items = [{"title": "Paracetamol Tablet"}, {"title": "Air Fryer 6L"}, {"title": "Vitamin D3"}, {"title": None}]
        kept, dropped = sensitive.split(items, "health-wellness", CFG)
        self.assertEqual([i["title"] for i in kept], ["Air Fryer 6L", None])
        s = sensitive.summarize_dropped(dropped)
        self.assertEqual((s["count"], s["by_rule"]), (2, {"medicine": 1, "supplement": 1}))
        self.assertEqual(s["examples"][0]["title"], "Paracetamol Tablet")

    def test_config_validation(self):
        bad = [({"rules": [], "scope_categories": "x"}, "scope"),
               ({"rules": [{"id": "a", "label": "x", "phrases": ["p"]}, {"id": "a", "label": "y", "phrases": ["q"]}], "scope_categories": []}, "ডুপ্লিকেট"),
               ({"rules": [{"id": "a", "label": "x"}], "scope_categories": []}, "phrases"),
               ({"rules": [{"id": "a", "label": "x", "regex": ["("]}], "scope_categories": []}, "regex"),
               ({"rules": [{"id": "a", "label": "x", "phrases": ["p"], "categories": "some"}], "scope_categories": []}, "categories")]
        for cfg, word in bad:
            with self.assertRaisesRegex(sensitive.SensitiveConfigError, word):
                sensitive.validate(cfg)


class FakeAdapter:
    def __init__(self, found):
        self.found = found

    def discover(self, seed, limit, max_pages):
        return list(self.found), {"seed": seed, "notes": [], "pages": 1}


class IngestTests(unittest.TestCase):
    def _collect(self, found, slug="health-wellness"):
        daraz = {"settings": {"max_pages_per_seed": 1}, "seeds": {slug: [{"type": "category", "url": "https://x/"}]}}
        cats = {"categories": [{"slug": slug, "target_products": 50, "enabled": True}]}
        return run_daraz.collect(FakeAdapter(found), daraz, cats)

    def test_sensitive_items_do_not_enter_and_are_reported(self):
        found = [{"external_id": "1", "title": "Paracetamol Tablet"}, {"external_id": "2", "title": "Hand Sanitizer 500ml"}]
        by_cat, diags, errors, circuit = self._collect(found)
        self.assertEqual([i["external_id"] for i in by_cat["health-wellness"]], ["2"])
        self.assertEqual(errors, [])
        merged = run_daraz.merge_sensitive(diags)
        self.assertEqual((merged["count"], merged["by_rule"]), (1, {"medicine": 1}))

    def test_all_dropped_is_not_reported_as_no_items_error(self):
        _, _, errors, _ = self._collect([{"external_id": "1", "title": "Vitamin C 1000mg"}])
        self.assertEqual(errors, [])

    def test_run_markdown_lists_what_was_skipped(self):
        s = {"status": "ok", "run_id": 1, "date": "2026-11-23", "listings": 1, "snapshots": 1, "details": 0, "reviews": 0,
             "circuit_open": False, "coverage": {}, "notes": [], "errors": [],
             "sensitive": {"count": 2, "by_rule": {"medicine": 2}, "examples": [{"rule": "medicine", "hit": "tablet", "title": "X Tablet"}]}}
        md = run_daraz.run_markdown(s)
        self.assertIn("স্পর্শকাতর পণ্য বাদ (2টা)", md)
        self.assertIn("X Tablet", md)
        self.assertNotIn("স্পর্শকাতর", run_daraz.run_markdown({**s, "sensitive": {"count": 0, "by_rule": {}, "examples": []}}))


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def select(self, table, params=None, **kw):
        return list(self.rows.get(table, []))


class ScoringTests(unittest.TestCase):
    def test_existing_sensitive_listings_are_excluded_from_scoring(self):
        rows = {"listing_overview": [
            {"id": 1, "canonical_product_id": 10, "category": "health-wellness", "title_raw": "Paracetamol 500mg Tablet", "url": "u1", "seller_name": "s"},
            {"id": 2, "canonical_product_id": 11, "category": "kitchen", "title_raw": "Air Fryer 6L", "url": "u2", "seller_name": "s"},
            {"id": 3, "canonical_product_id": 12, "category": "grocery", "title_raw": "Pran Milk Powder", "url": "u3", "seller_name": "s"}]}
        run_scoring.fetch_products(FakeDB(rows), date(2026, 11, 23), load_scoring_config())
        ex = run_scoring.fetch_products.excluded
        self.assertEqual((ex["count"], ex["by_rule"]), (1, {"medicine": 1}))
        self.assertEqual(ex["examples"][0]["title"], "Paracetamol 500mg Tablet")

    def test_summary_markdown_mentions_exclusions(self):
        s = {"scored": 0, "unscored": 0, "sensitive": {"count": 3, "by_rule": {"supplement": 3}, "examples": [{"rule": "supplement", "hit": "vitamin", "title": "Vitamin D3"}]}}
        md = run_scoring.summary_markdown(s, date(2026, 11, 23), False, "absolute")
        self.assertIn("স্পর্শকাতর পণ্য স্কোরের বাইরে রাখা: 3টা", md)
        self.assertIn("Vitamin D3", md)


if __name__ == "__main__":
    unittest.main()
