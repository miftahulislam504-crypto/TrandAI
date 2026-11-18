import unittest

from reviewintel import run_intel
from reviewintel.config import load_config
from scrapers.common.supabase_rest import SupabaseError

CFG = load_config()


class DB:
    def __init__(self, rows, missing_flags=False):
        self.rows = [dict(r) for r in rows]
        self.updates = []
        self.missing_flags = missing_flags

    def select(self, table, params=None, page_size=1000):
        if self.missing_flags:
            raise SupabaseError("HTTP 400")
        return [dict(r) for r in self.rows]

    def update(self, table, values, params):
        ids = [int(x) for x in params["id"][4:-1].split(",")]
        self.updates.append((values, ids))
        for r in self.rows:
            if r["id"] in ids:
                r.update(values)


def row(i, body, listing=1, day="2026-11-01", **kw):
    return {"id": i, "listing_id": listing, "stars": 5, "body": body, "reviewed_at": day, "reviewer_hash": None,
            "suspected_fake": False, "flags": None, **kw}


class RunTests(unittest.TestCase):
    def rows(self):
        return [row(1, "this is fake, nokol"), row(2, "good quality product"), row(3, "ডুপ্লিকেট দিয়েছে", listing=2)]

    def test_flags_written_and_second_run_is_noop(self):
        db = DB(self.rows())
        s = run_intel.run(db, CFG)
        self.assertEqual((s["counterfeit"], s["changed"], s["written"]), (2, 2, 2))
        self.assertEqual(db.updates, [({"suspected_fake": False, "flags": ["counterfeit"]}, [1, 3])])   # এক আপডেটে দুই সারি
        s2 = run_intel.run(db, CFG)
        self.assertEqual((s2["changed"], s2["written"]), (0, 0))
        self.assertEqual(len(db.updates), 1)

    def test_dry_run_writes_nothing(self):
        db = DB(self.rows())
        s = run_intel.run(db, CFG, dry_run=True)
        self.assertEqual((s["changed"], s["written"], db.updates), (2, 0, []))

    def test_stale_flags_are_cleared_when_rules_change(self):
        db = DB([row(1, "good product", suspected_fake=True, flags=["counterfeit"])])
        s = run_intel.run(db, CFG)
        self.assertEqual(s["written"], 1)
        self.assertEqual((db.rows[0]["suspected_fake"], db.rows[0]["flags"]), (False, None))

    def test_duplicate_texts_mark_fake_and_summary_lists_samples(self):
        t = "এই লেখাটা অনেক লম্বা এবং একই রকম বারবার কপি করা হয়েছে সবখানে"
        db = DB([row(i, t, listing=i) for i in range(1, 5)] + [row(9, "ভালো")])
        s = run_intel.run(db, CFG)
        self.assertEqual(s["suspected_fake"], 4)
        self.assertEqual(s["reasons"], {"duplicate_text": 4})
        md = run_intel.summary_markdown(s)
        self.assertIn("সন্দেহজনক রিভিউয়ের নমুনা", md)
        self.assertTrue(all(db.rows[i]["suspected_fake"] for i in range(4)))

    def test_large_updates_are_chunked(self):
        db = DB([row(i, "fake nokol product", listing=i) for i in range(1, 401)])
        run_intel.run(db, CFG)
        self.assertEqual([len(ids) for _, ids in db.updates], [150, 150, 100])

    def test_missing_migration_stops_with_clear_message(self):
        with self.assertRaises(SystemExit) as cm:
            run_intel.run(DB([], missing_flags=True), CFG)
        self.assertIn("migration", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
