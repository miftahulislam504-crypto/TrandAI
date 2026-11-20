import math
import unittest
from datetime import date, timedelta

from trends.config import TrendsConfigError, load_config, validate
from trends.normalize import normalize_batch, seasonality

CFG = load_config()
S = CFG["settings"]
LAST = date(2026, 11, 1)  # রবিবার


def raw(fn, n=53, partial_last=True, last=LAST):
    out = []
    for k in range(n):
        d = last - timedelta(weeks=n - 1 - k)
        out.append((d, float(fn(k)), partial_last and k == n - 1))
    return out


class NormalizeTests(unittest.TestCase):
    def test_anchor_scaling_makes_batches_comparable(self):
        # একই শব্দ, দুই ভিন্ন রিকোয়েস্ট: Google ভিন্ন স্কেলে দেখায়, কিন্তু anchor-এর অনুপাত একই
        a1 = normalize_batch({"online shopping": raw(lambda k: 50), "kurti": raw(lambda k: 25)}, "online shopping", S)
        a2 = normalize_batch({"online shopping": raw(lambda k: 20), "kurti": raw(lambda k: 10)}, "online shopping", S)
        n1 = a1.keywords["kurti"].points[-1][3]
        n2 = a2.keywords["kurti"].points[-1][3]
        self.assertAlmostEqual(n1, 50.0)
        self.assertAlmostEqual(n1, n2)
        self.assertEqual(a1.anchor_mean, 50.0)

    def test_partial_week_is_dropped(self):
        r = normalize_batch({"a": raw(lambda k: 40), "x": raw(lambda k: 20)}, "a", S)
        pts = r.keywords["x"].points
        self.assertEqual(len(pts), 52)
        self.assertEqual(pts[-1][0], LAST - timedelta(weeks=1))

    def test_partial_week_does_not_fake_a_drop(self):
        # চলতি অসম্পূর্ণ সপ্তাহে মান ১ (আংশিক), বাদ না দিলে ভুল পতন দেখাত
        series = [(d, v if not p else 1.0, p) for d, v, p in raw(lambda k: 30)]
        r = normalize_batch({"a": raw(lambda k: 40), "x": series}, "a", S)
        self.assertTrue(all(p[1] == 30 for p in r.keywords["x"].points))

    def test_anchor_window_uses_last_52_weeks_only(self):
        a = [(d, 100.0 if i < 20 else 10.0, False) for i, (d, _, _) in enumerate(raw(lambda k: 0, n=80, partial_last=False))]
        x = raw(lambda k: 10, n=80, partial_last=False)
        r = normalize_batch({"a": a, "x": x}, "a", S)
        self.assertAlmostEqual(r.anchor_mean, sum(v for _, v, _ in a[-52:]) / 52)

    def test_statuses(self):
        r = normalize_batch({
            "a": raw(lambda k: 40),
            "ok": raw(lambda k: 30),
            "zero": raw(lambda k: 0),
            "tiny": raw(lambda k: 4),                       # সর্বোচ্চ ৪ < min_peak_raw
            "sparse": raw(lambda k: 30 if k % 4 == 0 else 0),  # ১৩-১৪টা অশূন্য সপ্তাহ < ২০
        }, "a", S)
        self.assertEqual({k: v.status for k, v in r.keywords.items()},
                         {"ok": "ok", "zero": "no_data", "tiny": "low_volume", "sparse": "low_volume"})
        self.assertEqual(r.keywords["tiny"].points, [])     # অব্যবহারযোগ্য শব্দের পয়েন্ট জমা হয় না

    def test_anchor_missing_or_low(self):
        self.assertEqual(normalize_batch({"x": raw(lambda k: 30)}, "a", S).error, "anchor_missing")
        low = normalize_batch({"a": raw(lambda k: 2), "x": raw(lambda k: 30)}, "a", S)
        self.assertFalse(low.ok)
        self.assertEqual(low.error, "anchor_low")

    def test_anchor_value_recorded_per_week(self):
        r = normalize_batch({"a": raw(lambda k: 40 + k % 3), "x": raw(lambda k: 30)}, "a", S)
        d, rv, av, norm = r.keywords["x"].points[5]
        self.assertEqual(rv, 30)
        self.assertEqual(av, 40 + 5 % 3)


