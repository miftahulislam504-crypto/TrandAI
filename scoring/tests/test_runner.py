import unittest
from datetime import timedelta

from scoring import run_scoring
from scoring.config import load_config
from scoring.tests.test_engine import TODAY, filler, hot

CFG = load_config()


class FakeDB:
    def __init__(self, products, previous=None, extra_snaps=None):
        self.tables = {"listing_overview": [], "listing_snapshots": [], "reviews": [],
                       "product_scores": previous or [], "product_costs": []}
        self.upserts = []
        for p in products:
            # ১:১ — listing id = product id
            self.tables["listing_overview"].append({
                "id": p.id, "canonical_product_id": p.id, "category": p.category,
                "title_raw": p.title, "url": f"https://x/{p.id}", "seller_name": f"seller{p.id}"})
            if p.unit_cost is not None:
                self.tables["product_costs"].append({"canonical_product_id": p.id, "unit_cost": p.unit_cost, "extra_cost": p.extra_cost})
            for s in p.snaps:
                self.tables["listing_snapshots"].append({
                    "listing_id": p.id, "captured_on": s.day.isoformat(), "price": s.price,
                    "rating_avg": s.rating_avg, "rating_count": s.rating_count,
                    "review_count": s.review_count, "sold_count": s.sold_count})
            for r in p.reviews:
                self.tables["reviews"].append({
                    "listing_id": p.id, "stars": r.stars,
                    "reviewed_at": r.day.isoformat() if r.day else None, "suspected_fake": r.suspected_fake,
                    "flags": ["counterfeit"] if r.counterfeit else None,
                    "sentiment": r.sentiment, "topics": list(r.topics)})
        self.tables["listing_snapshots"] += extra_snaps or []

    def select(self, table, params=None, page_size=1000):
        return list(self.tables[table])

    def upsert(self, table, rows, on_conflict, returning=False, chunk=200):
        self.upserts.append((table, on_conflict, rows))
        return []


def population():
    return [filler(i) for i in range(1, 21)] + [hot()]


class RunnerTests(unittest.TestCase):
    def test_writes_scores(self):
        db = FakeDB(population())
        out = run_scoring.run(db, CFG, TODAY)
        self.assertEqual(len(db.upserts), 1)
        table, conflict, rows = db.upserts[0]
        self.assertEqual((table, conflict), ("product_scores", "canonical_product_id,scored_on"))
        self.assertEqual(len(rows), 21)
        row = next(r for r in rows if r["canonical_product_id"] == 100)
        self.assertEqual((row["tier"], row["confidence"], row["scored_on"]), ("best", "high", TODAY.isoformat()))
        self.assertGreater(row["total"], 85)
        self.assertIsNone(row["ads_signal"])
        self.assertIn("summary", row["reasons"])
        self.assertEqual(set(row), {"canonical_product_id", "scored_on", "demand", "trend", "review_quality",
                                    "bad_review", "ads_signal", "total", "tier", "confidence", "reasons"})
        self.assertEqual(out["summary"]["tiers"]["best"], 1)
        self.assertEqual(out["summary"]["written"], 21)

    def test_dry_run_writes_nothing(self):
        db = FakeDB(population())
        out = run_scoring.run(db, CFG, TODAY, dry_run=True)
        self.assertEqual(db.upserts, [])
        self.assertEqual(out["summary"]["written"], 0)
        self.assertEqual(out["summary"]["scored"], 21)

    def test_future_snapshots_are_ignored(self):
        extra = [{"listing_id": 100, "captured_on": (TODAY + timedelta(days=3)).isoformat(), "price": 1,
                  "rating_avg": 1.0, "rating_count": 1, "review_count": 1, "sold_count": 0}]
        out = run_scoring.run(FakeDB(population(), extra_snaps=extra), CFG, TODAY, dry_run=True)
        self.assertEqual(out["summary"]["tiers"]["best"], 1)

    def test_previous_scores_apply_hysteresis(self):
        prev = [{"canonical_product_id": 100, "scored_on": (TODAY - timedelta(days=k)).isoformat(),
                 "tier": "mid", "raw_tier": "mid"} for k in (1, 2)]
        out = run_scoring.run(FakeDB(population(), previous=prev), CFG, TODAY, dry_run=True)
        r = next(r for r in out["results"] if r.product_id == 100)
        self.assertEqual((r.raw_tier, r.tier), ("best", "mid"))

    def test_todays_own_row_is_not_treated_as_previous(self):
        prev = [{"canonical_product_id": 100, "scored_on": TODAY.isoformat(), "tier": "mid", "raw_tier": "mid"}]
        out = run_scoring.run(FakeDB(population(), previous=prev), CFG, TODAY, dry_run=True)
        self.assertEqual(next(r for r in out["results"] if r.product_id == 100).tier, "best")

    def test_only_category(self):
        pop = population() + [filler(500 + i, "fashion") for i in range(3)]
        out = run_scoring.run(FakeDB(pop), CFG, TODAY, only="fashion", dry_run=True)
        self.assertEqual({r.category for r in out["results"]}, {"fashion"})

    def test_product_without_data_is_unscored(self):
        pop = population()
        db = FakeDB(pop)
        db.tables["listing_overview"].append({"id": 999, "canonical_product_id": 999, "category": "kitchen",
                                              "title_raw": "ghost", "url": None})
        out = run_scoring.run(db, CFG, TODAY)
        self.assertEqual(out["summary"]["unscored"], 1)
        self.assertEqual(len(db.upserts[0][2]), 21)

    def test_empty_db(self):
        out = run_scoring.run(FakeDB([]), CFG, TODAY)
        self.assertEqual(out["summary"]["scored"], 0)
        self.assertEqual(out["spotcheck"], "")

    def test_summary_and_spotcheck_text(self):
        out = run_scoring.run(FakeDB(population()), CFG, TODAY, dry_run=True, spot_n=5)
        md = run_scoring.summary_markdown(out["summary"], TODAY, True, "absolute")
        self.assertIn("Best: 1", md)
        self.assertIn("| kitchen |", md)
        sc = out["spotcheck"]
        self.assertIn("## Best (1টা)", sc)
        self.assertIn("**hot**", sc)
        self.assertIn("একমত?", sc)
        # একই তারিখে একই নমুনা
        again = run_scoring.run(FakeDB(population()), CFG, TODAY, dry_run=True, spot_n=5)["spotcheck"]
        self.assertEqual(sc, again)


if __name__ == "__main__":
    unittest.main()
