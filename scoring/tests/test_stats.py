import unittest

from scoring import stats


class StatsTests(unittest.TestCase):
    def test_percentile_mid_rank(self):
        pop = [1, 2, 3, 4, 5]
        self.assertEqual(stats.percentile_rank(5, pop), 90.0)   # (4 + 0.5)/5
        self.assertEqual(stats.percentile_rank(1, pop), 10.0)
        self.assertEqual(stats.percentile_rank(3, pop), 50.0)

    def test_percentile_ties_are_fair(self):
        self.assertEqual(stats.percentile_rank(0, [0, 0, 0, 0]), 50.0)
        self.assertEqual(stats.percentile_rank(0, [0, 0, 0, 10]), 37.5)

    def test_percentile_ignores_none_and_empty(self):
        self.assertEqual(stats.percentile_rank(2, [None, 1, 2, 3]), 50.0)
        self.assertIsNone(stats.percentile_rank(2, []))
        self.assertIsNone(stats.percentile_rank(2, [None]))

    def test_bayesian_examples_from_plan(self):
        # পরিকল্পনার উদাহরণ: C=4.2, m=30
        self.assertAlmostEqual(stats.bayesian_adjusted(5.0, 2, 4.2, 30), 4.25, places=2)
        self.assertAlmostEqual(stats.bayesian_adjusted(4.7, 3000, 4.2, 30), 4.695, places=3)
        self.assertEqual(stats.bayesian_adjusted(5.0, 0, 4.2, 30), 4.2)

    def test_smoothed_ratio(self):
        self.assertAlmostEqual(stats.smoothed_ratio(0, 0, 0.1, 10), 0.1)
        self.assertAlmostEqual(stats.smoothed_ratio(0, 20, 0.1, 10), 1 / 30)
        self.assertGreater(stats.smoothed_ratio(5, 10, 0.1, 10), stats.smoothed_ratio(1, 10, 0.1, 10))

    def test_scale(self):
        self.assertEqual(stats.scale(4.0, 3.0, 5.0), 50.0)
        self.assertEqual(stats.scale(2.0, 3.0, 5.0), 0.0)
        self.assertEqual(stats.scale(6.0, 3.0, 5.0), 100.0)
        with self.assertRaises(ValueError):
            stats.scale(1, 5, 5)

    def test_weighted_mean(self):
        self.assertEqual(stats.weighted_mean([(100, 30), (50, 30)]), 75.0)
        self.assertEqual(stats.weighted_mean([(100, 30), (None, 70)]), 100.0)  # None বাদ, ওজন আবার ভাগ
        self.assertIsNone(stats.weighted_mean([(None, 30)]))
        self.assertIsNone(stats.weighted_mean([(10, 0)]))

    def test_quantile(self):
        self.assertEqual(stats.quantile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(stats.quantile([5], 0.9), 5)
        self.assertIsNone(stats.quantile([], 0.5))


if __name__ == "__main__":
    unittest.main()
