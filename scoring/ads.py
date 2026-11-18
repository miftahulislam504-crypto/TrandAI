"""Facebook Ads Library চেক -> বিজ্ঞাপন সংকেত ফ্যাক্টর (০–১০০) ও 'বিজ্ঞাপনে ভিড়' ব্যাজ। বিশুদ্ধ গণিত, নেটওয়ার্ক বা DB ছাড়া।

ইনপুট হাতে-দেওয়া চেক (AdsSignal)। তিনটা উপাদান, যেটার তথ্য নেই সেটা বাদ, বাকিদের ওজন আবার ভাগ হয়:
- breadth   : আলাদা বিজ্ঞাপনদাতার সংখ্যা (না দিলে বিজ্ঞাপন সংখ্যা)। বেশি = বাজার-সমর্থন বেশি।
- longevity : সবচেয়ে পুরনো সক্রিয় বিজ্ঞাপন কত দিন ধরে চলছে (চেকের তারিখ পর্যন্ত)। ৩০+ দিন মানে বিজ্ঞাপনদাতার কাছে লাভজনক হওয়ার ইঙ্গিত।
- growth    : আগের চেক থাকলে বিজ্ঞাপন সংখ্যার বদল (ln অনুপাত, দ্বিগুণ/অর্ধেক = ১০০/০)। না থাকলে গত ৩০ দিনে শুরু হওয়া বিজ্ঞাপনের ভাগ।

সীমা: Ads Library-তে ইম্প্রেশন বা খরচ নেই, তাই এটা "কতজন, কতদিন" মাত্র। বিজ্ঞাপনদাতা বেশি মানে সমর্থনও, প্রতিযোগিতাও,
তাই আলাদা ব্যাজ (crowded) আছে, স্কোরে ভিড়ের জরিমানা নেই। চেক প্রোডাক্টের ধরনের শব্দে হলে একই ধরনের সব প্রোডাক্ট একই মান পায়।
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

from .features import AdsSignal
from .stats import scale, weighted_mean


def ads_features(sig: AdsSignal, a: dict, today: Optional[date] = None) -> tuple[Optional[dict], Optional[str]]:
    """(features, কেন নেই)। ব্যবহার করা না গেলে (None, কারণ)। শুধু পুরনো হলে না।"""
    age = (today - sig.observed_on).days if today is not None else 0
    if age > a["max_age_days"]:
        return None, "stale"
    comps: dict[str, Optional[float]] = {}
    if sig.advertisers is not None:
        comps["breadth"] = scale(sig.advertisers, 0, a["full_advertisers"])
    else:
        comps["breadth"] = scale(sig.active_ads, 0, a["full_ads"])
    days = None
    if sig.active_ads > 0 and sig.oldest_start is not None:
        days = max(0, (sig.observed_on - sig.oldest_start).days)
        comps["longevity"] = scale(days, a["longevity_floor_days"], a["longevity_full_days"])
    else:
        comps["longevity"] = None

    g = a["growth"]
    growth_pct = None
    growth_basis = None
    comps["growth"] = None
    if sig.prior is not None:
        gap = (sig.observed_on - sig.prior[0]).days
        if g["min_gap_days"] <= gap <= g["max_gap_days"]:
            s = g["smoothing_ads"]
            ratio = math.log((sig.active_ads + s) / (sig.prior[1] + s)) if (sig.active_ads + s) > 0 and (sig.prior[1] + s) > 0 else 0.0
            comps["growth"] = scale(ratio, -g["span"], g["span"])
            growth_pct = round(100 * (math.exp(ratio) - 1))
            growth_basis = "history"
    if comps["growth"] is None and sig.new_30d is not None and sig.active_ads > 0:
        share = sig.new_30d / sig.active_ads
        comps["growth"] = scale(share, 0, 2 * g["new_share_neutral"])
        growth_basis = "new_share"

    pairs = [(comps[k], a["component_weights"][k]) for k in ("breadth", "longevity", "growth")]
    score = weighted_mean(pairs)
    if score is None:      # breadth সবসময় থাকে, শুধু ওজন ০ হলে হতো, যা config যাচাইয়ে আটকায়
        return None, "unusable"
    crowded = (sig.advertisers >= a["crowded_advertisers"]) if sig.advertisers is not None else (sig.active_ads >= a["crowded_ads"])
    return {"score": score, "components": comps, "longest_days": days, "growth_pct": growth_pct,
            "growth_basis": growth_basis, "crowded": crowded, "age_days": age}, None


def evaluate(sig: Optional[AdsSignal], cfg: dict, today: Optional[date] = None) -> tuple[Optional[float], Optional[dict]]:
    """(বিজ্ঞাপন স্কোর বা None, ব্যাখ্যার detail বা None)। sig না থাকলে (None, None)।"""
    a = cfg["ads"]
    if sig is None or not a["enabled"]:
        return None, None
    base = {"keyword": sig.keyword, "level": sig.level, "group": sig.group, "observed_on": sig.observed_on.isoformat(),
            "active_ads": sig.active_ads, "advertisers": sig.advertisers,
            "oldest_start": sig.oldest_start.isoformat() if sig.oldest_start else None, "new_30d": sig.new_30d}
    feat, why = ads_features(sig, a, today)
    if feat is None:
        return None, {**base, "status": why}
    comps = {k: (None if v is None else round(v, 1)) for k, v in feat["components"].items()}
    return feat["score"], {**base, "status": "ok", "score": round(feat["score"], 1), "components": comps,
                           "longest_days": feat["longest_days"], "growth_pct": feat["growth_pct"],
                           "growth_basis": feat["growth_basis"], "crowded": feat["crowded"], "age_days": feat["age_days"]}
