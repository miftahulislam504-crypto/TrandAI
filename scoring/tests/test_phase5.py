"""Phase 5: মার্জিন, প্রতিযোগিতা ও নকল-অভিযোগের রেড ফ্ল্যাগ।"""
import unittest
from dataclasses import replace
from datetime import timedelta

from scoring import engine, run_scoring
from scoring.business import competition_eval, margin_eval
from scoring.config import ConfigError, load_config
from scoring.features import Review
from scoring.tests.test_engine import CFG, TODAY, by_id, filler, hot, population
from scoring.tests.test_runner import FakeDB
from scrapers.common.supabase_rest import SupabaseError


def hot_with(**kw):
    h = hot()
    for k, v in kw.items():
        setattr(h, k, v)
    return h


def run_hot(cfg=CFG, **kw):
    return by_id(engine.score_products([filler(i) for i in range(1, 21)] + [hot_with(**kw)], cfg, TODAY))[100]


class MarginTests(unittest.TestCase):
    def test_numbers(self):
        s, d = margin_eval(1000, 600, 50, CFG)
        self.assertAlmostEqual(d["profit"], 330.0)        # 0.95*(1000-600-50) - 0.05*50
        self.assertAlmostEqual(d["margin_pct"], 33.0)
        self.assertAlmostEqual(d["roi_pct"], 50.8, places=1)
        self.assertAlmostEqual(s, 100 * (33 - 5) / (35 - 5), places=3)
        # ন্যূনতম বিক্রয়মূল্যে লাভ ঠিক শূন্য
        _, at = margin_eval(d["break_even_price"], 600, 50, CFG)
        self.assertAlmostEqual(at["profit"], 0.0, places=1)

    def test_platform_fee_reduces_profit(self):
        cfg = load_config(override={"margin": {"platform_fee_pct": 10}})
        _, d = margin_eval(1000, 600, 50, cfg)
        self.assertAlmostEqual(d["profit"], 0.95 * (1000 - 100 - 650) - 2.5)
        _, at = margin_eval(d["break_even_price"], 600, 50, cfg)
        self.assertAlmostEqual(at["profit"], 0.0, places=1)

    def test_loss_scores_zero(self):
        s, d = margin_eval(500, 600, 0, CFG)
        self.assertEqual(s, 0.0)
        self.assertLess(d["margin_pct"], 0)

    def test_missing_inputs_or_disabled(self):
        self.assertEqual(margin_eval(None, 600, 0, CFG), (None, {}))
        self.assertEqual(margin_eval(1000, None, 0, CFG), (None, {}))
        self.assertEqual(margin_eval(0, 600, 0, CFG), (None, {}))
        off = load_config(override={"margin": {"enabled": False}})
        self.assertEqual(margin_eval(1000, 600, 0, off), (None, {}))

    def test_zero_cost_has_no_roi(self):
        _, d = margin_eval(1000, 0, 0, CFG)
        self.assertIsNone(d["roi_pct"])


class CompetitionTests(unittest.TestCase):
    def test_scale(self):
        self.assertEqual(competition_eval(1, 1, CFG)[0], 100.0)
        self.assertEqual(competition_eval(15, 15, CFG)[0], 0.0)
        self.assertEqual(competition_eval(40, 40, CFG)[0], 0.0)
        self.assertAlmostEqual(competition_eval(8, 8, CFG)[0], 50.0)

    def test_falls_back_to_listing_count_without_seller_names(self):
        s, d = competition_eval(None, 4, CFG)
        self.assertEqual((d["sellers"], d["by"]), (4, "listing"))
        self.assertAlmostEqual(s, 100 * (15 - 4) / 14)

    def test_disabled_or_empty(self):
        off = load_config(override={"competition": {"enabled": False}})
        self.assertEqual(competition_eval(3, 3, off), (None, {}))
        self.assertEqual(competition_eval(None, 0, CFG), (None, {}))


