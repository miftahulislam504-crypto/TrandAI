import unittest
from datetime import date, timedelta

from trends import run_trends
from trends.config import load_config
from trends.fetcher import FetchFailed, RateLimited

CFG = load_config()
S = CFG["settings"]
TODAY = date(2026, 11, 10)
LAST = date(2026, 11, 1)


def raw(fn, n=53, last=LAST, partial_last=True):
    return [(last - timedelta(weeks=n - 1 - k), float(fn(k)), partial_last and k == n - 1) for k in range(n)]


class FakeDB:
    """ছোট in-memory PostgREST: select (ফিল্টার ছাড়া), upsert (কনফ্লিক্ট কী অনুযায়ী মার্জ, serial id)।"""

    def __init__(self):
        self.t = {"categories": [{"id": 1, "slug": "fashion"}, {"id": 2, "slug": "home"}, {"id": 3, "slug": "kitchen"}],
                  "trend_keywords": [], "trend_points": []}
        self.upsert_calls = []
        self._next = 1

    def select(self, table, params=None, page_size=1000):
        return [dict(r) for r in self.t[table]]

    def upsert(self, table, rows, on_conflict, returning=False, chunk=200):
        self.upsert_calls.append((table, on_conflict, [dict(r) for r in rows]))
        keys = on_conflict.split(",")
        out = []
        for r in rows:
            hit = next((x for x in self.t[table] if all(str(x.get(k)) == str(r.get(k)) for k in keys)), None)
            if hit is None:
                hit = {}
                if table == "trend_keywords":
                    hit["id"] = self._next
                    self._next += 1
                self.t[table].append(hit)
            hit.update(r)
            out.append(dict(hit))
        return out if returning else []


class FakeClient:
    """anchor ও শব্দ অনুযায়ী ছক বানানো সিরিজ ফেরত দেয়।"""

    def __init__(self, series_for=None, fail=None):
        self.calls = []
        self.series_for = series_for or (lambda kw, tf: raw(lambda k: 30) if tf == S["timeframe"] else [
            (LAST - timedelta(weeks=259 - k), 50 + 40 * __import__("math").sin(2 * 3.14159265 * k / 52), False) for k in range(260)])
        self.fail = fail or (lambda kws, tf, n: None)

    def interest(self, keywords, timeframe):
        self.calls.append((list(keywords), timeframe))
        err = self.fail(keywords, timeframe, len(self.calls))
        if err:
            raise err
        out = {}
        for k in keywords:
            if k == S["anchor"]:
                out[k] = raw(lambda i: 40) if timeframe == S["timeframe"] else []
            else:
                out[k] = self.series_for(k, timeframe)
        return out


def go(db, client, **kw):
    sleeps = []
    return run_trends.run(db, client, CFG, TODAY, sleep=sleeps.append, rand=lambda: 0.0, **kw), sleeps


