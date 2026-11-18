import math
import unittest
from datetime import date, timedelta

from scoring import engine, google, run_scoring
from scoring.config import ConfigError, load_config
from scoring.features import GoogleSignal, Product
from scoring.tests.test_engine import TODAY, filler, hot, snaps, reviews
from scoring.tests.test_runner import FakeDB
from trends.config import load_config as load_trends

CFG = load_config()
G = CFG["trend"]["google"]
LAST_SUNDAY = date(2026, 11, 8)


def weekly(fn, n=52, last=LAST_SUNDAY):
    """fn(k): পুরনো থেকে k-তম সপ্তাহের মান (k=0 সবচেয়ে পুরনো)।"""
    return [(last - timedelta(weeks=n - 1 - k), float(fn(k))) for k in range(n)]


def sig(series, **kw):
    return GoogleSignal(group="air-fryer", label="air fryer", series=series, **kw)


class GoogleMathTests(unittest.TestCase):
    def test_flat_is_neutral(self):
        score, d = google.evaluate(sig(weekly(lambda k: 20)), CFG, TODAY)
        self.assertAlmostEqual(score, 50, delta=0.01)
        self.assertEqual(d["status"], "ok")
        self.assertEqual(d["momentum_pct"], 0)

    def test_rising_scores_high_falling_low(self):
        up = weekly(lambda k: 10 if k < 48 else 30)       # শেষ ৪ সপ্তাহে তিনগুণ
        down = weekly(lambda k: 30 if k < 48 else 10)
        s_up, d_up = google.evaluate(sig(up), CFG, TODAY)
        s_down, _ = google.evaluate(sig(down), CFG, TODAY)
        self.assertGreater(s_up, 85)
        self.assertLess(s_down, 15)
        self.assertGreater(d_up["momentum_pct"], 100)

    def test_doubling_in_momentum_hits_scale_top(self):
        # prior ৮ সপ্তাহ = ১০, recent ৪ সপ্তাহ = ২০: momentum ≈ ln2 (smoothing-এ সামান্য কম)
        s = weekly(lambda k: 10 if k < 48 else 20)
        feat, _ = google.google_features(sig(s), G, TODAY)
        self.assertAlmostEqual(feat["momentum"], math.log((20 + feat["year_avg"] * 0.1) / (10 + feat["year_avg"] * 0.1)), delta=1e-4)

    def test_needs_enough_weeks(self):
        score, d = google.evaluate(sig(weekly(lambda k: 20, n=20)), CFG, TODAY)
        self.assertIsNone(score)
        self.assertEqual(d["status"], "short")

    def test_stale_series_is_ignored(self):
        old = weekly(lambda k: 20, last=LAST_SUNDAY - timedelta(weeks=8))
        score, d = google.evaluate(sig(old), CFG, TODAY)
        self.assertIsNone(score)
        self.assertEqual(d["status"], "stale")

    def test_all_zero_year(self):
        score, d = google.evaluate(sig(weekly(lambda k: 0)), CFG, TODAY)
        self.assertIsNone(score)
        self.assertEqual(d["status"], "zero")

    def test_no_signal(self):
        self.assertEqual(google.evaluate(None, CFG, TODAY), (None, None))

    def test_disabled(self):
        cfg = load_config(override={"trend": {"google": {"enabled": False}}})
        self.assertEqual(google.evaluate(sig(weekly(lambda k: 20)), cfg, TODAY), (None, None))

    def test_seasonal_uses_yoy_not_position(self):
        # ১২ মাসের গড়ের চেয়ে অনেক উপরে (position বেশি) কিন্তু গত বছরও একই রকম ছিল (yoy = ০): মৌসুমি, তাই ~৫০-এর কাছে
        s = weekly(lambda k: 10 if k < 48 else 40)
        plain, _ = google.evaluate(sig(s), CFG, TODAY)
        seasonal, d = google.evaluate(sig(s, seasonal=True, yoy_log=0.0), CFG, TODAY)
        self.assertTrue(d["seasonal"])
        self.assertLess(seasonal, plain)
        self.assertGreater(plain, 90)
        # seasonal = 0.7*yoy(50) + 0.3*momentum(100)
        self.assertAlmostEqual(seasonal, 0.7 * 50 + 0.3 * 100, delta=2)

    def test_seasonal_hint_without_yoy_falls_back_to_momentum_only(self):
        s = weekly(lambda k: 10 if k < 48 else 40)
        feat, _ = google.google_features(sig(s, seasonal_hint=True), G, TODAY)
        self.assertTrue(feat["seasonal"])
        self.assertAlmostEqual(google.google_score(feat, G), 100 * min(1, max(0, (feat["momentum"] + G["span"]) / (2 * G["span"]))), places=6)


