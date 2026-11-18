import random
import unittest
from datetime import date, timedelta

from backtest.config import BacktestConfigError, load_config, validate
from backtest.engine import (CORE, ScoreRow, Series, build_samples, category_spearman, flip_stats, grid,
                             interval_delta, spearman, split_by_date, sufficiency, threshold_table, tier_table,
                             total_with, tune)

CFG = load_config()
D0 = date(2026, 9, 1)


def d(n):
    return D0 + timedelta(days=n)


class SpearmanTests(unittest.TestCase):
    def test_perfect_and_inverse(self):
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)

    def test_ties_use_average_ranks(self):
        # x-এ টাই: [1,1,2,3] vs [1,2,3,4] — হাতে হিসাব ≈ 0.9487
        self.assertAlmostEqual(spearman([1, 1, 2, 3], [1, 2, 3, 4]), 0.9486832981, places=6)

    def test_degenerate_cases(self):
        self.assertIsNone(spearman([1, 2], [1, 2]))
        self.assertIsNone(spearman([5, 5, 5], [1, 2, 3]))
        self.assertIsNone(spearman([1, 2, 3], [7, 7, 7]))

    def test_monotone_nonlinear_is_one(self):
        self.assertAlmostEqual(spearman([1, 2, 3, 4, 5], [1, 4, 9, 16, 1000]), 1.0)


class SeriesTests(unittest.TestCase):
    def test_at_uses_latest_within_tolerance(self):
        s = Series([(d(0), 10), (d(5), 20)])
        self.assertEqual(s.at(d(5), 3), 20)
        self.assertEqual(s.at(d(7), 3), 20)
        self.assertIsNone(s.at(d(9), 3))      # ৪ দিন আগের, tol ৩
        self.assertIsNone(s.at(d(-1), 3))     # প্রথম স্ন্যাপশটের আগে

    def test_interval_delta_sums_only_listings_with_both_ends(self):
        a = Series([(d(0), 10), (d(10), 30)])            # +20
        b = Series([(d(0), 5), (d(10), 8)])              # +3
        late = Series([(d(6), 100), (d(10), 500)])       # শুরুতে নেই: বাদ (নকল লাফ আটকানো)
        self.assertEqual(interval_delta([a, b, late], d(0), d(10), 3), 23)
        self.assertIsNone(interval_delta([late], d(0), d(10), 3))

    def test_negative_growth_clamped_to_zero(self):
        self.assertEqual(interval_delta([Series([(d(0), 50), (d(7), 10)])], d(0), d(7), 3), 0)


def make_world(n=80, days=70, seed=3, planted=True):
    """n প্রোডাক্ট, ৭০ দিন। planted: ডিমান্ড-ফ্যাক্টর বেশি হলে পরের বিক্রি বেশি; বাকি ফ্যাক্টর আওয়াজ।"""
    rnd = random.Random(seed)
    scores, sold = [], {}
    for pid in range(1, n + 1):
        cat = "fashion" if pid % 2 else "kitchen"
        quality = rnd.uniform(0, 100)
        rate = (quality / 10 + rnd.uniform(0, 1)) if planted else rnd.uniform(0, 10)
        pts, total = [], 0.0
        for day in range(days + 1):
            total += rate
            pts.append((d(day), total))
        sold[pid] = [Series(pts)]
        for day in range(0, days - 14, 7):
            f = {"demand": quality + rnd.gauss(0, 3), "trend": rnd.uniform(0, 100),
                 "review_quality": rnd.uniform(0, 100), "bad_review": rnd.uniform(0, 100)}
            tot = total_with({"demand": 30, "trend": 25, "review_quality": 20, "bad_review": 15}, f)
            tier = "best" if tot >= 70 else ("dont" if tot < 40 else "mid")
            scores.append(ScoreRow(pid, d(day), cat, tier, tot, f))
    return scores, sold


