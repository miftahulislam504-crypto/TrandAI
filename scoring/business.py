"""ব্যবসার দিক: মার্জিন (আপনার কেনা দাম থেকে) ও প্রতিযোগিতা (একই প্রোডাক্টে সেলার সংখ্যা)। নেটওয়ার্ক বা DB ছাড়া, শুধু হিসাব।

মার্জিন: বাজারের সবচেয়ে কম দামে বিক্রি ধরা (aggregate_snaps দাম নেয় সর্বনিম্ন), তাই এটা সাবধানি হিসাব।
প্রতি অর্ডারে প্রত্যাশিত লাভ = (1 - r) * (দাম - ফি - কেনা - বাড়তি খরচ) - r * বাড়তি খরচ, যেখানে r = ফেরতের হার।
(ফেরত এলে পণ্য আবার বিক্রয়যোগ্য ধরা, শুধু যাওয়া-আসার বাড়তি খরচটা লস।)
"""
from __future__ import annotations

from typing import Optional

from .stats import scale


def margin_eval(price: Optional[float], unit_cost: Optional[float], extra_cost: float, cfg: dict) -> tuple[Optional[float], dict]:
    """(স্কোর 0..100 বা None, বিস্তারিত)। দাম বা কেনা দাম না থাকলে None।"""
    m = cfg["margin"]
    if not m["enabled"] or price is None or price <= 0 or unit_cost is None:
        return None, {}
    extra = extra_cost or 0.0
    fee_frac = m["platform_fee_pct"] / 100.0
    r = m["return_rate_pct"] / 100.0
    fee = price * fee_frac
    profit = (1 - r) * (price - fee - unit_cost - extra) - r * extra
    margin_pct = 100.0 * profit / price
    base = unit_cost + extra
    # যে দামে লাভ ঠিক শূন্য: (1-r)*(p*(1-f) - c - e) - r*e = 0
    denom = 1 - fee_frac
    break_even = ((r * extra) / (1 - r) + unit_cost + extra) / denom if denom > 0 and r < 1 else None
    detail = {"price": round(price, 2), "unit_cost": round(unit_cost, 2), "extra_cost": round(extra, 2),
              "profit": round(profit, 2), "margin_pct": round(margin_pct, 1),
              "roi_pct": None if base <= 0 else round(100.0 * profit / base, 1),
              "break_even_price": None if break_even is None else round(break_even, 2),
              "fee_pct": m["platform_fee_pct"], "return_rate_pct": m["return_rate_pct"]}
    return scale(margin_pct, m["floor_pct"], m["ceiling_pct"]), detail


def competition_eval(sellers: Optional[int], listings: int, cfg: dict) -> tuple[Optional[float], dict]:
    """১ সেলার = ১০০ (কোনো প্রতিযোগী নেই), saturated_sellers বা তার বেশি = ০। সেলারের নাম না থাকলে listing সংখ্যা ধরা।"""
    c = cfg["competition"]
    if not c["enabled"] or listings <= 0:
        return None, {}
    n = sellers if sellers else listings
    detail = {"sellers": n, "listings": listings, "by": "seller" if sellers else "listing"}
    if c["saturated_sellers"] <= 1:
        return None, detail
    return scale(c["saturated_sellers"] - n, 0, c["saturated_sellers"] - 1), detail
