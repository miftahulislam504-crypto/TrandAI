"""জোড়ার মিল-স্কোর। বিশুদ্ধ গণিত, DB বা নেটওয়ার্ক ছাড়া।

স্কোর = (title_ওজন × শব্দ-মিল + price_ওজন × দাম-মিল) ÷ উপস্থিত ওজন, মডেল কোড মিললে + bonus।
- শব্দ-মিল: IDF-ওজনযুক্ত Jaccard (বিরল শব্দের মিল বেশি দামি, "air", "set"-এর মতো সাধারণ শব্দের কম)
- দাম-মিল: দুই দামের অনুপাত (ছোট÷বড়) full_score_ratio বা তার উপরে = ১, zero_score_ratio বা নিচে = ০, মাঝে সরলরেখা। দাম না থাকলে বাদ
- সংঘাত (ভিন্ন ব্র্যান্ড বা ভিন্ন মাপ/ওজন/সংখ্যা/ওয়াট) থাকলে মিল নেই, স্কোর যতই হোক
ছবির মিল (image.py): দুই listing-এর ছবির dHash কাছাকাছি হলে বোনাস। ছবি শুধু প্রমাণ বাড়ায়, কখনও একা নিজে মার্জ করায় না
(টাইটেলের মিল auto_title_floor-এর নিচে হলে স্কোর auto-র নিচে আটকানো), আর টাইটেলে মিল না থাকলেও (যেমন বাংলা বনাম
ইংরেজি নাম) ছবি একদম এক হলে ও দাম কাছাকাছি হলে জোড়াটা রিভিউ কিউতে যায়। সংঘাত (ব্র্যান্ড/মাপ/ওজন) থাকলে ছবি যতই মিলুক, মিল নেই।
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional

from .image import distance as image_distance
from .image import drop_ambiguous, near_pairs
from .parse import Parsed, brand_conflict, parse, unit_conflict


@dataclass
class Item:
    id: int                      # listing id
    canonical_id: Optional[int]
    source: str
    category: Optional[str]
    title: str
    brand: Optional[str]
    price: Optional[float]
    parsed: Parsed = field(default=None)  # type: ignore[assignment]
    image_hash: Optional[int] = None     # 64-বিট dHash; None = নেই, বা বিভ্রান্তিকর বলে বাদ


@dataclass
class Pair:
    a: int                       # listing id (a < b)
    b: int
    score: float
    title_sim: float
    price_ratio: Optional[float]
    shared: list[str]
    code_match: bool
    conflict: Optional[str]      # None | "brand" | "vol" | "wt" | "len" | "cnt" | "pwr"
    same_source: bool
    decision: Optional[str] = None   # "auto" | "review" | None
    note: Optional[str] = None
    image_dist: Optional[int] = None  # দুই ছবির dHash দূরত্ব (0 = একই), ছবি না থাকলে None
    image_lift: bool = False          # ছবির কারণে স্কোর বেড়েছে বা রিভিউয়ে উঠেছে

    def evidence(self) -> dict:
        return {"title_sim": round(self.title_sim, 3), "price_ratio": None if self.price_ratio is None else round(self.price_ratio, 3),
                "shared": self.shared[:12], "code_match": self.code_match, "same_source": self.same_source, "note": self.note,
                "image_dist": self.image_dist, "image_lift": self.image_lift}


def prepare(items: list[Item], cfg: dict) -> dict:
    """টাইটেল পার্স ও ছবির হ্যাশ ছাঁটাই। ফেরত: {\"image_ambiguous\": বাদ পড়া হ্যাশের সংখ্যা}।"""
    for it in items:
        it.parsed = parse(it.title, it.brand, cfg)
    im = cfg.get("image") or {}
    if not im.get("enabled"):
        for it in items:
            it.image_hash = None
        return {"image_ambiguous": 0}
    kept, dropped = drop_ambiguous({it.id: it.image_hash for it in items if it.image_hash is not None}, im["max_hash_group"])
    for it in items:
        if it.image_hash is not None and it.id not in kept:
            it.image_hash = None
    return {"image_ambiguous": dropped}


def idf_weights(items: list[Item]) -> dict[str, float]:
    df: dict[str, int] = defaultdict(int)
    for it in items:
        for t in it.parsed.tokens:
            df[t] += 1
    n = len(items)
    return {t: math.log((n + 1) / (d + 0.5)) + 0.3 for t, d in df.items()}


def title_similarity(a: Parsed, b: Parsed, idf: dict[str, float]) -> tuple[float, list[str]]:
    inter = a.tokens & b.tokens
    union = a.tokens | b.tokens
    if not union:
        return 0.0, []
    w = lambda ts: sum(idf.get(t, 1.0) for t in ts)  # noqa: E731
    return w(inter) / w(union), sorted(inter, key=lambda t: -idf.get(t, 1.0))


def price_score(pa: Optional[float], pb: Optional[float], cfg: dict) -> tuple[Optional[float], Optional[float]]:
    if not pa or not pb or pa <= 0 or pb <= 0:
        return None, None
    ratio = min(pa, pb) / max(pa, pb)
    full, zero = cfg["price"]["full_score_ratio"], cfg["price"]["zero_score_ratio"]
    if ratio >= full:
        return 1.0, ratio
    if ratio <= zero:
        return 0.0, ratio
    return (ratio - zero) / (full - zero), ratio


def score_pair(x: Item, y: Item, idf: dict[str, float], cfg: dict) -> Pair:
    a, b = (x, y) if x.id < y.id else (y, x)
    sim, shared = title_similarity(a.parsed, b.parsed, idf)
    ps, ratio = price_score(a.price, b.price, cfg)
    w = cfg["weights"]
    num, den = w["title"] * sim, w["title"]
    if ps is not None and w["price"] > 0:
        num += w["price"] * ps
        den += w["price"]
    score = num / den
    code_match = bool(a.parsed.codes & b.parsed.codes)
    if code_match:
        score = min(1.0, score + cfg["model_code_bonus"])
    conflict = "brand" if brand_conflict(a.parsed, b.parsed) else unit_conflict(a.parsed, b.parsed, cfg["unit_tolerance"])
    dist, lifted = None, False
    im = cfg.get("image") or {}
    if im.get("enabled") and a.image_hash is not None and b.image_hash is not None:
        dist = image_distance(a.image_hash, b.image_hash)
        if not conflict:
            score, lifted = _apply_image(score, sim, ratio, dist, cfg)
    p = Pair(a.id, b.id, score, sim, ratio, shared, code_match, conflict, a.source == b.source)
    p.image_dist, p.image_lift = dist, lifted
    return p


def _apply_image(score: float, sim: float, ratio: Optional[float], dist: int, cfg: dict) -> tuple[float, bool]:
    """ছবির দূরত্ব থেকে স্কোর সমন্বয়। (নতুন স্কোর, ছবির কারণে বদলেছে কি না)।"""
    im, t = cfg["image"], cfg["thresholds"]
    if dist <= im["strong_dist"]:
        bonus = im["strong_bonus"]
    elif dist <= im["near_dist"]:
        bonus = im["near_bonus"]
    else:
        return score, False        # ছবি আলাদা মানে আলাদা প্রোডাক্ট নয় (একই প্রোডাক্টের ভিন্ন ফটো থাকে), তাই শাস্তি নেই
    new = min(1.0, score + bonus)
    # ছবি একা নিজে মার্জ করাতে পারে না: টাইটেল যথেষ্ট না মিললে auto-র নিচে আটকানো
    if sim < im["auto_title_floor"]:
        new = min(new, max(score, t["auto"] - 0.001))   # ছবি স্কোর কখনও কমায় না
    # টাইটেলে মিল না থাকলেও (বাংলা বনাম ইংরেজি নাম) একদম এক ছবি ও কাছাকাছি দাম হলে অন্তত রিভিউতে তোলা
    price_ok = ratio is None or ratio >= cfg["price"]["zero_score_ratio"]
    if im.get("image_only_review") and dist <= im["strong_dist"] and price_ok:
        new = max(new, t["review"])
    return new, new > score


def decide(p: Pair, cfg: dict) -> Optional[str]:
    if p.conflict:
        return None
    if p.same_source and cfg["same_source"] == "never":
        return None
    t = cfg["thresholds"]
    if p.score >= t["auto"]:
        return "review" if (p.same_source and cfg["same_source"] == "review") else "auto"
    if p.score >= t["review"]:
        return "review"
    return None


def candidate_pairs(items: list[Item], idf: dict[str, float], cfg: dict) -> list[tuple[Item, Item]]:
    """একই ক্যাটাগরির ভেতরে বিরল শব্দ ভাগ করা জোড়া। খুব সাধারণ শব্দ (পোস্টিং লিস্ট বড়) দিয়ে ব্লক করা হয় না, নইলে জোড়া বিস্ফোরিত হয়।"""
    bl = cfg["blocking"]
    by_cat: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        if it.category:
            by_cat[it.category].append(it)
    seen: set[tuple[int, int]] = set()
    out: list[tuple[Item, Item]] = []
    need = cfg["min_shared_tokens"]
    for group in by_cat.values():
        index: dict[str, list[Item]] = defaultdict(list)
        for it in group:
            for t in it.parsed.tokens:
                index[t].append(it)
        cap = max(bl["min_posting_size"], int(bl["max_posting_share"] * len(group)))
        counts: dict[tuple[int, int], int] = defaultdict(int)
        for t, posting in index.items():
            if len(posting) < 2 or len(posting) > cap:
                continue
            for x, y in combinations(posting, 2):
                counts[(min(x.id, y.id), max(x.id, y.id))] += 1
        byid = {it.id: it for it in group}
        for (i, j), c in counts.items():
            if c >= need and (i, j) not in seen:
                seen.add((i, j))
                out.append((byid[i], byid[j]))
    # ছবির মিল থেকে বাড়তি প্রার্থী: টাইটেলে কোনো শব্দ না মিললেও (বাংলা বনাম ইংরেজি) ধরা পড়ে
    im = cfg.get("image") or {}
    if im.get("enabled"):
        for group in by_cat.values():
            withimg = {it.id: it.image_hash for it in group if it.image_hash is not None}
            if len(withimg) < 2:
                continue
            byid = {it.id: it for it in group}
            cap = max(bl["min_posting_size"], int(bl["max_posting_share"] * len(group)))
            for i, j, _d in near_pairs(withimg, im["near_dist"], posting_cap=cap):
                if (i, j) not in seen:
                    seen.add((i, j))
                    out.append((byid[i], byid[j]))
    return out
