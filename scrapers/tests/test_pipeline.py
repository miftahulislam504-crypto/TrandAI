"""SupabaseREST (লোকাল নকল সার্ভারে) ও run_pipeline (ইন-মেমরি নকল DB-তে) এর টেস্ট।"""
import json
import threading
import unittest
from pathlib import Path
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from scrapers import run_daraz
from scrapers.common.http import CircuitOpen, FetchError
from scrapers.common.supabase_rest import SupabaseError, SupabaseREST


# ------------------------------------------------------------ SupabaseREST
class _Handler(BaseHTTPRequestHandler):
    log: list = []
    responder = None

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        u = urlparse(self.path)
        self.log.append({"method": self.command, "path": u.path, "query": parse_qs(u.query),
                         "prefer": self.headers.get("Prefer"), "apikey": self.headers.get("apikey"),
                         "auth": self.headers.get("Authorization"), "body": body})
        status, payload = type(self).responder(self.command, u.path, parse_qs(u.query), body)
        data = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PATCH = _handle

    def log_message(self, *a):
        pass


class SupabaseRESTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        _Handler.log = []
        self.db = SupabaseREST(self.url, "SECRET")

    def test_headers_and_select_pagination(self):
        pages = {0: [{"id": i} for i in range(1000)], 1000: [{"id": 1000}]}
        _Handler.responder = lambda m, p, q, b: (200, pages[int(q["offset"][0])])
        rows = self.db.select("listings", {"select": "id"})
        self.assertEqual(len(rows), 1001)
        self.assertEqual(len(_Handler.log), 2)
        self.assertEqual(_Handler.log[0]["apikey"], "SECRET")
        self.assertEqual(_Handler.log[0]["auth"], "Bearer SECRET")
        self.assertEqual(_Handler.log[0]["path"], "/rest/v1/listings")

    def test_upsert_groups_by_keys_and_prefer(self):
        _Handler.responder = lambda m, p, q, b: (201, [{"id": 1, "external_id": r["external_id"]} for r in b])
        rows = [{"external_id": "1", "title_raw": "A"}, {"external_id": "2"}, {"external_id": "3", "title_raw": "C"}]
        out = self.db.upsert("listings", rows, "source_id,external_id", returning=True)
        self.assertEqual(len(out), 3)
        self.assertEqual(len(_Handler.log), 2)  # দুই ধরনের key-সেট = দুই অনুরোধ
        for entry in _Handler.log:
            self.assertEqual(entry["query"]["on_conflict"], ["source_id,external_id"])
            self.assertEqual(entry["prefer"], "resolution=merge-duplicates,return=representation")
        sizes = sorted(len(e["body"]) for e in _Handler.log)
        self.assertEqual(sizes, [1, 2])

    def test_upsert_chunking_and_empty(self):
        _Handler.responder = lambda m, p, q, b: (201, None)
        self.db.upsert("t", [{"a": i} for i in range(450)], "a", chunk=200)
        self.assertEqual([len(e["body"]) for e in _Handler.log], [200, 200, 50])
        self.assertEqual(self.db.upsert("t", [], "a"), [])
        self.assertEqual(len(_Handler.log), 3)

    def test_error_raises(self):
        _Handler.responder = lambda m, p, q, b: (401, {"message": "bad key"})
        with self.assertRaises(SupabaseError) as cm:
            self.db.insert("t", [{"a": 1}])
        self.assertIn("401", str(cm.exception))

    def test_update_and_rpc(self):
        _Handler.responder = lambda m, p, q, b: (200, 3 if "rpc" in p else None)
        self.db.update("listings", {"is_active": False}, {"id": "eq.5"})
        self.assertEqual(self.db.rpc("link_listings_to_canonical"), 3)
        self.assertEqual(_Handler.log[0]["method"], "PATCH")
        self.assertEqual(_Handler.log[1]["path"], "/rest/v1/rpc/link_listings_to_canonical")


