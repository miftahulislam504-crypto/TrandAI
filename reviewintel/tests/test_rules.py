import unittest
from datetime import date, timedelta

from reviewintel.config import IntelConfigError, load_config
from reviewintel.rules import Rev, analyze, is_counterfeit_complaint, normalize

CFG = load_config()
D0 = date(2026, 11, 1)


class CounterfeitTests(unittest.TestCase):
    def test_complaints_are_caught(self):
        for t in ["This is fake, don't buy", "Totally FAKE product!!", "duplicate item received", "Looks like a counterfeit",
                  "এটা নকল জিনিস", "ডুপ্লিকেট দিয়েছে", "ভুয়া প্রোডাক্ট", "ফেক মাল", "nokol product dise", "ekdom nakol",
                  "not original at all", "Not genuine", "original na, asol na", "first copy delivered", "অরিজিনাল না", "আসল নয় এটা",
                  "ফার্স্ট কপি দিয়েছে", "It is a replica", "knockoff quality"]:
            self.assertTrue(is_counterfeit_complaint(t), t)

    def test_praise_and_negations_are_not(self):
        for t in ["100% original product, very good", "not fake, genuine", "It is not a fake", "no fake, asol", "fake na, original",
                  "নকল না, আসল জিনিস", "নকল নয়, দারুণ", "doesn't look fake", "never fake, trust me", "Good quality, fast delivery",
                  "খুব ভালো প্রোডাক্ট", "", None, "isn't duplicate", "জাল নোট না, ঠিক আছে", "fake nai"]:
            self.assertFalse(is_counterfeit_complaint(t), repr(t))

    def test_hedged_doubt_is_not_a_complaint(self):
        self.assertFalse(is_counterfeit_complaint("jodi fake hoy tahole problem"))
        self.assertFalse(is_counterfeit_complaint("original naki fake bujhlam na"))

    def test_normalize(self):
        self.assertEqual(normalize("  Isn't   FAKE!! "), "isnt fake")
        self.assertEqual(normalize("নকল, না।"), "নকল না")
        self.assertEqual(normalize(None), "")


def rev(i, listing=1, stars=5, body="ok", day=0, who=None):
    return Rev(i, listing, stars, body, D0 + timedelta(days=day), who)


class FakeReviewTests(unittest.TestCase):
    def test_duplicate_long_text_across_products(self):
        t = "খুব ভালো প্রোডাক্ট আমি অনেক খুশি সবাই কিনতে পারেন"
        revs = [rev(1, 1, body=t), rev(2, 2, body=t), rev(3, 3, body=t), rev(4, 4, body="আলাদা মন্তব্য যা অন্য কেউ লেখেনি এখানে")]
        v = analyze(revs, CFG)
        self.assertTrue(all(v[i].suspected_fake for i in (1, 2, 3)))
        self.assertFalse(v[4].suspected_fake)
        self.assertEqual(v[1].reasons, ["duplicate_text"])

    def test_two_copies_ok_when_short_but_not_when_very_long(self):
        short = "good product fast delivery thanks"          # ৩৩ অক্ষর
        self.assertFalse(any(x.suspected_fake for x in analyze([rev(1, body=short), rev(2, 2, body=short)], CFG).values()))
        long = "this is a very long and detailed review text that was copy pasted by a farm " * 1
        self.assertTrue(all(x.suspected_fake for x in analyze([rev(1, body=long), rev(2, 2, body=long)], CFG).values()))

    def test_tiny_generic_texts_never_count(self):
        revs = [rev(i, i, body="good") for i in range(1, 30)]
        self.assertFalse(any(x.suspected_fake for x in analyze(revs, CFG).values()))

    def test_burst_of_five_stars_on_one_day(self):
        revs = [rev(100 + d, day=d, body=f"r{d}") for d in range(10)]            # ১০ দিন, দিনে ১টা
        revs += [rev(200 + i, day=3, body=f"burst{i}") for i in range(12)]       # এক দিনে আরও ১২টা ৫★
        revs.append(rev(300, day=3, stars=2, body="bad one"))
        v = analyze(revs, CFG)
        self.assertTrue(all(v[200 + i].suspected_fake and v[200 + i].reasons == ["burst"] for i in range(12)))
        self.assertFalse(v[300].suspected_fake)                                  # ২★ রিভিউ ছোঁয়া হয় না
        self.assertFalse(any(v[100 + d].suspected_fake for d in (0, 5, 9)))

    def test_busy_listing_is_not_a_burst(self):
        revs = [rev(i * 10 + j, day=i, body=f"x{i}{j}") for i in range(10) for j in range(8)]   # প্রতিদিন ৮টা: স্বাভাবিক ভিড়
        self.assertFalse(any(x.suspected_fake for x in analyze(revs, CFG).values()))

    def test_burst_needs_enough_days(self):
        revs = [rev(i, day=0, body=f"x{i}") for i in range(15)]
        self.assertFalse(any(x.suspected_fake for x in analyze(revs, CFG).values()))

    def test_repeat_reviewer_keeps_first(self):
        revs = [rev(1, day=0, who="h"), rev(2, day=2, who="h"), rev(3, day=4, who="h"), rev(4, day=5, who="other"), rev(5, 2, day=1, who="h")]
        v = analyze(revs, CFG)
        self.assertEqual([i for i in (1, 2, 3, 4, 5) if v[i].suspected_fake], [2, 3])

    def test_counterfeit_flag_is_independent_of_fake(self):
        v = analyze([rev(1, body="fake product, nokol")], CFG)
        self.assertEqual(v[1].flags, ["counterfeit"])
        self.assertFalse(v[1].suspected_fake)

    def test_switches(self):
        cfg = load_config(override={"counterfeit": {"enabled": False}, "fake_reviews": {"enabled": False}})
        t = "this is fake " * 10
        v = analyze([rev(1, body=t), rev(2, 2, body=t), rev(3, 3, body=t)], cfg)
        self.assertTrue(all(not x.flags and not x.suspected_fake for x in v.values()))

    def test_bad_config(self):
        for bad in ({"fake_reviews": {"dup_min_count": 1}}, {"fake_reviews": {"burst_min": 1}}, {"fake_reviews": {"dup_long_len": 3}}):
            with self.assertRaises(IntelConfigError):
                load_config(override=bad)


if __name__ == "__main__":
    unittest.main()
