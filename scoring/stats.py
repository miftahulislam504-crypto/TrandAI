"""স্কোরিংয়ের গাণিতিক সহায়ক ফাংশন (নেটওয়ার্ক বা DB ছাড়া)।"""
from __future__ import annotations

from typing import Iterable, Optional


def percentile_rank(value: float, population: Iterable[Optional[float]]) -> Optional[float]:
    """মিড-র‍্যাংক পার্সেন্টাইল (0-100)। সমান মানগুলো অর্ধেক করে গোনা হয়, তাই টাই থাকলেও ন্যায্য।"""
    pop = [x for x in population if x is not None]
    if not pop:
        return None
    less = sum(1 for x in pop if x < value)
    equal = sum(1 for x in pop if x == value)
    return 100.0 * (less + 0.5 * equal) / len(pop)


def bayesian_adjusted(avg: float, n: float, prior_mean: float, m: float) -> float:
    """রিভিউ কম হলে রেটিংকে ক্যাটাগরির গড়ের দিকে টানে: (v/(v+m))*R + (m/(v+m))*C।"""
    n = max(n, 0.0)
    if n + m == 0:
        return prior_mean
    return (n / (n + m)) * avg + (m / (n + m)) * prior_mean


def smoothed_ratio(bad: int, n: int, prior_ratio: float, strength: float) -> float:
    """বিটা-প্রায়র দিয়ে মসৃণ করা অনুপাত। নমুনা ছোট হলে ক্যাটাগরির অনুপাতের কাছাকাছি থাকে।"""
    return (bad + prior_ratio * strength) / (n + strength)


def scale(x: float, lo: float, hi: float) -> float:
    """[lo, hi] কে 0-100-তে রৈখিকভাবে নেয়, সীমার বাইরে ছেঁটে ফেলে।"""
    if hi <= lo:
        raise ValueError("hi must be greater than lo")
    return 100.0 * min(1.0, max(0.0, (x - lo) / (hi - lo)))


def weighted_mean(pairs: Iterable[tuple[Optional[float], float]]) -> Optional[float]:
    """(মান, ওজন) জোড়ার ওজনযুক্ত গড়; মান None হলে বাদ। কিছু না থাকলে None।"""
    num = den = 0.0
    for v, w in pairs:
        if v is None or w <= 0:
            continue
        num += v * w
        den += w
    return num / den if den else None


def quantile(values: list[float], q: float) -> Optional[float]:
    """সরল লিনিয়ার ইন্টারপোলেশন কোয়ান্টাইল (q: 0..1)।"""
    xs = sorted(values)
    if not xs:
        return None
    pos = q * (len(xs) - 1)
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
