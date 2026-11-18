"""Phase 6: Facebook Ads Library (হাতে-দেওয়া চেক) -> ফ্যাক্টর, ব্যাজ, ম্যাপিং, রানার। সব নকল ডেটায়।"""
import unittest
from datetime import date, timedelta

from scoring import ads as ads_mod
from scoring import engine, run_scoring
from scoring.config import ConfigError, load_config
from scoring.features import AdsSignal
from scoring.tests.test_engine import CFG, TODAY, by_id, filler, hot, population
from scoring.tests.test_runner import FakeDB

A = CFG["ads"]


def sig(**kw):
    base = dict(keyword="air fryer", level="segment", observed_on=TODAY, active_ads=40, advertisers=10,
                oldest_start=TODAY - timedelta(days=45))
    base.update(kw)
    return AdsSignal(**base)


class FeatureMathTests(unittest.TestCase):
    def test_strong_signal_scores_high(self):
        score, d = ads_mod.evaluate(sig(), CFG, TODAY)
        self.assertEqual(d["status"], "ok")
        self.assertAlmostEqual(score, 100.0)          # breadth ১০০, longevity ১০০, growth নেই
        self.assertEqual(d["longest_days"], 45)
        self.assertIsNone(d["components"]["growth"])

    def test_weak_signal_scores_low(self):
        score, d = ads_mod.evaluate(sig(active_ads=1, advertisers=1, oldest_start=TODAY - timedelta(days=3)), CFG, TODAY)
        self.assertLess(score, 15)
        self.assertEqual(d["components"]["longevity"], 0.0)

    def test_breadth_falls_back_to_ad_count_without_advertisers(self):
        s, d = ads_mod.evaluate(sig(advertisers=None, active_ads=15, oldest_start=None), CFG, TODAY)
        self.assertAlmostEqual(s, 50.0)               # ১৫ / full_ads ৩০
        self.assertIsNone(d["components"]["longevity"])

    def test_missing_components_renormalize_weights(self):
        # longevity নেই: breadth(৫০) ও growth-এ ভাগ হয়, ০.৪:০.২
        s, d = ads_mod.evaluate(sig(advertisers=5, oldest_start=None, new_30d=24, active_ads=40), CFG, TODAY)
        growth = 100.0 * (24 / 40) / (2 * A["growth"]["new_share_neutral"])
        self.assertAlmostEqual(d["components"]["growth"], min(growth, 100.0), places=1)
        self.assertAlmostEqual(s, (0.4 * 50 + 0.2 * min(growth, 100.0)) / 0.6, places=1)

    def test_growth_from_history_beats_new_share(self):
        s = sig(prior=(TODAY - timedelta(days=20), 20), new_30d=0)
        _, d = ads_mod.evaluate(s, CFG, TODAY)
        self.assertEqual(d["growth_basis"], "history")
        self.assertEqual(d["growth_pct"], round(100 * ((40 + 3) / (20 + 3) - 1)))
        self.assertGreater(d["components"]["growth"], 80)

    def test_history_too_recent_or_too_old_is_ignored(self):
        for days in (5, 200):
            _, d = ads_mod.evaluate(sig(prior=(TODAY - timedelta(days=days), 5)), CFG, TODAY)
            self.assertIsNone(d["growth_basis"])

    def test_shrinking_ads_lower_growth(self):
        _, d = ads_mod.evaluate(sig(prior=(TODAY - timedelta(days=30), 80)), CFG, TODAY)
        self.assertLess(d["components"]["growth"], 30)
        self.assertLess(d["growth_pct"], 0)

    def test_zero_ads_is_valid_and_weak(self):
        s, d = ads_mod.evaluate(sig(active_ads=0, advertisers=0, oldest_start=None), CFG, TODAY)
        self.assertEqual((d["status"], s), ("ok", 0.0))
        self.assertIsNone(d["components"]["longevity"])

    def test_stale_check_not_used(self):
        old = sig(observed_on=TODAY - timedelta(days=A["max_age_days"] + 1),
                  oldest_start=TODAY - timedelta(days=90))
        s, d = ads_mod.evaluate(old, CFG, TODAY)
        self.assertIsNone(s)
        self.assertEqual(d["status"], "stale")

    def test_longevity_counts_days_up_to_check_date_not_today(self):
        obs = TODAY - timedelta(days=10)
        _, d = ads_mod.evaluate(sig(observed_on=obs, oldest_start=obs - timedelta(days=30)), CFG, TODAY)
        self.assertEqual(d["longest_days"], 30)

    def test_crowded_badge(self):
        self.assertFalse(ads_mod.evaluate(sig(advertisers=14), CFG, TODAY)[1]["crowded"])
        self.assertTrue(ads_mod.evaluate(sig(advertisers=15, active_ads=40), CFG, TODAY)[1]["crowded"])
        # advertisers না থাকলে বিজ্ঞাপন সংখ্যা দিয়ে
        self.assertTrue(ads_mod.evaluate(sig(advertisers=None, active_ads=60), CFG, TODAY)[1]["crowded"])
        self.assertFalse(ads_mod.evaluate(sig(advertisers=None, active_ads=59), CFG, TODAY)[1]["crowded"])

    def test_disabled_or_missing(self):
        self.assertEqual(ads_mod.evaluate(None, CFG, TODAY), (None, None))
        off = load_config(override={"ads": {"enabled": False}})
        self.assertEqual(ads_mod.evaluate(sig(), off, TODAY), (None, None))