class RunTests(unittest.TestCase):
    def test_disabled_categories_not_collected(self):
        db, client = FakeDB(), FakeClient()
        o, _ = go(db, client, enabled_categories={"home"})
        self.assertEqual(o["terms_total"], 24)              # শুধু home: ১২ entry × ২
        kws = {r["keyword"] for r in db.t["trend_keywords"]}
        self.assertIn("curtain", kws)
        self.assertNotIn("saree", kws)
        self.assertNotIn("yoga mat", kws)

    def test_named_disabled_category_still_runs(self):
        db, client = FakeDB(), FakeClient()
        o, _ = go(db, client, only_category="sports", enabled_categories={"home"}, do_seasonality=False)
        self.assertEqual(o["terms_total"], 16)              # ৮ entry × ২

    def test_full_run_writes_keywords_points_and_seasonality(self):
        db, client = FakeDB(), FakeClient()
        o, _ = go(db, client, only_category="home")
        self.assertEqual(o["terms_total"], 24)              # ১২ entry × (en+bn)
        self.assertEqual(o["statuses"], {"ok": 24})
        kws = db.t["trend_keywords"]
        self.assertEqual(len(kws), 24)
        k = next(x for x in kws if x["keyword"] == "bed sheet")
        self.assertEqual((k["lang"], k["group_key"], k["category_id"], k["last_status"]), ("en", "bed-sheet", 2, "ok"))
        self.assertEqual(k["last_fetched_on"], TODAY.isoformat())
        pts = [p for p in db.t["trend_points"] if p["keyword_id"] == k["id"]]
        self.assertEqual(len(pts), 52)                      # আংশিক সপ্তাহ বাদ
        self.assertEqual(pts[0]["value"], 75.0)             # raw ৩০ × ১০০ / anchor ৪০
        self.assertEqual((pts[0]["raw_value"], pts[0]["anchor_value"]), (30.0, 40.0))
        self.assertEqual(max(p["week_start"] for p in pts), (LAST - timedelta(weeks=1)).isoformat())
        # ধাপ ২: ৫ বছরের সিরিজ -> seasonal শনাক্ত
        self.assertTrue(k["seasonal"])
        self.assertEqual(k["seasonality_checked_on"], TODAY.isoformat())
        self.assertEqual(o["seasonality"]["updated"], 24)
        # রিকোয়েস্ট: ২৪/৪ = ৬ ব্যাচ (anchor সহ) + ২৪/৫ = ৫ ব্যাচ সিজনালিটি
        main = [c for c in client.calls if c[1] == S["timeframe"]]
        seas = [c for c in client.calls if c[1] != S["timeframe"]]
        self.assertEqual((len(main), len(seas)), (6, 5))
        self.assertTrue(all(c[0][0] == S["anchor"] and len(c[0]) == 5 for c in main))
        self.assertTrue(all(S["anchor"] not in c[0] for c in seas))

    def test_second_run_skips_fresh_keywords(self):
        db = FakeDB()
        go(db, FakeClient(), only_category="home")
        c2 = FakeClient()
        o, _ = go(db, c2, only_category="home")
        self.assertEqual((o["terms_selected"], o["skipped_fresh"]), (0, 24))
        self.assertEqual(c2.calls, [])
        o, _ = go(db, FakeClient(), only_category="home", force=True)
        self.assertEqual(o["terms_selected"], 24)

    def test_refreshes_after_refresh_days(self):
        db = FakeDB()
        go(db, FakeClient(), only_category="home")
        for r in db.t["trend_keywords"]:
            r["last_fetched_on"] = (TODAY - timedelta(days=S["refresh_days"])).isoformat()
        o, _ = go(db, FakeClient(), only_category="home", do_seasonality=False)
        self.assertEqual(o["terms_selected"], 24)
        # সিজনালিটি ৩০ দিনের মধ্যে, আবার চলে না
        c = FakeClient()
        go(db, c, only_category="home")
        self.assertFalse([x for x in c.calls if x[1] != S["timeframe"]])

    def test_dry_run_writes_nothing(self):
        db = FakeDB()
        o, _ = go(db, FakeClient(), only_category="home", dry_run=True)
        self.assertEqual(db.upsert_calls, [])
        self.assertEqual(o["statuses"], {"ok": 24})
        self.assertEqual(o["written_points"], 0)

    def test_runs_without_db(self):
        o, _ = go(None, FakeClient(), only_category="home", do_seasonality=False)
        self.assertEqual(o["statuses"], {"ok": 24})

    def test_rate_limit_stops_run_and_resumes_next_time(self):
        db = FakeDB()
        # ৩য় ব্যাচের (৩য় রিকোয়েস্ট) পর থেকে সব রেট-লিমিট
        client = FakeClient(fail=lambda kws, tf, n: RateLimited("429") if n >= 3 else None)
        o, _ = go(db, client, only_category="home")
        self.assertTrue(o["circuit_open"])
        self.assertEqual(o["statuses"], {"ok": 8})          # ২টা ব্যাচ × ৪
        self.assertEqual(o["seasonality"]["batches"], 0)    # সার্কিট খোলা, সিজনালিটি বাদ
        self.assertTrue(any("রেট-লিমিট" in h for h in o["hints"]))
        # আবার চালালে বাকি ১৬টা থেকে শুরু
        o2, _ = go(db, FakeClient(), only_category="home", do_seasonality=False)
        self.assertEqual((o2["terms_selected"], o2["skipped_fresh"]), (16, 8))
        self.assertEqual(o2["statuses"], {"ok": 16})

    def test_failed_batch_is_marked_error_and_retried_next_run(self):
        db = FakeDB()
        client = FakeClient(fail=lambda kws, tf, n: FetchFailed("boom") if n <= 3 else None)   # ১ম ব্যাচের ৩ চেষ্টাই ব্যর্থ
        o, _ = go(db, client, only_category="home", do_seasonality=False)
        self.assertEqual(o["statuses"], {"error": 4, "ok": 20})
        errs = [r for r in db.t["trend_keywords"] if r["last_status"] == "error"]
        self.assertEqual(len(errs), 4)
        self.assertTrue(all(r.get("last_fetched_on") is None for r in errs))
        o2, _ = go(db, FakeClient(), only_category="home", do_seasonality=False)
        self.assertEqual(o2["terms_selected"], 4)
        self.assertEqual(o2["statuses"], {"ok": 4})

    def test_weak_keywords_hint_about_anchor(self):
        client = FakeClient(series_for=lambda kw, tf: raw(lambda k: 3))      # সব শব্দ anchor-এর তুলনায় ছোট
        o, _ = go(None, client, only_category="home", do_seasonality=False)
        self.assertEqual(o["statuses"], {"low_volume": 24})
        self.assertTrue(any("anchor" in h for h in o["hints"]))

    def test_low_anchor_marks_error(self):
        class LowAnchor(FakeClient):
            def interest(self, keywords, timeframe):
                out = super().interest(keywords, timeframe)
                out[S["anchor"]] = raw(lambda i: 1)
                return out
        o, _ = go(FakeDB(), LowAnchor(), only_category="home", do_seasonality=False)
        self.assertEqual(o["statuses"], {"error": 24})
        self.assertTrue(any("anchor_low" in e for e in o["errors"]))

    def test_max_batches_limits_requests(self):
        c = FakeClient()
        o, _ = go(FakeDB(), c, max_batches=2, do_seasonality=False)
        self.assertEqual(len(c.calls), 2)
        self.assertEqual(o["statuses"], {"ok": 8})

    def test_no_data_keywords_store_no_points(self):
        db = FakeDB()
        client = FakeClient(series_for=lambda kw, tf: raw(lambda k: 0) if kw == "bed sheet" else raw(lambda k: 30))
        o, _ = go(db, client, only_category="home", do_seasonality=False)
        self.assertEqual(o["statuses"], {"ok": 23, "no_data": 1})
        k = next(x for x in db.t["trend_keywords"] if x["keyword"] == "bed sheet")
        self.assertEqual(k["last_status"], "no_data")
        self.assertFalse([p for p in db.t["trend_points"] if p["keyword_id"] == k["id"]])

    def test_seasonality_skips_unusable_keywords(self):
        db = FakeDB()
        client = FakeClient(series_for=lambda kw, tf: raw(lambda k: 0) if kw == "bed sheet" else (
            raw(lambda k: 30) if tf == S["timeframe"] else FakeClient().series_for(kw, tf)))
        o, _ = go(db, client, only_category="home")
        asked = [k for c in client.calls if c[1] != S["timeframe"] for k in c[0]]
        self.assertNotIn("bed sheet", asked)
        self.assertEqual(o["seasonality"]["updated"], 23)


