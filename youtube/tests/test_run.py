import json
import os
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from trends.config import enabled_categories, load_config as load_trends_config
from trends.keywords import build_terms
from youtube import run_youtube as ry
from youtube.client import KeyRejected, QuotaExceeded, YouTubeError

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 22, 20, 0, tzinfo=timezone.utc)   # বাংলাদেশে ২০২৬-১১-২৩ ভোর
TODAY = "2026-11-23"

TRENDS = {
    "settings": {"use_bengali": True},
    "entries": [
        {"id": "air-fryer", "category": "kitchen", "q": "air fryer", "bn": "এয়ার ফ্রায়ার", "match": ["air fryer"]},
        {"id": "panjabi", "category": "fashion", "q": "panjabi", "bn": "পাঞ্জাবি", "match": ["panjabi"]},
        {"id": "kettle", "category": "kitchen", "q": "electric kettle", "match": ["kettle"]},
    ],
}


def cfg(**over):
    s = {"region": "BD", "window_days": 30, "max_results": 25, "order": "viewCount", "refresh_days": 14,
         "max_keywords_per_run": 40, "quota_budget": 6000, "search_cost": 100, "videos_cost": 1, "sleep_seconds": 0}
    s.update(over)
    return {"settings": s}


class FakeDB:
    def __init__(self, rows=None):
        self.rows, self.upserts, self.selects = rows or [], [], []

    def select(self, table, params=None, page_size=1000):
        self.selects.append((table, dict(params or {})))
        gt = (params or {}).get("fetched_on", "gt.").split("gt.", 1)[1]
        return [r for r in self.rows if r["fetched_on"] > gt]

    def upsert(self, table, rows, on_conflict, returning=False, chunk=200):
        self.upserts.append((table, on_conflict, [dict(r) for r in rows]))


class FakeClient:
    def __init__(self, views=(1000, 5000, 300), raise_on=None):
        self.views, self.raise_on, self.searches, self.video_calls = views, raise_on or {}, [], []

    def search(self, q, published_after, region, max_results, lang=None, order="viewCount"):
        self.searches.append({"q": q, "after": published_after, "region": region, "max": max_results, "lang": lang, "order": order})
        exc = self.raise_on.get(q)
        if exc:
            raise exc
        return [f"{q}-{i}" for i in range(len(self.views))]

    def videos(self, ids):
        self.video_calls.append(ids)
        return [{"id": i, "title": f"T {i}", "channel": "Ch", "published_at": None, "views": v} for i, v in zip(ids, self.views)]


def go(db=None, client=None, config=None, **kw):
    db = FakeDB() if db is None else db
    client = client or FakeClient()
    return ry.run(db, client, config or cfg(), TRENDS, NOW, sleep=lambda s: None, **kw), db, client


