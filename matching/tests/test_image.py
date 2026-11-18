"""ছবির মিলের টেস্ট: dHash, ছাঁটাই, কাছাকাছি-জোড়া খোঁজা, স্কোর/সিদ্ধান্তে প্রভাব, রান, হ্যাশ-রানার।
Pillow না থাকলে শুধু হ্যাশ বের করার টেস্টগুলো বাদ যায়, বাকিগুলো (পূর্ণসংখ্যা হ্যাশ নিয়ে) চলে।"""
import io
import random
import unittest
from datetime import datetime, timezone

from matching import hash_images, run_matching
from matching.config import MatchConfigError, load_config
from matching.image import ImageError, dhash_bytes, distance, drop_ambiguous, from_hex, near_pairs, to_hex
from matching.plan import build_plan
from matching.score import Item, candidate_pairs, decide, idf_weights, prepare, score_pair
from matching.tests.test_plan_run import FakeDB, L
from scrapers.common.http import BlockedError, CircuitOpen, FetchError

try:
    from PIL import Image, ImageDraw
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False

CFG = load_config()
NOW = datetime(2026, 11, 15, 2, 40, tzinfo=timezone.utc)

H = 0x0F0F_3C3C_A5A5_6969          # একটা "ছবির" হ্যাশ
H_NEAR = H ^ 0b101                  # ২ বিট আলাদা
H_MID = H ^ 0b1111111111            # ১০ বিট আলাদা
H_FAR = H ^ 0x00FF_FFFF_FFFF_0000   # ৪০ বিট আলাদা


def flip(h, n, seed=0):
    r = random.Random(seed)
    for b in r.sample(range(64), n):
        h ^= 1 << b
    return h


def pic(seed: int, size=(480, 480)) -> "Image.Image":
    """সিড-ভিত্তিক গঠনযুক্ত নকল 'ছবি' (গ্রেডিয়েন্ট + কিছু আকার)।"""
    r = random.Random(seed)
    im = Image.new("RGB", size, (r.randint(0, 255), r.randint(0, 255), r.randint(0, 255)))
    d = ImageDraw.Draw(im)
    for _ in range(14):
        x0, y0 = r.randint(0, size[0] - 60), r.randint(0, size[1] - 60)
        box = (x0, y0, x0 + r.randint(30, 200), y0 + r.randint(30, 200))
        col = (r.randint(0, 255), r.randint(0, 255), r.randint(0, 255))
        (d.ellipse if r.random() < 0.5 else d.rectangle)(box, fill=col)
    return im


def encode(im, fmt="JPEG", **kw) -> bytes:
    b = io.BytesIO()
    im.save(b, fmt, **kw)
    return b.getvalue()


def it(i, title, source="daraz", cat="kitchen", price=None, h=None, canon=None, brand=None):
    return Item(id=i, canonical_id=i if canon is None else canon, source=source, category=cat, title=title,
                brand=brand, price=price, image_hash=h)


def pair(a, b, cfg=CFG, extra=()):
    items = [a, b, *extra]
    prepare(items, cfg)
    return score_pair(a, b, idf_weights(items), cfg)


@unittest.skipUnless(HAVE_PIL, "Pillow ইনস্টল নেই")
class DhashTests(unittest.TestCase):
    def test_same_picture_after_resize_and_recompress_is_close(self):
        im = pic(1)
        base = dhash_bytes(encode(im, quality=95))
        small = dhash_bytes(encode(im.resize((200, 200)), quality=60))
        png = dhash_bytes(encode(im.resize((640, 640)), "PNG"))
        self.assertLessEqual(distance(base, small), 6)
        self.assertLessEqual(distance(base, png), 6)

    def test_different_pictures_are_far(self):
        ds = [distance(dhash_bytes(encode(pic(1))), dhash_bytes(encode(pic(s)))) for s in (2, 3, 4, 5, 6)]
        self.assertGreater(min(ds), 10)

    def test_flat_image_is_unreliable(self):
        self.assertIsNone(dhash_bytes(encode(Image.new("RGB", (300, 300), "white"))))

    def test_garbage_and_truncated_raise(self):
        with self.assertRaises(ImageError):
            dhash_bytes(b"not an image at all")
        with self.assertRaises(ImageError):
            dhash_bytes(encode(pic(1))[:200])

    def test_transparent_png_is_composited_on_white(self):
        rgba = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        ImageDraw.Draw(rgba).ellipse((60, 60, 240, 240), fill=(200, 30, 30, 255))
        opaque = Image.new("RGB", (300, 300), "white")
        opaque.paste(rgba, mask=rgba.split()[3])
        self.assertLessEqual(distance(dhash_bytes(encode(rgba, "PNG")), dhash_bytes(encode(opaque))), 8)