class SmokeTests(unittest.TestCase):
    def test_smoke_report(self):
        probe = CFG["smoke"]["probe_terms"]
        levels = {"saree": 60, "air fryer": 8, "bed sheet": 20, "online shopping": 35, "daraz": 90}

        class C(FakeClient):
            def interest(self, keywords, timeframe):
                self.calls.append(keywords)
                if keywords == probe:
                    return {k: raw(lambda i: levels[k]) for k in keywords}
                return super().interest(keywords, timeframe)

        o = run_trends.smoke(C(), CFG, sleep=lambda s: None, rand=lambda: 0)
        self.assertEqual(o["suggested_anchor"], "online shopping")     # মাঝারি (median) ভলিউম
        self.assertTrue(o["pipeline"]["ok"])
        self.assertEqual({v["status"] for v in o["pipeline"]["keywords"].values()}, {"ok"})
        md = run_trends.smoke_markdown(o)
        self.assertIn("online shopping", md)
        self.assertIn("ok", md)

    def test_smoke_reports_blocking(self):
        c = FakeClient(fail=lambda k, tf, n: RateLimited("429 Too Many Requests"))
        o = run_trends.smoke(c, CFG, sleep=lambda s: None, rand=lambda: 0)
        self.assertIsNone(o["probe"])
        self.assertTrue(o["errors"])
        self.assertIn("429", run_trends.smoke_markdown(o))


class StaleTests(unittest.TestCase):
    def test_pick_stale_rules(self):
        terms = [{"keyword": k} for k in ("a", "b", "c", "d")]
        ex = {"a": {"last_fetched_on": "2026-11-09", "last_status": "ok"},
              "b": {"last_fetched_on": "2026-11-09", "last_status": "error"},
              "c": {"last_fetched_on": "2026-10-01", "last_status": "ok"}}
        got = [t["keyword"] for t in run_trends.pick_stale(terms, ex, TODAY, 6, False)]
        self.assertEqual(got, ["b", "c", "d"])


if __name__ == "__main__":
    unittest.main()
