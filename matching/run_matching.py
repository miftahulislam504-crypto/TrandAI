#!/usr/bin/env python3
"""প্রোডাক্ট ম্যাচিং রান। রিপো রুট থেকে: python -m matching.run_matching [--dry-run]

  ১. যেসব listing-এর canonical product নেই তাদের একটা করে বানায়
  ২. সব সক্রিয় listing জোড়ায় জোড়ায় মেলায় (একই ক্যাটাগরির ভেতরে)
  ৩. নিশ্চিত জোড়া নিজে মার্জ করে, মাঝারি জোড়া রিভিউ কিউতে (match_candidates) পাঠায়
  ৪. আগে মানুষের accept/reject করা জোড়া আর ছোঁয় না, reject করা জোড়ার দুই পাশ কখনও নিজে মার্জ হয় না

env: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from scrapers.common.supabase_rest import SupabaseError, SupabaseREST

from .config import load_config
from .image import from_hex
from .plan import Plan, build_plan
from .score import Item

OUT_DIR = Path(os.environ.get("RUN_OUT", "run-output"))


def load_items(db) -> list[Item]:
    rows = db.select("listing_overview", {
        "select": "id,source,canonical_product_id,category,title_raw,brand_raw,price",
        "is_active": "eq.true"})
    # ছবির হ্যাশ listing_overview ভিউতে নেই, listings থেকে আলাদা আনা (ভিউ না বদলে)। কলাম না থাকলে (migration চলেনি) ছবি ছাড়াই চলে
    hashes: dict[int, int] = {}
    try:
        for r in db.select("listings", {"select": "id,image_hash", "is_active": "eq.true", "image_hash": "not.is.null"}):
            h = from_hex(r["image_hash"])
            if h is not None:
                hashes[r["id"]] = h
    except SupabaseError:
        pass
    return [Item(id=r["id"], canonical_id=r["canonical_product_id"], source=r["source"], category=r["category"],
                 title=r["title_raw"] or "", brand=r["brand_raw"],
                 price=float(r["price"]) if r["price"] is not None else None,
                 image_hash=hashes.get(r["id"])) for r in rows]


def load_candidates(db) -> tuple[dict[tuple[int, int], str], dict[tuple[int, int], dict]]:
    """(মানুষ/সিস্টেমের সিদ্ধান্ত হয়ে যাওয়া জোড়া, এখনও pending জোড়া)।"""
    decided: dict[tuple[int, int], str] = {}
    pending: dict[tuple[int, int], dict] = {}
    for r in db.select("match_candidates", {"select": "id,listing_a,listing_b,status"}):
        key = (r["listing_a"], r["listing_b"])
        if r["status"] in ("accepted", "rejected", "auto"):
            decided[key] = r["status"]
        elif r["status"] == "pending":
            pending[key] = r
    return decided, pending


def apply_plan(db, plan: Plan, pending: dict[tuple[int, int], dict], now_iso: str) -> dict:
    out = {"merged": 0, "merge_errors": [], "auto_recorded": 0, "review_written": 0, "staled": 0}
    failed_losers: set[int] = set()
    for winner, loser in plan.merges:
        try:
            db.rpc("merge_canonicals", {"p_winner": winner, "p_loser": loser})
            out["merged"] += 1
        except SupabaseError as e:
            failed_losers.add(loser)
            out["merge_errors"].append(f"{winner}<-{loser}: {str(e)[:150]}")
    rows = []
    for p in plan.auto:
        rows.append({"listing_a": p.a, "listing_b": p.b, "score": round(p.score, 4), "evidence": p.evidence(),
                     "status": "auto", "decided_at": now_iso, "decided_by": "auto"})
    out["auto_recorded"] = len(rows)
    review_keys = set()
    for p in plan.review:
        review_keys.add((p.a, p.b))
        rows.append({"listing_a": p.a, "listing_b": p.b, "score": round(p.score, 4), "evidence": p.evidence(),
                     "status": "pending"})
    out["review_written"] = len(review_keys)
    db.upsert("match_candidates", rows, "listing_a,listing_b")
    # আর প্রাসঙ্গিক নয় এমন pending (মার্জ হয়ে গেছে, দাম/টাইটেল বদলে নেমে গেছে, listing নিষ্ক্রিয়): কিউ থেকে সরানো
    auto_keys = {(p.a, p.b) for p in plan.auto}
    gone = [r["id"] for k, r in pending.items() if k not in review_keys and k not in auto_keys]
    for i in range(0, len(gone), 100):
        db.update("match_candidates", {"status": "stale"}, {"id": "in.(" + ",".join(map(str, gone[i:i + 100])) + ")"})
    out["staled"] = len(gone)
    return out


def run(db, cfg: dict, dry_run: bool = False, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    linked = 0
    if not dry_run:
        linked = db.rpc("link_listings_to_canonical") or 0
    items = load_items(db)
    if dry_run:
        # canonical এখনও না থাকা listing-কে (বাস্তব রানে link ধাপ বানাতো) অস্থায়ী নিজস্ব প্রোডাক্ট ধরা, নইলে dry-run কিছুই দেখাত না
        for i in items:
            if i.canonical_id is None:
                i.canonical_id = -i.id
    decided, pending = load_candidates(db)
    plan = build_plan(items, cfg, decided)
    summary = {
        "date": now.date().isoformat(), "dry_run": dry_run, "linked_new_canonical": linked,
        "listings": len(items), "with_image_hash": sum(1 for i in items if i.image_hash is not None), "by_source": dict(Counter(i.source for i in items)),
        "plan": {**plan.stats, "auto_pairs": len(plan.auto), "planned_merges": len(plan.merges),
                 "review_pairs": len(plan.review)},
        "samples": {"auto": [_sample(p, items) for p in plan.auto[:8]], "review": [_sample(p, items) for p in plan.review[:8]]},
    }
    if not dry_run:
        summary["applied"] = apply_plan(db, plan, pending, now.isoformat())
    return summary


def _sample(p, items: list[Item]) -> dict:
    by = {i.id: i for i in items}
    return {"score": round(p.score, 3), "a": by[p.a].title[:70], "b": by[p.b].title[:70],
            "sources": f"{by[p.a].source}/{by[p.b].source}", "note": p.note}


def summary_markdown(s: dict) -> str:
    pl = s["plan"]
    L = [f"# ম্যাচিং রান ({s['date']}{', dry-run' if s['dry_run'] else ''})", "",
         f"- সক্রিয় listing: {s['listings']} ({', '.join(f'{k} {v}' for k, v in s['by_source'].items())})",
         f"- যাচাই করা জোড়া: {pl['candidates']}, সংঘাতে বাদ: {pl['conflicts']}, আগেই একই প্রোডাক্ট: {pl['same_canonical']}, "
         f"আগে সিদ্ধান্ত হওয়া: {pl['already_decided']}, reject-ব্লক: {pl['blocked']}, মিল কম: {pl['below_review']}",
         f"- নিজে মার্জের জন্য নিশ্চিত জোড়া: {pl['auto_pairs']} (মার্জ হবে {pl['planned_merges']}টা)",
         f"- ছবি: হ্যাশ আছে {s.get('with_image_hash', 0)}টা listing-এ, ছবি দিয়ে স্কোর বাড়া/রিভিউয়ে ওঠা জোড়া {pl.get('image_lifted', 0)}, "
         f"বিভ্রান্তিকর (বহু listing-এ একই ছবি) বলে বাদ {pl.get('image_ambiguous', 0)}",
         f"- রিভিউ কিউতে: {pl['review_pairs']}" + (f" (সীমার কারণে {pl['review_dropped_by_cap']}টা বাদ)" if pl.get("review_dropped_by_cap") else "")]
    if "applied" in s:
        a = s["applied"]
        L.append(f"- প্রয়োগ: মার্জ {a['merged']}, রিভিউ লেখা {a['review_written']}, কিউ থেকে সরানো {a['staled']}")
        for e in a["merge_errors"][:5]:
            L.append(f"  - ⚠️ মার্জ ব্যর্থ: {e}")
    if len(s["by_source"]) < 2:
        L.append("- ℹ️ এখন একটাই সোর্স, তাই জোড়া শুধু একই সোর্সের ভেতরের (একই প্রোডাক্ট ভিন্ন সেলারে)। সেগুলো রিভিউতে যায়, নিজে মার্জ হয় না।")
    for kind, title in (("auto", "নিজে মার্জের নমুনা"), ("review", "রিভিউ কিউর নমুনা")):
        if s["samples"][kind]:
            L += ["", f"## {title}", ""]
            L += [f"- {x['score']} [{x['sources']}] {x['a']} ⟷ {x['b']}" + (f" ({x['note']})" if x["note"] else "") for x in s["samples"][kind]]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="কিছু লেখে না, শুধু কী হতো দেখায়")
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(Path(args.config) if args.config else None)
    db = SupabaseREST.from_env()
    s = run(db, cfg, args.dry_run)
    md = summary_markdown(s)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "matching-summary.md").write_text(md, encoding="utf-8")
    (OUT_DIR / "matching-summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