class ConfigTests(unittest.TestCase):
    def test_invalid_ads_config_rejected(self):
        bad = [{"ads": {"longevity_floor_days": 50}},
               {"ads": {"component_weights": {"breadth": 0, "longevity": 1, "growth": 1}}},
               {"ads": {"component_weights": {"extra": 1}}},
               {"ads": {"growth": {"min_gap_days": 200}}},
               {"ads": {"growth": {"new_share_neutral": 1.2}}},
               {"ads": {"full_advertisers": 0}},
               {"ads": {"crowded_ads": 1}}]
        for o in bad:
            with self.assertRaises(ConfigError, msg=str(o)):
                load_config(override=o)


class EngineTests(unittest.TestCase):
    def _pop(self, ads=None):
        h = hot()
        h.ads = ads
        return [filler(i) for i in range(1, 21)] + [h]

    def test_default_weight_zero_leaves_scores_untouched(self):
        base = by_id(engine.score_products(self._pop(), CFG, TODAY))[100]
        with_ads = by_id(engine.score_products(self._pop(sig(active_ads=1, advertisers=1, oldest_start=None)), CFG, TODAY))[100]
        self.assertEqual(base.total, with_ads.total)
        self.assertEqual((base.tier, base.confidence, base.available_weight), (with_ads.tier, with_ads.confidence, with_ads.available_weight))
        self.assertIsNone(base.factors["ads_signal"])
        self.assertIsNotNone(with_ads.factors["ads_signal"])      # ফ্যাক্টর হিসাব হয়, শুধু ওজন ০
        self.assertEqual(with_ads.reasons["detail"]["ads"]["status"], "ok")

    def test_positive_weight_moves_total(self):
        cfg = load_config(override={"weights": {"ads_signal": 20}})
        weak = sig(active_ads=1, advertisers=1, oldest_start=None, keyword="x")
        base = by_id(engine.score_products(self._pop(), cfg, TODAY))[100]
        r = by_id(engine.score_products(self._pop(weak), cfg, TODAY))[100]
        self.assertLess(r.total, base.total)
        self.assertGreater(r.available_weight, base.available_weight)

    def test_crowded_badge_in_summary_even_with_zero_weight(self):
        r = by_id(engine.score_products(self._pop(sig(advertisers=20, active_ads=50)), CFG, TODAY))[100]
        self.assertTrue(any("বিজ্ঞাপনে ভিড়" in s for s in r.reasons["summary"] + r.reasons["notes"]))
        self.assertEqual(r.tier, "best")                          # ব্যাজ Best আটকায় না

    def test_notes_say_info_only_and_level(self):
        r = by_id(engine.score_products(self._pop(sig()), CFG, TODAY))[100]
        note = next(n for n in r.reasons["notes"] if "Ads Library" in n)
        self.assertIn("নিজস্ব নয়", note)
        self.assertIn("ওজন ০", note)
        own = by_id(engine.score_products(self._pop(sig(level="product")), CFG, TODAY))[100]
        self.assertTrue(any("এই প্রোডাক্টের নিজস্ব চেক" in n for n in own.reasons["notes"]))

    def test_stale_note_and_no_factor(self):
        old = sig(observed_on=TODAY - timedelta(days=90), oldest_start=None)
        r = by_id(engine.score_products(self._pop(old), CFG, TODAY))[100]
        self.assertIsNone(r.factors["ads_signal"])
        self.assertTrue(any("চেক পুরনো" in n for n in r.reasons["notes"]))

    def test_strong_and_weak_ads_reason_lines(self):
        for ads, word in ((sig(advertisers=12, active_ads=30), "জোরালো"),
                          (sig(active_ads=1, advertisers=1, oldest_start=None), "দুর্বল")):
            pop = [filler(i) for i in range(1, 21)]
            pop[9].ads = ads
            r = by_id(engine.score_products(pop, CFG, TODAY))[10]
            line = next(x for x in r.reasons["summary"] if "বিজ্ঞাপনে বাজার-সমর্থন" in x)
            self.assertIn(word, line)
            self.assertIn("'air fryer'", line)


