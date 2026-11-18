import unittest
from datetime import date, timedelta

from alerts.config import AlertsConfigError, load_config, validate
from alerts.detect import Score, detect, price_move, price_moves, redflag, score_move, tier_change

CFG = load_config()
TODAY = date(2026, 11, 20)
NAMES = {1: "পাঞ্জাবি", 2: "Air Fryer"}


def sc(pid=1, days_ago=0, tier="mid", total=50.0, cf=0, conf="high"):
    return Score(pid, TODAY - timedelta(days=days_ago), tier, total, conf, cf)


class TierChangeTests(unittest.TestCase):
    def test_watched_any_change_alerts(self):
        a = tier_change(sc(tier="dont"), sc(days_ago=1, tier="mid"), True, CFG, NAMES)
        self.assertEqual((a["kind"], a["severity"], a["watched"]), ("tier_change", "warn", True))
        self.assertEqual(a["title"], "পাঞ্জাবি: Mid → Don't")
        self.assertEqual((a["detail"]["from"], a["detail"]["to"]), ("mid", "dont"))

    def test_up_is_good(self):
        a = tier_change(sc(tier="best"), sc(days_ago=1, tier="mid"), True, CFG, NAMES)
        self.assertEqual(a["severity"], "good")
        a = tier_change(sc(tier="mid"), sc(days_ago=1, tier="dont"), True, CFG, NAMES)
        self.assertEqual(a["severity"], "good")

    def test_unwatched_only_discovery_tiers(self):
        self.assertIsNotNone(tier_change(sc(tier="best"), sc(days_ago=1, tier="mid"), False, CFG, NAMES))
        self.assertIsNone(tier_change(sc(tier="dont"), sc(days_ago=1, tier="mid"), False, CFG, NAMES))
        self.assertIsNone(tier_change(sc(tier="mid"), sc(days_ago=1, tier="best"), False, CFG, NAMES))

    def test_discovery_can_be_turned_off_or_widened(self):
        off = {**CFG, "discovery": {"enabled": False, "tiers": ["best"]}}
        self.assertIsNone(tier_change(sc(tier="best"), sc(days_ago=1, tier="mid"), False, off, NAMES))
        wide = {**CFG, "discovery": {"enabled": True, "tiers": ["best", "dont"]}}
        self.assertIsNotNone(tier_change(sc(tier="dont"), sc(days_ago=1, tier="mid"), False, wide, NAMES))

    def test_no_alert_when_same_first_time_or_unscored(self):
        self.assertIsNone(tier_change(sc(tier="mid"), sc(days_ago=1, tier="mid"), True, CFG, NAMES))
        self.assertIsNone(tier_change(sc(tier="mid"), None, True, CFG, NAMES))
        self.assertIsNone(tier_change(sc(tier=None, total=None), sc(days_ago=1), True, CFG, NAMES))
        self.assertIsNone(tier_change(sc(tier="mid"), sc(days_ago=1, tier=None), True, CFG, NAMES))

    def test_unknown_name_falls_back_to_id_and_long_names_are_cut(self):
        a = tier_change(sc(pid=9, tier="best"), sc(pid=9, days_ago=1), True, CFG, {})
        self.assertTrue(a["title"].startswith("প্রোডাক্ট #9:"))
        a = tier_change(sc(tier="best"), sc(days_ago=1), True, CFG, {1: "x" * 200})
        self.assertLess(len(a["title"].split(":")[0]), 70)


class ScoreMoveTests(unittest.TestCase):
    def hist(self, *pairs):
        return [sc(days_ago=d, total=t) for d, t in pairs]  # নতুন -> পুরনো

    def test_big_drop_and_rise(self):
        a = score_move(sc(total=40), self.hist((1, 52), (7, 60)), CFG, NAMES)
        self.assertEqual((a["severity"], a["detail"]["days"]), ("warn", 7))
        self.assertEqual((a["detail"]["from_score"], a["detail"]["to_score"]), (60.0, 40.0))
        a = score_move(sc(total=80), self.hist((7, 60)), CFG, NAMES)
        self.assertEqual(a["severity"], "good")

    def test_boundary_is_inclusive(self):
        self.assertIsNotNone(score_move(sc(total=75), self.hist((7, 60)), CFG, NAMES))        # ঠিক ১৫
        self.assertIsNone(score_move(sc(total=74.9), self.hist((7, 60)), CFG, NAMES))

    def test_uses_nearest_row_at_least_days_old_within_gap(self):
        # ৫ দিন আগের সারি যথেষ্ট পুরনো নয়; ৯ দিন আগেরটা নেয়
        a = score_move(sc(total=30), self.hist((5, 60), (9, 55)), CFG, NAMES)
        self.assertEqual(a["detail"]["days"], 9)
        self.assertIsNone(score_move(sc(total=30), self.hist((5, 60)), CFG, NAMES))
        self.assertIsNone(score_move(sc(total=30), self.hist((20, 60)), CFG, NAMES))           # max_gap ১৪-র বাইরে

    def test_missing_totals(self):
        self.assertIsNone(score_move(sc(total=None), self.hist((7, 60)), CFG, NAMES))
        self.assertIsNone(score_move(sc(total=30), [sc(days_ago=7, total=None)], CFG, NAMES))


