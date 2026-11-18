"""রিভিউ টেক্সটের নিয়মভিত্তিক বিশ্লেষণ (নেটওয়ার্ক বা DB ছাড়া, LLM নয়)।

১. নকল/ডুপ্লিকেট অভিযোগ (counterfeit): বাংলা, ইংরেজি ও বাংলিশ শব্দ, নেগেশন সামলে ("fake না", "not fake" গোনা হয় না)।
২. সন্দেহজনক রিভিউ (suspected_fake): একই লেখা বারবার, একদিনে হঠাৎ অনেক ৫★, একই রিভিউয়ার বারবার।

সীমা: কাঁচা নিয়ম, তাই কিছু ভুল ধরবে ও কিছু এড়াবে। ভুল ধরা হলে সীমা বাড়ানোর জন্য Summary-তে নমুনা দেওয়া হয়।
এখানে সেন্টিমেন্ট বা টপিক নেই (সেটা LLM-ভিত্তিক, আলাদা ধাপ)।
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Optional

# ------------------------------------------------------------------ টেক্সট
_PUNCT = re.compile(r"[^\w\s\u0980-\u09FF]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize(text: Optional[str]) -> str:
    """ছোট হাতের, ইউনিকোড-নর্মালাইজড, যতিচিহ্নহীন, একক ফাঁকা। 'isn't' -> 'isnt'।"""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).lower().replace("'", "").replace("’", "")
    return _SPACE.sub(" ", _PUNCT.sub(" ", t)).strip()


# ------------------------------------------------------------------ নকল অভিযোগ
# একক শব্দ: কেউ "fake" বললেই অভিযোগ, তবে নেগেশন থাকলে নয়
CLAIM_TERMS = {
    "fake", "duplicate", "duplicated", "counterfeit", "replica", "imitation", "knockoff", "dupli", "fakee",
    "nokol", "nakol", "nokal", "জাল", "নকল", "ভুয়া", "ফেক", "ডুপ্লিকেট", "ডুপ্লিকেড", "ভেজাল",
}
# শব্দগুলো নিজেই অভিযোগ ("original না" = আসল নয়), নেগেশনের প্রশ্ন নেই
COMPLAINT_PHRASES = [
    r"\bnot (?:an? )?(?:original|genuine|authentic|real)\b", r"\bnot orginal\b", r"\b(?:original|orginal|asol|asl) (?:na|noy|nai|nei)\b",
    r"\bfirst copy\b", r"\bsecond copy\b", r"\b(?:1st|2nd) copy\b", r"\bcopy (?:product|item|maal|mal)\b",
    r"(?:অরিজিনাল|অরিজিনাল|আসল|এসল|অরজিনাল) (?:না|নয়|নাই|নেই)", r"(?:ফার্স্ট|সেকেন্ড) কপি", r"ডুপ্লিকেট মাল",
]
_COMPLAINT_RE = [re.compile(p) for p in COMPLAINT_PHRASES]
NEG_BEFORE = {"not", "no", "never", "isnt", "arent", "wasnt", "dont", "doesnt", "didnt", "cant", "without", "nor", "none",
              "কোনো", "কোন", "মোটেও", "মোটেই"}
NEG_AFTER = {"na", "noy", "nai", "nei", "nahi", "not", "no", "না", "নয়", "নাই", "নেই", "নয়তো", "নহে", "নয়", "noi"}
# "fake" ভাবার আগে এসব থাকলে ওটা অভিযোগ নয়, সন্দেহ বা প্রশ্ন, তবু ধরি না (সাবধানি)
HEDGE = {"if", "maybe", "perhaps", "jodi", "যদি", "hoy", "naki", "নাকি"}


def _negated(tokens: list[str], i: int) -> bool:
    before = tokens[max(0, i - 3):i]
    after = tokens[i + 1:i + 3]
    return any(t in NEG_BEFORE for t in before) or any(t in NEG_AFTER for t in after) \
        or any(t in HEDGE for t in tokens[max(0, i - 2):i + 3])


def is_counterfeit_complaint(text: Optional[str]) -> bool:
    t = normalize(text)
    if not t:
        return False
    if any(rx.search(t) for rx in _COMPLAINT_RE):
        return True
    tokens = t.split()
    for i, tok in enumerate(tokens):
        if tok in CLAIM_TERMS and not _negated(tokens, i):
            return True
    return False


# ------------------------------------------------------------------ সন্দেহজনক রিভিউ
@dataclass
class Rev:
    id: int
    listing_id: int
    stars: Optional[int]
    body: Optional[str]
    day: Optional[date]
    reviewer: Optional[str]


@dataclass
class Verdict:
    suspected_fake: bool = False
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def analyze(revs: list[Rev], cfg: dict) -> dict[int, Verdict]:
    """সব রিভিউ একসাথে (ডুপ্লিকেট লেখা ধরতে সব প্রোডাক্টের রিভিউ লাগে)। ফেরত: {review id: Verdict}।"""
    out = {r.id: Verdict() for r in revs}
    if cfg["counterfeit"]["enabled"]:
        for r in revs:
            if is_counterfeit_complaint(r.body):
                out[r.id].flags.append("counterfeit")
    fk = cfg["fake_reviews"]
    if not fk["enabled"]:
        return out

    # ১) একই লেখা বারবার (পুরো ডেটাবেজ জুড়ে)
    groups: dict[str, list[Rev]] = defaultdict(list)
    for r in revs:
        n = normalize(r.body)
        if len(n) >= fk["dup_min_len"]:
            groups[n].append(r)
    for n, g in groups.items():
        need = fk["dup_long_count"] if len(n) >= fk["dup_long_len"] else fk["dup_min_count"]
        if len(g) >= need:
            for r in g:
                out[r.id].suspected_fake = True
                out[r.id].reasons.append("duplicate_text")

    # ২) একদিনে হঠাৎ অনেক ৫★ (প্রোডাক্ট ধরে)
    by_listing: dict[int, list[Rev]] = defaultdict(list)
    for r in revs:
        if r.day is not None:
            by_listing[r.listing_id].append(r)
    for lid, g in by_listing.items():
        per_day = Counter(r.day for r in g)
        if len(per_day) < fk["burst_min_days"]:
            continue
        med = median(per_day.values())
        for day, c in per_day.items():
            if c >= fk["burst_min"] and c >= fk["burst_ratio"] * med:
                for r in g:
                    if r.day == day and r.stars == 5:
                        out[r.id].suspected_fake = True
                        out[r.id].reasons.append("burst")

    # ৩) একই রিভিউয়ার একই প্রোডাক্টে বারবার (প্রথমটা বাদে বাকিগুলো)
    seen: dict[tuple[int, str], list[Rev]] = defaultdict(list)
    for r in revs:
        if r.reviewer:
            seen[(r.listing_id, r.reviewer)].append(r)
    for g in seen.values():
        if len(g) >= fk["repeat_reviewer_min"]:
            g.sort(key=lambda r: (r.day or date.min, r.id))
            for r in g[1:]:
                out[r.id].suspected_fake = True
                out[r.id].reasons.append("repeat_reviewer")
    return out