def long_series(fn, n=260):
    return raw(fn, n=n, partial_last=False)


class SeasonalityTests(unittest.TestCase):
    def test_yearly_pattern_is_seasonal(self):
        s = long_series(lambda k: 50 + 40 * math.sin(2 * math.pi * k / 52))
        r = seasonality(s, CFG)
        self.assertTrue(r["seasonal"])
        self.assertGreater(r["corr"], 0.9)
        self.assertAlmostEqual(r["yoy_log"], 0, delta=0.15)     # প্যাটার্ন একই, গত বছরের সাথে প্রায় সমান

    def test_noise_is_not_seasonal(self):
        import random
        rng = random.Random(7)
        r = seasonality(long_series(lambda k: 30 + rng.random() * 10), CFG)
        self.assertFalse(r["seasonal"])

    def test_yoy_detects_growth(self):
        s = long_series(lambda k: 20 if k < 208 else 60)        # শেষ ৫২ সপ্তাহে তিনগুণ
        r = seasonality(s, CFG)
        self.assertGreater(r["yoy_log"], 0.8)

    def test_short_series_returns_none(self):
        self.assertIsNone(seasonality(long_series(lambda k: 40, n=80), CFG))

    def test_low_volume_returns_none(self):
        self.assertIsNone(seasonality(long_series(lambda k: 3), CFG))


class ConfigTests(unittest.TestCase):
    def test_shipped_config_is_valid(self):
        self.assertEqual(len(CFG["entries"]), 109)

    def test_every_category_has_trend_entries(self):
        """categories.json-এর ১৫টা ক্যাটাগরির প্রত্যেকটার অন্তত ৩টা Trends entry (নতুন ক্যাটাগরি ভুলে বাদ পড়া ধরে)।"""
        from collections import Counter
        from trends.config import known_categories
        cnt = Counter(e["category"] for e in CFG["entries"])
        self.assertEqual(len(known_categories()), 15)
        for slug in known_categories():
            self.assertGreaterEqual(cnt[slug], 3, slug)
        self.assertEqual(set(cnt), set(known_categories()))

    def test_unknown_category_rejected(self):
        import copy
        c = copy.deepcopy(CFG)
        c["entries"].append({"id": "x", "category": "no-such-cat", "q": "zzz term", "match": ["zzz"]})
        with self.assertRaises(TrendsConfigError):
            validate(c)

    def test_enabled_categories_reads_categories_json(self):
        import json, tempfile
        from pathlib import Path
        from trends.config import enabled_categories
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config").mkdir()
            self.assertIsNone(enabled_categories(Path(d)))          # ফাইল নেই: সব ধরা (None)
            (Path(d) / "config" / "categories.json").write_text(json.dumps({"categories": [
                {"slug": "a"}, {"slug": "b", "enabled": False}, {"slug": "c", "enabled": True}]}), encoding="utf-8")
            self.assertEqual(enabled_categories(Path(d)), {"a", "c"})

    def _with(self, **over):
        import copy
        c = copy.deepcopy(CFG)
        for k, v in over.items():
            c[k].update(v) if isinstance(v, dict) else c.__setitem__(k, v)
        return c

    def test_batch_size_limit(self):
        with self.assertRaises(TrendsConfigError):
            validate(self._with(settings={"batch_size": 5}))

    def test_anchor_cannot_be_an_entry_term(self):
        with self.assertRaises(TrendsConfigError):
            validate(self._with(settings={"anchor": "Saree"}))

    def test_duplicate_term_rejected(self):
        import copy
        c = copy.deepcopy(CFG)
        c["entries"].append({"id": "x", "category": "home", "q": "SAREE", "match": ["x"]})
        with self.assertRaises(TrendsConfigError):
            validate(c)


if __name__ == "__main__":
    unittest.main()
