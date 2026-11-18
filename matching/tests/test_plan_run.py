import unittest
from datetime import datetime, timezone

from matching import run_matching
from matching.config import load_config
from matching.plan import build_plan
from matching.score import Item, idf_weights, prepare, score_pair
from scrapers.common.supabase_rest import SupabaseError

CFG = load_config()


def it(i, title, source="daraz", canon=None, cat="kitchen", brand=None, price=None):
    return Item(id=i, canonical_id=i if canon is None else canon, source=source, category=cat, title=title, brand=brand, price=price)


class PlanTests(unittest.TestCase):
    def test_cross_source_identical_is_auto_merged_into_lowest_canonical(self):
        plan = build_plan([it(7, "Digital Air Fryer", "cartup", canon=70), it(3, "Digital Air Fryer", "daraz", canon=30)], CFG)
        self.assertEqual(plan.merges, [(30, 70)])
        self.assertEqual([(p.a, p.b) for p in plan.auto], [(3, 7)])
        self.assertEqual(plan.review, [])

    def test_same_source_goes_to_review_never_auto(self):
        plan = build_plan([it(1, "Digital Air Fryer", "daraz"), it(2, "Digital Air Fryer", "daraz")], CFG)
        self.assertEqual((plan.merges, plan.auto), ([], []))
        self.assertEqual([(p.a, p.b) for p in plan.review], [(1, 2)])

    def test_unrelated_and_conflicting_pairs_are_dropped(self):
        plan = build_plan([it(1, "Air Fryer 5L"), it(2, "Air Fryer 3.5L", "cartup"),
                           it(3, "Steel Water Bottle", "daraz"), it(4, "Rice Cooker Pot", "cartup")], CFG)
        self.assertEqual((plan.merges, plan.review), ([], []))
        self.assertEqual(plan.stats["conflicts"], 1)

    def test_review_band(self):
        a, b = it(1, "Steel Water Bottle Insulated Cold", "daraz"), it(2, "Steel Water Bottle Hot", "cartup")
        items = [a, b]
        prepare(items, CFG)
        s = score_pair(a, b, idf_weights(items), CFG).score
        cfg = load_config(override={"thresholds": {"review": round(s - 0.02, 3), "auto": round(s + 0.02, 3)}})
        plan = build_plan([it(1, a.title, "daraz"), it(2, b.title, "cartup")], cfg)
        self.assertEqual(([(p.a, p.b) for p in plan.review], plan.merges), ([(1, 2)], []))

    def test_already_merged_pairs_are_skipped(self):
        plan = build_plan([it(1, "Digital Air Fryer", "daraz", canon=9), it(2, "Digital Air Fryer", "cartup", canon=9)], CFG)
        self.assertEqual((plan.merges, plan.review, plan.stats["same_canonical"]), ([], [], 1))

    def test_listings_without_canonical_are_ignored(self):
        a = it(1, "Digital Air Fryer", "daraz")
        b = Item(2, None, "cartup", "kitchen", "Digital Air Fryer", None, None)
        self.assertEqual(build_plan([a, b], CFG).merges, [])

    def test_rejected_pair_blocks_future_merges_of_both_products(self):
        items = [it(1, "Digital Air Fryer", "daraz"), it(2, "Digital Air Fryer", "cartup"), it(3, "Digital Air Fryer", "othoba", canon=2)]
        plan = build_plan(items, CFG, decided={(1, 2): "rejected"})
        # 3 আর 2 একই canonical, তাই (1,3) জোড়াও canonical 1 বনাম 2: ব্লক
        self.assertEqual((plan.merges, plan.auto, plan.review), ([], [], []))
        self.assertGreaterEqual(plan.stats["blocked"], 1)

    def test_decided_pairs_are_not_proposed_again(self):
        items = [it(1, "Digital Air Fryer", "daraz"), it(2, "Digital Air Fryer", "cartup")]
        for st in ("accepted", "auto"):
            self.assertEqual(build_plan(items, CFG, decided={(1, 2): st}).merges, [])

    def test_chain_guard_blocks_conflicting_cluster(self):
        # A(5L) ~ B(মাপ নেই) ~ C(3L), কিন্তু A আর C-তে সংঘাত। A-B আগে মার্জ, B-C রিভিউতে যায়।
        items = [it(1, "Air Fryer 5L Steel", "daraz", price=5000), it(2, "Air Fryer Steel", "cartup", price=5000),
                 it(3, "Air Fryer 3L Steel", "othoba", price=4000)]
        plan = build_plan(items, CFG)
        self.assertEqual(plan.merges, [(1, 2)])
        self.assertEqual([(p.a, p.b, p.note) for p in plan.review], [(2, 3, "cluster_conflict")])

    def test_cluster_size_limit(self):
        cfg = load_config(override={"max_cluster_size": 2})
        items = [it(1, "Digital Air Fryer", "daraz"), it(2, "Digital Air Fryer", "cartup"), it(3, "Digital Air Fryer", "othoba")]
        plan = build_plan(items, cfg)
        self.assertEqual(len(plan.merges), 1)
        # তৃতীয়টার দুই জোড়াই রিভিউতে (একটা accept করলে অন্যটা পরের রানে নিজে stale হয়)
        self.assertEqual([p.note for p in plan.review], ["cluster_too_big", "cluster_too_big"])

    def test_three_way_merge_picks_lowest_id_everywhere(self):
        items = [it(5, "Digital Air Fryer", "daraz", canon=50), it(2, "Digital Air Fryer", "cartup", canon=20),
                 it(9, "Digital Air Fryer", "othoba", canon=90)]
        plan = build_plan(items, CFG)
        self.assertEqual(sorted(plan.merges), [(20, 50), (20, 90)])
        self.assertEqual(plan.review, [])           # একই রানে একই গ্রুপে যাওয়া জোড়া রিভিউতে আসে না

    def test_review_cap(self):
        cfg = load_config(override={"max_review_per_run": 2})
        items = [it(i, "Digital Air Fryer Steel", "daraz") for i in range(1, 6)]    # একই সোর্স, ১০ জোড়া
        plan = build_plan(items, cfg)
        self.assertEqual(len(plan.review), 2)
        self.assertEqual(plan.stats["review_dropped_by_cap"], 8)


