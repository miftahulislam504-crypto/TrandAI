"""Google Trends সিগন্যাল -> Trend ফ্যাক্টরের Google অংশ (০–১০০)। বিশুদ্ধ গণিত, নেটওয়ার্ক বা DB ছাড়া।

ইনপুট: সাপ্তাহিক, anchor-নর্মালাইজড, সম্পূর্ণ সপ্তাহের সিরিজ (পুরনো -> নতুন)।

- momentum = ln(গত ৪ সপ্তাহের গড় / তার আগের ৮ সপ্তাহের গড়)
- position = ln(গত ৪ সপ্তাহের গড় / ১২ মাসের গড়)
- yoy      = ln(গত ৪ সপ্তাহ / গত বছরের একই ৪ সপ্তাহ), ৫ বছরের ডেটা থেকে, থাকলে

স্কেল: ln(২) বদল (দ্বিগুণ বা অর্ধেক) = ১০০ বা ০, অপরিবর্তিত = ৫০। মৌসুমি শব্দে momentum/position বিভ্রান্ত করে
(ঈদের আগে ওঠা মানেই নতুন ট্রেন্ড নয়), তাই সেখানে YoY প্রধান, YoY না থাকলে শুধু momentum।

সীমা: এটা প্রোডাক্টের ধরনের (segment) সার্চ ইন্টারেস্ট, নির্দিষ্ট প্রোডাক্টের নয়। একই segment-এর সব প্রোডাক্ট একই মান পায়।
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

from .features import GoogleSignal
from .stats import scale


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def google_features(sig: GoogleSignal, g: dict, today: Optional[date] = None) -> tuple[Optional[dict], Optional[str]]:
    """(features, কেন নেই)। ব্যবহার করা না গেলে (None, কারণ)।"""
    vals = [v for _, v in sorted(sig.series)]
    if today is not None and sig.series:
        age = (today - max(d for d, _ in sig.series)).days
        if age > g["max_age_days"]:
            return None, "stale"
    need = max(g["recent_weeks"] + g["prior_weeks"], g["min_weeks"])
    if len(vals) < need:
        return None, "short"
    year = vals[-g["year_weeks"]:]
    year_avg = _mean(year)
    if year_avg <= 0:
        return None, "zero"
    s = g["smoothing_share"] * year_avg
    recent = _mean(vals[-g["recent_weeks"]:])
    prior = _mean(vals[-(g["recent_weeks"] + g["prior_weeks"]):-g["recent_weeks"]])
    return {
        "recent_avg": round(recent, 3), "prior_avg": round(prior, 3), "year_avg": round(year_avg, 3),
        "momentum": math.log((recent + s) / (prior + s)),
        "position": math.log((recent + s) / (year_avg + s)),
        "yoy": sig.yoy_log,
        "seasonal": bool(sig.seasonal_hint or sig.seasonal),
        "weeks": len(vals),
    }, None


def google_score(feat: dict, g: dict) -> float:
    span = g["span"]
    m = scale(feat["momentum"], -span, span)
    if not feat["seasonal"]:
        wm, wp = g["momentum_weight"], g["position_weight"]
        return (wm * m + wp * scale(feat["position"], -span, span)) / (wm + wp)
    if feat["yoy"] is not None:
        w = g["seasonal_yoy_weight"]
        return w * scale(feat["yoy"], -span, span) + (1 - w) * m
    return m


def evaluate(sig: Optional[GoogleSignal], cfg: dict, today: Optional[date] = None) -> tuple[Optional[float], Optional[dict]]:
    """(Google স্কোর বা None, ব্যাখ্যার detail বা None)। sig না থাকলে (None, None)।"""
    g = cfg["trend"]["google"]
    if sig is None or not g["enabled"]:
        return None, None
    base = {"group": sig.group, "label": sig.label, "level": sig.level}
    feat, why = google_features(sig, g, today)
    if feat is None:
        return None, {**base, "status": why}
    score = google_score(feat, g)
    return score, {**base, "status": "ok", "score": round(score, 1),
                   "momentum_pct": round(100 * (math.exp(feat["momentum"]) - 1)),
                   "position_pct": round(100 * (math.exp(feat["position"]) - 1)),
                   "yoy_pct": None if feat["yoy"] is None else round(100 * (math.exp(feat["yoy"]) - 1)),
                   "seasonal": feat["seasonal"], "weeks": feat["weeks"],
                   "recent_weeks": g["recent_weeks"], "prior_weeks": g["prior_weeks"]}
