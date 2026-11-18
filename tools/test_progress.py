"""tools/progress.py-এর টেস্ট। চালান: python -m unittest tools/test_progress.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import progress  # noqa: E402

SAMPLE = """# P
<!-- progress:summary:start -->
old
<!-- progress:summary:end -->

## Phase 0 — কাঠামো
- [x] a
- [x] b
### উপ-শিরোনাম
- [ ] c

## Phase 1: ডেটা
- [ ] d
  - [x] nested e

## এখন করণীয়
- [ ] এটা গোনা হবে না
"""


class ProgressTests(unittest.TestCase):
    def test_parse_counts_only_phase_sections(self):
        ph = progress.parse(SAMPLE)
        self.assertEqual([(p["id"], p["done"], p["total"]) for p in ph], [("Phase 0", 2, 3), ("Phase 1", 1, 2)])
        self.assertEqual(ph[0]["title"], "কাঠামো")

    def test_update_replaces_table_and_is_idempotent(self):
        out = progress.update(SAMPLE)
        self.assertNotIn("\nold\n", out)
        self.assertIn("| Phase 0: কাঠামো | 2 | 1 |", out)
        self.assertIn("**মোট** | **3** | **2**", out)
        self.assertEqual(progress.update(out), out)

    def test_bar_and_status(self):
        self.assertEqual(progress.bar(5, 10), "█████░░░░░")
        self.assertEqual(progress.bar(0, 0), "░░░░░░░░░░")
        self.assertEqual((progress.status(0, 3), progress.status(1, 3), progress.status(3, 3)),
                         ("শুরু হয়নি", "চলছে", "সম্পন্ন"))

    def test_missing_markers(self):
        with self.assertRaises(ValueError):
            progress.update("## Phase 0\n- [x] a\n")

    def test_check_mode(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "progress.md"
            f.write_text(SAMPLE, encoding="utf-8")
            self.assertEqual(progress.main(["--check", str(f)]), 1)
            self.assertEqual(progress.main([str(f)]), 0)
            self.assertEqual(progress.main(["--check", str(f)]), 0)


if __name__ == "__main__":
    unittest.main()
