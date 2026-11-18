import json
import unittest
from datetime import date, timedelta

from scoring import engine
from scoring.config import ConfigError, load_config
from scoring.features import Product, Review, Snap

TODAY = date(2026, 11, 10)
CFG = load_config()


def snaps(inc, days=30, rating=4.3, rcount=50, review_count=None):
    """inc(i): i-তম দিনের বিক্রি বৃদ্ধি। `days`+১টা স্ন্যাপশট, শেষটা আজকের।"""
    out, cum = [], 0
    for i in range(days + 1):
        cum += inc(i) if i else 0
        out.append(Snap(TODAY - timedelta(days=days - i), price=100.0, rating_avg=rating, rating_count=rcount,
                        review_count=review_count if review_count is not None else rcount,
                        sold_count=(cum if inc is not None else None)))
    return out


def reviews(n, bad, stars_good=5):
    return [Review(1 if i < bad else stars_good, TODAY - timedelta(days=i % 40)) for i in range(n)]


def filler(i, category="kitchen"):
    """১..২০ নম্বর ফিলার: দিনে i টা, রেটিং ৪.৩, ১০টা রিভিউ নমুনায় ১টা খারাপ।"""
    return Product(i, category, f"filler {i}", snaps(lambda _: i), reviews(10, 1))


def hot(pid=100, category="kitchen"):
    # ২৩ দিন দিনে ২০, শেষ ৭ দিন দিনে ৮০: গতি ও ট্রেন্ড দুটোই সবার উপরে
    return Product(pid, category, "hot", snaps(lambda i: 20 if i <= 23 else 80, rating=4.8, rcount=200),
                   reviews(20, 0))


def population(extra=()):
    return [filler(i) for i in range(1, 21)] + [hot()] + list(extra)


def by_id(results):
    return {r.product_id: r for r in results}


