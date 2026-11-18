#!/usr/bin/env python3
"""সব রিভিউ পড়ে নিয়মভিত্তিক বিশ্লেষণ চালায়, বদলানো সারিগুলো `reviews.suspected_fake` ও `reviews.flags`-এ লেখে।
রিপো রুট থেকে: python -m reviewintel.run_intel [--dry-run]

- এই ধাপই suspected_fake ও flags-এর মালিক: প্রতি রানে নতুন করে হিসাব, তাই সীমা বদলালে আগের চিহ্ন নিজে ঠিক হয়ে যায়
- শুধু যে সারির ফল বদলেছে সেগুলোই আপডেট (প্রথম রানের পর খুব কম লেখা লাগে)
- Phase 5 migration (reviews.flags কলাম) না চললে পরিষ্কার বার্তা দিয়ে থামে, স্কোরিং আগের মতোই চলে

env: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from scrapers.common.supabase_rest import SupabaseError, SupabaseREST

from .config import load_config
from .rules import Rev, analyze

OUT_DIR = Path(os.environ.get("RUN_OUT", "run-output"))
CHUNK = 150


def _d(v):
    return date.fromisoformat(v[:10]) if v else None


def fetch(db) -> tuple[list[Rev], dict[int, dict]]:
    try:
        rows = db.select("reviews", {"select": "id,listing_id,stars,body,reviewed_at,reviewer_hash,suspected_fake,flags", "order": "id.asc"})
    except SupabaseError as e:
        raise SystemExit(f"reviews.flags পড়া গেল না। Phase 5 migration (20261115000000_phase5.sql) চালিয়েছেন? ({str(e)[:120]})")
    revs = [Rev(id=r["id"], listing_id=r["listing_id"], stars=r["stars"], body=r["body"], day=_d(r["reviewed_at"]),
                reviewer=r["reviewer_hash"]) for r in rows]
    return revs, {r["id"]: r for r in rows}


def run(db, cfg: dict, dry_run: bool = False) -> dict:
    revs, current = fetch(db)
    verdicts = analyze(revs, cfg)
    text = {r.id: (r.body or "") for r in revs}
    changes: dict[tuple, list[int]] = defaultdict(list)
    for rid, v in verdicts.items():
        cur = current[rid]
        new = (bool(v.suspected_fake), tuple(sorted(v.flags)))
        old = (bool(cur.get("suspected_fake")), tuple(sorted(cur.get("flags") or [])))
        if new != old:
            changes[new].append(rid)
    n_fake = sum(1 for v in verdicts.values() if v.suspected_fake)
    n_cf = sum(1 for v in verdicts.values() if "counterfeit" in v.flags)
    sample = cfg["sample_size"]

    def pick(pred):
        return [{"id": rid, "text": text[rid][:140], "why": v.reasons or v.flags}
                for rid, v in verdicts.items() if pred(v)][:sample]

    out = {"date": date.today().isoformat(), "reviews": len(revs), "suspected_fake": n_fake, "counterfeit": n_cf,
           "reasons": dict(Counter(x for v in verdicts.values() for x in set(v.reasons))),
           "changed": sum(len(ids) for ids in changes.values()), "written": 0, "dry_run": dry_run,
           "sample_fake": pick(lambda v: v.suspected_fake), "sample_counterfeit": pick(lambda v: "counterfeit" in v.flags)}
    if not dry_run:
        for (fake, flags), ids in changes.items():
            for i in range(0, len(ids), CHUNK):
                part = ids[i:i + CHUNK]
                db.update("reviews", {"suspected_fake": fake, "flags": list(flags) or None},
                          {"id": "in.(" + ",".join(str(x) for x in part) + ")"})
                out["written"] += len(part)
    return out


def summary_markdown(s: dict) -> str:
    L = [f"# রিভিউ বিশ্লেষণ ({s['date']}{', dry-run' if s['dry_run'] else ''})", "",
         f"- রিভিউ: {s['reviews']}, সন্দেহজনক: {s['suspected_fake']}, নকল/ডুপ্লিকেট অভিযোগ: {s['counterfeit']}",
         f"- সন্দেহের কারণ: " + (", ".join(f"{k} {v}" for k, v in sorted(s["reasons"].items())) or "নেই"),
         f"- বদলেছে: {s['changed']}, লেখা হয়েছে: {s['written']}"]
    for title, key in (("নকল অভিযোগের নমুনা (ভুল ধরা হলে জানান)", "sample_counterfeit"), ("সন্দেহজনক রিভিউয়ের নমুনা", "sample_fake")):
        if s[key]:
            L += ["", f"## {title}", ""] + [f"- #{x['id']} [{', '.join(x['why'])}] {x['text']}" for x in s[key]]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(Path(args.config) if args.config else None)
    s = run(SupabaseREST.from_env(), cfg, args.dry_run or os.environ.get("DRY_RUN") == "true")
    md = summary_markdown(s)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "review-intel.md").write_text(md, encoding="utf-8")
    (OUT_DIR / "review-intel.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
