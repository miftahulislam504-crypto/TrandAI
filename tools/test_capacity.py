import json
import unittest
from pathlib import Path

from tools import capacity

ROOT = Path(__file__).resolve().parents[1]
DARAZ = {"settings": {"delay_seconds": 3.0, "jitter_seconds": 1.5, "max_pages_per_seed": 6, "detail_limit": 30,
                      "reviews_limit": 20, "reviews_max_pages": 2},
         "seeds": {"a": [{"q": str(i)} for i in range(10)], "b": [{"q": str(i)} for i in range(5)], "c": []}}
CATS = {"total_target_products": 300, "categories": [
    {"slug": "a", "target_products": 200, "enabled": True},
    {"slug": "b", "target_products": 100},
    {"slug": "c", "target_products": 50, "enabled": False}]}


class CapacityTests(unittest.TestCase):
    def test_seed_pages_bounds(self):
        self.assertEqual(capacity.seed_pages(15, 40, 6), 1)
        self.assertEqual(capacity.seed_pages(41, 40, 6), 2)
        self.assertEqual(capacity.seed_pages(10000, 40, 6), 6)
        self.assertEqual(capacity.seed_pages(1, 40, 6), 1)

    def test_estimate_counts_requests(self):
        e = capacity.estimate(DARAZ, CATS, page_size=40)
        # a: per_seed=20 -> ১ পাতা × ১০ seed = ১০; b: per_seed=20 -> ১ × ৫ = ৫
        self.assertEqual(e["discovery_requests"], 15)
        self.assertEqual((e["detail_requests"], e["review_requests"]), (30, 40))
        self.assertEqual(e["total_requests"], 85)
        self.assertEqual(e["products"], 300)
        self.assertEqual([c["slug"] for c in e["categories"]], ["a", "b"])         # c বন্ধ

    def test_sec_per_request_default_and_override(self):
        self.assertEqual(capacity.estimate(DARAZ, CATS)["sec_per_request"], 5.25)    # ৩ + ০.৭৫ + ১.৫
        e = capacity.estimate(DARAZ, CATS, sec_per_request=6)
        self.assertAlmostEqual(e["scrape_minutes_per_day"], round(85 * 6 / 60, 1))

    def test_minutes_per_month_formula(self):
        e = capacity.estimate(DARAZ, CATS, sec_per_request=6)
        per_day = 85 * 6 / 60 + capacity.OTHER_JOBS_MIN_PER_DAY
        self.assertEqual(e["minutes_per_month"], round(per_day * 30 + capacity.TRENDS_MIN_PER_MONTH))

    def test_include_disabled_without_seeds_is_flagged_not_crashing(self):
        e = capacity.estimate(DARAZ, CATS, include_disabled=True)
        c = next(x for x in e["categories"] if x["slug"] == "c")
        self.assertEqual((c["requests"], c["note"]), (0, "কোনো seed নেই"))

    def test_scale_increases_discovery_only_when_pages_grow(self):
        small = capacity.estimate(DARAZ, CATS, scale=1)["discovery_requests"]
        big = capacity.estimate(DARAZ, CATS, scale=10)["discovery_requests"]
        self.assertGreater(big, small)
        self.assertEqual(capacity.estimate(DARAZ, CATS, scale=1.5)["detail_requests"], 30)   # ডিটেইল সীমা বাঁধা

    def test_cap_note_when_pages_cannot_reach_target(self):
        e = capacity.estimate(DARAZ, CATS, scale=20)       # a: per_seed=400 > ৪০×৬
        self.assertIn("লক্ষ্যে পৌঁছাবে না", next(x for x in e["categories"] if x["slug"] == "a")["note"])

    def test_check_total(self):
        self.assertIsNone(capacity.check_total({"total_target_products": 300, "categories": CATS["categories"]}))
        self.assertIn("300", capacity.check_total({"total_target_products": 999, "categories": CATS["categories"]}))

    def test_shipped_config_is_consistent(self):
        daraz = json.loads((ROOT / "config" / "daraz.json").read_text(encoding="utf-8"))
        cats = json.loads((ROOT / "config" / "categories.json").read_text(encoding="utf-8"))
        self.assertIsNone(capacity.check_total(cats))
        self.assertGreater(capacity.estimate(daraz, cats, include_disabled=True)["products"],
                           capacity.estimate(daraz, cats)["products"])

    def test_report_mentions_budget_warning(self):
        text = capacity.report(DARAZ, CATS, 40, False, 100, 6)
        self.assertIn("⚠️", text)
        ok = capacity.report(DARAZ, CATS, 40, False, 100000, 6)
        self.assertNotIn("মাসে ~", ok)

    def test_detail_fill_days(self):
        self.assertEqual(capacity.estimate(DARAZ, CATS)["detail_fill_days"], 10)     # ৩০০ ÷ ৩০
        self.assertEqual(capacity.estimate(DARAZ, CATS, scale=2)["detail_fill_days"], 20)

    def test_cli_rejects_bad_args(self):
        self.assertEqual(capacity.main(["--page-size", "0"]), 2)
        self.assertEqual(capacity.main(["--sec-per-request", "-1"]), 2)


if __name__ == "__main__":
    unittest.main()