class BuildSamplesTests(unittest.TestCase):
    def test_step_and_horizon_respected(self):
        scores, sold = make_world(n=3, days=40)
        s = build_samples(scores, sold, {}, CFG, d(40))
        for pid in (1, 2, 3):
            days = sorted(x.day for x in s if x.pid == pid)
            self.assertTrue(all(b - a >= timedelta(days=CFG["step_days"]) for a, b in zip(days, days[1:])))
            self.assertTrue(all(x + timedelta(days=CFG["horizon_days"]) <= d(40) for x in days))

    def test_future_without_data_gives_no_sample(self):
        scores, sold = make_world(n=2, days=70)
        self.assertEqual(build_samples(scores, sold, {}, CFG, d(5)), [])   # শেষ স্ন্যাপশট খুব আগে

    def test_sold_preferred_over_reviews_and_reviews_fallback(self):
        scores, sold = make_world(n=1, days=60)
        rev = {1: [Series([(d(i), i * 2.0) for i in range(61)])]}
        both = build_samples(scores, sold, rev, CFG, d(60))
        self.assertTrue(both and all(x.basis == "sold" for x in both))
        only_rev = build_samples(scores, {}, rev, CFG, d(60))
        self.assertTrue(only_rev and all(x.basis == "reviews" for x in only_rev))

    def test_unscored_rows_skipped(self):
        scores, sold = make_world(n=1, days=60)
        scores = [ScoreRow(s.pid, s.day, s.category, None, None, s.factors) for s in scores]
        self.assertEqual(build_samples(scores, sold, {}, CFG, d(60)), [])

    def test_fwd_and_base_rates_are_daily(self):
        pts = [(d(i), 3.0 * i) for i in range(40)]             # দিনে ৩
        sc = [ScoreRow(1, d(20), "fashion", "mid", 50.0, {k: 50.0 for k in CORE})]
        s = build_samples(sc, {1: [Series(pts)]}, {}, CFG, d(39))[0]
        self.assertAlmostEqual(s.fwd_rate, 3.0)
        self.assertAlmostEqual(s.base_rate, 3.0)


class TablesTests(unittest.TestCase):
    def test_tier_table_counts_and_sustain(self):
        scores, sold = make_world()
        s = build_samples(scores, sold, {}, CFG, d(70))
        tab = {r["tier"]: r for r in tier_table(s, CFG["sustain_ratio"])}
        self.assertEqual(sum(r["n"] for r in tab.values()), len(s))
        self.assertGreater(tab["best"]["median_fwd_rate"], tab["dont"]["median_fwd_rate"])
        self.assertEqual(tab["best"]["sustained_pct"], 100.0)        # ধ্রুবক হার: সবাই টিকেছে

    def test_threshold_table_monotone_counts(self):
        scores, sold = make_world()
        s = build_samples(scores, sold, {}, CFG, d(70))
        rows = threshold_table(s, [0, 50, 70, 101], 0.8)
        ns = [r["n"] for r in rows]
        self.assertEqual(ns, sorted(ns, reverse=True))
        self.assertEqual((rows[0]["n"], rows[-1]["n"]), (len(s), 0))
        self.assertIsNone(rows[-1]["median_fwd_rate"])

    def test_sustain_detects_decline(self):
        pts = [(d(i), 10.0 * i if i <= 20 else 200 + 1.0 * (i - 20)) for i in range(45)]   # ২০ দিনের পর হঠাৎ ধীর
        sc = [ScoreRow(1, d(20), "fashion", "best", 90.0, {k: 90.0 for k in CORE})]
        s = build_samples(sc, {1: [Series(pts)]}, {}, CFG, d(44))
        self.assertEqual(tier_table(s, 0.8)[0]["sustained_pct"], 0.0)

    def test_flip_stats(self):
        hist = {1: [(d(0), "mid"), (d(1), "best"), (d(2), "best"), (d(3), "mid")],
                2: [(d(0), "mid"), (d(1), "mid"), (d(8), "best")]}       # ২ নং-এ ৭ দিনের ফাঁক: ধরা হয় না
        r = flip_stats(hist)
        self.assertEqual((r["changes"], r["observed_product_days"]), (2, 4))
        self.assertAlmostEqual(r["changes_per_product_14d"], round(2 / 4 * 14, 3))
        self.assertIsNone(flip_stats({})["changes_per_product_14d"])