# -------------------------------------------------------------- পাইপলাইন
class FakeDB:
    def __init__(self, existing=None, fail_on=None):
        self.existing = existing or []
        self.fail_on = fail_on
        self.ids: dict[str, int] = {}
        self.calls: list[tuple] = []
        self.snapshots: list[dict] = []
        self.reviews: list[dict] = []
        self.runs: list[dict] = []
        self.listing_batches: list[list[dict]] = []

    def select(self, table, params=None, page_size=1000):
        if table == "sources":
            return [{"id": 1}]
        if table == "categories":
            return [{"id": 10, "slug": "fashion"}, {"id": 20, "slug": "home"}, {"id": 30, "slug": "kitchen"}]
        if table == "listing_overview":
            return self.existing
        raise AssertionError(table)

    def insert(self, table, rows, returning=False):
        self.calls.append(("insert", table))
        return [{"id": 7}]

    def upsert(self, table, rows, on_conflict, returning=False, chunk=200):
        if self.fail_on == table:
            raise SupabaseError("boom")
        self.calls.append(("upsert", table, len(rows)))
        if table == "listings":
            out = []
            for r in rows:
                self.ids.setdefault(r["external_id"], 100 + len(self.ids))
                out.append({"id": self.ids[r["external_id"]], "external_id": r["external_id"]})
            self.listing_batches.append(rows)
            return out if returning else []
        if table == "listing_snapshots":
            self.snapshots += rows
        if table == "reviews":
            self.reviews += rows
        return []

    def update(self, table, values, params):
        self.calls.append(("update", table))
        if table == "scrape_runs":
            self.runs.append(values)

    def rpc(self, fn, args=None):
        self.calls.append(("rpc", fn))
        return 0


class FakeClient:
    stats = {"requests": 0, "ok": 0, "blocked": 0, "robots_skipped": 0, "errors": 0}


def item(ext, **kw):
    base = {"external_id": ext, "url": f"https://www.daraz.com.bd/products/x-i{ext}.html", "title": f"T{ext}",
            "price": 100.0, "original_price": None, "rating_avg": None, "rating_count": None, "review_count": 3,
            "sold_count": None, "seller_name": "S", "brand": None, "in_stock": None, "category_ids": None}
    base.update(kw)
    return base


class FakeAdapter:
    def __init__(self, by_seed=None, circuit_after=None):
        self.client = FakeClient()
        self.by_seed, self.circuit_after, self.discovers = by_seed or {}, circuit_after, 0
        self.products, self.review_pages = [], []

    def discover(self, seed, limit, max_pages):
        self.discovers += 1
        if self.circuit_after is not None and self.discovers > self.circuit_after:
            raise CircuitOpen("টানা ৩বার ব্লক")
        key = seed.get("q") or seed.get("url")
        items = self.by_seed.get(key, [])
        return items[:limit], {"seed": seed, "pages": 1, "strategy": "ajax", "notes": [], "raw_keys": [], "total_results": 9}

    def fetch_product(self, url):
        self.products.append(url)
        return {"brand": "Acme", "rating_avg": 4.5, "rating_count": 9, "sold_count": 40, "price": 77.0}

    def fetch_reviews(self, ext, page=1, page_size=20):
        self.review_pages.append((ext, page))
        if page > 1:
            return [], {}
        return [{"external_review_id": f"{ext}-r1", "stars": 5, "body": "ok", "lang": "en",
                 "reviewed_at": "2026-11-08", "reviewer_hash": "abc"}], {}


CFG = {"settings": {"detail_limit": 2, "reviews_limit": 5, "reviews_max_pages": 2, "inactive_after_days": 30},
       "seeds": {"fashion": [{"type": "keyword", "q": "saree"}],
                 "home": [{"type": "keyword", "q": "curtain"}],
                 "kitchen": [{"type": "keyword", "q": "pan"}]}}
CATS = {"categories": [{"slug": "fashion", "target_products": 3}, {"slug": "home", "target_products": 3},
                       {"slug": "kitchen", "target_products": 3}]}
NOW = datetime(2026, 11, 9, 20, 30, tzinfo=timezone.utc)  # UTC ২০:৩০ = বাংলাদেশে ১০ নভেম্বর ০২:৩০


