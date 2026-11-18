import unittest
from datetime import date, timedelta

from scoring import features as F

END = date(2026, 11, 10)


def ser(values, end=END):
    """values: পুরনো -> নতুন, প্রতিদিন একটা।"""
    start = end - timedelta(days=len(values) - 1)
    return [(start + timedelta(days=i), float(v)) for i, v in enumerate(values)]


class SeriesTests(unittest.TestCase):
    def test_point_at(self):
        s = ser([1, 2, 3, 4, 5])
        self.assertEqual(F.point_at(s, END)[1], 5.0)
        self.assertEqual(F.point_at(s, END - timedelta(days=2))[1], 3.0)
        self.assertIsNone(F.point_at(s, END - timedelta(days=10)))

    def test_rate_clamps_decrease(self):
        s = ser([10, 4])
        self.assertEqual(F.rate(s[0], s[1]), 0.0)
        self.assertIsNone(F.rate(s[0], s[0]))

    def test_velocity_full_window(self):
        s = ser([3 * i for i in range(31)])          # ৩০ দিন, দিনে ৩টা
        self.assertEqual(F.velocity(s, 30, 14), (3.0, 30))

    def test_velocity_short_history(self):
        self.assertIsNone(F.velocity(ser([2 * i for i in range(10)]), 30, 14))   # ৯ দিন < ১৪
        v = F.velocity(ser([2 * i for i in range(15)]), 30, 14)                  # ১৪ দিন, পুরোটা ধরা হয়
        self.assertEqual(v, (2.0, 14))
        self.assertIsNone(F.velocity(ser([5]), 30, 14))

    def test_trend_accelerating_and_decelerating(self):
        # শেষ ৭ দিনে ৬/দিন, তার আগের ৭ দিনে ২/দিন
        up = [0]
        for inc in [2] * 7 + [6] * 7:
            up.append(up[-1] + inc)
        t = F.trend(ser(up), 7, 0.3)
        self.assertAlmostEqual(t["recent"], 6.0)
        self.assertAlmostEqual(t["prior"], 2.0)
        self.assertGreater(t["log_ratio"], 0.9)
        down = [0]
        for inc in [6] * 7 + [2] * 7:
            down.append(down[-1] + inc)
        self.assertLess(F.trend(ser(down), 7, 0.3)["log_ratio"], -0.9)

    def test_trend_flat_is_zero_and_needs_history(self):
        flat = [4 * i for i in range(15)]
        self.assertAlmostEqual(F.trend(ser(flat), 7, 0.3)["log_ratio"], 0.0)
        self.assertIsNone(F.trend(ser([0, 5, 9, 14, 20]), 7, 0.3))   # মাত্র ৫ দিন

    def test_weekly_deltas_and_falling(self):
        vals = [0]
        for week_inc in [50, 40, 30, 20]:           # প্রতি সপ্তাহের মোট বৃদ্ধি
            for _ in range(7):
                vals.append(vals[-1] + week_inc / 7)
        d = F.weekly_deltas(ser(vals), 4)
        self.assertEqual([round(x) for x in d], [50, 40, 30, 20])
        self.assertTrue(F.is_falling(d))
        self.assertFalse(F.is_falling([20, 30, 40, 50]))
        self.assertFalse(F.is_falling([0, 0, 0, 0]))          # সব শূন্য = পড়ছে না, স্থির
        self.assertFalse(F.is_falling([30, 30, 20, 10]))      # সমান ধাপ কঠোরভাবে কমা নয়
        self.assertIsNone(F.weekly_deltas(ser([1, 2, 3]), 4))  # ইতিহাস কম

    def test_aggregate_snaps(self):
        d = date(2026, 11, 1)
        a = [F.Snap(d, price=100, rating_avg=4.0, rating_count=30, review_count=5, sold_count=10)]
        b = [F.Snap(d, price=90, rating_avg=5.0, rating_count=10, review_count=2, sold_count=None)]
        out = F.aggregate_snaps([a, b])
        self.assertEqual(len(out), 1)
        s = out[0]
        self.assertEqual((s.price, s.rating_count, s.review_count, s.sold_count), (90, 40, 7, 10))
        self.assertAlmostEqual(s.rating_avg, 4.25)   # (4*30 + 5*10)/40


CFG = {"demand": {"velocity_window_days": 30}, "min_history_days_for_velocity": 14,
       "trend": {"recent_days": 7, "smoothing_per_day": 0.3}, "dont": {"falling_weeks": 4},
       "review_quality": {"recent_days": 90}}


class ComputeFeaturesTests(unittest.TestCase):
    def _product(self, sold=None, reviews=None, rcount=None):
        n = 31
        snaps = [F.Snap(END - timedelta(days=n - 1 - i), rating_avg=4.5, rating_count=50,
                        review_count=(rcount(i) if rcount else None),
                        sold_count=(sold(i) if sold else None)) for i in range(n)]
        return F.Product(1, "kitchen", "x", snaps, reviews or [])

    def test_sold_basis(self):
        f = F.compute_features(self._product(sold=lambda i: 3 * i), CFG)
        self.assertEqual((f.basis, f.history_days, f.lifetime), ("sold", 30, 90.0))
        self.assertEqual(f.velocity, 3.0)
        self.assertIsNotNone(f.trend)

    def test_review_basis_when_no_sold(self):
        f = F.compute_features(self._product(rcount=lambda i: i), CFG)
        self.assertEqual(f.basis, "review")
        self.assertEqual(f.velocity, 1.0)

    def test_no_basis(self):
        f = F.compute_features(self._product(), CFG)
        self.assertIsNone(f.basis)
        self.assertIsNone(f.velocity)

    def test_review_sample_excludes_fake_and_splits_recent(self):
        rv = [F.Review(5, END - timedelta(days=5)), F.Review(1, END - timedelta(days=10)),
              F.Review(5, END - timedelta(days=200)), F.Review(1, END, suspected_fake=True)]
        f = F.compute_features(self._product(sold=lambda i: i, reviews=rv), CFG)
        self.assertEqual((f.n_reviews, f.n_bad), (3, 1))
        self.assertAlmostEqual(f.sample_avg, 11 / 3)
        self.assertEqual(f.recent_n, 2)
        self.assertEqual(f.recent_avg, 3.0)

    def test_single_snapshot(self):
        p = F.Product(1, "kitchen", "x", [F.Snap(END, sold_count=5)])
        f = F.compute_features(p, CFG)
        self.assertEqual((f.history_days, f.basis, f.lifetime, f.velocity), (0, "sold", 5.0, None))


if __name__ == "__main__":
    unittest.main()
