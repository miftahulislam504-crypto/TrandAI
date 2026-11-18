"""স্কোরিং ইঞ্জিন: ফ্যাক্টর -> মোট স্কোর -> কনফিডেন্স -> ট্যাগ (Best / Mid / Don't)।

নীতি:
- সব তুলনা ক্যাটাগরির ভেতরে (পার্সেন্টাইল)। নমুনা ছোট হলে সব ক্যাটাগরির পুল ব্যবহার হয়।
- যে ফ্যাক্টরের ডেটা নেই সেটা বাদ, বাকি ওজন আবার ভাগ হয় (renormalize)।
- কনফিডেন্স কম হলে Best/Don't স্কোর-ভিত্তিক ট্যাগ পায় না: ট্যাগ Mid থাকে, reasons.provisional_tier-এ আসল সম্ভাবনা লেখা থাকে।
- ট্যাগ বারবার উল্টাপাল্টা হওয়া আটকাতে hysteresis: নতুন ট্যাগ টানা N দিন একই থাকলে তবেই বদলায়।
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from . import ads as ads_mod
from . import google as google_mod
from .business import competition_eval, margin_eval
from .config import CONFIDENCE_ORDER, FACTORS
from .features import Features, Product, compute_features
from .stats import bayesian_adjusted, percentile_rank, scale, smoothed_ratio, weighted_mean

DEFAULT_PRIOR_RATING = 4.2
DEFAULT_PRIOR_BAD = 0.10
MIN_POOL = 3  # এর কম নমুনায় পার্সেন্টাইল অর্থহীন


@dataclass
class Result:
    product_id: int
    category: str
    factors: dict = field(default_factory=dict)      # factor -> 0..100 বা None
    total: Optional[float] = None
    available_weight: float = 0.0
    confidence: str = "low"
    raw_tier: Optional[str] = None
    tier: Optional[str] = None
    reasons: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)       # ডিবাগ/ব্যাখ্যার কাঁচা মান


# ---------------------------------------------------------------- পুল
class Pools:
    """(kind, category, basis) অনুযায়ী মানের তালিকা। পুল ছোট হলে সব ক্যাটাগরির পুলে ফেরে।"""

    def __init__(self, min_pop: int):
        self.min_pop = min_pop
        self._by_cat: dict[tuple, list[float]] = {}
        self._all: dict[tuple, list[float]] = {}

    def add(self, kind: str, category: str, basis: str, value: float) -> None:
        self._by_cat.setdefault((kind, category, basis), []).append(value)
        self._all.setdefault((kind, basis), []).append(value)

    def pct(self, kind: str, category: str, basis: str, value: float) -> tuple[Optional[float], str]:
        local = self._by_cat.get((kind, category, basis), [])
        if len(local) >= self.min_pop:
            return percentile_rank(value, local), "category"
        wide = self._all.get((kind, basis), [])
        if len(wide) >= MIN_POOL:
            return percentile_rank(value, wide), "all"
        return None, "none"


# ----------------------------------------------------- ক্যাটাগরির গড় (প্রায়র)
def category_priors(products: list[Product], feats: dict[int, Features]) -> tuple[dict, dict, float, float]:
    """ক্যাটাগরির গড় রেটিং (ওজন = রেটিং সংখ্যা) ও খারাপ-রিভিউ অনুপাত। (cat_rating, cat_bad, g_rating, g_bad)।"""
    rnum: dict[str, float] = {}
    rden: dict[str, float] = {}
    bad: dict[str, int] = {}
    tot: dict[str, int] = {}
    for p in products:
        f = feats[p.id]
        if f.last and f.last.rating_avg is not None:
            w = max(f.last.rating_count or 0, 1)
            rnum[p.category] = rnum.get(p.category, 0.0) + f.last.rating_avg * w
            rden[p.category] = rden.get(p.category, 0.0) + w
        bad[p.category] = bad.get(p.category, 0) + f.n_bad
        tot[p.category] = tot.get(p.category, 0) + f.n_reviews
    cat_rating = {c: rnum[c] / rden[c] for c in rden if rden[c] > 0}
    cat_bad = {c: bad[c] / tot[c] for c in tot if tot[c] >= 20}
    g_rating = sum(rnum.values()) / sum(rden.values()) if rden and sum(rden.values()) > 0 else DEFAULT_PRIOR_RATING
    g_bad = sum(bad.values()) / sum(tot.values()) if sum(tot.values()) >= 20 else DEFAULT_PRIOR_BAD
    return cat_rating, cat_bad, g_rating, g_bad


# ------------------------------------------------------------ ফ্যাক্টর
def review_quality(f: Features, prior: float, cfg: dict) -> tuple[Optional[float], dict]:
    rq = cfg["review_quality"]
    avg, n = (f.last.rating_avg, f.last.rating_count) if f.last else (None, None)
    source = "listing"
    if avg is None and f.sample_avg is not None:
        avg, n, source = f.sample_avg, f.n_reviews, "sample"
    if avg is None:
        return None, {}
    n = n if n is not None else f.n_reviews
    blended = avg
    if f.recent_avg is not None and f.recent_n >= rq["min_recent_reviews"] and source == "listing":
        blended = (1 - rq["recent_weight"]) * avg + rq["recent_weight"] * f.recent_avg
    adj = bayesian_adjusted(blended, n, prior, rq["m"])
    return scale(adj, rq["floor"], rq["ceiling"]), {
        "adj_rating": round(adj, 3), "raw_rating": round(avg, 3), "rating_count": n,
        "recent_avg": None if f.recent_avg is None else round(f.recent_avg, 3), "source": source}


def bad_review(f: Features, prior: float, cfg: dict) -> tuple[Optional[float], dict]:
    b = cfg["bad_review"]
    if f.n_reviews < b["min_reviews"]:
        return None, {"n": f.n_reviews}
    ratio = smoothed_ratio(f.n_bad, f.n_reviews, prior, b["prior_strength"])
    score = 100.0 * (1 - min(ratio / b["cap_ratio"], 1.0))
    return score, {"ratio": round(ratio, 4), "raw_ratio": round(f.n_bad / f.n_reviews, 4),
                   "n": f.n_reviews, "bad": f.n_bad}


# --------------------------------------------------------------- কনফিডেন্স
def confidence(f: Features, available_weight: float, rating_count: int, cfg: dict) -> str:
    c = cfg["confidence"]
    level = "low"
    if available_weight >= c["medium_weight"] and rating_count >= c["medium_min_rating_count"]:
        level = "medium"
    if (available_weight >= c["high_weight"] and f.history_days >= c["high_min_history_days"]
            and rating_count >= c["high_min_rating_count"] and f.basis == "sold"):
        level = "high"
    return level


def _conf_ge(level: str, minimum: str) -> bool:
    return CONFIDENCE_ORDER[level] >= CONFIDENCE_ORDER[minimum]


# ------------------------------------------------------------------ ট্যাগ
def decide_tier(r: Result, f: Features, cfg: dict, total_pct: Optional[float]) -> tuple[str, Optional[str], dict]:
    """(tier, provisional_tier, gates) ফেরত দেয়। gates: নাম -> True/False/None(অজানা)।"""
    best, dont, mode = cfg["best"], cfg["dont"], cfg["tier_mode"]
    d = r.detail
    adj = d.get("review_quality", {}).get("adj_rating")
    rating_count = d.get("review_quality", {}).get("rating_count") or 0
    bad_ratio = d.get("bad_review", {}).get("ratio")
    bad_n = d.get("bad_review", {}).get("n", 0)

    gates = {
        "rating_count": rating_count >= best["min_rating_count"],
        "adj_rating": None if adj is None else adj >= best["min_adj_rating"],
        "bad_ratio": None if bad_ratio is None else bad_ratio <= best["max_bad_ratio"],
        "demand": None if r.factors.get("demand") is None else r.factors["demand"] >= best["min_demand_score"],
    }
    rf = cfg["red_flags"]
    if rf["enabled"]:
        cf = rf["counterfeit"]
        flagged = f.n_counterfeit >= cf["min_count"] and f.n_counterfeit / max(f.n_reviews, 1) >= cf["min_ratio"]
        gates["counterfeit"] = not flagged
    margin_pct = d.get("margin", {}).get("margin_pct")
    if margin_pct is not None:     # কেনা দাম জানা থাকলেই এই শর্ত, নইলে Best আটকায় না
        gates["margin"] = margin_pct >= cfg["margin"]["best_min_margin_pct"]
    hard_dont = []
    if adj is not None and rating_count >= dont["min_rating_count"] and adj < dont["max_adj_rating"]:
        hard_dont.append("low_rating")
    if bad_ratio is not None and bad_n >= dont["min_bad_reviews_n"] and bad_ratio >= dont["min_bad_ratio"]:
        hard_dont.append("many_bad_reviews")
    if f.falling:
        hard_dont.append("falling_sales")
    gates["hard_dont"] = hard_dont

    if r.total is None:
        return "mid", None, gates
    if hard_dont:
        return "dont", None, gates

    if mode == "percentile" and total_pct is not None:
        score_best = total_pct >= 100 - best["percentile_top"]
        score_dont = total_pct <= dont["percentile_bottom"]
    else:
        score_best = r.total >= best["min_score"]
        score_dont = r.total < dont["max_score"]
    confident = _conf_ge(r.confidence, best["min_confidence"])

    if score_best:
        known_fail = any(v is False for k, v in gates.items() if k != "hard_dont")
        if known_fail:
            return "mid", None, gates
        unknown = any(v is None for k, v in gates.items() if k != "hard_dont")
        if confident and not unknown:
            return "best", None, gates
        return "mid", "best", gates
    if score_dont:
        return ("dont", None, gates) if confident else ("mid", "dont", gates)
    return "mid", None, gates


def apply_hysteresis(raw: str, prev_rows: list[dict], days: int) -> str:
    """prev_rows: আজকের আগের সারি, নতুন -> পুরনো, প্রতিটায় {"tier", "raw_tier"}।"""
    if not prev_rows:
        return raw
    published = prev_rows[0]["tier"]
    if raw == published:
        return raw
    need = days - 1
    recent = prev_rows[:need]
    if len(recent) >= need and all(row.get("raw_tier") == raw for row in recent):
        return raw
    return published


# --------------------------------------------------------------- মূল ফাংশন
def score_products(products: list[Product], cfg: dict, today: date,
                   previous: Optional[dict[int, list[dict]]] = None) -> list[Result]:
    from .reasons import build_reasons  # বৃত্তাকার ইম্পোর্ট এড়াতে এখানে

    previous = previous or {}
    feats = {p.id: compute_features(p, cfg) for p in products}
    cat_rating, cat_bad, g_rating, g_bad = category_priors(products, feats)

    pools = Pools(cfg["percentile"]["min_population"])
    for p in products:
        f = feats[p.id]
        if f.basis == "sold":
            if f.velocity is not None:
                pools.add("vel", p.category, "sold", f.velocity)
            pools.add("life", p.category, "sold", f.lifetime)
            if f.trend is not None:
                pools.add("trend", p.category, "sold", f.trend["log_ratio"])
        if f.rev:  # রিভিউ-পুলে সবাই থাকে, যাতে বিক্রি-হীন প্রোডাক্ট সবার সাথে তুলনীয় হয়
            if f.rev["velocity"] is not None:
                pools.add("vel", p.category, "review", f.rev["velocity"])
            pools.add("life", p.category, "review", f.rev["lifetime"])
            if f.rev["trend"] is not None:
                pools.add("trend", p.category, "review", f.rev["trend"]["log_ratio"])

    weights = cfg["weights"]
    results: list[Result] = []
    for p in products:
        f = feats[p.id]
        r = Result(product_id=p.id, category=p.category)
        r.detail["history_days"] = f.history_days
        r.detail["basis"] = f.basis
        scope = {}

        demand = trend_score = None
        if f.basis is not None:
            life_pct, scope["life"] = pools.pct("life", p.category, f.basis, f.lifetime)
            vel_pct = None
            if f.velocity is not None:
                vel_pct, scope["vel"] = pools.pct("vel", p.category, f.basis, f.velocity)
            if vel_pct is not None and life_pct is not None:
                share = cfg["demand"]["velocity_share"]
                demand = share * vel_pct + (1 - share) * life_pct
            else:
                demand = life_pct if life_pct is not None else vel_pct
            if f.trend is not None:
                trend_score, scope["trend"] = pools.pct("trend", p.category, f.basis, f.trend["log_ratio"])
        # Google Trends: বিক্রির গতির সাথে share অনুযায়ী মেশে (ডিফল্ট ৫০/৫০), একটাই থাকলে সেটাই
        g_score, g_detail = google_mod.evaluate(p.google, cfg, today)
        if g_detail is not None:
            r.detail["google"] = g_detail
        if g_score is not None:
            share = cfg["trend"]["google"]["share"]
            trend_score = g_score if trend_score is None else (1 - share) * trend_score + share * g_score
        r.detail["demand"] = {"velocity": f.velocity, "velocity_days": f.velocity_days,
                              "lifetime": f.lifetime, "basis": f.basis}
        r.detail["trend"] = f.trend
        r.detail["pool_scope"] = scope

        rq, rq_detail = review_quality(f, cat_rating.get(p.category, g_rating), cfg)
        br, br_detail = bad_review(f, cat_bad.get(p.category, g_bad), cfg)
        r.detail["review_quality"], r.detail["bad_review"] = rq_detail, br_detail

        # Facebook Ads Library (হাতে-দেওয়া চেক): ফ্যাক্টর ও ভিড়ের ব্যাজ। ওজন ডিফল্ট ০, তাই আসল ডেটা যাচাইয়ের আগে স্কোর বদলায় না
        ad_score, ad_detail = ads_mod.evaluate(p.ads, cfg, today)
        if ad_detail is not None:
            r.detail["ads"] = ad_detail

        mg, mg_detail = margin_eval(f.last.price if f.last else None, p.unit_cost, p.extra_cost, cfg)
        cp, cp_detail = competition_eval(p.sellers, p.listings, cfg)
        r.detail["margin"], r.detail["competition"] = mg_detail, cp_detail
        r.detail["counterfeit"] = {"n": f.n_counterfeit, "of": f.n_reviews}
        r.detail["complaints"] = {"topics": dict(sorted(f.neg_topics.items(), key=lambda x: -x[1])), "analyzed": f.n_sentiment}

        r.factors = {"demand": demand, "trend": trend_score, "review_quality": rq,
                     "bad_review": br, "ads_signal": ad_score, "margin": mg, "competition": cp}
        pairs = [(r.factors[k], weights[k]) for k in FACTORS]
        r.total = weighted_mean(pairs)
        r.available_weight = sum(weights[k] for k in FACTORS if r.factors[k] is not None)
        rating_count = (rq_detail.get("rating_count") or 0) if rq_detail else 0
        r.confidence = confidence(f, r.available_weight, rating_count, cfg)
        if f.basis == "review" and r.confidence == "high":
            r.confidence = "medium"  # বিক্রির তথ্য নেই, শুধু আন্দাজ
        results.append(r)

    # percentile মোডের জন্য ক্যাটাগরির ভেতরে মোট স্কোরের র‍্যাংক
    totals: dict[str, list[float]] = {}
    for r in results:
        if r.total is not None:
            totals.setdefault(r.category, []).append(r.total)
    all_totals = [t for ts in totals.values() for t in ts]

    for r, p in zip(results, products):
        f = feats[p.id]
        total_pct = None
        if r.total is not None:
            pool = totals[r.category] if len(totals[r.category]) >= cfg["percentile"]["min_population"] else all_totals
            total_pct = percentile_rank(r.total, pool) if len(pool) >= MIN_POOL else None
        r.detail["total_percentile"] = total_pct
        raw, provisional, gates = decide_tier(r, f, cfg, total_pct)
        r.raw_tier = raw
        r.tier = apply_hysteresis(raw, previous.get(r.product_id, []), cfg["tier_change_days"]) if r.total is not None else None
        r.reasons = build_reasons(r, f, gates, provisional, cfg)
    return results