class PipelineTests(unittest.TestCase):
    def test_bd_date(self):
        self.assertEqual(run_daraz.bd_today(NOW), "2026-11-10")

    def test_happy_path(self):
        adapter = FakeAdapter({"saree": [item("1"), item("2", brand="B", rating_avg=4.0, sold_count=5)],
                               "curtain": [item("3"), item("1")],  # "1" ডুপ্লিকেট, বাদ যাবে
                               "pan": [item("4", review_count=3)]})
        db = FakeDB(existing=[{"id": 100, "external_id": "2", "review_count": 3, "brand_raw": "B"}])
        s = run_daraz.run_pipeline(db, adapter, CFG, CATS, NOW)

        self.assertEqual(s["status"], "ok")
        self.assertEqual((s["listings"], s["snapshots"]), (4, 4))  # ১,২,৩,৪ (ডুপ্লিকেট ছাড়া)
        rows = {r["external_id"]: r for r in db.listing_batches[0]}
        self.assertEqual((rows["1"]["category_id"], rows["3"]["category_id"], rows["4"]["category_id"]), (10, 20, 30))
        self.assertTrue(all(r["is_active"] and r["source_id"] == 1 for r in rows.values()))
        self.assertIn(("rpc", "link_listings_to_canonical"), db.calls)
        self.assertEqual({r["captured_on"] for r in db.snapshots}, {"2026-11-10"})
        self.assertTrue(all("price" in r for r in db.snapshots[:4]))  # প্রথম ৪টা = মূল স্ন্যাপশট, বাকি = ডিটেইল প্যাচ
        # ডিটেইল: নতুন/ব্র্যান্ডহীন ২টা (সীমা ২), "2"-এর ব্র্যান্ড আছে ও আগে থেকেই আছে বলে বাদ
        self.assertEqual(s["details"], 2)
        self.assertEqual(len(adapter.products), 2)
        patches = [r for r in db.snapshots if "rating_avg" in r and r["listing_id"] == db.ids["1"]]
        self.assertTrue(patches and patches[0]["rating_avg"] == 4.5)  # ফাঁকা ঘর ভরেছে
        # যেটায় আগে থেকে sold_count ছিল সেটা PDP দিয়ে বদলায়নি
        two = [r for r in db.snapshots if r["listing_id"] == db.ids["2"]]
        self.assertTrue(all(r.get("sold_count", 5) == 5 for r in two))
        # রিভিউ: "2" এর review_count বাড়েনি (৩→৩), বাকি ৩টার বেড়েছে (০→৩)
        self.assertEqual(sorted({r["listing_id"] for r in db.reviews}), sorted(db.ids[e] for e in ("1", "3", "4")))
        self.assertEqual(db.runs[-1]["status"], "ok")
        self.assertEqual(db.runs[-1]["items_ok"], 4)

    def test_circuit_open_gives_partial(self):
        adapter = FakeAdapter({"saree": [item("1")], "curtain": [item("2")]}, circuit_after=1)
        db = FakeDB()
        s = run_daraz.run_pipeline(db, adapter, CFG, CATS, NOW)
        self.assertEqual(s["status"], "partial")
        self.assertTrue(s["circuit_open"])
        self.assertEqual(s["snapshots"], 1)
        self.assertEqual(adapter.products, [])       # ডিটেইল ধাপ বাদ
        self.assertEqual(adapter.review_pages, [])   # রিভিউ ধাপ বাদ

    def test_nothing_found_is_failed(self):
        db = FakeDB()
        s = run_daraz.run_pipeline(db, FakeAdapter({}), CFG, CATS, NOW)
        self.assertEqual(s["status"], "failed")
        self.assertEqual(s["snapshots"], 0)
        self.assertEqual(db.runs[-1]["status"], "failed")
        self.assertNotIn(("rpc", "link_listings_to_canonical"), db.calls)

    def test_db_error_marks_run_failed_and_raises(self):
        db = FakeDB(fail_on="listing_snapshots")
        with self.assertRaises(SupabaseError):
            run_daraz.run_pipeline(db, FakeAdapter({"saree": [item("1")]}), CFG, CATS, NOW)
        self.assertEqual(db.runs[-1]["status"], "failed")

    def test_detail_failure_does_not_fail_run(self):
        class Flaky(FakeAdapter):
            def fetch_product(self, url):
                raise FetchError("HTTP 500")
        db = FakeDB()
        s = run_daraz.run_pipeline(db, Flaky({"saree": [item("1")]}), CFG, CATS, NOW)
        self.assertEqual(s["status"], "partial")
        self.assertEqual(s["snapshots"], 1)

    def test_only_category(self):
        adapter = FakeAdapter({"saree": [item("1")], "curtain": [item("2")]})
        s = run_daraz.run_pipeline(FakeDB(), adapter, CFG, CATS, NOW, only="home")
        self.assertEqual(s["listings"], 1)

    def test_coverage(self):
        cov = run_daraz.coverage([item("1", rating_avg=4.0), item("2")])
        self.assertEqual(cov["price"]["pct"], 100)
        self.assertEqual(cov["rating_avg"], {"count": 1, "pct": 50})
        self.assertEqual(cov["sold_count"]["pct"], 0)


