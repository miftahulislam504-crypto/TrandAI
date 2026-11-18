"""কীওয়ার্ড ম্যাপিং: প্রোডাক্টের টাইটেল -> Google Trends segment।

Daraz-এর বেশিরভাগ ফ্যাশন/হোম/কিচেন প্রোডাক্ট \"No Brand\", আর প্রোডাক্ট-নামে Google Trends-এ ভলিউম প্রায় শূন্য।
তাই কীওয়ার্ড হয় প্রোডাক্টের ধরনের (segment) স্তরে (\"air fryer\", \"panjabi\")। প্রতিটা entry-তে match phrase থাকে:
টাইটেলের শব্দে phrase-এর সব শব্দ থাকলে মিল। বেশি শব্দের phrase মানে বেশি নির্দিষ্ট মিল, সেটাই জেতে।
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_SPLIT = re.compile(r"[^\w\u0980-\u09FF]+", re.UNICODE)


def tokens(text: str) -> list[str]:
    """ছোট হাতের শব্দ-তালিকা। ইংরেজি শব্দের বহুবচন-s ছাঁটা হয় (sandals -> sandal)। বাংলা অক্ষর অক্ষত।"""
    out = []
    for t in _SPLIT.split((text or "").lower()):
        if not t:
            continue
        if t.isascii() and len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


@dataclass(frozen=True)
class Match:
    entry_id: str
    level: str          # "segment"
    specificity: int    # মিলে যাওয়া phrase-এর শব্দসংখ্যা
    phrase: str


def _compiled(entries: list[dict]) -> list[tuple[dict, list[tuple[str, tuple[str, ...]]]]]:
    return [(e, [(p, tuple(tokens(p))) for p in e["match"] if tokens(p)]) for e in entries]


def match_entry(title: str, category: Optional[str], entries: list[dict]) -> Optional[Match]:
    """সেরা entry। অগ্রাধিকার: বেশি নির্দিষ্ট phrase, তারপর একই ক্যাটাগরি, তারপর তালিকার ক্রম।"""
    words = set(tokens(title))
    if not words:
        return None
    best: Optional[tuple[tuple[int, int, int], Match]] = None
    for idx, (e, phrases) in enumerate(_compiled(entries)):
        for phrase, toks in phrases:
            if all(t in words for t in toks):
                key = (len(toks), 1 if e["category"] == category else 0, -idx)
                if best is None or key > best[0]:
                    best = (key, Match(e["id"], "segment", len(toks), phrase))
    return best[1] if best else None


def build_terms(cfg: dict, only_category: Optional[str] = None, use_bengali: Optional[bool] = None) -> list[dict]:
    """সংগ্রহের শব্দ-তালিকা: [{keyword, lang, group_key, category}]।"""
    bn = cfg["settings"]["use_bengali"] if use_bengali is None else use_bengali
    out = []
    for e in cfg["entries"]:
        if only_category and e["category"] != only_category:
            continue
        out.append({"keyword": e["q"], "lang": "en", "group_key": e["id"], "category": e["category"]})
        if bn and e.get("bn"):
            out.append({"keyword": e["bn"], "lang": "bn", "group_key": e["id"], "category": e["category"]})
    return out


def entry_by_id(cfg: dict) -> dict[str, dict]:
    return {e["id"]: e for e in cfg["entries"]}