class FakeDB:
    def __init__(self, listings):
        self.listings = [dict(l) for l in listings]
        self.cands: list[dict] = []
        self.rpcs: list[tuple] = []
        self.fail_merge = False
        self._id = 1

    def select(self, table, params=None, page_size=1000):
        if table == "listing_overview":
            return [dict(l) for l in self.listings if l.get("is_active", True)]
        if table == "match_candidates":
            return [dict(c) for c in self.cands]
        if table == "listings":      # ছবির হ্যাশ (listing-এ "image_hash" hex থাকলে)
            return [{"id": l["id"], "image_hash": l["image_hash"]} for l in self.listings
                    if l.get("image_hash") and l.get("is_active", True)]
        raise KeyError(table)

    def rpc(self, fn, args=None):
        self.rpcs.append((fn, args))
        if fn == "link_listings_to_canonical":
            return 0
        if fn == "merge_canonicals":
            if self.fail_merge:
                raise SupabaseError("boom")
            for l in self.listings:
                if l["canonical_product_id"] == args["p_loser"]:
                    l["canonical_product_id"] = args["p_winner"]
        return None

    def upsert(self, table, rows, on_conflict, returning=False, chunk=200):
        assert table == "match_candidates" and on_conflict == "listing_a,listing_b"
        for r in rows:
            hit = next((c for c in self.cands if (c["listing_a"], c["listing_b"]) == (r["listing_a"], r["listing_b"])), None)
            if hit is None:
                hit = {"id": self._id}
                self._id += 1
                self.cands.append(hit)
            hit.update(r)
        return []

    def update(self, table, values, params):
        ids = {int(x) for x in params["id"][4:-1].split(",")}
        for c in self.cands:
            if c["id"] in ids:
                c.update(values)