class RunTest(unittest.TestCase):
    def test_saves_one_row_per_term_with_summary(self):
        o, db, c = go()
        self.assertEqual((o["terms_total"], o["tried"], o["saved"], o["stopped"]), (5, 5, 5, None))
        table, conflict, rows = db.upserts[0]
        self.assertEqual((table, conflict), ("youtube_keyword_stats", "keyword,lang,region,fetched_on"))
        r = next(x for x in rows if x["keyword"] == "air fryer")
        self.assertEqual((r["lang"], r["category"], r["group_key"], r["region"], r["fetched_on"], r["window_days"]),
                         ("en", "kitchen", "air-fryer", "BD", TODAY, 30))
        self.assertEqual((r["videos"], r["views_total"], r["views_median"], r["top_video_views"]), (3, 6300, 1000, 5000))

    def test_bengali_term_uses_bn_language_and_window_start(self):
        _, _, c = go()
        by_q = {s["q"]: s for s in c.searches}
        self.assertEqual(by_q["এয়ার ফ্রায়ার"]["lang"], "bn")
        self.assertEqual(by_q["air fryer"]["lang"], "en")
        self.assertEqual(by_q["air fryer"]["after"], "2026-10-23T20:00:00Z")
        self.assertEqual((by_q["air fryer"]["region"], by_q["air fryer"]["max"], by_q["air fryer"]["order"]), ("BD", 25, "viewCount"))

    def test_quota_accounting(self):
        o, _, _ = go()
        self.assertEqual(o["quota_used"], 5 * 101)

    def test_no_videos_found_costs_only_search(self):
        o, db, _ = go(client=FakeClient(views=()))
        self.assertEqual(o["quota_used"], 5 * 100)
        self.assertEqual(db.upserts[0][2][0]["videos"], 0)
        self.assertIsNone(db.upserts[0][2][0]["views_total"])

    def test_recently_fetched_terms_skipped_and_stale_ones_redone(self):
        rows = [{"keyword": "air fryer", "lang": "en", "fetched_on": "2026-11-20"},     # ৩ দিন আগে: বাদ
                {"keyword": "panjabi", "lang": "en", "fetched_on": "2026-11-01"}]        # ২২ দিন আগে: আবার
        o, db, c = go(db=FakeDB(rows))
        self.assertEqual((o["due"], o["tried"]), (4, 4))
        self.assertNotIn("air fryer", [s["q"] for s in c.searches])
        self.assertIn("panjabi", [s["q"] for s in c.searches])
        self.assertEqual(db.selects[0][1]["region"], "eq.BD")
        self.assertEqual(db.selects[0][1]["fetched_on"], "gt.2026-11-09")   # আজ − ১৪ দিন

    def test_force_ignores_recent(self):
        rows = [{"keyword": "air fryer", "lang": "en", "fetched_on": "2026-11-22"}]
        o, db, _ = go(db=FakeDB(rows), force=True)
        self.assertEqual(o["tried"], 5)
        self.assertEqual(db.selects, [])

    def test_caps_per_run_and_cli_limit(self):
        o, _, _ = go(config=cfg(max_keywords_per_run=2))
        self.assertEqual((o["tried"], o["due"]), (2, 5))
        o, _, _ = go(limit=3)
        self.assertEqual(o["tried"], 3)
        o, _, _ = go(config=cfg(max_keywords_per_run=2), limit=4)   # limit config-এর সীমা ছাড়ায় না
        self.assertEqual(o["tried"], 2)

    def test_quota_budget_stops_before_overspending(self):
        o, db, _ = go(config=cfg(quota_budget=250))   # ২টা শব্দ (২০২), তৃতীয়টায় ৩০৩ > ২৫০
        self.assertEqual((o["tried"], o["stopped"], o["quota_used"]), (2, "quota_budget", 202))
        self.assertEqual(len(db.upserts[0][2]), 2)

    def test_quota_exceeded_from_api_keeps_partial_results(self):
        c = FakeClient(raise_on={"panjabi": QuotaExceeded("দৈনিক কোটা শেষ")})
        o, db, _ = go(client=c)
        self.assertEqual(o["stopped"], "quota_exceeded")
        self.assertEqual([r["keyword"] for r in db.upserts[0][2]], ["air fryer", "এয়ার ফ্রায়ার"])

    def test_key_rejected_stops_and_saves_nothing(self):
        c = FakeClient(raise_on={"air fryer": KeyRejected("key গ্রহণ হয়নি")})
        o, db, _ = go(client=c)
        self.assertEqual((o["stopped"], o["tried"], db.upserts), ("key_rejected", 0, []))

    def test_single_term_error_is_skipped_not_fatal(self):
        c = FakeClient(raise_on={"panjabi": YouTubeError("HTTP 500")})
        o, db, _ = go(client=c)
        self.assertEqual((o["tried"], o["saved"], o["stopped"]), (5, 4, None))
        self.assertIn("panjabi: HTTP 500", o["errors"])

    def test_dry_run_writes_nothing(self):
        o, db, _ = go(dry_run=True)
        self.assertEqual((o["saved"], db.upserts, len(o["results"])), (0, [], 5))

    def test_no_db_dry_run_treats_everything_as_due(self):
        o = ry.run(None, FakeClient(), cfg(), TRENDS, NOW, dry_run=True, sleep=lambda s: None)
        self.assertEqual(o["tried"], 5)

    def test_disabled_category_skipped_unless_named(self):
        o, _, c = go(enabled={"kitchen"})
        self.assertEqual(sorted({s["q"] for s in c.searches}), ["air fryer", "electric kettle", "এয়ার ফ্রায়ার"])
        o, _, c = go(only_category="fashion", enabled={"kitchen"})
        self.assertEqual(sorted({s["q"] for s in c.searches}), ["panjabi", "পাঞ্জাবি"])

    def test_bd_today_is_utc_plus_6(self):
        self.assertEqual(ry.bd_today(NOW).isoformat(), TODAY)

    def test_summary_markdown_mentions_stop_and_errors(self):
        o, _, _ = go(config=cfg(quota_budget=250), dry_run=True)
        md = ry.summary_markdown(o)
        self.assertIn("quota_budget", md)
        self.assertIn("ড্রাই-রান", md)
        self.assertIn("| air fryer |", md)


