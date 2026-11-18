import unittest

from matching.config import MatchConfigError, load_config
from matching.parse import brand_conflict, normalize_brand, parse, unit_conflict
from matching.score import Item, candidate_pairs, decide, idf_weights, prepare, price_score, score_pair

CFG = load_config()


def item(i, title, source="daraz", cat="kitchen", brand=None, price=None, canon=None):
    return Item(id=i, canonical_id=canon if canon is not None else i, source=source, category=cat,
                title=title, brand=brand, price=price)


def pair(a: Item, b: Item, extra=()):
    items = [a, b, *extra]
    prepare(items, CFG)
    return score_pair(a, b, idf_weights(items), CFG)


class ParseTests(unittest.TestCase):
    def test_units_are_normalized_and_removed_from_tokens(self):
        p = parse("Digital Air Fryer 5L 1500W - Black", None, CFG)
        self.assertEqual(p.units, {"vol": {5000.0}, "pwr": {1500.0}})
        self.assertEqual(p.tokens, {"digital", "air", "fryer"})        # রঙ (black) শব্দ-তালিকায় নেই

    def test_colors_and_sizes_are_variants_not_identity(self):
        self.assertEqual(parse("Cotton Panjabi Maroon XL", None, CFG).tokens, {"cotton", "panjabi"})
        self.assertEqual(parse("কটন পাঞ্জাবি কালো", None, CFG).tokens, {"কটন", "পাঞ্জাবি"})
        a = pair(item(1, "Cotton Panjabi Red L"), item(2, "Cotton Panjabi Blue XL", "cartup"))
        self.assertAlmostEqual(a.score, 1.0)

    def test_unit_spellings_agree(self):
        a = parse("Air Fryer 5L", None, CFG)
        b = parse("Air Fryer 5 Liter", None, CFG)
        c = parse("Air Fryer 5000 ml", None, CFG)
        self.assertEqual(a.units, b.units)
        self.assertEqual(a.units, c.units)

    def test_inch_and_cm(self):
        self.assertEqual(parse("Mirror 40 inch", None, CFG).units, {"len": {101.6}})
        self.assertIsNone(unit_conflict(parse("Mirror 40 inch", None, CFG), parse("Mirror 101.6cm", None, CFG), 0.03))

    def test_pack_of(self):
        self.assertEqual(parse("Steel Bottle pack of 2", None, CFG).units, {"cnt": {2.0}})
        self.assertEqual(parse("Knife Set 6 pcs", None, CFG).units, {"cnt": {6.0}})

    def test_bengali_digits_and_words(self):
        p = parse("পাঞ্জাবি ২ pcs", None, CFG)
        self.assertEqual(p.units, {"cnt": {2.0}})
        self.assertIn("পাঞ্জাবি", p.tokens)

    def test_model_codes(self):
        self.assertEqual(parse("Philips HD9252 Air Fryer", None, CFG).codes, {"hd9252"})
        self.assertEqual(parse("Panasonic MX-AC300 Mixer", None, CFG).codes, {"mxac300"})
        self.assertEqual(parse("Air Fryer 5L 1500W", None, CFG).codes, set())     # একক-সহ সংখ্যা কোড নয়

    def test_noise_and_brand_ignoring(self):
        self.assertEqual(parse("No Brand Best Quality Premium Mug", None, CFG).tokens, {"mug"})
        self.assertIsNone(normalize_brand("No Brand", CFG))
        self.assertIsNone(normalize_brand("Generic", CFG))
        self.assertEqual(normalize_brand("Philips", CFG), "philip")

    def test_brand_conflict_rules(self):
        a, b, c = (parse("x", br, CFG) for br in ("Philips", "Samsung", "Samsung Electronics"))
        self.assertTrue(brand_conflict(a, b))
        self.assertFalse(brand_conflict(b, c))            # একটা অন্যটার অংশ
        self.assertFalse(brand_conflict(a, parse("x", None, CFG)))

    def test_unit_conflict_only_when_both_have_dimension(self):
        a, b, c = (parse(t, None, CFG) for t in ("Fryer 5L", "Fryer 3.5L", "Fryer"))
        self.assertEqual(unit_conflict(a, b, 0.03), "vol")
        self.assertIsNone(unit_conflict(a, c, 0.03))
        self.assertIsNone(unit_conflict(a, parse("Fryer 5.1L", None, CFG), 0.03))   # সহনসীমার ভেতর


