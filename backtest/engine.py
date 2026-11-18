"""ব্যাকটেস্টের হিসাব (ডাটাবেজ ছোঁয় না, তাই সহজে টেস্ট হয়)।

প্রশ্ন: "কোনো দিনে যে স্কোর/ট্যাগ ছিল, তার পরের horizon_days দিনে বিক্রি কেমন গেল?"
ফল-মাপ (outcome) = ওই দিনের পরের দৈনিক বিক্রির হার (fwd_rate), আর আগের একই-দৈর্ঘ্যের সময়ের হার (base_rate)।
'টিকেছে' = fwd_rate >= sustain_ratio × base_rate (base_rate > 0 হলে)।

সীমাবদ্ধতা (রিপোর্টেও লেখা হয়):
- স্কোরের 'ডিমান্ড' ফ্যাক্টর নিজেই আগের বিক্রি থেকে বানানো, তাই পরের বিক্রির সাথে মেলা অংশত স্বতঃসিদ্ধ।
  ব্যাকটেস্ট প্রমাণ করে না যে প্রোডাক্ট আপনার জন্য লাভজনক হবে; শুধু দেখায় বিক্রি টেকে কি না।
- ফল-মাপ শুধু একই listing-এ শুরু ও শেষ দুই প্রান্তেই স্ন্যাপশট আছে এমন listing ধরে (পরে আসা listing নকল লাফ দেয় না)।
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import product as iproduct
from statistics import median
from typing import Optional

CORE = ("demand", "trend", "review_quality", "bad_review")


@dataclass(frozen=True)
class ScoreRow:
    pid: int
    day: date
    category: str
    tier: Optional[str]
    total: Optional[float]
    factors: dict  # CORE-এর চারটা, None হতে পারে


@dataclass(frozen=True)
class Sample:
    pid: int
    day: date
    category: str
    tier: Optional[str]
    total: Optional[float]
    factors: dict
    basis: str                      # sold | reviews
    fwd_rate: float
    base_rate: Optional[float]



def sustained_flag(s: Sample, ratio: float) -> Optional[bool]:
    if s.base_rate is None or s.base_rate <= 0:
        return None
    return s.fwd_rate >= ratio * s.base_rate


# ------------------------------------------------------------------ ফল-মাপ
class Series:
    """একটা listing-এর (তারিখ, মান) সিরিজ; কোনো তারিখের মান = ওই তারিখ বা tol দিনের মধ্যে আগের সর্বশেষ মান।"""

    def __init__(self, points: list[tuple[date, float]]):
        pts = sorted(points)
        self.days = [d for d, _ in pts]
        self.vals = [v for _, v in pts]

    def at(self, day: date, tol: int) -> Optional[float]:
        i = bisect.bisect_right(self.days, day) - 1
        if i < 0 or (day - self.days[i]).days > tol:
            return None
        return self.vals[i]


def interval_delta(listings: list[Series], start: date, end: date, tol: int) -> Optional[float]:
    """শুরু ও শেষ দুই প্রান্তেই ডেটা আছে এমন listing-গুলোর বৃদ্ধির যোগফল। ঋণাত্মক (সংখ্যা রিসেট) ০ ধরা হয়।
    কোনো listing-এর দুই প্রান্ত না থাকলে None।"""
    total, used = 0.0, 0
    for s in listings:
        a, b = s.at(start, tol), s.at(end, tol)
        if a is None or b is None:
            continue
        total += max(0.0, b - a)
        used += 1
    return total if used else None


def build_samples(scores: list[ScoreRow], sold: dict[int, list[Series]], reviews: dict[int, list[Series]],
                  cfg: dict, last_snapshot: date) -> list[Sample]:
    h, tol = cfg["horizon_days"], cfg["snapshot_tolerance_days"]
    by_pid: dict[int, list[ScoreRow]] = defaultdict(list)
    for r in scores:
        by_pid[r.pid].append(r)
    out: list[Sample] = []
    for pid, rows in by_pid.items():
        rows.sort(key=lambda r: r.day)
        next_ok: Optional[date] = None
        for r in rows:
            if r.total is None or r.day + timedelta(days=h) > last_snapshot:
                continue
            if next_ok is not None and r.day < next_ok:
                continue                                 # step_days-এর ফাঁক
            for basis, src in (("sold", sold), ("reviews", reviews)):
                ls = src.get(pid)
                if not ls:
                    continue
                f = interval_delta(ls, r.day, r.day + timedelta(days=h), tol)
                if f is None:
                    continue
                b = interval_delta(ls, r.day - timedelta(days=h), r.day, tol)
                out.append(Sample(pid, r.day, r.category, r.tier, r.total, r.factors, basis, f / h,
                                  None if b is None else b / h))
                next_ok = r.day + timedelta(days=cfg["step_days"])
                break                                    # বিক্রি থাকলে রিভিউ ধরা হয় না
    return out


# ------------------------------------------------------------------- পরিসংখ্যান
def _ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(x: list[float], y: list[float]) -> Optional[float]:
    n = len(x)
    if n < 3 or n != len(y):
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return None if sxx == 0 or syy == 0 else sxy / (sxx * syy) ** 0.5


def category_spearman(samples: list[Sample], totals: list[float], min_n: int) -> tuple[Optional[float], int]:
    """ক্যাটাগরি ধরে আলাদা Spearman, নমুনা-সংখ্যার ওজনে গড়। ক্যাটাগরি মেশালে বিক্রির আকারের ফারাক ফলকে বিকৃত করে।"""
    groups: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    for s, t in zip(samples, totals):
        groups[s.category][0].append(t)
        groups[s.category][1].append(s.fwd_rate)
    num = den = 0
    for xs, ys in groups.values():
        if len(xs) < min_n:
            continue
        r = spearman(xs, ys)
        if r is not None:
            num += r * len(xs)
            den += len(xs)
    return (num / den if den else None), den


def pct(a: int, b: int) -> Optional[float]:
    return None if b == 0 else round(100 * a / b, 1)


def tier_table(samples: list[Sample], ratio: float) -> list[dict]:
    rows = []
    for tier in ("best", "mid", "dont", None):
        sub = [s for s in samples if s.tier == tier]
        if not sub:
            continue
        flags = [f for f in (sustained_flag(s, ratio) for s in sub) if f is not None]
        ratios = [s.fwd_rate / s.base_rate for s in sub if s.base_rate and s.base_rate > 0]
        rows.append({"tier": tier or "none", "n": len(sub), "products": len({s.pid for s in sub}),
                     "median_fwd_rate": round(median(s.fwd_rate for s in sub), 2),
                     "median_ratio": None if not ratios else round(median(ratios), 2),
                     "sustained_pct": pct(sum(flags), len(flags)), "sustained_n": len(flags)})
    return rows


def threshold_table(samples: list[Sample], thresholds: list[float], ratio: float) -> list[dict]:
    rows = []
    for th in thresholds:
        sub = [s for s in samples if s.total is not None and s.total >= th]
        flags = [f for f in (sustained_flag(s, ratio) for s in sub) if f is not None]
        rows.append({"min_score": th, "n": len(sub), "products": len({s.pid for s in sub}),
                     "median_fwd_rate": round(median(s.fwd_rate for s in sub), 2) if sub else None,
                     "sustained_pct": pct(sum(flags), len(flags)), "sustained_n": len(flags)})
    return rows


def flip_stats(history: dict[int, list[tuple[date, Optional[str]]]], window_days: int = 14) -> dict:
    """প্রতি প্রোডাক্টে ট্যাগ বদল (flip) — ১৪ দিনের হিসাবে। অস্থির ট্যাগ বিশ্বাসযোগ্য নয়।"""
    changes = observed = 0
    for rows in history.values():
        rows = sorted(rows)
        for (d0, t0), (d1, t1) in zip(rows, rows[1:]):
            if t0 is None or t1 is None or (d1 - d0).days > 3:
                continue
            observed += (d1 - d0).days
            changes += t0 != t1
    per14 = None if observed == 0 else round(changes / observed * window_days, 3)
    return {"changes": changes, "observed_product_days": observed, "changes_per_product_14d": per14}


# ---------------------------------------------------------------------- টিউনিং
def total_with(weights: dict, factors: dict) -> Optional[float]:
    num = den = 0.0
    for k in CORE:
        v = factors.get(k)
        if v is None or weights[k] <= 0:
            continue
        num += v * weights[k]
        den += weights[k]
    return num / den if den else None


def grid(step: int, lo: int, hi: int) -> list[dict]:
    """চার ফ্যাক্টরের ওজন, প্রতিটা step-এর গুণিতক, lo..hi-এর মধ্যে, যোগফল ১০০।"""
    units, lo_u, hi_u = 100 // step, -(-lo // step), hi // step
    out = []
    for combo in iproduct(range(lo_u, hi_u + 1), repeat=3):
        last = units - sum(combo)
        if lo_u <= last <= hi_u:
            out.append(dict(zip(CORE, [c * step for c in combo] + [last * step])))
    return out


def split_by_date(samples: list[Sample], test_share: float) -> tuple[list[Sample], list[Sample]]:
    days = sorted({s.day for s in samples})
    cut = max(1, min(len(days) - 1, round(len(days) * (1 - test_share))))
    boundary = days[cut]
    return [s for s in samples if s.day < boundary], [s for s in samples if s.day >= boundary]


def score_under(weights: dict, samples: list[Sample], min_n: int) -> tuple[Optional[float], int]:
    xs, keep = [], []
    for s in samples:
        t = total_with(weights, s.factors)
        if t is not None:
            xs.append(t)
            keep.append(s)
    return category_spearman(keep, xs, min_n)


def tune(samples: list[Sample], current: dict, cfg: dict) -> dict:
    """সময় অনুযায়ী ভাগ: আগের অংশে সেরা ওজন খোঁজে, পরের অংশে (যা খোঁজার সময় দেখেনি) যাচাই করে।
    সুপারিশ কেবল তখনই, যখন পরের অংশেও বর্তমান ওজনের চেয়ে min_gain-এর বেশি ভালো।"""
    t = cfg["tune"]
    train, test = split_by_date(samples, t["test_share"])
    mn = cfg["min_category_samples"]
    total = sum(current[k] for k in CORE)
    cur_norm = {k: current[k] * 100 / total for k in CORE}
    cur_train, n_tr = score_under(cur_norm, train, mn)
    cur_test, n_te = score_under(cur_norm, test, mn)
    res = {"train_n": len(train), "test_n": len(test), "current": {k: current[k] for k in CORE},
           "current_train": cur_train, "current_test": cur_test, "candidates": 0, "best": None,
           "best_train": None, "best_test": None, "recommend": False, "reason": "", "required_gain": None}
    if cur_train is None or cur_test is None:
        res["reason"] = "কোনো ক্যাটাগরিতে যথেষ্ট নমুনা নেই (tune ভাগ করার পর)"
        return res
    cands = grid(t["step"], t["weight_min"], t["weight_max"])
    res["candidates"] = len(cands)
    best, best_tr = None, cur_train
    for w in cands:
        sc, _ = score_under(w, train, mn)
        if sc is not None and sc > best_tr + 1e-12:
            best, best_tr = w, sc
    if best is None:
        res["reason"] = "আগের অংশে বর্তমান ওজনের চেয়ে ভালো কিছু পাওয়া যায়নি"
        return res
    best_te, _ = score_under(best, test, mn)
    scaled = {k: round(best[k] * total / 100) for k in CORE}
    res.update(best=scaled, best_train=best_tr, best_test=best_te)
    # আকস্মিকতার সীমা: একই প্রোডাক্টের বারবার নমুনা স্বাধীন নয়, তাই কার্যকর সংখ্যা = আলাদা প্রোডাক্ট।
    # র‍্যাংক-মিলের মানের এলোমেলো ওঠানামা মোটামুটি ১/√n; উন্নতি তার চেয়ে বেশি না হলে আওয়াজ ধরা হয়
    n_eff = len({s.pid for s in test})
    required = max(t["min_gain"], 1 / (n_eff ** 0.5)) if n_eff else 1.0
    res["required_gain"] = round(required, 3)
    gain = None if best_te is None else best_te - cur_test
    if gain is not None and gain >= required:
        res["recommend"] = True
        res["reason"] = f"পরের (না-দেখা) অংশেও {gain:+.3f} উন্নতি (আকস্মিকতার সীমা {required:.3f}-এর বেশি)"
    else:
        got = "–" if gain is None else f"{gain:+.3f}"
        res["reason"] = (f"আগের অংশে ভালো দেখালেও পরের অংশে উন্নতি {got}, লাগত অন্তত {required:.3f} "
                         "(এর নিচে আকস্মিক হতে পারে; ওভারফিটিং-এর লক্ষণ), সুপারিশ নেই")
    return res


def sufficiency(samples: list[Sample], cfg: dict) -> tuple[bool, list[str]]:
    why = []
    if len(samples) < cfg["min_samples"]:
        why.append(f"নমুনা {len(samples)}টা, লাগবে কমপক্ষে {cfg['min_samples']}টা")
    prods = len({s.pid for s in samples})
    if prods < cfg["min_products"]:
        why.append(f"প্রোডাক্ট {prods}টা, লাগবে কমপক্ষে {cfg['min_products']}টা")
    dates = len({s.day for s in samples})
    if dates < cfg["min_distinct_dates"]:
        why.append(f"আলাদা তারিখ {dates}টা, লাগবে কমপক্ষে {cfg['min_distinct_dates']}টা")
    return (not why), why