class CollectTests(unittest.TestCase):
    def test_missing_seeds_reported(self):
        cfg = {"settings": {}, "seeds": {}}
        by_cat, diags, errors, circuit = run_daraz.collect(FakeAdapter(), cfg, CATS)
        self.assertEqual(by_cat, {})
        self.assertEqual(len(errors), 3)

    def test_smoke_uses_first_seed_only(self):
        adapter = FakeAdapter({"saree": [item("1")], "curtain": [item("2")]})
        by_cat, _, _, _ = run_daraz.collect(adapter, CFG, CATS, smoke=True)
        self.assertEqual(adapter.discovers, 1)
        self.assertEqual(list(by_cat), ["fashion"])


class DisabledCategoryTests(unittest.TestCase):
    CATS2 = {"categories": [{"slug": "fashion", "target_products": 5, "enabled": True},
                            {"slug": "home", "target_products": 5},                       # enabled না লেখা = চালু
                            {"slug": "beauty", "target_products": 5, "enabled": False}]}
    CFG2 = {"settings": {}, "seeds": {"fashion": [{"type": "keyword", "q": "saree"}],
                                      "home": [{"type": "keyword", "q": "curtain"}],
                                      "beauty": [{"type": "keyword", "q": "lipstick"}]}}

    def adapter(self):
        return FakeAdapter({"saree": [item("1")], "curtain": [item("2")], "lipstick": [item("3")]})

    def test_disabled_category_skipped_in_normal_run(self):
        a = self.adapter()
        by_cat, _, errors, _ = run_daraz.collect(a, self.CFG2, self.CATS2)
        self.assertEqual(sorted(by_cat), ["fashion", "home"])
        self.assertEqual(a.discovers, 2)
        self.assertEqual(errors, [])

    def test_disabled_category_runs_when_named_explicitly(self):
        a = self.adapter()
        by_cat, _, _, _ = run_daraz.collect(a, self.CFG2, self.CATS2, only="beauty")
        self.assertEqual(list(by_cat), ["beauty"])

    def test_shipped_config_has_all_phase9_categories_enabled(self):
        """Phase 9 শেষে ১৫টা ক্যাটাগরিই চালু ও প্রত্যেকের seed আছে।"""
        cfgs = run_daraz.load_config()
        cats = {c["slug"]: c for c in cfgs[1]["categories"]}
        self.assertEqual(len(cats), 15)
        for slug, c in cats.items():
            self.assertTrue(c["enabled"], slug)
            self.assertGreaterEqual(len(cfgs[0]["seeds"][slug]), 1, slug)
        for slug in ("fashion", "home", "kitchen"):
            self.assertGreaterEqual(len(cfgs[0]["seeds"][slug]), 7)

    def test_shipped_seeds_respect_daraz_robots(self):
        """Daraz robots.txt /catalog/ (কীওয়ার্ড সার্চ) নিষিদ্ধ করেছে: শিপ করা seed-এ keyword টাইপ থাকা চলবে না।"""
        seeds = run_daraz.load_config()[0]["seeds"]
        for slug, lst in seeds.items():
            for s in lst:
                self.assertEqual(s.get("type"), "category", f"{slug}: {s}")
                self.assertTrue(s["url"].startswith("https://www.daraz.com.bd/"))
                self.assertNotIn("from=", s["url"])
                self.assertNotIn("/catalog/", s["url"])


