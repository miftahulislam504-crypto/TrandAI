import unittest

from youtube.stats import summarize


class StatsTest(unittest.TestCase):
    def test_basic(self):
        v = [{"id": "a", "title": "A", "channel": "CA", "views": 100},
             {"id": "b", "title": "B", "channel": "CB", "views": 900},
             {"id": "c", "title": "C", "channel": "CC", "views": 300}]
        s = summarize(v)
        self.assertEqual((s["videos"], s["views_total"], s["views_median"]), (3, 1300, 300))
        self.assertEqual((s["top_video_id"], s["top_video_views"], s["top_channel"]), ("b", 900, "CB"))

    def test_median_of_even_count_rounds(self):
        s = summarize([{"id": "a", "title": "", "channel": "", "views": 1}, {"id": "b", "title": "", "channel": "", "views": 2}])
        self.assertEqual(s["views_median"], 2)  # 1.5 -> 2 (round half to even gives 2)

    def test_hidden_views_ignored_but_counted_as_videos(self):
        s = summarize([{"id": "a", "title": "A", "channel": "x", "views": None}, {"id": "b", "title": "B", "channel": "y", "views": 50}])
        self.assertEqual((s["videos"], s["views_total"], s["views_median"], s["top_video_id"]), (2, 50, 50, "b"))

    def test_all_hidden_or_empty(self):
        for v in ([], [{"id": "a", "title": "A", "channel": "x", "views": None}]):
            s = summarize(v)
            self.assertEqual(s["views_total"], None)
            self.assertEqual(s["views_median"], None)
            self.assertEqual(s["top_video_id"], None)
        self.assertEqual(summarize([])["videos"], 0)

    def test_long_title_truncated(self):
        s = summarize([{"id": "a", "title": "t" * 500, "channel": "c" * 500, "views": 1}])
        self.assertEqual((len(s["top_video_title"]), len(s["top_channel"])), (200, 120))


if __name__ == "__main__":
    unittest.main()
