"""অ্যালার্ট শনাক্তকরণ (শুধু হিসাব, ডাটাবেজ বা নেটওয়ার্ক ছোঁয় না, তাই সহজে টেস্ট হয়)।

চার ধরন:
  tier_change  প্রকাশিত ট্যাগ (hysteresis পার হওয়া) আগের স্কোরের দিনের চেয়ে বদলেছে
  score_move   মোট স্কোর কয়েক দিনে অনেক সরেছে                      (শুধু ওয়াচলিস্ট)
  price_move   বাজারদর (একই প্রোডাক্টের listing-গুলোর মধ্যমা) অনেক সরেছে (শুধু ওয়াচলিস্ট)
  redflag      রিভিউয়ে নকল/ফেক অভিযোগ নতুন করে সীমা ছাড়িয়েছে            (শুধু ওয়াচলিস্ট)

ওয়াচলিস্টের বাইরের প্রোডাক্টে শুধু tier_change, তা-ও কেবল config-এর discovery.tiers-এ ঢুকলে (ডিফল্ট: নতুন Best)।
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Optional

TIER_BN = {"best": "Best", "mid": "Mid", "dont": "Don't"}
TIER_RANK = {"dont": 0, "mid": 1, "best": 2}


@dataclass(frozen=True)
class Score:
    pid: int
    scored_on: date
    tier: Optional[str]
    total: Optional[float]
    confidence: Optional[str] = None
    counterfeit_n: int = 0


def _name(names: dict[int, str], pid: int) -> str:
    n = (names.get(pid) or "").strip()
    return (n[:60] + "…") if len(n) > 60 else (n or f"প্রোডাক্ট #{pid}")


def _row(pid: int, kind: str, today: date, watched: bool, severity: str, title: str, detail: dict) -> dict:
    return {"canonical_product_id": pid, "kind": kind, "created_on": today.isoformat(), "watched": watched,
            "severity": severity, "title": title, "detail": detail}


def tier_change(cur: Score, prev: Optional[Score], watched: bool, cfg: dict, names: dict[int, str]) -> Optional[dict]:
    if prev is None or not cur.tier or not prev.tier or cur.tier == prev.tier:
        return None
    if not watched and not (cfg["discovery"]["enabled"] and cur.tier in cfg["discovery"]["tiers"]):
        return None
    up = TIER_RANK[cur.tier] > TIER_RANK[prev.tier]
    detail = {"from": prev.tier, "to": cur.tier, "from_on": prev.scored_on.isoformat(),
              "score": None if cur.total is None else round(cur.total, 1), "confidence": cur.confidence}
    title = f"{_name(names, cur.pid)}: {TIER_BN[prev.tier]} → {TIER_BN[cur.tier]}"
    return _row(cur.pid, "tier_change", cur.scored_on, watched, "good" if up else "warn", title, detail)


def score_move(cur: Score, history: list[Score], cfg: dict, names: dict[int, str]) -> Optional[dict]:
    """history: আজকের আগের সারি, নতুন -> পুরনো। days দিন বা তার আগের সবচেয়ে কাছের সারির সাথে তুলনা।"""
    c = cfg["score_move"]
    if cur.total is None:
        return None
    newest_allowed = cur.scored_on - timedelta(days=c["days"])
    oldest_allowed = cur.scored_on - timedelta(days=c["max_gap_days"])
    ref = next((h for h in history if h.total is not None and oldest_allowed <= h.scored_on <= newest_allowed), None)
    if ref is None:
        return None
    diff = cur.total - ref.total
    if abs(diff) < c["points"]:
        return None
    days = (cur.scored_on - ref.scored_on).days
    up = diff > 0
    title = (f"{_name(names, cur.pid)}: স্কোর {round(ref.total)} → {round(cur.total)} "
             f"({'+' if up else '−'}{round(abs(diff))}, {days} দিনে)")
    detail = {"from_score": round(ref.total, 1), "to_score": round(cur.total, 1), "days": days}
    return _row(cur.pid, "score_move", cur.scored_on, True, "good" if up else "warn", title, detail)


def price_move(pid: int, pct: Optional[float], today: date, cfg: dict, names: dict[int, str]) -> Optional[dict]:
    if pct is None or abs(pct) < cfg["price_move"]["pct"]:
        return None
    down = pct < 0
    title = f"{_name(names, pid)}: বাজারদর ৭ দিনে {abs(round(pct))}% {'কমেছে' if down else 'বেড়েছে'}"
    # দাম কমা = প্রতিযোগীরা ছাড় দিচ্ছে, সতর্কতা; বাড়া = তথ্য
    return _row(pid, "price_move", today, True, "warn" if down else "info", title, {"pct": round(pct, 1), "days": 7})


def redflag(cur: Score, prev: Optional[Score], cfg: dict, names: dict[int, str]) -> Optional[dict]:
    need = cfg["redflag"]["min_count"]
    if cur.counterfeit_n < need or (prev is not None and prev.counterfeit_n >= need):
        return None
    title = f"{_name(names, cur.pid)}: ⚠️ নকল/ফেক অভিযোগ ({cur.counterfeit_n}টা রিভিউয়ে)"
    return _row(cur.pid, "redflag", cur.scored_on, True, "warn", title, {"counterfeit_reviews": cur.counterfeit_n})


def price_moves(rows: list[dict]) -> dict[int, float]:
    """listing_overview-এর সারি থেকে প্রোডাক্ট ধরে ৭ দিনের দামের বদলের মধ্যমা (%)।
    একটা সেলারের এক-দুটো অস্বাভাবিক দাম যেন পুরো বাজারের চিত্র না বদলায় তাই গড় নয়, মধ্যমা।"""
    per: dict[int, list[float]] = {}
    for r in rows:
        pid, price, delta = r.get("canonical_product_id"), r.get("price"), r.get("price_delta_7d")
        if pid is None or price is None or delta is None:
            continue
        before = float(price) - float(delta)
        if before <= 0:
            continue
        per.setdefault(pid, []).append(100.0 * float(delta) / before)
    return {pid: round(median(v), 1) for pid, v in per.items() if v}


def detect(today_scores: dict[int, Score], history: dict[int, list[Score]], watch: set[int],
           price_pct: dict[int, float], names: dict[int, str], cfg: dict, today: date) -> list[dict]:
    out: list[dict] = []
    for pid, cur in sorted(today_scores.items()):
        hist = history.get(pid, [])
        prev = hist[0] if hist else None
        watched = pid in watch
        found = [tier_change(cur, prev, watched, cfg, names)]
        if watched:
            found += [score_move(cur, hist, cfg, names),
                      price_move(pid, price_pct.get(pid), today, cfg, names),
                      redflag(cur, prev, cfg, names)]
        out += [a for a in found if a]
    return out