class HashHelperTests(unittest.TestCase):
    def test_hex_roundtrip_and_bad_input(self):
        self.assertEqual(from_hex(to_hex(H)), H)
        self.assertEqual(len(to_hex(1)), 16)
        for bad in (None, "", "zz", "abc", "0" * 17):
            self.assertIsNone(from_hex(bad))

    def test_distance(self):
        self.assertEqual(distance(H, H), 0)
        self.assertEqual(distance(H, H_NEAR), 2)

    def test_drop_ambiguous_removes_placeholder_groups(self):
        hashes = {i: 0xAAAA for i in range(15)}
        hashes.update({100: H, 101: H, 102: H_FAR})
        kept, dropped = drop_ambiguous(hashes, 12)
        self.assertEqual(dropped, 15)
        self.assertEqual(sorted(kept), [100, 101, 102])

    def test_near_pairs_matches_brute_force(self):
        r = random.Random(7)
        base = [r.getrandbits(64) for _ in range(40)]
        hashes = {}
        for k, h in enumerate(base):
            hashes[k] = h
            hashes[1000 + k] = flip(h, r.randint(0, 12), seed=k)     # কাছাকাছি/মাঝারি/দূরের কপি
        for md in (3, 6, 10):
            expect = {(i, j, distance(hashes[i], hashes[j])) for i in hashes for j in hashes
                      if i < j and distance(hashes[i], hashes[j]) <= md}
            got = set(near_pairs(hashes, md, posting_cap=10_000))
            self.assertEqual(got, expect, f"max_dist={md}")

    def test_near_pairs_trivial(self):
        self.assertEqual(near_pairs({}, 6), [])
        self.assertEqual(near_pairs({1: H}, 6), [])
        self.assertEqual(near_pairs({1: H, 2: H}, 6), [(1, 2, 0)])


