import unittest
from datetime import date, timedelta

from scoring import features as F
from scoring.config import load_config
from scoring.features import Product, Snap, aggregate_snaps, compute_features

END = date(2026, 11, 10)
CFG = load_config()


def days(n):
    return [END - timedelta(days=n - 1 - i) for i in range(n)]


def snaps(ds, sold=lambda i: None, price=lambda i: 100, rc=lambda i: 10):
    return [Snap(d, price=price(i), rating_avg=4.5, rating_count=rc(i), review_count=rc(i), sold_count=sold(i)) for i, d in enumerate(ds)]


class AggregateTests(unittest.TestCase):
    def test_single_listing_unchanged(self):
        a = snaps(days(5), sold=lambda i: i)
        self.assertEqual(aggregate_snaps([a]), a)
        self.assertEqual(aggregate_snaps([]), [])
        self.assertEqual(aggregate_snaps([[], a]), a)

    def test_missing_day_for_one_platform_does_not_dip_total(self):
        ds = days(6)
        a = snaps(ds, sold=lambda i: 100 + 10 * i)
        b = snaps(ds, sold=lambda i: 50 + 5 * i)
        b = [s for s in b if s.day != ds[3]]                      # ৪র্থ দিনে b স্ক্র্যাপ হয়নি
        out = aggregate_snaps([a, b])
        totals = [s.sold_count for s in out]
        self.assertEqual(totals, sorted(totals))                  # কখনও কমেনি
        self.assertEqual(totals[3], 130 + 65 - 5)                 # b-র ৩য় দিনের মান বহাল (৬০)

    def test_late_joining_listing_does_not_fake_a_velocity_spike(self):
        ds = days(40)
        a = snaps(ds, sold=lambda i: 1000 + 10 * i)               # দিনে ১০
        b = snaps(ds[20:], sold=lambda i: 800 + 5 * i)            # ২০ দিন পরে ম্যাচ, আজীবন বিক্রি ৮০০, দিনে ৫
        agg = aggregate_snaps([a, b])
        f = compute_features(Product(1, "kitchen", "x", agg), CFG)
        # b-র পর্যবেক্ষণ ৩০ দিনের উইন্ডোর মাত্র ২০ দিনে, আগের অংশে বৃদ্ধি অজানা বলে ০ ধরা (সমতল)। তাই গতি ঠিক ১৫ নয়,
        # ১৩.২ (কম ধরা), নকল লাফ নয়। b-র ইতিহাস উইন্ডো ভরলে ১৫-তে পৌঁছায়।
        self.assertAlmostEqual(f.velocity, 10 + 5 * 19 / 29, delta=0.3)
        self.assertLess(f.velocity, 15.0)
        self.assertAlmostEqual(f.lifetime, (1000 + 390) + (800 + 5 * 19), delta=1)   # মোট ঠিকই বাড়ে

    def test_without_fill_the_old_behaviour_would_have_spiked(self):
        # প্রমাণ: নকল লাফ আসতো (নতুন কোডে আসে না), যাতে টেস্টটা সত্যিই কিছু ধরছে বোঝা যায়
        ds = days(40)
        a = snaps(ds, sold=lambda i: 1000 + 10 * i)
        b = snaps(ds[20:], sold=lambda i: 800 + 5 * i)
        naive = []
        for d in ds:
            tot = sum(s.sold_count for g in (a, b) for s in g if s.day == d)
            naive.append(Snap(d, sold_count=tot))
        v_naive = compute_features(Product(1, "kitchen", "x", naive), CFG).velocity
        self.assertGreater(v_naive, 30)               # ~৪০, আসল ১৫-এর প্রায় তিনগুণ

    def test_young_listing_adds_to_lifetime_but_not_to_velocity_or_trend(self):
        ds = days(40)
        a = snaps(ds, sold=lambda i: 1000 + 10 * i)               # দিনে ১০
        b = snaps(ds[34:], sold=lambda i: 800 + 9 * i)            # মাত্র ৬ দিন আগে ম্যাচ, দিনে ৯
        agg = aggregate_snaps([a, b], mature_days=14)
        f = compute_features(Product(1, "kitchen", "x", agg), CFG)
        self.assertAlmostEqual(f.velocity, 10.0, delta=0.05)      # b-র বৃদ্ধি গতিতে নেই
        self.assertAlmostEqual(f.lifetime, (1000 + 390) + (800 + 45))   # কিন্তু মোটে আছে
        # mature_days ছাড়া (পুরনো আচরণ): b-র সাম্প্রতিক বৃদ্ধি নকল ত্বরণ আনে
        f2 = compute_features(Product(1, "kitchen", "x", aggregate_snaps([a, b])), CFG)
        self.assertGreater(f2.velocity, f.velocity + 1)

    def test_listing_becomes_part_of_velocity_once_mature(self):
        ds = days(40)
        a = snaps(ds, sold=lambda i: 1000 + 10 * i)
        b = snaps(ds[24:], sold=lambda i: 800 + 9 * i)            # ১৬ দিনের ইতিহাস >= ১৪
        f = compute_features(Product(1, "kitchen", "x", aggregate_snaps([a, b], mature_days=14)), CFG)
        self.assertGreater(f.velocity, 12)

    def test_all_young_falls_back_to_normal_fill(self):
        ds = days(10)
        a = snaps(ds, sold=lambda i: 100 + 10 * i)
        b = snaps(ds, sold=lambda i: 50 + 5 * i)
        out = aggregate_snaps([a, b], mature_days=14)
        self.assertEqual([s.sold_count for s in out], [150 + 15 * i for i in range(10)])

    def test_platform_without_sold_counts_stays_out_of_sold_total(self):
        ds = days(5)
        a = snaps(ds, sold=lambda i: 100 + i)
        b = snaps(ds, sold=lambda i: None)
        self.assertEqual([s.sold_count for s in aggregate_snaps([a, b])], [100, 101, 102, 103, 104])

    def test_stopped_listing_keeps_last_value(self):
        ds = days(6)
        a = snaps(ds, sold=lambda i: 100 + 10 * i)
        b = snaps(ds[:3], sold=lambda i: 50 + 5 * i)               # b ৩ দিন পর আর স্ক্র্যাপ হয় না
        totals = [s.sold_count for s in aggregate_snaps([a, b])]
        self.assertEqual(totals, [150, 165, 180, 190, 200, 210])

    def test_price_is_min_and_carry_is_limited(self):
        ds = days(8)
        a = snaps(ds, price=lambda i: 100)
        b = snaps(ds[:2], price=lambda i: 80)                      # b-র দাম শুধু প্রথম ২ দিন
        prices = [s.price for s in aggregate_snaps([a, b])]
        self.assertEqual(prices[:2], [80, 80])
        self.assertEqual(prices[2:5], [80, 80, 80])                # ৩ দিন বহাল
        self.assertEqual(prices[5:], [100, 100, 100])              # তারপর বাদ

    def test_rating_is_weighted_by_filled_counts(self):
        d = days(3)
        a = [Snap(x, rating_avg=4.0, rating_count=30, review_count=30, sold_count=None) for x in d]
        b = [Snap(d[2], rating_avg=5.0, rating_count=10, review_count=10, sold_count=None)]
        out = aggregate_snaps([a, b])
        self.assertAlmostEqual(out[0].rating_avg, 4.0 * 30 / 40 + 5.0 * 10 / 40)   # b-র প্রথম মান সমতল বসেছে
        self.assertEqual(out[2].rating_count, 40)


if __name__ == "__main__":
    unittest.main()
