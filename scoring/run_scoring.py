#!/usr/bin/env python3
"""স্কোরিং রান। রিপো রুট থেকে: python -m scoring.run_scoring [অপশন]

  --dry-run          DB-তে কিছু লেখে না, শুধু রিপোর্ট দেখায় (DB থেকে পড়া লাগে)
  --date YYYY-MM-DD  এই তারিখের স্কোর (ডিফল্ট: আজকের বাংলাদেশ তারিখ)
  --category slug    শুধু এই ক্যাটাগরি
  --spotcheck N      প্রতি ট্যাগ থেকে N টা (ডিফল্ট ১০) যাচাইয়ের নমুনা বানায়
  --config path      অন্য কনফিগ (ডিফল্ট config/scoring.json)

env: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from scrapers import sensitive
from scrapers.common.supabase_rest import SupabaseError, SupabaseREST
from trends.config import load_config as load_trends_config
from trends.keywords import entry_by_id, match_entry

from .config import ROOT, load_config
from .engine import Result, score_products
from .features import AdsSignal, GoogleSignal, Product, Review, Snap, aggregate_snaps
from .stats import quantile

OUT_DIR = Path(os.environ.get("RUN_OUT", "run-output"))
TIER_LABEL = {"best": "Best", "mid": "Mid", "dont": "Don't"}


def bd_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=6)).date()


def _d(v) -> date | None:
    return date.fromisoformat(v[:10]) if v else None


# ------------------------------------------------------------------ DB থেকে পড়া
def fetch_products(db, today: date, cfg: dict, only: str | None = None) -> list[Product]:
    since = (today - timedelta(days=cfg["history_days"])).isoformat()
    listings = db.select("listing_overview", {
        "select": "id,canonical_product_id,category,title_raw,url,seller_name",
        "is_active": "eq.true", "canonical_product_id": "not.is.null"})
    if only:
        listings = [l for l in listings if l["category"] == only]
    # স্পর্শকাতর পণ্য স্কোরের বাইরে (আগে ঢোকা ডেটাও); কত গেল Summary-তে দেখায়
    kept, dropped = [], []
    for l in listings:
        m = sensitive.match(l.get("title_raw"), l.get("category"))
        (dropped if m else kept).append({**l, "_sensitive": m} if m else l)
    fetch_products.excluded = sensitive.summarize_dropped(dropped, title_key="title_raw")
    listings = kept
    by_listing = {l["id"]: l for l in listings}
    if not by_listing:
        return []

    snaps: dict[int, list[Snap]] = {}
    for r in db.select("listing_snapshots", {
            "captured_on": f"gte.{since}", "order": "captured_on.asc,listing_id.asc",
            "select": "listing_id,captured_on,price,rating_avg,rating_count,review_count,sold_count"}):
        if r["listing_id"] in by_listing and _d(r["captured_on"]) <= today:
            snaps.setdefault(r["listing_id"], []).append(Snap(
                day=_d(r["captured_on"]), price=r["price"], rating_avg=r["rating_avg"],
                rating_count=r["rating_count"], review_count=r["review_count"], sold_count=r["sold_count"]))

    revs: dict[int, list[Review]] = {}
    try:
        review_rows = db.select("reviews", {"select": "listing_id,stars,reviewed_at,suspected_fake,flags,sentiment,topics"})
    except SupabaseError:       # Phase 5 migration চলেনি: flags কলাম নেই, আগের মতো চলে (sentiment/topics প্রথম migration থেকেই আছে)
        review_rows = db.select("reviews", {"select": "listing_id,stars,reviewed_at,suspected_fake,sentiment,topics"})
    for r in review_rows:
        if r["listing_id"] in by_listing and r["stars"]:
            revs.setdefault(r["listing_id"], []).append(
                Review(stars=r["stars"], day=_d(r["reviewed_at"]), suspected_fake=bool(r["suspected_fake"]),
                       counterfeit="counterfeit" in (r.get("flags") or []),
                       sentiment=r.get("sentiment"), topics=tuple(r.get("topics") or ())))

    costs: dict[int, tuple[float, float]] = {}
    try:
        for r in db.select("product_costs", {"select": "canonical_product_id,unit_cost,extra_cost"}):
            costs[r["canonical_product_id"]] = (float(r["unit_cost"]), float(r["extra_cost"] or 0))
    except SupabaseError:       # product_costs টেবিল নেই (migration চলেনি): মার্জিন ছাড়াই
        pass

    groups: dict[int, list[dict]] = {}
    for l in listings:
        groups.setdefault(l["canonical_product_id"], []).append(l)
    products = []
    for pid, ls in groups.items():
        agg = aggregate_snaps([snaps.get(l["id"], []) for l in ls], cfg["min_history_days_for_velocity"])
        sellers = {(l.get("seller_name") or "").strip().lower() for l in ls} - {""}
        cost = costs.get(pid)
        products.append(Product(
            id=pid, category=ls[0]["category"] or "unknown", title=ls[0]["title_raw"] or "",
            snaps=agg, reviews=[rv for l in ls for rv in revs.get(l["id"], [])], url=ls[0]["url"],
            unit_cost=cost[0] if cost else None, extra_cost=cost[1] if cost else 0.0,
            sellers=len(sellers) or None, listings=len(ls)))
    return products


def fetch_google(db, today: date, cfg: dict, tcfg: dict) -> tuple[dict[str, GoogleSignal], Optional[str]]:
    """segment id -> GoogleSignal। en ও bn শব্দের সিরিজ একই সপ্তাহগুলোতে যোগ হয় (দুটোই anchor-নর্মালাইজড, তাই এককে মেলে)।

    Phase 3 migration না চললে বা ডেটা না থাকলে ফাঁকা ফেরত, স্কোরিং Google ছাড়াই চলে (Phase 2-এর মতো)।"""
    entries = entry_by_id(tcfg)
    g = cfg["trend"]["google"]
    if not g["enabled"]:
        return {}, None
    since = (today - timedelta(weeks=g["year_weeks"] + 6)).isoformat()
    try:
        kws = db.select("trend_keywords", {"is_active": "eq.true", "last_status": "eq.ok", "geo": f"eq.{tcfg['settings']['geo']}",
                                           "select": "id,keyword,group_key,seasonal,yoy_log"})
        pts = db.select("trend_points", {"week_start": f"gte.{since}", "select": "keyword_id,week_start,value"})
    except (SupabaseError, KeyError) as e:
        return {}, f"Google Trends ডেটা পড়া যায়নি ({str(e)[:120]}), Google ছাড়াই স্কোর হচ্ছে"
    by_kw: dict[int, dict[date, float]] = {}
    for r in pts:
        if r["value"] is not None:
            by_kw.setdefault(r["keyword_id"], {})[_d(r["week_start"])] = float(r["value"])
    members: dict[str, list[dict]] = {}
    for k in kws:
        if k.get("group_key") in entries and by_kw.get(k["id"]):
            members.setdefault(k["group_key"], []).append(k)
    out: dict[str, GoogleSignal] = {}
    for gid, ms in members.items():
        weeks = set.intersection(*(set(by_kw[m["id"]]) for m in ms))
        series = sorted((w, round(sum(by_kw[m["id"]][w] for m in ms), 4)) for w in weeks)
        seas = [m["seasonal"] for m in ms if m.get("seasonal") is not None]
        yoys = [float(m["yoy_log"]) for m in ms if m.get("yoy_log") is not None]
        e = entries[gid]
        out[gid] = GoogleSignal(group=gid, label=e["q"], series=series, seasonal_hint=bool(e.get("seasonal")),
                                seasonal=(any(seas) if seas else None),
                                yoy_log=(sum(yoys) / len(yoys) if yoys else None))
    return out, None


def attach_google(products: list[Product], signals: dict[str, GoogleSignal], tcfg: dict) -> None:
    """প্রতিটা প্রোডাক্টের টাইটেল থেকে segment বের করে সিগন্যাল বসায়। মিল আছে কিন্তু ডেটা নেই হলে ফাঁকা সিরিজের সিগন্যাল
    (কারণ \"short\" হিসেবে দেখা যায়)।"""
    entries = entry_by_id(tcfg)
    for p in products:
        m = match_entry(p.title, p.category, tcfg["entries"])
        if m is None:
            continue
        p.google = signals.get(m.entry_id) or GoogleSignal(group=m.entry_id, label=entries[m.entry_id]["q"], series=[])


def fetch_ads(db, today: date, cfg: dict) -> tuple[list[dict], Optional[str]]:
    """হাতে-দেওয়া Ads Library চেক (ad_checks)। আজকের পরের তারিখের চেক বাদ। Phase 6 migration না চললে ফাঁকা ফেরত,
    স্কোরিং বিজ্ঞাপন ছাড়াই চলে (আগের মতো)।"""
    if not cfg["ads"]["enabled"]:
        return [], None
    try:
        rows = db.select("ad_checks", {"select": "id,keyword,keyword_norm,canonical_product_id,observed_on,active_ads,advertisers,oldest_start,new_30d",
                                       "order": "observed_on.asc,id.asc"})
    except (SupabaseError, KeyError) as e:
        return [], f"বিজ্ঞাপন চেক পড়া যায়নি ({str(e)[:120]}), বিজ্ঞাপন ছাড়াই স্কোর হচ্ছে (Phase 6 migration চালিয়েছেন?)"
    return [r for r in rows if _d(r["observed_on"]) <= today], None


def _prior(history: list[dict], chosen: dict, a: dict) -> Optional[tuple]:
    """একই শব্দ (ও একই প্রোডাক্ট/segment-চেক) দিয়ে আগের চেক, যেটা chosen-এর min_gap দিন বা আরও আগে, max_gap-এর বেশি আগে নয়। সবচেয়ে সাম্প্রতিকটা।"""
    g = a["growth"]
    day = _d(chosen["observed_on"])
    best = None
    for h in history:
        if h["keyword_norm"] != chosen["keyword_norm"] or h["canonical_product_id"] != chosen["canonical_product_id"]:
            continue
        gap = (day - _d(h["observed_on"])).days
        if g["min_gap_days"] <= gap <= g["max_gap_days"] and (best is None or _d(h["observed_on"]) > best[0]):
            best = (_d(h["observed_on"]), int(h["active_ads"]))
    return best


def _signal(chosen: dict, level: str, history: list[dict], a: dict, group: Optional[str] = None) -> AdsSignal:
    return AdsSignal(
        keyword=chosen["keyword"], level=level, observed_on=_d(chosen["observed_on"]), active_ads=int(chosen["active_ads"]),
        advertisers=None if chosen["advertisers"] is None else int(chosen["advertisers"]),
        oldest_start=_d(chosen["oldest_start"]), new_30d=None if chosen["new_30d"] is None else int(chosen["new_30d"]),
        prior=_prior(history, chosen, a), group=group)


def attach_ads(products: list[Product], checks: list[dict], tcfg: dict, cfg: dict) -> dict:
    """প্রতিটা প্রোডাক্টে বিজ্ঞাপনের সিগন্যাল বসায়। অগ্রাধিকার: (১) প্রোডাক্টের নিজের চেক (সবচেয়ে সাম্প্রতিক), (২) প্রোডাক্টের ধরনের
    (segment) চেক: চেকের শব্দ ও প্রোডাক্টের টাইটেল একই match phrase দিয়ে config/trends.json-এর segment-এ মেলে (Google Trends-এর মতো)।
    ফেরত দেয় কোন শব্দ কোনো segment-এ মেলেনি তার তালিকা (সারাংশে দেখানোর জন্য)।"""
    a = cfg["ads"]
    entries = tcfg["entries"]
    own: dict[int, dict] = {}
    seg: dict[str, dict] = {}
    unmapped: dict[str, str] = {}
    for c in checks:          # observed_on.asc, id.asc: পরেরটা সাম্প্রতিক
        key = (c["observed_on"], c["id"])
        if c["canonical_product_id"] is not None:
            if c["canonical_product_id"] not in own or key >= (own[c["canonical_product_id"]]["observed_on"], own[c["canonical_product_id"]]["id"]):
                own[c["canonical_product_id"]] = c
            continue
        m = match_entry(c["keyword"], None, entries)
        if m is None:
            unmapped[c["keyword_norm"]] = c["keyword"]
            continue
        cur = seg.get(m.entry_id)
        if cur is None or key >= (cur["observed_on"], cur["id"]):
            seg[m.entry_id] = c
    for p in products:
        if p.id in own:
            p.ads = _signal(own[p.id], "product", checks, a)
            continue
        m = match_entry(p.title, p.category, entries)
        if m is not None and m.entry_id in seg:
            p.ads = _signal(seg[m.entry_id], "segment", checks, a, group=m.entry_id)
    return {"checks": len(checks), "unmapped_keywords": sorted(unmapped.values())}


def fetch_previous(db, today: date, cfg: dict) -> dict[int, list[dict]]:
    since = (today - timedelta(days=max(10, cfg["tier_change_days"] + 3))).isoformat()
    rows = db.select("product_scores", {
        "scored_on": f"gte.{since}", "order": "scored_on.desc",
        "select": "canonical_product_id,scored_on,tier,raw_tier:reasons->>raw_tier"})
    out: dict[int, list[dict]] = {}
    for r in rows:
        if _d(r["scored_on"]) < today:
            out.setdefault(r["canonical_product_id"], []).append({"tier": r["tier"], "raw_tier": r.get("raw_tier")})
    return out


# ---------------------------------------------------------------------- লেখা
def to_row(r: Result, today: date) -> dict:
    f = r.factors
    rnd = lambda v: None if v is None else round(v, 2)
    return {"canonical_product_id": r.product_id, "scored_on": today.isoformat(),
            "demand": rnd(f["demand"]), "trend": rnd(f["trend"]), "review_quality": rnd(f["review_quality"]),
            "bad_review": rnd(f["bad_review"]), "ads_signal": rnd(f["ads_signal"]), "total": rnd(r.total),
            "tier": r.tier, "confidence": r.confidence, "reasons": r.reasons}


# ------------------------------------------------------------------ রিপোর্ট
def google_summary(results: list[Result]) -> dict:
    scored = [r for r in results if r.total is not None]
    st = Counter((r.detail.get("google") or {}).get("status", "no_keyword") for r in scored)
    return {"used": st.get("ok", 0), "mapped_no_data": sum(v for k, v in st.items() if k not in ("ok", "no_keyword")),
            "no_keyword": st.get("no_keyword", 0),
            "by_segment": dict(Counter((r.detail["google"]["group"]) for r in scored
                                       if (r.detail.get("google") or {}).get("status") == "ok"))}


def ads_summary(results: list[Result], info: Optional[dict]) -> dict:
    scored = [r for r in results if r.total is not None]
    ads = [(r.detail.get("ads") or {}) for r in scored]
    st = Counter(a.get("status", "no_check") for a in ads)
    return {"checks": (info or {}).get("checks", 0), "used": st.get("ok", 0),
            "used_product": sum(1 for a in ads if a.get("status") == "ok" and a["level"] == "product"),
            "used_segment": sum(1 for a in ads if a.get("status") == "ok" and a["level"] == "segment"),
            "stale": st.get("stale", 0), "no_check": st.get("no_check", 0),
            "crowded": sum(1 for a in ads if a.get("status") == "ok" and a.get("crowded")),
            "unmapped_keywords": (info or {}).get("unmapped_keywords", [])}


def summarize(results: list[Result], unscored: int) -> dict:
    scored = [r for r in results if r.total is not None]
    totals = [r.total for r in scored]
    per_cat: dict[str, Counter] = {}
    for r in scored:
        per_cat.setdefault(r.category, Counter())[r.tier] += 1
    return {
        "scored": len(scored), "unscored": unscored,
        "tiers": dict(Counter(r.tier for r in scored)),
        "confidence": dict(Counter(r.confidence for r in scored)),
        "provisional": dict(Counter(r.reasons["provisional_tier"] for r in scored if r.reasons["provisional_tier"])),
        "basis": dict(Counter(r.detail.get("basis") or "none" for r in scored)),
        "by_category": {c: dict(cnt) for c, cnt in sorted(per_cat.items())},
        "google": google_summary(results),
        "ads": ads_summary(results, None),
        "score_quantiles": {q: (None if not totals else round(quantile(totals, v), 1))
                            for q, v in (("min", 0), ("p25", .25), ("median", .5), ("p75", .75), ("p90", .9), ("max", 1))},
    }


def summary_markdown(s: dict, today: date, dry: bool, mode: str) -> str:
    L = [f"# স্কোরিং রান ({today}{', dry-run' if dry else ''})", "",
         f"- স্কোর হয়েছে: **{s['scored']}**, স্কোর করা যায়নি (ডেটা নেই): {s['unscored']}",
         f"- ট্যাগ মোড: `{mode}`"]
    if s.get("google_warning"):
        L.append(f"- ⚠️ {s['google_warning']}")
    if s.get("ads_warning"):
        L.append(f"- ⚠️ {s['ads_warning']}")
    sn = s.get("sensitive") or {}
    if sn.get("count"):
        L.append(f"- স্পর্শকাতর পণ্য স্কোরের বাইরে রাখা: {sn['count']}টা (" + ", ".join(f"{k} {v}" for k, v in sorted(sn["by_rule"].items())) + ")")
        L += [f"  - `{e['rule']}` ({e['hit']}): {e['title']}" for e in sn["examples"][:8]]
    if s["scored"]:
        t = s["tiers"]
        L.append(f"- Best: {t.get('best', 0)}, Mid: {t.get('mid', 0)}, Don't: {t.get('dont', 0)}")
        L.append(f"- কনফিডেন্স: " + ", ".join(f"{k} {v}" for k, v in sorted(s["confidence"].items())))
        if s["provisional"]:
            L.append("- সম্ভাব্য (ডেটা অনিশ্চিত বলে Mid রাখা): " + ", ".join(f"{k} {v}" for k, v in s["provisional"].items()))
        L.append("- বিক্রির তথ্যের ধরন: " + ", ".join(f"{k} {v}" for k, v in s["basis"].items()))
        gg = s["google"]
        L.append(f"- Google Trends: কাজে লেগেছে {gg['used']}টা, কীওয়ার্ড মিলেছে কিন্তু ডেটা নেই/পুরনো {gg['mapped_no_data']}টা, "
                 f"কোনো কীওয়ার্ড মেলেনি {gg['no_keyword']}টা")
        if s["scored"] and gg["no_keyword"] / s["scored"] > 0.3:
            L.append("  - ⚠️ ৩০%-এর বেশি প্রোডাক্টের কীওয়ার্ড নেই। config/trends.json-এ entry বা match phrase যোগ করুন।")
        ad = s["ads"]
        if ad["checks"]:
            L.append(f"- Facebook Ads Library (হাতে-দেওয়া {ad['checks']}টা চেক): কাজে লেগেছে {ad['used']}টা প্রোডাক্টে "
                     f"(নিজের চেক {ad['used_product']}, ধরনের চেক {ad['used_segment']}), পুরনো চেক {ad['stale']}টা, চেক নেই {ad['no_check']}টা, "
                     f"'ভিড়' ব্যাজ {ad['crowded']}টা")
            if ad["unmapped_keywords"]:
                L.append("  - ⚠️ এই শব্দগুলো কোনো segment-এ মেলেনি, তাই কোনো প্রোডাক্টে লাগেনি (প্রোডাক্টের পেজ থেকে সরাসরি দিন, "
                         "বা config/trends.json-এ entry যোগ করুন): " + ", ".join(ad["unmapped_keywords"][:10]))
        else:
            L.append("- Facebook Ads Library: কোনো চেক নেই (ড্যাশবোর্ডের /ads থেকে দিন)")
        q = s["score_quantiles"]
        L += ["", "## স্কোরের বণ্টন (থ্রেশহোল্ড ক্যালিব্রেশনের জন্য)", "",
              "| min | p25 | median | p75 | p90 | max |", "|---|---|---|---|---|---|",
              f"| {q['min']} | {q['p25']} | {q['median']} | {q['p75']} | {q['p90']} | {q['max']} |",
              "", "## ক্যাটাগরি অনুযায়ী", "", "| ক্যাটাগরি | Best | Mid | Don't |", "|---|---|---|---|"]
        for c, cnt in s["by_category"].items():
            L.append(f"| {c} | {cnt.get('best', 0)} | {cnt.get('mid', 0)} | {cnt.get('dont', 0)} |")
    return "\n".join(L)


def spotcheck_markdown(results: list[Result], products: dict[int, Product], per_tier: int, today: date) -> str:
    """আপনার নিজে যাচাইয়ের জন্য নমুনা। প্রতি ট্যাগ থেকে র‍্যান্ডম (একই তারিখে একই নমুনা)।"""
    rng = random.Random(today.toordinal())
    L = ["# স্কোর যাচাইয়ের নমুনা", "",
         "প্রতিটা প্রোডাক্ট দেখে নিজের বিচারে ট্যাগ ঠিক কি না বলুন। ৩০টার মধ্যে ≥ ৮০% মিললে Phase 2 পাস।", ""]
    for tier in ("best", "mid", "dont"):
        pool = [r for r in results if r.tier == tier and r.total is not None]
        pick = rng.sample(pool, min(per_tier, len(pool)))
        L += [f"## {TIER_LABEL[tier]} ({len(pick)}টা)", ""]
        for i, r in enumerate(pick, 1):
            p = products[r.product_id]
            L.append(f"{i}. **{p.title or '(নাম নেই)'}**")
            L.append(f"   - স্কোর {r.total:.0f}, কনফিডেন্স {r.confidence}"
                     + (f", সম্ভাব্য {r.reasons['provisional_tier']}" if r.reasons["provisional_tier"] else ""))
            for line in r.reasons["summary"]:
                L.append(f"   - {line}")
            for line in r.reasons["notes"]:
                L.append(f"   - নোট: {line}")
            if p.url:
                L.append(f"   - {p.url}")
            L.append("   - একমত? ☐ হ্যাঁ  ☐ না")
            L.append("")
    return "\n".join(L)


# -------------------------------------------------------------------- মূল রান
def run(db, cfg: dict, today: date, only: str | None = None, dry_run: bool = False,
        spot_n: int = 10) -> dict:
    products = fetch_products(db, today, cfg, only)
    tcfg = load_trends_config()
    signals, google_warning = fetch_google(db, today, cfg, tcfg)
    attach_google(products, signals, tcfg)
    ad_checks, ads_warning = fetch_ads(db, today, cfg)
    ads_info = attach_ads(products, ad_checks, tcfg, cfg)
    previous = fetch_previous(db, today, cfg)
    results = score_products(products, cfg, today, previous)
    scored = [r for r in results if r.total is not None]
    if not dry_run and scored:
        db.upsert("product_scores", [to_row(r, today) for r in scored], "canonical_product_id,scored_on")
    summary = summarize(results, unscored=len(results) - len(scored))
    summary["written"] = 0 if dry_run else len(scored)
    summary["google_warning"] = google_warning
    summary["ads_warning"] = ads_warning
    summary["ads"] = ads_summary(results, ads_info)
    summary["sensitive"] = getattr(fetch_products, "excluded", None) or {"count": 0, "by_rule": {}, "examples": []}
    pmap = {p.id: p for p in products}
    return {"summary": summary, "results": results, "products": pmap,
            "spotcheck": spotcheck_markdown(results, pmap, spot_n, today) if scored else ""}


def write_outputs(out: dict, today: date, dry: bool, mode: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md = summary_markdown(out["summary"], today, dry, mode)
    (OUT_DIR / "scoring-summary.md").write_text(md, encoding="utf-8")
    (OUT_DIR / "scoring-summary.json").write_text(
        json.dumps(out["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    if out["spotcheck"]:
        (OUT_DIR / "spotcheck.md").write_text(out["spotcheck"], encoding="utf-8")
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--category")
    ap.add_argument("--spotcheck", type=int, default=10)
    ap.add_argument("--config")
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config) if args.config else None)
    today = date.fromisoformat(args.date) if args.date else bd_today()
    out = run(SupabaseREST.from_env(), cfg, today, args.category, args.dry_run, args.spotcheck)
    write_outputs(out, today, args.dry_run, cfg["tier_mode"])
    return 0 if out["summary"]["scored"] or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