class ScoreImageTests(unittest.TestCase):
    def test_strong_image_adds_bonus(self):
        no = pair(it(1, "Steel Water Bottle Insulated", price=500), it(2, "Steel Water Bottle Vacuum", "cartup", price=500))
        yes = pair(it(1, "Steel Water Bottle Insulated", price=500, h=H), it(2, "Steel Water Bottle Vacuum", "cartup", price=500, h=H_NEAR))
        self.assertGreater(yes.score, no.score)
        self.assertEqual(yes.image_dist, 2)
        self.assertTrue(yes.image_lift)
        self.assertEqual(yes.evidence()["image_dist"], 2)

    def test_near_bonus_smaller_than_strong(self):
        strong = pair(it(1, "Steel Water Bottle Insulated", h=H), it(2, "Steel Water Bottle Vacuum", "cartup", h=H_NEAR))
        near = pair(it(1, "Steel Water Bottle Insulated", h=H), it(2, "Steel Water Bottle Vacuum", "cartup", h=H_MID))
        self.assertGreater(strong.score, near.score)

    def test_different_image_is_not_a_penalty(self):
        a, b = it(1, "Steel Water Bottle Insulated", price=500), it(2, "Steel Water Bottle Vacuum", "cartup", price=500)
        base = pair(a, b)
        far = pair(it(1, "Steel Water Bottle Insulated", price=500, h=H), it(2, "Steel Water Bottle Vacuum", "cartup", price=500, h=H_FAR))
        self.assertAlmostEqual(far.score, base.score)
        self.assertEqual(far.image_dist, distance(H, H_FAR))
        self.assertGreater(far.image_dist, CFG["image"]["near_dist"])
        self.assertFalse(far.image_lift)

    def test_image_alone_cannot_auto_merge(self):
        # টাইটেলের মিল কম (১ শব্দ মেলে), ছবি একদম এক, দামও এক: আগে auto হতো না, এখনও auto নয়, তবে রিভিউতে উঠবে
        p = pair(it(1, "Steel Bottle Large Premium Thermos Flask", price=500, h=H),
                 it(2, "Steel Mug Small Travel Cup Handle", "cartup", price=500, h=H))
        self.assertLess(p.score, CFG["thresholds"]["auto"])
        self.assertEqual(decide(p, CFG), "review")

    def test_image_can_confirm_when_titles_are_close(self):
        # নাম মোটামুটি মেলে (auto_title_floor পার) + একই ছবি: নিজে মার্জের যোগ্য হতে পারে
        p = pair(it(1, "Digital Air Fryer Oven Steel", "daraz", price=5000, h=H),
                 it(2, "Digital Air Fryer Oven", "cartup", price=5100, h=H_NEAR))
        self.assertGreaterEqual(p.score, CFG["thresholds"]["auto"])
        self.assertEqual(decide(p, CFG), "auto")

    def test_image_does_not_lower_an_already_high_score(self):
        a, b = it(1, "Digital Air Fryer Oven", price=5000), it(2, "Digital Air Fryer Oven", "cartup", price=5000)
        base = pair(a, b).score
        with_img = pair(it(1, "Digital Air Fryer Oven", price=5000, h=H), it(2, "Digital Air Fryer Oven", "cartup", price=5000, h=H_MID)).score
        self.assertGreaterEqual(with_img, base - 1e-9)

    def test_conflict_vetoes_even_with_identical_image(self):
        p = pair(it(1, "Air Fryer 5L", price=5000, h=H), it(2, "Air Fryer 3.5L", "cartup", price=5000, h=H))
        self.assertEqual(p.conflict, "vol")
        self.assertIsNone(decide(p, CFG))
        self.assertFalse(p.image_lift)
        p = pair(it(1, "Steel Bottle Large", brand="Acme", h=H), it(2, "Steel Bottle Large", "cartup", brand="Zeta", h=H))
        self.assertEqual(p.conflict, "brand")
        self.assertIsNone(decide(p, CFG))

    def test_bengali_vs_english_same_image_goes_to_review(self):
        p = pair(it(1, "কটন পাঞ্জাবি", price=900, h=H), it(2, "Cotton Panjabi", "cartup", price=950, h=H_NEAR))
        self.assertEqual(p.title_sim, 0.0)
        self.assertEqual(decide(p, CFG), "review")
        self.assertTrue(p.image_lift)

    def test_image_only_needs_plausible_price(self):
        p = pair(it(1, "কটন পাঞ্জাবি", price=900, h=H), it(2, "Cotton Panjabi", "cartup", price=3000, h=H))
        self.assertIsNone(decide(p, CFG))                 # দাম ৩ গুণ: একই ছবি তবু জোড়া নয় (ভিন্ন প্যাক হতে পারে)
        p = pair(it(1, "কটন পাঞ্জাবি", h=H), it(2, "Cotton Panjabi", "cartup", h=H))
        self.assertEqual(decide(p, CFG), "review")        # দাম অজানা হলে বাধা নেই

    def test_image_only_review_can_be_disabled(self):
        cfg = load_config(override={"image": {"image_only_review": False}})
        p = pair(it(1, "কটন পাঞ্জাবি", price=900, h=H), it(2, "Cotton Panjabi", "cartup", price=950, h=H), cfg=cfg)
        self.assertIsNone(decide(p, cfg))

    def test_disabled_ignores_hashes(self):
        cfg = load_config(override={"image": {"enabled": False}})
        a, b = it(1, "কটন পাঞ্জাবি", h=H), it(2, "Cotton Panjabi", "cartup", h=H)
        p = pair(a, b, cfg=cfg)
        self.assertIsNone(p.image_dist)
        self.assertIsNone(a.image_hash)

    def test_missing_hash_on_one_side_is_neutral(self):
        p = pair(it(1, "Steel Water Bottle Insulated", h=H), it(2, "Steel Water Bottle Vacuum", "cartup"))
        self.assertIsNone(p.image_dist)
        self.assertFalse(p.image_lift)

    def test_bad_image_config_rejected(self):
        for bad in ({"strong_dist": 12, "near_dist": 8}, {"near_bonus": 0.4, "strong_bonus": 0.2}, {"max_hash_group": 1}):
            with self.assertRaises(MatchConfigError):
                load_config(override={"image": bad})