class EngineTests(unittest.TestCase):
    def test_default_weights_leave_scores_unchanged(self):
        base = run_hot()
        withb = run_hot(unit_cost=60.0, extra_cost=5.0, sellers=3, listings=3)
        self.assertAlmostEqual(base.total, withb.total)
        self.assertIsNotNone(withb.factors["margin"])
        self.assertIsNotNone(withb.factors["competition"])
        self.assertEqual(withb.tier, "best")

    def test_weights_pull_total(self):
        cfg = load_config(override={"weights": {"margin": 30, "competition": 20}})
        weak = run_hot(cfg, unit_cost=92.0, sellers=14, listings=14)      # দাম ১০০: মার্জিন ছোট, ভিড় বেশি
        strong = run_hot(cfg, unit_cost=50.0, sellers=1, listings=1)
        self.assertGreater(strong.total, weak.total)

    def test_unknown_cost_does_not_block_best_or_add_gate(self):
        r = run_hot()
        self.assertEqual(r.tier, "best")
        self.assertNotIn("margin", r.reasons["gates"])
        self.assertIsNone(r.factors["margin"])

    def test_low_margin_blocks_best_and_explains(self):
        r = run_hot(unit_cost=95.0)      # দাম ১০০, ৫% ফেরত: মার্জিন প্রায় ০
        self.assertIs(r.reasons["gates"]["margin"], False)
        self.assertEqual(r.tier, "mid")
        self.assertIn("মার্জিন কম", " ".join(r.reasons["notes"]))

    def test_loss_is_called_out_first(self):
        r = run_hot(unit_cost=130.0)
        self.assertTrue(r.reasons["summary"][0].startswith("এই দামে লোকসান"))
        self.assertIn("ন্যূনতম বিক্রয়মূল্য", r.reasons["summary"][0])

    def test_healthy_margin_keeps_best(self):
        r = run_hot(unit_cost=50.0)
        self.assertEqual(r.tier, "best")
        self.assertIs(r.reasons["gates"]["margin"], True)

    def test_only_crowding_is_called_out(self):
        few = run_hot(sellers=1, listings=1)
        self.assertEqual(few.factors["competition"], 100.0)
        self.assertFalse(any("প্রতিযোগিতা" in s for s in few.reasons["summary"]))     # ১ সেলার = ট্র্যাক করা সংখ্যা, সুখবর নয়
        crowded = run_hot(sellers=14, listings=14)
        self.assertLess(crowded.factors["competition"], 10)
        # hot প্রোডাক্টে অন্য কারণ বেশি জোরালো বলে সেরা ৩-এ আসে না। সাধারণ প্রোডাক্টে ভিড়ের কথা আসে
        plain = filler(5)
        plain.sellers, plain.listings = 14, 14
        r = by_id(engine.score_products([filler(i) for i in range(1, 21) if i != 5] + [plain, hot()], CFG, TODAY))[5]
        self.assertTrue(any("প্রতিযোগিতা বেশি" in s for s in r.reasons["summary"]), r.reasons["summary"])


class CounterfeitTests(unittest.TestCase):
    def reviews(self, n_flagged, n=20):
        return [Review(5, TODAY - timedelta(days=i % 40), False, counterfeit=i < n_flagged) for i in range(n)]

    def test_flagged_reviews_block_best_and_show_red_flag(self):
        r = run_hot(reviews=self.reviews(3))
        self.assertIs(r.reasons["gates"]["counterfeit"], False)
        self.assertEqual(r.tier, "mid")
        self.assertTrue(r.reasons["summary"][0].startswith("⚠️ নকল"))
        self.assertIn("নকল/ডুপ্লিকেট", " ".join(r.reasons["notes"]))

    def test_single_complaint_is_below_threshold(self):
        r = run_hot(reviews=self.reviews(1))
        self.assertIs(r.reasons["gates"]["counterfeit"], True)
        self.assertEqual(r.tier, "best")

    def test_count_without_ratio_is_not_enough(self):
        r = run_hot(reviews=self.reviews(2, n=100))       # ২% < ৫%
        self.assertIs(r.reasons["gates"]["counterfeit"], True)

    def test_fake_flagged_reviews_are_not_counted(self):
        revs = [replace(x, suspected_fake=True) for x in self.reviews(5)] + self.reviews(0)
        self.assertEqual(run_hot(reviews=revs).reasons["detail"]["counterfeit"]["n"], 0)

    def test_can_be_disabled(self):
        cfg = load_config(override={"red_flags": {"enabled": False}})
        r = run_hot(cfg, reviews=self.reviews(5))
        self.assertNotIn("counterfeit", r.reasons["gates"])
        self.assertEqual(r.tier, "best")


class ConfigTests(unittest.TestCase):
    def test_bad_values_rejected(self):
        for bad in ({"margin": {"floor_pct": 40, "ceiling_pct": 30}}, {"margin": {"return_rate_pct": 100}},
                    {"competition": {"saturated_sellers": 1}}, {"red_flags": {"counterfeit": {"min_count": 0}}},
                    {"weights": {"margin": -1}}):
            with self.assertRaises(ConfigError, msg=str(bad)):
                load_config(override=bad)


class PreMigrationDB(FakeDB):
    """Phase 5 migration চলেনি: product_costs টেবিল ও reviews.flags কলাম নেই, REST ত্রুটি দেয়।"""
    def select(self, table, params=None, page_size=1000):
        if table == "product_costs" or (table == "reviews" and "flags" in (params or {}).get("select", "")):
            raise SupabaseError("HTTP 400/404")
        return super().select(table, params, page_size)