class ConfigTest(unittest.TestCase):
    def test_real_config_is_valid_and_fits_free_quota(self):
        s = ry.load_config()["settings"]
        self.assertLessEqual(s["max_keywords_per_run"] * (s["search_cost"] + s["videos_cost"]), s["quota_budget"])
        self.assertLessEqual(s["quota_budget"], 10000)       # বিনামূল্যে দৈনিক সীমা
        self.assertEqual((s["search_cost"], s["videos_cost"]), (100, 1))

    def test_real_terms_cover_every_enabled_category(self):
        terms = build_terms(load_trends_config(), None, None, enabled_categories())
        self.assertGreater(len(terms), 100)
        self.assertEqual({t["category"] for t in terms}, enabled_categories())

    def test_rejects_bad_settings(self):
        base = json.loads((ROOT / "config" / "youtube.json").read_text(encoding="utf-8"))
        for key, bad in (("region", "Bangladesh"), ("order", "popular"), ("max_results", 80), ("window_days", 0),
                         ("refresh_days", 0), ("quota_budget", 50)):
            d = json.loads(json.dumps(base))
            d["settings"][key] = bad
            p = ROOT / "run-output" / "_yt_bad.json"
            p.parent.mkdir(exist_ok=True)
            p.write_text(json.dumps(d), encoding="utf-8")
            try:
                with self.assertRaises(ry.YouTubeConfigError, msg=key):
                    ry.load_config(p)
            finally:
                p.unlink()

    def test_migration_columns_cover_every_written_field(self):
        sql = next((ROOT / "supabase" / "migrations").glob("*phase11b.sql")).read_text(encoding="utf-8")
        cols = set(re.findall(r"^\s{2}(\w+)\s+(?:bigserial|text|int|bigint|date|timestamptz)\b", sql, re.M))
        o, db, _ = go()
        written = set(db.upserts[0][2][0])
        self.assertEqual(written - cols, set())
        self.assertIn("unique (keyword, lang, region, fetched_on)", sql)    # on_conflict-এর সাথে মেলে

    def test_workflow_secret_and_schedule(self):
        wf = (ROOT / ".github" / "workflows" / "youtube-daily.yml").read_text(encoding="utf-8")
        self.assertIn("YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}", wf)
        self.assertIn("python -m youtube.run_youtube", wf)
        self.assertIn("cron:", wf)


class MainTest(unittest.TestCase):
    def test_missing_key_skips_with_exit_0(self):
        with mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}):
            self.assertEqual(ry.main([]), 0)

    def test_missing_supabase_env_fails_unless_dry_run(self):
        env = {"YOUTUBE_API_KEY": "k", "SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": ""}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(ry.main([]), 1)


if __name__ == "__main__":
    unittest.main()
