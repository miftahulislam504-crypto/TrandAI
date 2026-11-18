"""টাইটেল থেকে ম্যাচিংয়ের উপাদান: শব্দ, একক-সহ সংখ্যা (৫ লিটার, ২৮ সেমি), মডেল কোড, ব্র্যান্ড।

ইচ্ছে করে রঙ ও সাইজ (S/M/L/XL) আলাদা করা হয়নি, শুধু শব্দ হিসেবে থাকে। ফ্যাশনে একই প্রোডাক্টের ভ্যারিয়েন্ট একটাই প্রোডাক্ট (README: ভ্যারিয়েন্ট মিলিয়ে স্কোর)।
কিন্তু ধারণক্ষমতা, ওজন, মাপ, সংখ্যা ও ওয়াট ভিন্ন হলে ভিন্ন প্রোডাক্ট ধরা হয় (৫ লিটার এয়ার ফ্রায়ার আর ৩.৫ লিটার এক নয়)।
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from trends.keywords import tokens

# একক -> (ডাইমেনশন, বেস এককে গুণক)। ভলিউম ml, ওজন g, দৈর্ঘ্য cm, সংখ্যা pc, ক্ষমতা w
_UNITS = {
    "l": ("vol", 1000.0), "ltr": ("vol", 1000.0), "litre": ("vol", 1000.0), "liter": ("vol", 1000.0), "lit": ("vol", 1000.0),
    "ml": ("vol", 1.0),
    "kg": ("wt", 1000.0), "g": ("wt", 1.0), "gm": ("wt", 1.0), "gram": ("wt", 1.0), "mg": ("wt", 0.001),
    "cm": ("len", 1.0), "mm": ("len", 0.1), "m": ("len", 100.0), "inch": ("len", 2.54), "in": ("len", 2.54), "ft": ("len", 30.48),
    "pcs": ("cnt", 1.0), "pc": ("cnt", 1.0), "piece": ("cnt", 1.0), "pieces": ("cnt", 1.0), "pic": ("cnt", 1.0), "pics": ("cnt", 1.0),
    "pack": ("cnt", 1.0), "set": ("cnt", 1.0),
    "w": ("pwr", 1.0), "watt": ("pwr", 1.0), "watts": ("pwr", 1.0), "kw": ("pwr", 1000.0),
}
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_NUM_UNIT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*-?\s*(" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")\b", re.I)
_PACK_OF = re.compile(r"\b(?:pack|set|combo|box)\s+of\s+(\d+)\b", re.I)
_CODE = re.compile(r"^(?:[a-z]{1,6}\d{2,6}[a-z]{0,2}|\d{2,5}[a-z]{1,4}\d{0,3})$")
_CHUNK = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_UNIT_LIKE = re.compile(r"^\d+(?:\.\d+)?(?:" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")$", re.I)


@dataclass
class Parsed:
    tokens: set[str] = field(default_factory=set)
    units: dict[str, set[float]] = field(default_factory=dict)   # ডাইমেনশন -> বেস এককে মান
    codes: set[str] = field(default_factory=set)
    brand: Optional[str] = None


def normalize_brand(brand: Optional[str], cfg: dict) -> Optional[str]:
    if not brand:
        return None
    b = " ".join(tokens(brand))
    return None if not b or b in set(cfg["ignore_brands"]) else b


def parse(title: Optional[str], brand: Optional[str], cfg: dict) -> Parsed:
    text = (title or "").translate(_BN_DIGITS).lower()
    p = Parsed(brand=normalize_brand(brand, cfg))
    for num, unit in _NUM_UNIT.findall(text):
        dim, mult = _UNITS[unit.lower()]
        p.units.setdefault(dim, set()).add(round(float(num) * mult, 3))
    for n in _PACK_OF.findall(text):
        p.units.setdefault("cnt", set()).add(float(n))
    codes_src = text
    # একক-সহ সংখ্যা ও "pack of N" শব্দ-তালিকা থেকে বাদ: এগুলো units দিয়ে আলাদাভাবে মেলানো হয়
    text = _PACK_OF.sub(" ", _NUM_UNIT.sub(" ", text))
    for chunk in _CHUNK.findall(codes_src):
        c = chunk.replace("-", "")
        if _CODE.match(c) and not _UNIT_LIKE.match(c):
            p.codes.add(c)
    noise = set(cfg["noise_words"])
    for t in tokens(text):
        if t in noise or (t.isdigit() and len(t) < 3):
            continue
        p.tokens.add(t)
    if p.brand:
        p.tokens.update(tokens(p.brand))
    return p


def unit_conflict(a: Parsed, b: Parsed, tol: float) -> Optional[str]:
    """একই ডাইমেনশনে দুই পক্ষেরই মান আছে অথচ কোনো মান মেলে না, তাহলে সংঘাত (কারণ-সহ)।"""
    for dim in a.units.keys() & b.units.keys():
        if not any(abs(x - y) <= tol * max(x, y) for x in a.units[dim] for y in b.units[dim]):
            return dim
    return None


def brand_conflict(a: Parsed, b: Parsed) -> bool:
    if not a.brand or not b.brand or a.brand == b.brand:
        return False
    # একটা অন্যটার অংশ ("samsung" বনাম "samsung electronics") হলে সংঘাত নয়
    return not (a.brand in b.brand or b.brand in a.brand)
