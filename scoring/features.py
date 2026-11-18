"""প্রোডাক্টের স্ন্যাপশট ইতিহাস ও রিভিউ থেকে স্কোরিংয়ের ইনপুট (feature) বের করে।

মূল নীতি: মোট বিক্রির চেয়ে সাম্প্রতিক বিক্রির গতি বেশি গুরুত্বপূর্ণ। ইতিহাস কম থাকলে গতি ধরা হয় না
(ভুল সংকেতের চেয়ে "জানি না" ভালো), তখন বাকি ফ্যাক্টর ও কনফিডেন্স সেটা সামলায়।
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

Point = tuple[date, float]


@dataclass(frozen=True)
class Snap:
    day: date
    price: Optional[float] = None
    rating_avg: Optional[float] = None
    rating_count: Optional[int] = None
    review_count: Optional[int] = None
    sold_count: Optional[int] = None


@dataclass(frozen=True)
class Review:
    stars: int
    day: Optional[date] = None
    suspected_fake: bool = False
    counterfeit: bool = False      # টেক্সটে নকল/ডুপ্লিকেট অভিযোগ (reviewintel)
    sentiment: Optional[int] = None            # -১/০/+১ (Groq), না হলে None
    topics: tuple = ()


@dataclass
class GoogleSignal:
    """প্রোডাক্টের ধরনের (segment) Google সার্চ ইন্টারেস্ট। series: সাপ্তাহিক, নর্মালাইজড, সম্পূর্ণ সপ্তাহ।"""
    group: str                              # config/trends.json-এর entry id
    label: str                              # দেখানোর নাম (ইংরেজি সার্চ শব্দ)
    series: list[Point]
    level: str = "segment"
    seasonal_hint: bool = False             # config-এ seasonal: true
    seasonal: Optional[bool] = None         # ৫ বছরের ডেটা থেকে শনাক্ত
    yoy_log: Optional[float] = None


@dataclass
class AdsSignal:
    """Facebook Ads Library-তে হাতে-দেওয়া একটা চেক (ড্যাশবোর্ডের /ads)। level: product = এই প্রোডাক্টের নিজের চেক,
    segment = প্রোডাক্টের ধরনের শব্দের চেক (একই ধরনের সব প্রোডাক্ট একই মান পায়)।"""
    keyword: str
    level: str
    observed_on: date
    active_ads: int
    advertisers: Optional[int] = None       # দেখা অংশে আলাদা পেজ (সর্বনিম্ন সংখ্যা)
    oldest_start: Optional[date] = None     # সবচেয়ে পুরনো সক্রিয় বিজ্ঞাপনের শুরুর তারিখ
    new_30d: Optional[int] = None
    prior: Optional[tuple] = None           # (তারিখ, active_ads) একই শব্দের আগের চেক, বৃদ্ধি মাপার জন্য
    group: Optional[str] = None             # segment হলে config/trends.json-এর entry id


@dataclass
class Product:
    id: int
    category: str
    title: str
    snaps: list[Snap]
    reviews: list[Review] = field(default_factory=list)
    url: Optional[str] = None
    google: Optional[GoogleSignal] = None
    ads: Optional[AdsSignal] = None
    unit_cost: Optional[float] = None      # আপনার কেনা দাম (product_costs), না দিলে None
    extra_cost: float = 0.0
    sellers: Optional[int] = None          # আলাদা সেলারের সংখ্যা (নাম জানা listing থেকে)
    listings: int = 0


# ------------------------------------------------------------------ সিরিজ
def series(snaps: list[Snap], attr: str) -> list[Point]:
    return [(s.day, float(getattr(s, attr))) for s in snaps if getattr(s, attr) is not None]


def point_at(ser: list[Point], target: date) -> Optional[Point]:
    """target বা তার আগের সর্বশেষ পয়েন্ট।"""
    best = None
    for p in ser:
        if p[0] <= target:
            best = p
        else:
            break
    return best


def rate(p0: Point, p1: Point) -> Optional[float]:
    """দিনপ্রতি বৃদ্ধি। কমে গেলে (সোল্ড কাউন্ট রিসেট/রাউন্ডিং) ০ ধরা হয়।"""
    days = (p1[0] - p0[0]).days
    if days <= 0:
        return None
    return max(p1[1] - p0[1], 0.0) / days


def velocity(ser: list[Point], window: int, min_history: int) -> Optional[tuple[float, int]]:
    """শেষ `window` দিনের দিনপ্রতি গতি। ইতিহাস window-এর চেয়ে ছোট হলে min_history দিন থাকলে পুরোটা ধরে।"""
    if len(ser) < 2:
        return None
    end = ser[-1]
    start = point_at(ser, end[0] - timedelta(days=window))
    if start is None:
        first = ser[0]
        if (end[0] - first[0]).days < min_history:
            return None
        start = first
    r = rate(start, end)
    return None if r is None else (r, (end[0] - start[0]).days)


def trend(ser: list[Point], recent_days: int, smoothing: float) -> Optional[dict]:
    """সাম্প্রতিক `recent_days` দিনের গতি বনাম তার আগের `recent_days` দিনের গতি (লগ-অনুপাত)।"""
    if len(ser) < 3:
        return None
    end = ser[-1]
    mid = point_at(ser, end[0] - timedelta(days=recent_days))
    start = point_at(ser, end[0] - timedelta(days=2 * recent_days))
    if mid is None or start is None or mid[0] >= end[0] or start[0] >= mid[0]:
        return None
    v_recent, v_prior = rate(mid, end), rate(start, mid)
    if v_recent is None or v_prior is None:
        return None
    return {"recent": v_recent, "prior": v_prior,
            "log_ratio": math.log((v_recent + smoothing) / (v_prior + smoothing))}


def weekly_deltas(ser: list[Point], weeks: int) -> Optional[list[float]]:
    """শেষ `weeks` সপ্তাহের সাপ্তাহিক বৃদ্ধি (পুরনো -> নতুন)। ইতিহাস কম হলে None।"""
    if not ser:
        return None
    end = ser[-1][0]
    vals = []
    for k in range(weeks, -1, -1):
        p = point_at(ser, end - timedelta(days=7 * k))
        if p is None:
            return None
        vals.append(p[1])
    return [max(vals[i + 1] - vals[i], 0.0) for i in range(weeks)]


def is_falling(deltas: Optional[list[float]]) -> bool:
    return bool(deltas) and deltas[0] > 0 and all(deltas[i] > deltas[i + 1] for i in range(len(deltas) - 1))


# --------------------------------------------------------- একাধিক listing যোগ
_FIELDS = ("rating_avg", "rating_count", "review_count", "sold_count")
PRICE_CARRY_DAYS = 3


def _fill(snaps: list[Snap], days: list[date]) -> list[Snap]:
    """একটা listing-কে সব দিনে বসানো, যাতে একাধিক listing যোগ করলে ফাঁক বা দেরিতে-আসা listing মোটে নকল লাফ না আনে।
    - নিজের স্ন্যাপশট থাকলে সেটাই
    - ফাঁক (ঐ দিন স্ক্র্যাপ হয়নি): আগের জানা মান বহাল (দাম শুধু PRICE_CARRY_DAYS দিন)
    - listing-এর প্রথম স্ন্যাপশটের আগের দিন: প্রথম জানা মান (সমতল)। এতে পরে ম্যাচ হওয়া listing-এর আজীবন বিক্রি হঠাৎ এক দিনে
      যোগ হয়ে \"বিক্রি লাফিয়েছে\" দেখায় না। মোট (lifetime) ঠিকই বাড়ে, গতি (velocity) নয়।"""
    mine = {s.day: s for s in sorted(snaps, key=lambda s: s.day)}
    ordered = sorted(mine)
    first = {f: next((mine[d] for d in ordered if getattr(mine[d], f) is not None), None) for f in _FIELDS}
    last_val: dict[str, object] = {}
    last_price: tuple[Optional[date], Optional[float]] = (None, None)
    out = []
    for day in days:
        cur = mine.get(day)
        vals = {}
        for f in _FIELDS:
            v = getattr(cur, f) if cur is not None else None
            if v is None:
                v = last_val.get(f)
                if v is None and first[f] is not None:
                    v = getattr(first[f], f)          # প্রথম জানা মানের আগে: সমতল
            else:
                last_val[f] = v
            vals[f] = v
        price = None
        if cur is not None and cur.price is not None:
            last_price = (day, cur.price)
            price = cur.price
        elif last_price[0] is not None and (day - last_price[0]).days <= PRICE_CARRY_DAYS:
            price = last_price[1]
        out.append(Snap(day=day, price=price, **vals))
    return out