# ------------------------------------------------------------------ রানার
def check(id_, keyword, **kw):
    base = dict(id=id_, keyword=keyword, keyword_norm=keyword.lower(), canonical_product_id=None,
                observed_on=TODAY.isoformat(), active_ads=30, advertisers=8, oldest_start=(TODAY - timedelta(days=40)).isoformat(),
                new_30d=None)
    base.update(kw)
    return base


TCFG = {"entries": [
    {"id": "air-fryer", "category": "kitchen", "q": "air fryer", "match": ["air fryer", "এয়ার ফ্রায়ার"]},
    {"id": "panjabi", "category": "fashion", "q": "panjabi", "match": ["panjabi", "পাঞ্জাবি"]},
]}


def prods():
    a, b, c = filler(1), filler(2), filler(3)
    a.title, b.title, c.title = "Philips air fryer 4L", "Mini Air Fryer Digital", "steel water bottle"
    c.category = "kitchen"
    return [a, b, c]


class AttachTests(unittest.TestCase):
    def test_segment_check_applies_by_title_match(self):
        ps = prods()
        info = run_scoring.attach_ads(ps, [check(1, "Air Fryer")], TCFG, CFG)
        self.assertEqual([p.ads is not None for p in ps], [True, True, False])
        self.assertEqual((ps[0].ads.level, ps[0].ads.group), ("segment", "air-fryer"))
        self.assertEqual(info["unmapped_keywords"], [])

    def test_own_check_beats_segment_check(self):
        ps = prods()
        run_scoring.attach_ads(ps, [check(1, "air fryer", active_ads=99),
                                    check(2, "philips air fryer 4l", canonical_product_id=1, active_ads=7, id=2)], TCFG, CFG)
        self.assertEqual((ps[0].ads.level, ps[0].ads.active_ads), ("product", 7))
        self.assertEqual((ps[1].ads.level, ps[1].ads.active_ads), ("segment", 99))

    def test_latest_check_wins_and_same_keyword_gives_prior(self):
        ps = prods()
        old = check(1, "air fryer", observed_on=(TODAY - timedelta(days=25)).isoformat(), active_ads=15,
                    oldest_start=(TODAY - timedelta(days=60)).isoformat())
        new = check(2, "air fryer", active_ads=30)
        run_scoring.attach_ads(ps, [old, new], TCFG, CFG)
        self.assertEqual(ps[0].ads.active_ads, 30)
        self.assertEqual(ps[0].ads.prior, (TODAY - timedelta(days=25), 15))

    def test_prior_needs_same_keyword_and_enough_gap(self):
        ps = prods()
        other = check(1, "এয়ার ফ্রায়ার", observed_on=(TODAY - timedelta(days=25)).isoformat(), active_ads=15)
        recent = check(2, "air fryer", observed_on=(TODAY - timedelta(days=3)).isoformat(), active_ads=20)
        new = check(3, "air fryer")
        run_scoring.attach_ads(ps, [other, recent, new], TCFG, CFG)
        self.assertIsNone(ps[0].ads.prior)

    def test_bengali_keyword_maps_to_same_segment(self):
        ps = prods()
        run_scoring.attach_ads(ps, [check(1, "এয়ার ফ্রায়ার")], TCFG, CFG)
        self.assertEqual(ps[0].ads.group, "air-fryer")

    def test_unmapped_keyword_reported_and_unused(self):
        ps = prods()
        info = run_scoring.attach_ads(ps, [check(1, "blender grinder")], TCFG, CFG)
        self.assertEqual(info["unmapped_keywords"], ["blender grinder"])
        self.assertTrue(all(p.ads is None for p in ps))