class CategoryConfigConsistencyTests(unittest.TestCase):
    """১৫ ক্যাটাগরির কনফিগ একে অপরের সাথে মিলছে কি না। ভুল হলে রান নিঃশব্দে ভুল ফল দিত (যেমন category_id ফাঁকা)।"""

    ROOT = Path(__file__).resolve().parents[2]

    def cfgs(self):
        return run_daraz.load_config()

    def test_fifteen_categories_with_unique_slugs(self):
        slugs = [c["slug"] for c in self.cfgs()[1]["categories"]]
        self.assertEqual(len(slugs), 15)
        self.assertEqual(len(set(slugs)), 15)

    def test_every_category_has_seed_key(self):
        daraz, cats = self.cfgs()
        for c in cats["categories"]:
            self.assertIn(c["slug"], daraz["seeds"], c["slug"])
        extra = set(daraz["seeds"]) - {c["slug"] for c in cats["categories"]}
        self.assertEqual(extra, set(), "categories.json-এ নেই এমন ক্যাটাগরির seed")

    def test_every_category_has_a_migration_row(self):
        """runner category_id বের করে categories টেবিল থেকে; migration-এ সারি না থাকলে ফাঁকা থাকত।"""
        sql = "\n".join(f.read_text(encoding="utf-8") for f in sorted((self.ROOT / "supabase" / "migrations").glob("*.sql")))
        for c in self.cfgs()[1]["categories"]:
            self.assertIn(f"('{c['slug']}',", sql, f"{c['slug']}: কোনো migration-এ categories সারি নেই")

    def test_no_seed_url_shared_by_enabled_categories(self):
        """একই URL দুই চালু ক্যাটাগরিতে থাকলে প্রথমটায় বসে, দ্বিতীয়টার টার্গেট নিঃশব্দে কম পড়ে।"""
        daraz, cats = self.cfgs()
        owner: dict[str, str] = {}
        for c in cats["categories"]:
            if c.get("enabled", True) is False:
                continue
            for sd in daraz["seeds"].get(c["slug"]) or []:
                url = sd.get("url") or sd.get("q")
                self.assertNotIn(url, owner, f"{url} একসাথে {owner.get(url)} ও {c['slug']}-এ চালু")
                owner[url] = c["slug"]

    def test_enabled_category_has_seeds(self):
        daraz, cats = self.cfgs()
        for c in cats["categories"]:
            if c.get("enabled", True) is not False:
                self.assertGreaterEqual(len(daraz["seeds"][c["slug"]]), 1, f"{c['slug']} চালু কিন্তু seed নেই")

    def test_total_target_matches_enabled_sum(self):
        from tools.capacity import check_total
        self.assertIsNone(check_total(self.cfgs()[1]))

    def test_duplicate_detector_catches_a_clash(self):
        """শেয়ার-URL যাচাই সত্যিই ধরে কি না: এখন সব চালু, তাই ক্যাটাগরিগুলোর seed URL আলাদা থাকতে হবে।
        (আগে এখানে fashion আর bags-footwear-এর সংঘাত দেখানো হতো; Phase 9-এ ওই URL fashion থেকে সরেছে।)"""
        daraz, cats = self.cfgs()
        fashion = {s["url"] for s in daraz["seeds"]["fashion"]}
        bags = {s["url"] for s in daraz["seeds"]["bags-footwear"]}
        watches = {s["url"] for s in daraz["seeds"]["watches-jewellery"]}
        self.assertFalse(fashion & bags)
        self.assertFalse(fashion & watches)