def L(i, title, source, canon, cat="kitchen", brand=None, price=None, active=True, image_hash=None):
    return {"id": i, "source": source, "canonical_product_id": canon, "category": cat, "title_raw": title,
            "brand_raw": brand, "price": price, "is_active": active, "image_hash": image_hash}


NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


class RunTests(unittest.TestCase):
    def test_auto_merge_then_second_run_is_idempotent(self):
        db = FakeDB([L(1, "Digital Air Fryer", "daraz", 10), L(2, "Digital Air Fryer", "cartup", 20), L(3, "Mug", "daraz", 30)])
        s = run_matching.run(db, CFG, now=NOW)
        self.assertEqual(s["applied"]["merged"], 1)
        self.assertEqual([l["canonical_product_id"] for l in db.listings], [10, 10, 30])
        self.assertEqual([(c["status"], c["decided_by"]) for c in db.cands], [("auto", "auto")])
        s2 = run_matching.run(db, CFG, now=NOW)
        self.assertEqual((s2["applied"]["merged"], s2["plan"]["planned_merges"]), (0, 0))
        self.assertEqual(len(db.cands), 1)
        self.assertIn(("link_listings_to_canonical", None), db.rpcs)

    def test_dry_run_changes_nothing(self):
        db = FakeDB([L(1, "Digital Air Fryer", "daraz", 10), L(2, "Digital Air Fryer", "cartup", 20)])
        s = run_matching.run(db, CFG, dry_run=True, now=NOW)
        self.assertEqual(s["plan"]["planned_merges"], 1)
        self.assertEqual((db.rpcs, db.cands), ([], []))
        self.assertNotIn("applied", s)

    def test_review_pairs_written_pending_and_never_overwritten_after_decision(self):
        db = FakeDB([L(1, "Digital Air Fryer", "daraz", 10), L(2, "Digital Air Fryer", "daraz", 20)])
        s = run_matching.run(db, CFG, now=NOW)
        self.assertEqual((s["applied"]["review_written"], db.cands[0]["status"]), (1, "pending"))
        self.assertEqual(db.listings[0]["canonical_product_id"], 10)             # একই সোর্স: নিজে মার্জ হয়নি
        db.cands[0]["status"] = "rejected"                                       # মানুষ reject করল
        run_matching.run(db, CFG, now=NOW)
        self.assertEqual((len(db.cands), db.cands[0]["status"]), (1, "rejected"))

    def test_pending_that_no_longer_applies_becomes_stale(self):
        db = FakeDB([L(1, "Digital Air Fryer", "daraz", 10), L(2, "Digital Air Fryer", "daraz", 20)])
        run_matching.run(db, CFG, now=NOW)
        db.listings[1]["is_active"] = False                                      # একটা listing নিষ্ক্রিয়
        s = run_matching.run(db, CFG, now=NOW)
        self.assertEqual((s["applied"]["staled"], db.cands[0]["status"]), (1, "stale"))

    def test_merge_failure_is_reported_not_fatal(self):
        db = FakeDB([L(1, "Digital Air Fryer", "daraz", 10), L(2, "Digital Air Fryer", "cartup", 20)])
        db.fail_merge = True
        s = run_matching.run(db, CFG, now=NOW)
        self.assertEqual(s["applied"]["merged"], 0)
        self.assertEqual(len(s["applied"]["merge_errors"]), 1)
        self.assertIn("মার্জ ব্যর্থ", run_matching.summary_markdown(s))

    def test_summary_notes_single_source(self):
        db = FakeDB([L(1, "Digital Air Fryer", "daraz", 10), L(2, "Digital Air Fryer", "daraz", 20)])
        md = run_matching.summary_markdown(run_matching.run(db, CFG, now=NOW))
        self.assertIn("একটাই সোর্স", md)


if __name__ == "__main__":
    unittest.main()
