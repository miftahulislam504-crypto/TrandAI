"""anchor দিয়ে নর্মালাইজেশন, মান-যাচাই ও সিজনালিটি। (নেটওয়ার্ক বা DB ছাড়া, বিশুদ্ধ গণিত)

Google Trends প্রতিটা রিকোয়েস্টে ০–১০০ স্কেল নতুন করে বানায় (সেই রিকোয়েস্টের সর্বোচ্চ মান = ১০০)। তাই আলাদা রিকোয়েস্টের
মান সরাসরি তুলনীয় নয়। সমাধান: প্রতি রিকোয়েস্টে একটা anchor শব্দ রাখা। anchor-এর শেষ `window` সপ্তাহের গড় = ১০০ ধরে
বাকি সব শব্দের মান পুনর্মাপ করা হয়: norm = raw * 100 / anchor_mean। ফলে যেকোনো দুই রিকোয়েস্টের মান একই এককে।

Raw পয়েন্ট: (সপ্তাহের শুরু, মান, অসম্পূর্ণ_কি)। চলতি সপ্তাহ অসম্পূর্ণ (isPartial), ওটা বাদ যায়, নইলে ভুল পতন ধরা পড়ত।
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

RawPoint = tuple[date, float, bool]


@dataclass
class KeywordResult:
    keyword: str
    status: str                      # ok | no_data | low_volume
    points: list[tuple[date, float, float, float]] = field(default_factory=list)  # (week, raw, anchor_raw, norm)
    peak_raw: float = 0.0
    nonzero_weeks: int = 0
    mean_norm: Optional[float] = None


@dataclass
class BatchResult:
    ok: bool
    error: Optional[str] = None      # anchor_missing | anchor_low
    anchor_mean: Optional[float] = None
    keywords: dict[str, KeywordResult] = field(default_factory=dict)


def complete(points: list[RawPoint]) -> list[tuple[date, float]]:
    return sorted((d, float(v)) for d, v, partial in points if not partial)


def normalize_batch(raw: dict[str, list[RawPoint]], anchor: str, settings: dict) -> BatchResult:
    a = complete(raw.get(anchor, []))
    if not a:
        return BatchResult(False, "anchor_missing")
    window = a[-settings["norm_window_weeks"]:]
    anchor_mean = sum(v for _, v in window) / len(window)
    if anchor_mean < settings["min_anchor_mean"]:
        return BatchResult(False, "anchor_low", anchor_mean)
    scale = 100.0 / anchor_mean
    anchor_by_week = dict(a)

    res = BatchResult(True, None, anchor_mean)
    for kw, pts in raw.items():
        if kw == anchor:
            continue
        series = complete(pts)
        peak = max((v for _, v in series), default=0.0)
        nonzero = sum(1 for _, v in series if v > 0)
        kr = KeywordResult(kw, "ok", peak_raw=peak, nonzero_weeks=nonzero)
        if not series or peak == 0:
            kr.status = "no_data"
        elif peak < settings["min_peak_raw"] or nonzero < settings["min_nonzero_weeks"]:
            kr.status = "low_volume"
        else:
            kr.points = [(d, v, anchor_by_week.get(d, 0.0), round(v * scale, 4)) for d, v in series]
            kr.mean_norm = sum(p[3] for p in kr.points) / len(kr.points)
        res.keywords[kw] = kr
    return res


# ------------------------------------------------------------- সিজনালিটি
def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def seasonality(points: list[RawPoint], cfg: dict) -> Optional[dict]:
    """দীর্ঘ (৫ বছর) সাপ্তাহিক সিরিজ থেকে: বার্ষিক autocorrelation, seasonal কি না, গত বছরের একই সময়ের তুলনা (YoY)।

    শুধু শব্দের নিজের সিরিজের অনুপাত, তাই anchor লাগে না। `min_peak_raw`-এর নিচে বা ছোট সিরিজে None।"""
    se = cfg["seasonality"]
    vals = [v for _, v in complete(points)]
    lag = se["lag_weeks"]
    if len(vals) < se["min_weeks"] or max(vals, default=0) < se["min_peak_raw"]:
        return None
    corr = _pearson(vals[lag:], vals[:-lag])
    year_avg = sum(vals[-lag:]) / lag
    if year_avg <= 0:
        return None
    s = 0.1 * year_avg
    recent = sum(vals[-4:]) / 4
    last_year = sum(vals[-lag - 4:-lag]) / 4
    return {"corr": None if corr is None else round(corr, 4),
            "seasonal": corr is not None and corr >= se["corr_threshold"],
            "yoy_log": round(math.log((recent + s) / (last_year + s)), 4),
            "weeks": len(vals)}
