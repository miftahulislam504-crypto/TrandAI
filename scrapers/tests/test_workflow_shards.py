"""Daraz Daily-র ভাগ (shard) সংক্রান্ত পাহারা।

১) workflow-এর matrix-এর ভাগ-সংখ্যা আর `--shard $SHARD/N`-এর N একই হতে হবে, নইলে কিছু ক্যাটাগরি রোজ বাদ পড়ে যায়।
২) প্রতি ভাগের রোজকার অনুরোধ (ডিসকভারি + ভাগ-করা ডিটেইল) Daraz-এর ড্রাই-রানে দেখা ব্লক-সীমার (১০৪ অনুরোধে ৩ ব্লক)
   নিচে থাকতে হবে। `detail_limit` বাড়ালে ভাগও বাড়াতে হবে; এই টেস্ট না করলে ফেল করে।
(রিভিউ-ধাপ ধরা হয়নি, কারণ Daraz-এর robots.txt-এ রিভিউ API বন্ধ ও সেটা এখন চলে না।)
"""
import math
import re
import unittest
from pathlib import Path

from scrapers import run_daraz
from tools import capacity

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "daraz-daily.yml"
BLOCK_SEEN_AT = 104     # Phase 9 ড্রাই-রান: ১০৪ অনুরোধে ৩ ব্লক
SAFE_MAX = 90           # তার নিচে নিরাপদ ব্যবধান রেখে


def workflow_shards() -> tuple[list[int], int]:
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(r"shard:\s*\[([\d,\s]+)\]", text)
    assert m, "workflow-তে `shard: [..]` matrix পাওয়া যায়নি"
    listed = [int(x) for x in m.group(1).split(",") if x.strip()]
    n = re.search(r'--shard \$SHARD/(\d+)', text)
    assert n, "workflow-তে `--shard $SHARD/N` পাওয়া যায়নি"
    return listed, int(n.group(1))


class WorkflowShardTests(unittest.TestCase):
    def test_matrix_matches_shard_count(self):
        listed, n = workflow_shards()
        self.assertEqual(listed, list(range(1, n + 1)), "matrix-এর ভাগ ১..N হতে হবে আর N মিলতে হবে")

    def test_every_shard_stays_under_the_block_limit(self):
        _, n = workflow_shards()
        daraz, cats = run_daraz.load_config()
        per_cat = {c["slug"]: c["requests"] for c in capacity.estimate(daraz, cats)["categories"]}
        detail = math.ceil(daraz["settings"].get("detail_limit", 30) / n)
        for k in range(1, n + 1):
            discovery = sum(per_cat.get(s, 0) for s in run_daraz.shard_slugs(daraz, cats, k, n))
            self.assertLessEqual(discovery + detail, SAFE_MAX,
                                 f"ভাগ {k}/{n}: ডিসকভারি {discovery} + ডিটেইল {detail} অনুরোধ, "
                                 f"ব্লক দেখা গেছে {BLOCK_SEEN_AT}-এ; ভাগ বাড়ান বা detail_limit কমান")


if __name__ == "__main__":
    unittest.main()