class ConfigTests(unittest.TestCase):
    def test_bad_share_rejected(self):
        with self.assertRaises(ConfigError):
            load_config(override={"trend": {"google": {"share": 1.5}}})

    def test_bad_windows_rejected(self):
        with self.assertRaises(ConfigError):
            load_config(override={"trend": {"google": {"year_weeks": 5}}})


def pop(extra=()):
    return [filler(i) for i in range(1, 21)] + [hot()] + list(extra)


class EngineIntegrationTests(unittest.TestCase):
    def test_trend_is_mixed_half_half(self):
        base = {r.product_id: r for r in engine.score_products(pop(), CFG, TODAY)}[100]
        up = sig(weekly(lambda k: 10 if k < 48 else 30))
        p = pop()
        p[-1].google = up
        r = {r.product_id: r for r in engine.score_products(p, CFG, TODAY)}[100]
        g_score, _ = google.evaluate(up, CFG, TODAY)
        self.assertAlmostEqual(r.factors["trend"], 0.5 * base.factors["trend"] + 0.5 * g_score, places=6)
        self.assertEqual(r.detail["google"]["status"], "ok")

    def test_share_is_configurable(self):
        up = sig(weekly(lambda k: 10 if k < 48 else 30))
        p = pop(); p[-1].google = up
        cfg = load_config(override={"trend": {"google": {"share": 1.0}}})
        r = {r.product_id: r for r in engine.score_products(p, cfg, TODAY)}[100]
        self.assertAlmostEqual(r.factors["trend"], google.evaluate(up, cfg, TODAY)[0], places=6)

    def test_google_gives_trend_to_short_history_product(self):
        # ৫ দিনের ইতিহাস: বিক্রির গতি/ট্রেন্ড নেই, Google থেকেই Trend আসে (PLAN ৭.৪)
        newbie = Product(300, "kitchen", "new", snaps(lambda _: 5, days=5), reviews(10, 0))
        without = {r.product_id: r for r in engine.score_products(pop([newbie]), CFG, TODAY)}[300]
        self.assertIsNone(without.factors["trend"])
        newbie2 = Product(300, "kitchen", "new", snaps(lambda _: 5, days=5), reviews(10, 0), google=sig(weekly(lambda k: 20)))
        p = pop([newbie2])
        withg = {r.product_id: r for r in engine.score_products(p, CFG, TODAY)}[300]
        self.assertAlmostEqual(withg.factors["trend"], 50, delta=0.01)
        self.assertGreater(withg.available_weight, without.available_weight)

    def test_unusable_google_changes_nothing(self):
        base = {r.product_id: r for r in engine.score_products(pop(), CFG, TODAY)}
        p = pop(); p[-1].google = sig([])
        r = {r.product_id: r for r in engine.score_products(p, CFG, TODAY)}
        self.assertEqual(r[100].total, base[100].total)
        self.assertEqual(r[100].detail["google"]["status"], "short")

    def test_reasons_mention_google(self):
        # মাঝের সারির ফিলার: অন্য কোনো ফ্যাক্টর চরম নয়, তাই Google কারণটা সামনে আসে
        p = pop(); p[9].google = sig(weekly(lambda k: 10 if k < 48 else 30))
        r = {r.product_id: r for r in engine.score_products(p, CFG, TODAY)}[10]
        self.assertTrue(any("Google" in s for s in r.reasons["summary"]), r.reasons["summary"])
        self.assertTrue(any("segment" in n or "ধরনের" in n for n in r.reasons["notes"]))


class TrendDB(FakeDB):
    """FakeDB + trend টেবিল।"""

    def __init__(self, products, kws=(), pts=(), **kw):
        super().__init__(products, **kw)
        self.tables["trend_keywords"] = list(kws)
        self.tables["trend_points"] = list(pts)