class RunnerTests(unittest.TestCase):
    def _db(self, checks=None, with_table=True):
        db = FakeDB(population())
        if with_table:
            db.tables["ad_checks"] = checks or []
        return db

    def test_no_table_scores_without_ads_and_warns(self):
        out = run_scoring.run(self._db(with_table=False), CFG, TODAY, dry_run=True)
        self.assertIn("Phase 6", out["summary"]["ads_warning"])
        self.assertEqual(out["summary"]["ads"]["used"], 0)
        self.assertEqual(out["summary"]["scored"], 21)

    def test_future_checks_ignored(self):
        fut = check(1, "air fryer", observed_on=(TODAY + timedelta(days=2)).isoformat(), oldest_start=None)
        out = run_scoring.run(self._db([fut]), CFG, TODAY, dry_run=True)
        self.assertEqual(out["summary"]["ads"]["checks"], 0)

    def test_own_product_check_written_to_row_and_summary(self):
        c = check(1, "hot item", canonical_product_id=100, advertisers=20, active_ads=40)
        db = self._db([c])
        out = run_scoring.run(db, CFG, TODAY)
        row = next(r for r in db.upserts[0][2] if r["canonical_product_id"] == 100)
        self.assertIsNotNone(row["ads_signal"])
        self.assertTrue(row["reasons"]["detail"]["ads"]["crowded"])
        s = out["summary"]["ads"]
        self.assertEqual((s["checks"], s["used"], s["used_product"], s["used_segment"], s["crowded"]), (1, 1, 1, 0, 1))
        self.assertEqual(sum(1 for r in db.upserts[0][2] if r["ads_signal"] is not None), 1)

    def test_markdown_mentions_ads_and_unmapped(self):
        c = check(1, "zzz unknown thing")
        out = run_scoring.run(self._db([c]), CFG, TODAY, dry_run=True)
        md = run_scoring.summary_markdown(out["summary"], TODAY, True, "absolute")
        self.assertIn("Facebook Ads Library", md)
        self.assertIn("zzz unknown thing", md)
        empty = run_scoring.summary_markdown(run_scoring.run(self._db(), CFG, TODAY, dry_run=True)["summary"], TODAY, True, "absolute")
        self.assertIn("কোনো চেক নেই", empty)

    def test_scores_identical_with_and_without_checks_at_default_weight(self):
        a = run_scoring.run(self._db(), CFG, TODAY, dry_run=True)
        b = run_scoring.run(self._db([check(1, "hot item", canonical_product_id=100)]), CFG, TODAY, dry_run=True)
        self.assertEqual([(r.product_id, r.total, r.tier) for r in a["results"]],
                         [(r.product_id, r.total, r.tier) for r in b["results"]])


if __name__ == "__main__":
    unittest.main()