class CandidateAndPlanTests(unittest.TestCase):
    def test_image_finds_pair_without_any_shared_title_word(self):
        items = [it(1, "কটন পাঞ্জাবি", h=H), it(2, "Cotton Panjabi", "cartup", h=H_NEAR), it(3, "Steel Mug")]
        prepare(items, CFG)
        got = {(x.id, y.id) for x, y in candidate_pairs(items, idf_weights(items), CFG)}
        self.assertEqual(got, {(1, 2)})
        no_img = [it(1, "কটন পাঞ্জাবি"), it(2, "Cotton Panjabi", "cartup"), it(3, "Steel Mug")]
        prepare(no_img, CFG)
        self.assertEqual(candidate_pairs(no_img, idf_weights(no_img), CFG), [])

    def test_image_pairs_stay_inside_category(self):
        items = [it(1, "কটন পাঞ্জাবি", cat="fashion", h=H), it(2, "Cotton Panjabi", "cartup", cat="home", h=H)]
        prepare(items, CFG)
        self.assertEqual(candidate_pairs(items, idf_weights(items), CFG), [])

    def test_plan_puts_cross_language_image_pair_in_review_not_merge(self):
        plan = build_plan([it(1, "কটন পাঞ্জাবি", price=900, h=H), it(2, "Cotton Panjabi", "cartup", price=920, h=H_NEAR)], CFG)
        self.assertEqual((plan.merges, plan.auto), ([], []))
        self.assertEqual([(p.a, p.b) for p in plan.review], [(1, 2)])
        self.assertEqual(plan.stats["image_lifted"], 1)

    def test_placeholder_image_on_many_listings_is_ignored(self):
        items = [it(i, f"Item{i} Widget{i}", "daraz", h=0xDEAD_BEEF_DEAD_BEEF) for i in range(1, 16)]
        plan = build_plan(items, CFG)
        self.assertEqual(plan.stats["image_ambiguous"], 15)
        self.assertEqual((plan.merges, plan.auto, plan.review), ([], [], []))

    def test_small_real_group_of_sellers_is_kept(self):
        items = [it(i, f"Item{i} Widget{i}", "daraz", h=H) for i in range(1, 6)]    # ৫ সেলার একই ছবি: স্বাভাবিক
        plan = build_plan(items, CFG)
        self.assertEqual(plan.stats["image_ambiguous"], 0)
        self.assertEqual(len(plan.review), 10)

    def test_chain_guard_still_applies_with_images(self):
        a = it(1, "Digital Air Fryer 5L", "daraz", price=5000, h=H)
        b = it(2, "Digital Air Fryer", "cartup", price=5000, h=H)
        c = it(3, "Digital Air Fryer 3.5L", "othoba", price=5000, h=H)
        plan = build_plan([a, b, c], CFG)
        merged = {(w, l) for w, l in plan.merges}
        self.assertFalse({(1, 2), (1, 3)} <= merged)        # ৫L আর ৩.৫L একই গ্রুপে যেতে পারে না


class RunWithImagesTests(unittest.TestCase):
    def test_run_loads_hashes_and_records_evidence(self):
        db = FakeDB([L(1, "কটন পাঞ্জাবি", "daraz", 10, image_hash=to_hex(H), price=900),
                     L(2, "Cotton Panjabi", "cartup", 20, image_hash=to_hex(H_NEAR), price=920),
                     L(3, "Mug", "daraz", 30)])
        s = run_matching.run(db, CFG, now=NOW)
        self.assertEqual(s["with_image_hash"], 2)
        self.assertEqual(s["plan"]["image_lifted"], 1)
        row = next(c for c in db.cands if (c["listing_a"], c["listing_b"]) == (1, 2))
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["evidence"]["image_dist"], 2)
        self.assertIn("ছবি", run_matching.summary_markdown(s))

    def test_without_hashes_behaves_as_before(self):
        db = FakeDB([L(1, "কটন পাঞ্জাবি", "daraz", 10), L(2, "Cotton Panjabi", "cartup", 20)])
        s = run_matching.run(db, CFG, now=NOW)
        self.assertEqual((s["with_image_hash"], s["plan"]["review_pairs"]), (0, 0))