class PriceTests(unittest.TestCase):
    def test_price_moves_uses_median_not_mean(self):
        rows = [{"canonical_product_id": 1, "price": 100, "price_delta_7d": -1},
                {"canonical_product_id": 1, "price": 100, "price_delta_7d": 0},
                {"canonical_product_id": 1, "price": 10, "price_delta_7d": -9}]   # একটা অস্বাভাবিক ছাড়
        # বদল: −০.৯৯%, ০%, −৪৭.৪%। মধ্যমা −১.০%; গড় হলে প্রায় −১৬% হতো ও অ্যালার্ট ভুলে বাজত
        self.assertEqual(price_moves(rows), {1: -1.0})

    def test_price_moves_skips_missing_and_bad_rows(self):
        rows = [{"canonical_product_id": 1, "price": None, "price_delta_7d": 5},
                {"canonical_product_id": 1, "price": 100, "price_delta_7d": None},
                {"canonical_product_id": None, "price": 100, "price_delta_7d": 5},
                {"canonical_product_id": 2, "price": 50, "price_delta_7d": 50}]    # আগের দাম ০ => বাদ
        self.assertEqual(price_moves(rows), {})
        self.assertEqual(price_moves([{"canonical_product_id": 3, "price": 90, "price_delta_7d": -10}]), {3: -10.0})

    def test_price_move_threshold_and_severity(self):
        self.assertIsNone(price_move(1, -9.9, TODAY, CFG, NAMES))
        self.assertIsNone(price_move(1, None, TODAY, CFG, NAMES))
        down = price_move(1, -12.4, TODAY, CFG, NAMES)
        self.assertEqual((down["severity"], down["detail"]["pct"]), ("warn", -12.4))
        self.assertIn("কমেছে", down["title"])
        up = price_move(1, 10, TODAY, CFG, NAMES)
        self.assertEqual(up["severity"], "info")
        self.assertIn("বেড়েছে", up["title"])


class RedflagTests(unittest.TestCase):
    def test_fires_only_when_crossing(self):
        self.assertIsNotNone(redflag(sc(cf=2), sc(days_ago=1, cf=1), CFG, NAMES))
        self.assertIsNotNone(redflag(sc(cf=3), None, CFG, NAMES))
        self.assertIsNone(redflag(sc(cf=1), sc(days_ago=1, cf=0), CFG, NAMES))        # সীমার নিচে
        self.assertIsNone(redflag(sc(cf=4), sc(days_ago=1, cf=2), CFG, NAMES))        # আগেই ছিল, আবার নয়


class DetectTests(unittest.TestCase):
    def test_unwatched_gets_only_discovery_watched_gets_all(self):
        today = {1: sc(1, tier="best", total=80, cf=2), 2: sc(2, tier="best", total=80, cf=2)}
        hist = {1: [sc(1, 1, "mid", 79), sc(1, 7, "mid", 50)], 2: [sc(2, 1, "mid", 79), sc(2, 7, "mid", 50)]}
        out = detect(today, hist, {1}, {1: -20.0, 2: -20.0}, NAMES, CFG, TODAY)
        kinds = sorted((a["canonical_product_id"], a["kind"]) for a in out)
        self.assertEqual(kinds, [(1, "price_move"), (1, "redflag"), (1, "score_move"), (1, "tier_change"), (2, "tier_change")])
        self.assertTrue(all(a["created_on"] == TODAY.isoformat() for a in out))

    def test_quiet_day_has_no_alerts(self):
        today = {1: sc(1, tier="mid", total=50)}
        hist = {1: [sc(1, 1, "mid", 49), sc(1, 7, "mid", 48)]}
        self.assertEqual(detect(today, hist, {1}, {1: 2.0}, NAMES, CFG, TODAY), [])


class ConfigTests(unittest.TestCase):
    def bad(self, **over):
        import copy
        cfg = copy.deepcopy(CFG)
        for k, v in over.items():
            a, _, b = k.partition("__")
            if b:
                cfg[a][b] = v
            else:
                cfg[a] = v
        with self.assertRaises(AlertsConfigError):
            validate(cfg)

    def test_rejects_bad_values(self):
        self.bad(score_move__points=0)
        self.bad(score_move__days=100)
        self.bad(score_move__max_gap_days=3)
        self.bad(price_move__pct=True)
        self.bad(price_move__pct="10")
        self.bad(keep_days=3)
        self.bad(telegram__max_items=0)
        self.bad(discovery__tiers=["gold"])
        self.bad(discovery__tiers=[])
        self.bad(discovery__enabled="yes")

    def test_shipped_config_is_valid(self):
        self.assertEqual(CFG["score_move"]["points"], 15)


if __name__ == "__main__":
    unittest.main()