class RunnerTests(unittest.TestCase):
    def test_costs_sellers_and_flags_flow_into_products(self):
        pop = population()
        pop[-1] = hot_with(unit_cost=50.0, extra_cost=4.0, reviews=CounterfeitTests().reviews(3))
        prods = {p.id: p for p in run_scoring.fetch_products(FakeDB(pop), TODAY, CFG)}
        h = prods[100]
        self.assertEqual((h.unit_cost, h.extra_cost, h.sellers, h.listings), (50.0, 4.0, 1, 1))
        self.assertEqual(sum(r.counterfeit for r in h.reviews), 3)
        self.assertIsNone(prods[1].unit_cost)

    def test_scoring_still_runs_before_migration(self):
        out = run_scoring.run(PreMigrationDB(population()), CFG, TODAY, dry_run=True)
        self.assertEqual(out["summary"]["scored"], 21)
        self.assertEqual(out["summary"]["tiers"]["best"], 1)

    def test_written_row_shape_is_unchanged(self):
        db = FakeDB([hot_with(unit_cost=50.0)] + [filler(i) for i in range(1, 21)])
        run_scoring.run(db, CFG, TODAY)
        row = next(r for t, _, rows in db.upserts if t == "product_scores" for r in rows if r["canonical_product_id"] == 100)
        self.assertNotIn("margin", row)                   # নতুন কলাম লাগে না, মান reasons-এ থাকে
        self.assertIsNotNone(row["reasons"]["factors"]["margin"])
        self.assertEqual(row["reasons"]["detail"]["margin"]["unit_cost"], 50.0)


class ComplaintTopicTests(unittest.TestCase):
    def reviews(self, spec):
        """spec: [(sentiment, topics, count)]"""
        out = []
        for sent, topics, n in spec:
            out += [Review(4 if sent >= 0 else 1, TODAY - timedelta(days=len(out) % 40), False, sentiment=sent, topics=tuple(topics)) for _ in range(n)]
        return out + [Review(5, TODAY - timedelta(days=1), False) for _ in range(30 - len(out))]

    def test_negative_topics_are_counted_and_shown(self):
        r = run_hot(reviews=self.reviews([(-1, ["delivery", "quality"], 3), (-1, ["delivery"], 2), (1, ["quality"], 6)]))
        self.assertEqual(r.reasons["detail"]["complaints"]["topics"], {"delivery": 5, "quality": 3})
        text = " ".join(r.reasons["summary"] + r.reasons["notes"])
        self.assertIn("রিভিউয়ে বেশি অভিযোগ: ডেলিভারি (5টি), মান (3টি)", text)

    def test_positive_topics_are_not_complaints(self):
        r = run_hot(reviews=self.reviews([(1, ["quality"], 10)]))
        self.assertEqual(r.reasons["detail"]["complaints"]["topics"], {})

    def test_single_mention_is_below_threshold(self):
        r = run_hot(reviews=self.reviews([(-1, ["price"], 1)]))
        self.assertNotIn("রিভিউয়ে বেশি অভিযোগ", " ".join(r.reasons["summary"] + r.reasons["notes"]))

    def test_sentiment_never_changes_score_or_tier(self):
        base = run_hot()
        neg = run_hot(reviews=self.reviews([(-1, ["quality", "delivery"], 12)]))
        # একই তারকা, শুধু সেন্টিমেন্ট আলাদা: স্কোর ও ট্যাগ একই
        same_stars = run_hot(reviews=[Review(x.stars, x.day, False) for x in self.reviews([(-1, ["quality"], 12)])])
        self.assertEqual((neg.total, neg.tier), (same_stars.total, same_stars.tier))
        self.assertIsNotNone(base.total)

    def test_fake_reviews_are_excluded(self):
        revs = [replace(x, suspected_fake=True) for x in self.reviews([(-1, ["quality"], 6)])]
        self.assertEqual(run_hot(reviews=revs).reasons["detail"]["complaints"]["topics"], {})

    def test_runner_reads_sentiment_and_topics(self):
        pop = population()
        pop[-1] = hot_with(reviews=self.reviews([(-1, ["delivery"], 4)]))
        h = {p.id: p for p in run_scoring.fetch_products(FakeDB(pop), TODAY, CFG)}[100]
        self.assertEqual(sum(1 for r in h.reviews if r.sentiment == -1), 4)
        self.assertEqual(h.reviews[0].topics, ("delivery",))


if __name__ == "__main__":
    unittest.main()