class TierTests(unittest.TestCase):
    def test_hot_product_is_best(self):
        r = by_id(engine.score_products(population(), CFG, TODAY))[100]
        self.assertEqual(r.tier, "best")
        self.assertEqual(r.confidence, "high")
        self.assertGreater(r.total, 85)
        self.assertGreater(r.factors["demand"], 90)
        self.assertGreater(r.factors["trend"], 90)
        self.assertTrue(all(v is True for k, v in r.reasons["gates"].items() if k != "hard_dont"))
        self.assertIsNone(r.reasons["provisional_tier"])
        self.assertTrue(r.reasons["summary"])

    def test_filler_products_are_mostly_mid_and_never_best(self):
        res = by_id(engine.score_products(population(), CFG, TODAY))
        self.assertEqual({res[i].tier for i in range(5, 20)}, {"mid"})   # মাঝের সারি
        self.assertEqual(res[1].tier, "dont")                            # ক্যাটাগরির সবচেয়ে কম বিক্রি, স্কোর < ৪৫
        self.assertNotIn("best", {res[i].tier for i in range(1, 21)})
        scores = [res[i].total for i in range(1, 21)]
        self.assertEqual(scores, sorted(scores))                         # বিক্রি বাড়লে স্কোরও বাড়ে

    def test_low_rating_and_bad_reviews_is_dont(self):
        bad = Product(200, "kitchen", "bad", snaps(lambda _: 10, rating=2.8, rcount=80), reviews(10, 4, stars_good=4))
        r = by_id(engine.score_products(population([bad]), CFG, TODAY))[200]
        self.assertEqual(r.tier, "dont")
        self.assertIn("low_rating", r.reasons["gates"]["hard_dont"])
        self.assertIn("many_bad_reviews", r.reasons["gates"]["hard_dont"])
        self.assertTrue(any("রেটিং খুব কম" in s for s in r.reasons["summary"]))

    def test_falling_sales_is_dont(self):
        # সাপ্তাহিক বৃদ্ধি ক্রমশ কমছে: ৭০, ৫০, ৩০, ১০ (দিনে ১০, ~৭, ~৪, ~১)
        weekly = [70, 50, 30, 10]
        inc = lambda i: weekly[min((i - 1) // 7, 3)] / 7 if i else 0
        fall = Product(300, "kitchen", "falling", snaps(inc, days=28, rating=4.5, rcount=100), reviews(10, 0))
        r = by_id(engine.score_products(population([fall]), CFG, TODAY))[300]
        self.assertIn("falling_sales", r.reasons["gates"]["hard_dont"])
        self.assertEqual(r.tier, "dont")

    def test_unknown_gate_gives_provisional_best(self):
        # দারুণ সংখ্যা, কিন্তু রিভিউ নমুনা নেই বলে খারাপ-রিভিউ শর্ত অজানা
        p = Product(400, "kitchen", "nosample", snaps(lambda i: 20 if i <= 23 else 80, rating=4.9, rcount=300), [])
        r = by_id(engine.score_products(population([p]), CFG, TODAY))[400]
        self.assertIsNone(r.factors["bad_review"])
        self.assertIsNone(r.reasons["gates"]["bad_ratio"])
        self.assertEqual(r.raw_tier, "mid")
        self.assertEqual(r.reasons["provisional_tier"], "best")
        self.assertTrue(any("নিশ্চিত নয়" in n for n in r.reasons["notes"]))

    def test_known_failed_gate_blocks_best(self):
        # খুব ভালো বিক্রি ও রেটিং, কিন্তু রেটিং সংখ্যা মাত্র ১৫ (< ২০)
        p = Product(500, "kitchen", "few", snaps(lambda i: 20 if i <= 23 else 80, rating=4.9, rcount=15), reviews(15, 0))
        r = by_id(engine.score_products(population([p]), CFG, TODAY))[500]
        self.assertFalse(r.reasons["gates"]["rating_count"])
        self.assertNotEqual(r.tier, "best")
        self.assertIsNone(r.reasons["provisional_tier"])

    def test_new_product_short_history_is_low_confidence_not_best(self):
        new = Product(600, "kitchen", "new", snaps(lambda _: 50, days=5, rating=5.0, rcount=3), reviews(3, 0))
        r = by_id(engine.score_products(population([new]), CFG, TODAY))[600]
        self.assertEqual(r.confidence, "low")
        self.assertNotEqual(r.tier, "best")
        self.assertIsNone(r.factors["trend"])
        self.assertTrue(any("ইতিহাস মাত্র 5 দিনের" in n for n in r.reasons["notes"]))

    def test_low_confidence_low_score_is_provisional_dont_not_dont(self):
        weak = Product(700, "kitchen", "weak", snaps(lambda _: 0, days=5, rating=3.9, rcount=3), reviews(3, 1))
        r = by_id(engine.score_products(population([weak]), CFG, TODAY))[700]
        if r.total is not None and r.total < CFG["dont"]["max_score"]:
            self.assertEqual(r.tier, "mid")
            self.assertEqual(r.reasons["provisional_tier"], "dont")


class FactorTests(unittest.TestCase):
    def test_weights_renormalize_when_factor_missing(self):
        # রেটিং ও রিভিউ নেই, শুধু বিক্রির ইতিহাস: demand + trend ই থাকে
        snaps_only = [Snap(TODAY - timedelta(days=30 - i), sold_count=5 * i) for i in range(31)]
        p = Product(800, "kitchen", "salesonly", snaps_only, [])
        r = by_id(engine.score_products(population([p]), CFG, TODAY))[800]
        self.assertIsNone(r.factors["review_quality"])
        self.assertIsNone(r.factors["bad_review"])
        self.assertEqual(r.available_weight, 55)
        expected = (30 * r.factors["demand"] + 25 * r.factors["trend"]) / 55
        self.assertAlmostEqual(r.total, expected, places=6)

    def test_review_proxy_when_no_sold_counts(self):
        p = Product(900, "kitchen", "proxy", [
            Snap(TODAY - timedelta(days=30 - i), rating_avg=4.5, rating_count=40, review_count=10 + i)
            for i in range(31)], reviews(10, 0))
        r = by_id(engine.score_products(population([p]), CFG, TODAY))[900]
        self.assertEqual(r.detail["basis"], "review")
        self.assertIsNotNone(r.factors["demand"])
        self.assertNotEqual(r.confidence, "high")
        self.assertTrue(any("রিভিউ সংখ্যা দিয়ে আন্দাজ" in n for n in r.reasons["notes"]))

    def test_no_data_gives_no_total(self):
        p = Product(950, "kitchen", "empty", [Snap(TODAY)], [])
        r = by_id(engine.score_products(population([p]), CFG, TODAY))[950]
        self.assertIsNone(r.total)
        self.assertIsNone(r.tier)

    def test_bayesian_pulls_small_samples_to_category_mean(self):
        few = Product(960, "kitchen", "few", snaps(lambda _: 10, rating=5.0, rcount=2), reviews(10, 0))
        many = Product(961, "kitchen", "many", snaps(lambda _: 10, rating=4.7, rcount=3000), reviews(10, 0))
        res = by_id(engine.score_products(population([few, many]), CFG, TODAY))
        self.assertLess(res[960].detail["review_quality"]["adj_rating"], 4.7)   # ২ রিভিউয়ে ৫.০ < ৩০০০ রিভিউয়ে ৪.৭
        self.assertGreater(res[961].factors["review_quality"], res[960].factors["review_quality"])

    def test_small_category_falls_back_to_all_pool(self):
        tiny = [Product(1000 + i, "fashion", f"t{i}", snaps(lambda _: 3 + i), reviews(10, 1)) for i in range(3)]
        res = by_id(engine.score_products(population(tiny), CFG, TODAY))
        self.assertIn("all", res[1000].detail["pool_scope"].values())
        self.assertTrue(any("সব ক্যাটাগরির সাথে" in n for n in res[1000].reasons["notes"]))

    def test_reasons_are_json_serializable(self):
        res = engine.score_products(population(), CFG, TODAY)
        for r in res:
            json.dumps(r.reasons, ensure_ascii=False)


class ModeAndHysteresisTests(unittest.TestCase):
    def test_percentile_mode_limits_best_to_top_share(self):
        cfg = load_config(override={"tier_mode": "percentile", "best": {"percentile_top": 5}})
        res = engine.score_products(population(), cfg, TODAY)
        best = [r.product_id for r in res if r.tier == "best"]
        self.assertEqual(best, [100])

    def test_hysteresis_holds_previous_tag(self):
        prev = [{"tier": "mid", "raw_tier": "best"}, {"tier": "mid", "raw_tier": "mid"}]
        self.assertEqual(engine.apply_hysteresis("best", prev, 3), "mid")        # গতকাল mid ছিল, তাই ধরে রাখে
        prev2 = [{"tier": "mid", "raw_tier": "best"}, {"tier": "mid", "raw_tier": "best"}]
        self.assertEqual(engine.apply_hysteresis("best", prev2, 3), "best")      # টানা ৩ দিন best
        self.assertEqual(engine.apply_hysteresis("mid", prev2, 3), "mid")        # raw == published
        self.assertEqual(engine.apply_hysteresis("best", [], 3), "best")         # প্রথম দিন
        self.assertEqual(engine.apply_hysteresis("best", [{"tier": "mid", "raw_tier": "best"}], 3), "mid")  # ইতিহাস কম

    def test_hysteresis_applied_in_scoring(self):
        prev = {100: [{"tier": "mid", "raw_tier": "mid"}, {"tier": "mid", "raw_tier": "mid"}]}
        r = by_id(engine.score_products(population(), CFG, TODAY, previous=prev))[100]
        self.assertEqual(r.raw_tier, "best")
        self.assertEqual(r.tier, "mid")
        self.assertTrue(any("টানা 3 দিন" in n for n in r.reasons["notes"]))


class ConfigTests(unittest.TestCase):
    def test_defaults_valid(self):
        # মূল চার ফ্যাক্টর ৯০, বাকিগুলো (বিজ্ঞাপন, মার্জিন, প্রতিযোগিতা) ডিফল্টে ০: আসল ডেটা যাচাইয়ের আগে স্কোর বদলায় না
        w = CFG["weights"]
        self.assertEqual(w["demand"] + w["trend"] + w["review_quality"] + w["bad_review"], 90)
        self.assertEqual((w["ads_signal"], w["margin"], w["competition"]), (0, 0, 0))

    def test_invalid_configs_rejected(self):
        bad = [
            {"weights": {"demand": -5}},
            {"weights": {"demand": 0, "trend": 0, "review_quality": 0, "bad_review": 0, "ads_signal": 0}},
            {"tier_mode": "weird"},
            {"best": {"min_score": 40}},
            {"review_quality": {"floor": 5.0, "ceiling": 3.0}},
            {"demand": {"velocity_share": 1.5}},
            {"tier_change_days": 0},
            {"best": {"percentile_top": 60}, "dont": {"percentile_bottom": 50}},
        ]
        for o in bad:
            with self.subTest(o=o):
                with self.assertRaises(ConfigError):
                    load_config(override=o)


if __name__ == "__main__":
    unittest.main()