def _frozen(snaps: list[Snap], days: list[date]) -> list[Snap]:
    """সব দিনে listing-এর সর্বশেষ জানা মান বসানো (বৃদ্ধি ০)। মোটে যোগ হয় কিন্তু গতি/ট্রেন্ডে নকল বৃদ্ধি আনে না।"""
    last = sorted(snaps, key=lambda s: s.day)[-1]
    return [Snap(day=d, price=last.price, rating_avg=last.rating_avg, rating_count=last.rating_count,
                 review_count=last.review_count, sold_count=last.sold_count) for d in days]


def aggregate_snaps(groups: list[list[Snap]], mature_days: Optional[int] = None) -> list[Snap]:
    """একটা প্রোডাক্টের একাধিক listing-এর স্ন্যাপশট দিনভিত্তিক যোগ করে।
    বিক্রি/রিভিউ/রেটিং সংখ্যা যোগ, রেটিং ওজনযুক্ত গড়, দাম সর্বনিম্ন। যোগের আগে প্রতিটা listing সব দিনে বসানো হয় (_fill দেখুন),
    নইলে কোনো দিন একটা প্ল্যাটফর্ম স্ক্র্যাপ না হলে মোট বিক্রি কমে \"পতন\" দেখাত।

    mature_days দিলে: যে listing-এর ইতিহাস এর চেয়ে ছোট (সদ্য ম্যাচ হওয়া নতুন প্ল্যাটফর্ম) সেটা "জমাট" ধরা হয়, মোট বিক্রিতে
    যোগ হয় কিন্তু গতিতে না। নইলে ওর আগের বৃদ্ধি অজানা বলে সমতল ধরায় শুধু সাম্প্রতিক সপ্তাহে বৃদ্ধি দেখাত, মানে নকল ত্বরণ (ট্রেন্ড ফুলে
    যেত)। কোনো listing-ই পরিণত না হলে এটা করা হয় না।"""
    groups = [g for g in groups if g]
    if len(groups) <= 1:
        return list(groups[0]) if groups else []
    days = sorted({s.day for g in groups for s in g})
    span = lambda g: (max(s.day for s in g) - min(s.day for s in g)).days + 1  # noqa: E731
    young = [mature_days is not None and span(g) < mature_days for g in groups]
    if all(young):
        young = [False] * len(groups)
    filled = [_frozen(g, days) if y else _fill(g, days) for g, y in zip(groups, young)]

    def total(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    out = []
    for i, day in enumerate(days):
        ss = [f[i] for f in filled]
        rated = [(s.rating_avg, s.rating_count or 0) for s in ss if s.rating_avg is not None]
        wsum = sum(c for _, c in rated)
        avg = (sum(a * c for a, c in rated) / wsum if wsum else
               (sum(a for a, _ in rated) / len(rated) if rated else None))
        prices = [s.price for s in ss if s.price is not None]
        out.append(Snap(day=day, price=min(prices) if prices else None, rating_avg=avg,
                        rating_count=total([s.rating_count for s in ss]),
                        review_count=total([s.review_count for s in ss]),
                        sold_count=total([s.sold_count for s in ss])))
    return out


# --------------------------------------------------------------- মূল feature
@dataclass
class Features:
    history_days: int = 0
    last: Optional[Snap] = None
    basis: Optional[str] = None            # "sold" | "review" | None
    velocity: Optional[float] = None       # দিনপ্রতি
    velocity_days: Optional[int] = None
    lifetime: Optional[float] = None       # মোট বিক্রি বা মোট রিভিউ
    trend: Optional[dict] = None
    falling: bool = False
    # রিভিউ-সংখ্যার সিরিজ থেকে মেট্রিক, বিক্রির তথ্য থাকুক বা না থাকুক সবার জন্য (বিক্রি-হীনদের তুলনার ভিত্তি)
    rev: Optional[dict] = None
    # রিভিউ নমুনা (suspected_fake বাদে)
    n_reviews: int = 0
    n_bad: int = 0
    n_counterfeit: int = 0
    n_sentiment: int = 0                       # সেন্টিমেন্ট হওয়া রিভিউ
    neg_topics: dict = field(default_factory=dict)   # নেগেটিভ রিভিউয়ে টপিকের গণনা
    sample_avg: Optional[float] = None
    recent_n: int = 0
    recent_avg: Optional[float] = None


def compute_features(p: Product, cfg: dict) -> Features:
    f = Features()
    if p.snaps:
        f.last = p.snaps[-1]
        f.history_days = (p.snaps[-1].day - p.snaps[0].day).days

    sold, rev = series(p.snaps, "sold_count"), series(p.snaps, "review_count")
    if rev:
        rv = velocity(rev, cfg["demand"]["velocity_window_days"], cfg["min_history_days_for_velocity"])
        f.rev = {"velocity": rv[0] if rv else None, "velocity_days": rv[1] if rv else None,
                 "lifetime": rev[-1][1],
                 "trend": trend(rev, cfg["trend"]["recent_days"], cfg["trend"]["smoothing_per_day"])}
    ser = sold if sold else rev
    f.basis = "sold" if sold else ("review" if rev else None)
    if ser:
        f.lifetime = ser[-1][1]
        v = velocity(ser, cfg["demand"]["velocity_window_days"], cfg["min_history_days_for_velocity"])
        if v:
            f.velocity, f.velocity_days = v
        f.trend = trend(ser, cfg["trend"]["recent_days"], cfg["trend"]["smoothing_per_day"])
        f.falling = is_falling(weekly_deltas(ser, cfg["dont"]["falling_weeks"]))

    real = [r for r in p.reviews if not r.suspected_fake]
    f.n_reviews = len(real)
    f.n_bad = sum(1 for r in real if r.stars <= 2)
    f.n_counterfeit = sum(1 for r in real if r.counterfeit)
    f.n_sentiment = sum(1 for r in real if r.sentiment is not None)
    neg: dict[str, int] = {}
    for r in real:
        if r.sentiment == -1:
            for t in r.topics:
                neg[t] = neg.get(t, 0) + 1
    f.neg_topics = neg
    if real:
        f.sample_avg = sum(r.stars for r in real) / len(real)
        ref = f.last.day if f.last else max((r.day for r in real if r.day), default=None)
        if ref:
            cutoff = ref - timedelta(days=cfg["review_quality"]["recent_days"])
            recent = [r for r in real if r.day and r.day >= cutoff]
            f.recent_n = len(recent)
            if recent:
                f.recent_avg = sum(r.stars for r in recent) / len(recent)
    return f