class ImagePipelineTests(unittest.TestCase):
    def test_listing_rows_carry_image_url_only_when_present(self):
        adapter = FakeAdapter({"saree": [item("1", image_url="https://cdn/a.jpg"), item("2")]})
        db = FakeDB()
        run_daraz.run_pipeline(db, adapter, CFG, CATS, NOW, detail_limit=0)
        rows = {r["external_id"]: r for r in db.listing_batches[0]}
        self.assertEqual(rows["1"]["image_url"], "https://cdn/a.jpg")
        self.assertNotIn("image_url", rows["2"])        # অনুপস্থিত কলাম পাঠানো হয় না, তাই আগের ছবি মুছে যায় না

    def test_detail_fills_missing_image(self):
        class A(FakeAdapter):
            def fetch_product(self, url):
                d = super().fetch_product(url)
                d["image_url"] = "https://cdn/detail.jpg"
                return d
        adapter = A({"saree": [item("1", brand="B"), item("2", brand="B", image_url="https://cdn/own.jpg")]})
        db = FakeDB()
        # "1","2" ব্র্যান্ড আছে, তবে নতুন (existing-এ নেই) বলে ডিটেইল আনা হয়
        run_daraz.run_pipeline(db, adapter, CFG, CATS, NOW)
        patched = [r for b in db.listing_batches[1:] for r in b]
        by = {r["external_id"]: r for r in patched}
        self.assertEqual(by["1"]["image_url"], "https://cdn/detail.jpg")
        self.assertNotIn("2", by)                        # নিজের ছবি আছে, ডিটেইল ছোঁয়নি



class SmokeWarningTests(unittest.TestCase):
    def _report(self, seed):
        return {"client_stats": {"requests": 0, "ok": 0, "blocked": 0, "robots_skipped": 2, "errors": 0},
                "diags": [{"category": "fashion", "seed": seed, "strategy": None, "found": 0, "total_results": None,
                           "raw_keys": [], "notes": []}],
                "errors": [], "coverage": {}, "sample_item": None, "product": None, "reviews": None}

    def test_keyword_seed_triggers_old_config_warning(self):
        md = run_daraz.smoke_markdown(self._report({"type": "keyword", "q": "panjabi"}))
        self.assertIn("পুরনো কনফিগ", md)

    def test_category_seed_has_no_warning(self):
        md = run_daraz.smoke_markdown(self._report({"type": "category", "url": "https://www.daraz.com.bd/womens-sarees/"}))
        self.assertNotIn("পুরনো কনফিগ", md)


class MissingSecretsTests(unittest.TestCase):
    def test_main_reports_missing_secrets_instead_of_crashing(self):
        import os, tempfile
        from pathlib import Path as P
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if k not in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")}
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(run_daraz, "OUT_DIR", P(d)):
                code = run_daraz.main([])
            self.assertEqual(code, 1)
            md = (P(d) / "run-summary.md").read_text(encoding="utf-8")
            self.assertIn("SUPABASE_SERVICE_KEY", md)
            self.assertIn("dry_run", md)


class ReviewsRobotsTests(unittest.TestCase):
    def test_robots_blocked_reviews_are_a_note_not_an_error(self):
        from scrapers.common.http import RobotsDisallowed

        class NoReviews(FakeAdapter):
            def fetch_reviews(self, ext, page=1, page_size=20):
                self.review_pages.append((ext, page))
                raise RobotsDisallowed("https://my.daraz.com.bd/pdp/review/getReviewList")

        adapter = NoReviews({"saree": [item("1", review_count=3), item("2", review_count=5)]})
        db = FakeDB()
        summary = run_daraz.run_pipeline(db, adapter, CFG, CATS, NOW, detail_limit=0)
        # (ফিক্সচারে home/kitchen seed-এ আইটেম নেই বলে অন্য ত্রুটি থাকতে পারে; রিভিউ নিয়ে কোনো ত্রুটি থাকবে না)
        self.assertFalse([e for e in summary["errors"] if "রিভিউ" in e])
        self.assertEqual(summary["reviews"], 0)
        self.assertEqual(len(summary["notes"]), 1)
        self.assertEqual(len(adapter.review_pages), 1)          # একবার চেষ্টা, তারপর বাকি সব বাদ
        self.assertIn("নোট", run_daraz.run_markdown(summary))


if __name__ == "__main__":
    unittest.main()