class TuneTests(unittest.TestCase):
    CUR = {"demand": 30, "trend": 25, "review_quality": 20, "bad_review": 15}

    def test_grid_constraints(self):
        g = grid(5, 10, 50)
        self.assertTrue(all(sum(x.values()) == 100 and all(10 <= v <= 50 and v % 5 == 0 for v in x.values()) for x in g))
        self.assertEqual(len({tuple(x.values()) for x in g}), len(g))
        self.assertEqual(grid(25, 25, 25), [dict(zip(CORE, [25] * 4))])

    def test_total_with_redistributes_missing(self):
        w = {"demand": 30, "trend": 25, "review_quality": 20, "bad_review": 15}
        self.assertAlmostEqual(total_with(w, {"demand": 80, "trend": None, "review_quality": None, "bad_review": None}), 80)
        self.assertIsNone(total_with(w, {k: None for k in CORE}))

    def test_split_is_chronological_and_disjoint(self):
        scores, sold = make_world()
        s = build_samples(scores, sold, {}, CFG, d(70))
        tr, te = split_by_date(s, 0.4)
        self.assertTrue(tr and te)
        self.assertLess(max(x.day for x in tr), min(x.day for x in te))
        self.assertEqual(len(tr) + len(te), len(s))

    def test_finds_planted_signal_and_validates_out_of_sample(self):
        scores, sold = make_world(n=120, days=84, planted=True)
        s = build_samples(scores, sold, {}, CFG, d(84))
        r = tune(s, self.CUR, CFG)
        self.assertGreater(r["candidates"], 100)
        self.assertIsNotNone(r["best"])
        self.assertGreater(r["best"]["demand"], r["current"]["demand"])           # ডিমান্ডই আসল সংকেত
        self.assertGreaterEqual(r["best_test"], r["current_test"])
        for k in CORE:                                                            # ন্যূনতম ওজন বাঁধা: ৯০-এর স্কেলে ≥ ৯
            self.assertGreaterEqual(r["best"][k], 9)

    def test_no_signal_gives_no_recommendation(self):
        scores, sold = make_world(n=120, days=84, planted=False, seed=11)
        s = build_samples(scores, sold, {}, CFG, d(84))
        r = tune(s, self.CUR, CFG)
        self.assertFalse(r["recommend"])

    def test_scaled_to_current_sum(self):
        scores, sold = make_world(n=120, days=84, planted=True)
        r = tune(build_samples(scores, sold, {}, CFG, d(84)), self.CUR, CFG)
        self.assertIn(sum(r["best"].values()), range(88, 93))     # ৯০-র স্কেল, রাউন্ডিং-এ ±২

    def test_category_spearman_ignores_tiny_categories(self):
        scores, sold = make_world(n=4, days=60)
        s = build_samples(scores, sold, {}, CFG, d(60))
        rho, n = category_spearman(s, [x.total for x in s], 1000)
        self.assertEqual((rho, n), (None, 0))


class SufficiencyConfigTests(unittest.TestCase):
    def test_reasons_listed(self):
        scores, sold = make_world(n=5, days=40)
        s = build_samples(scores, sold, {}, CFG, d(40))
        ok, why = sufficiency(s, CFG)
        self.assertFalse(ok)
        self.assertGreaterEqual(len(why), 2)

    def test_sufficient_world(self):
        scores, sold = make_world(n=120, days=84)
        ok, why = sufficiency(build_samples(scores, sold, {}, CFG, d(84)), CFG)
        self.assertTrue(ok, why)

    def test_config_validation(self):
        import copy
        def bad(**kw):
            c = copy.deepcopy(CFG)
            for k, v in kw.items():
                if "__" in k:
                    a, b = k.split("__")
                    c[a][b] = v
                else:
                    c[k] = v
            with self.assertRaises(BacktestConfigError):
                validate(c)
        bad(horizon_days=1)
        bad(sustain_ratio=0)
        bad(thresholds=[])
        bad(thresholds=[150])
        bad(tune__step=7)
        bad(tune__weight_min=30)          # ৪×৩০ > ১০০
        bad(tune__weight_max=20)          # ৪×২০ < ১০০
        bad(tune__test_share=0.9)
        bad(min_samples=True)


if __name__ == "__main__":
    unittest.main()