class ScoreTests(unittest.TestCase):
    def test_identical_titles_score_one(self):
        p = pair(item(1, "Digital Air Fryer"), item(2, "Digital Air Fryer", "cartup"))
        self.assertAlmostEqual(p.score, 1.0)
        self.assertEqual((p.a, p.b), (1, 2))

    def test_pair_is_ordered_by_id(self):
        p = pair(item(9, "Air Fryer"), item(3, "Air Fryer", "cartup"))
        self.assertEqual((p.a, p.b), (3, 9))

    def test_price_component(self):
        self.assertEqual(price_score(1000, 1000, CFG), (1.0, 1.0))
        self.assertEqual(price_score(1000, 1250, CFG)[0], 1.0)                   # অনুপাত ০.৮
        self.assertEqual(price_score(1000, 3000, CFG)[0], 0.0)
        mid = price_score(1000, 1500, CFG)[0]                                    # অনুপাত ০.৬৭
        self.assertTrue(0 < mid < 1)
        self.assertEqual(price_score(None, 1000, CFG), (None, None))

    def test_price_difference_lowers_score(self):
        same = pair(item(1, "Air Fryer Steel", price=5000), item(2, "Air Fryer Steel", "cartup", price=5100))
        far = pair(item(1, "Air Fryer Steel", price=5000), item(2, "Air Fryer Steel", "cartup", price=9000))
        self.assertGreater(same.score, far.score)

    def test_missing_price_does_not_penalize(self):
        p = pair(item(1, "Air Fryer Steel", price=5000), item(2, "Air Fryer Steel", "cartup"))
        self.assertAlmostEqual(p.score, 1.0)

    def test_rare_shared_token_counts_more(self):
        filler = [item(10 + i, f"Kitchen Item Set Steel Common {i}") for i in range(10)]
        rare = pair(item(1, "Zorbax Common"), item(2, "Zorbax Other", "cartup"), filler)
        common = pair(item(1, "Common Zorbax"), item(2, "Common Other", "cartup"), filler)
        self.assertGreater(rare.title_sim, common.title_sim)

    def test_model_code_bonus(self):
        a, b = item(1, "Philips HD9252 Air Fryer Big"), item(2, "HD9252 Fryer", "cartup")
        p = pair(a, b)
        self.assertTrue(p.code_match)
        c, d = item(1, "Philips Air Fryer Big"), item(2, "Fryer", "cartup")
        self.assertGreater(p.score, pair(c, d).score)

    def test_conflicts_flagged(self):
        self.assertEqual(pair(item(1, "Air Fryer 5L"), item(2, "Air Fryer 3.5L", "cartup")).conflict, "vol")
        self.assertEqual(pair(item(1, "Air Fryer", brand="Philips"), item(2, "Air Fryer", "cartup", brand="Samsung")).conflict, "brand")
        self.assertIsNone(pair(item(1, "Air Fryer"), item(2, "Air Fryer", "cartup")).conflict)

    def test_bengali_titles(self):
        p = pair(item(1, "ছেলেদের পাঞ্জাবি কটন"), item(2, "পাঞ্জাবি কটন ছেলেদের", "cartup"))
        self.assertAlmostEqual(p.score, 1.0)


class DecisionTests(unittest.TestCase):
    def _p(self, score, same=False, conflict=None):
        from matching.score import Pair
        return Pair(1, 2, score, score, None, [], False, conflict, same)

    def test_bands(self):
        self.assertEqual(decide(self._p(0.9), CFG), "auto")
        self.assertEqual(decide(self._p(0.7), CFG), "review")
        self.assertIsNone(decide(self._p(0.5), CFG))

    def test_conflict_vetoes(self):
        self.assertIsNone(decide(self._p(0.99, conflict="vol"), CFG))

    def test_same_source_policy(self):
        self.assertEqual(decide(self._p(0.99, same=True), CFG), "review")
        self.assertIsNone(decide(self._p(0.99, same=True), load_config(override={"same_source": "never"})))
        self.assertEqual(decide(self._p(0.99, same=True), load_config(override={"same_source": "auto"})), "auto")


class BlockingTests(unittest.TestCase):
    def test_only_same_category_and_shared_token(self):
        items = [item(1, "Air Fryer"), item(2, "Air Cooler", cat="home"), item(3, "Fryer Basket"), item(4, "Mug")]
        prepare(items, CFG)
        got = {(a.id, b.id) for a, b in candidate_pairs(items, idf_weights(items), CFG)}
        self.assertEqual(got, {(1, 3)})

    def test_very_common_tokens_do_not_block(self):
        items = [item(i, f"Steel Thing{i}") for i in range(100)]
        prepare(items, CFG)
        self.assertEqual(candidate_pairs(items, idf_weights(items), CFG), [])      # "steel" ১০০টায়, সীমার বেশি

    def test_null_category_is_skipped(self):
        items = [item(1, "Air Fryer", cat=None), item(2, "Air Fryer", cat=None)]
        prepare(items, CFG)
        self.assertEqual(candidate_pairs(items, idf_weights(items), CFG), [])


class ConfigTests(unittest.TestCase):
    def test_shipped_config_valid(self):
        self.assertLess(CFG["thresholds"]["review"], CFG["thresholds"]["auto"])

    def test_bad_thresholds(self):
        with self.assertRaises(MatchConfigError):
            load_config(override={"thresholds": {"review": 0.9, "auto": 0.8}})
        with self.assertRaises(MatchConfigError):
            load_config(override={"same_source": "maybe"})


if __name__ == "__main__":
    unittest.main()