def kw(i, key, group, seasonal=None, yoy=None):
    return {"id": i, "keyword": key, "group_key": group, "seasonal": seasonal, "yoy_log": yoy}


def pts(i, series):
    return [{"keyword_id": i, "week_start": d.isoformat(), "value": v} for d, v in series]


class RunnerTests(unittest.TestCase):
    T = load_trends()

    def test_en_and_bn_series_are_summed_on_common_weeks(self):
        en = weekly(lambda k: 10)
        bn = weekly(lambda k: 4)[2:]                      # বাংলা সিরিজ ২ সপ্তাহ কম
        db = TrendDB([], [kw(1, "air fryer", "air-fryer"), kw(2, "এয়ার ফ্রায়ার", "air-fryer")], pts(1, en) + pts(2, bn))
        out, warn = run_scoring.fetch_google(db, TODAY, CFG, self.T)
        self.assertIsNone(warn)
        s = out["air-fryer"]
        self.assertEqual(len(s.series), 50)
        self.assertTrue(all(v == 14 for _, v in s.series))
        self.assertEqual(s.label, "air fryer")

    def test_seasonal_flags_merge(self):
        db = TrendDB([], [kw(1, "panjabi", "panjabi", True, 0.2), kw(2, "পাঞ্জাবি", "panjabi", False, 0.4)],
                     pts(1, weekly(lambda k: 5)) + pts(2, weekly(lambda k: 5)))
        s = run_scoring.fetch_google(db, TODAY, CFG, self.T)[0]["panjabi"]
        self.assertTrue(s.seasonal_hint)      # config-এ seasonal: true
        self.assertTrue(s.seasonal)           # একটা সদস্য seasonal
        self.assertAlmostEqual(s.yoy_log, 0.3)

    def test_missing_tables_do_not_break_scoring(self):
        out = run_scoring.run(FakeDB(pop()), CFG, TODAY, dry_run=True)    # FakeDB-তে trend টেবিলই নেই
        self.assertEqual(out["summary"]["scored"], 21)
        self.assertIn("Google", out["summary"]["google_warning"])
        self.assertEqual(out["summary"]["google"]["used"], 0)

    def test_attach_and_end_to_end_summary(self):
        products = pop()
        products[-1].title = "Digital Air Fryer 5L"
        for p in products[:-1]:
            p.title = "random item"
        db = TrendDB(products, [kw(1, "air fryer", "air-fryer")], pts(1, weekly(lambda k: 10 if k < 48 else 30)))
        out = run_scoring.run(db, CFG, TODAY, dry_run=True)
        g = out["summary"]["google"]
        self.assertEqual((g["used"], g["no_keyword"], g["mapped_no_data"]), (1, 20, 0))
        self.assertEqual(g["by_segment"], {"air-fryer": 1})
        r = next(r for r in out["results"] if r.product_id == 100)
        self.assertEqual(r.detail["google"]["group"], "air-fryer")
        md = run_scoring.summary_markdown(out["summary"], TODAY, True, CFG["tier_mode"])
        self.assertIn("Google Trends", md)
        self.assertIn("কীওয়ার্ড নেই", md)    # ৩০%-এর বেশি কীওয়ার্ডহীন

    def test_mapped_but_no_data_is_counted(self):
        products = pop()
        products[-1].title = "Digital Air Fryer"
        out = run_scoring.run(TrendDB(products), CFG, TODAY, dry_run=True)
        g = out["summary"]["google"]
        self.assertEqual((g["used"], g["mapped_no_data"]), (0, 1))

    def test_written_row_shape_unchanged(self):
        products = pop(); products[-1].title = "air fryer"
        db = TrendDB(products, [kw(1, "air fryer", "air-fryer")], pts(1, weekly(lambda k: 20)))
        run_scoring.run(db, CFG, TODAY)
        row = next(r for r in db.upserts[0][2] if r["canonical_product_id"] == 100)
        self.assertIn("google", row["reasons"]["detail"])
        self.assertEqual(set(row), {"canonical_product_id", "scored_on", "demand", "trend", "review_quality",
                                    "bad_review", "ads_signal", "total", "tier", "confidence", "reasons"})


if __name__ == "__main__":
    unittest.main()