# ------------------------------------------------------------------ হ্যাশ-রানার
class HashDB:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.updates = []

    def select(self, table, params=None, page_size=1000):
        assert table == "listings"
        return [dict(r) for r in self.rows if r.get("image_url") and r.get("is_active", True)]

    def update(self, table, values, params):
        i = int(params["id"][3:])
        self.updates.append((i, values))
        for r in self.rows:
            if r["id"] == i:
                r.update(values)


class HashClient:
    def __init__(self, by_url):
        self.by_url, self.calls = by_url, []

    def get_bytes(self, url, max_bytes=0):
        self.calls.append(url)
        v = self.by_url[url]
        if isinstance(v, Exception):
            raise v
        return v


@unittest.skipUnless(HAVE_PIL, "Pillow ইনস্টল নেই")
class HashRunnerTests(unittest.TestCase):
    def setUp(self):
        self.good = encode(pic(1))
        self.flat = encode(Image.new("RGB", (200, 200), "white"))

    def rows(self):
        return [{"id": 1, "image_url": "u1"}, {"id": 2, "image_url": "u2"}, {"id": 3, "image_url": "u3"},
                {"id": 4, "image_url": "u4"}, {"id": 5, "image_url": "u5"},
                {"id": 6, "image_url": "u6", "image_hash_url": "u6", "image_hash": to_hex(H)},     # আগেই হয়েছে
                {"id": 7, "image_url": None}]

    def test_outcomes_are_recorded_correctly(self):
        db = HashDB(self.rows())
        cl = HashClient({"u1": self.good, "u2": self.flat, "u3": b"junk", "u4": FetchError("HTTP 404"), "u5": self.good})
        s = hash_images.run(db, cl, CFG, now=NOW)
        self.assertEqual((s["pending_before"], s["tried"], s["hashed"], s["flat"], s["unreadable"], s["fetch_errors"]),
                         (5, 4, 2, 1, 1, 1))
        done = {i: v for i, v in db.updates}
        self.assertEqual(sorted(done), [1, 2, 3, 5])                 # ফেচ ব্যর্থ (৪) কিছু লেখেনি: পরের রানে আবার চেষ্টা
        self.assertIsNotNone(done[1]["image_hash"])
        self.assertIsNone(done[2]["image_hash"])                      # সমতল: null, কিন্তু চেষ্টা হয়েছে বলে URL বসানো
        self.assertEqual(done[2]["image_hash_url"], "u2")
        self.assertNotIn("u6", cl.calls)
        self.assertEqual(s["pending_after"], 1)

    def test_second_run_only_retries_failures(self):
        db = HashDB(self.rows())
        cl = HashClient({"u1": self.good, "u2": self.flat, "u3": b"junk", "u4": FetchError("x"), "u5": self.good})
        hash_images.run(db, cl, CFG, now=NOW)
        cl2 = HashClient({"u4": self.good})
        s = hash_images.run(db, cl2, CFG, now=NOW)
        self.assertEqual(cl2.calls, ["u4"])
        self.assertEqual(s["hashed"], 1)

    def test_changed_url_is_rehashed(self):
        db = HashDB([{"id": 1, "image_url": "new", "image_hash_url": "old", "image_hash": to_hex(H)}])
        cl = HashClient({"new": self.good})
        hash_images.run(db, cl, CFG, now=NOW)
        self.assertEqual(cl.calls, ["new"])
        self.assertEqual(db.rows[0]["image_hash_url"], "new")

    def test_limit_caps_the_batch(self):
        db = HashDB(self.rows())
        cl = HashClient({f"u{i}": self.good for i in range(1, 6)})
        s = hash_images.run(db, cl, CFG, limit=2, now=NOW)
        self.assertEqual((s["tried"], s["pending_after"]), (2, 3))

    def test_circuit_open_stops_without_writing_the_rest(self):
        db = HashDB(self.rows())
        cl = HashClient({"u1": self.good, "u2": CircuitOpen("stop")})
        s = hash_images.run(db, cl, CFG, now=NOW)
        self.assertTrue(s["circuit_open"])
        self.assertEqual([i for i, _ in db.updates], [1])
        self.assertEqual(len(cl.calls), 2)
        self.assertIn("থেমেছে", hash_images.summary_markdown(s))


if __name__ == "__main__":
    unittest.main()
