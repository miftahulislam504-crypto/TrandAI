#!/usr/bin/env python3
"""listing-এর ছবি নামিয়ে dHash বের করে `listings.image_hash`-এ রাখে। রিপো রুট থেকে: python -m matching.hash_images [--limit N]

- শুধু সক্রিয় listing, যাদের image_url আছে অথচ হ্যাশ নেই বা URL বদলেছে (image_hash_url != image_url)
- প্রতি রানে সর্বোচ্চ image.hash_limit_per_run (ডিফল্ট ৩০০), বাকিগুলো পরের রানে। প্রথম কয়েক দিনে জমে যাবে
- ভদ্র ক্লায়েন্ট: বিরতি (image.delay_seconds), robots মানা, টানা ব্লকে নিজে থামা
- ছবি পড়া না গেলে বা এত সমতল যে হ্যাশ ভরসাযোগ্য নয়: image_hash null রেখে image_hash_url বসানো (বারবার চেষ্টা হয় না)।
  নেটওয়ার্ক ত্রুটি বা ব্লক হলে কিছু লেখা হয় না, পরের রানে আবার চেষ্টা

env: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from scrapers.common.http import CircuitOpen, FetchError, PoliteClient
from scrapers.common.supabase_rest import SupabaseREST

from .config import load_config
from .image import ImageError, dhash_bytes, to_hex

OUT_DIR = Path(os.environ.get("RUN_OUT", "run-output"))


def pending_listings(db) -> list[dict]:
    rows = db.select("listings", {"select": "id,image_url,image_hash_url", "is_active": "eq.true",
                                  "image_url": "not.is.null", "order": "id.asc"})
    return [r for r in rows if r["image_url"] and r.get("image_hash_url") != r["image_url"]]


def run(db, client, cfg: dict, limit: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    im = cfg["image"]
    now = now or datetime.now(timezone.utc)
    todo = pending_listings(db)
    cap = im["hash_limit_per_run"] if limit is None else limit
    batch = todo[:cap]
    out = {"date": now.date().isoformat(), "pending_before": len(todo), "tried": 0, "hashed": 0, "flat": 0,
           "unreadable": 0, "fetch_errors": 0, "circuit_open": False, "errors": []}
    for r in batch:
        try:
            data = client.get_bytes(r["image_url"], max_bytes=im["max_image_bytes"])
        except CircuitOpen as e:
            out["circuit_open"] = True
            out["errors"].append(str(e))
            break
        except FetchError as e:
            out["fetch_errors"] += 1
            if len(out["errors"]) < 8:
                out["errors"].append(f"{r['id']}: {str(e)[:120]}")
            continue
        out["tried"] += 1
        try:
            h = dhash_bytes(data, im["min_bits"])
        except ImageError as e:
            out["unreadable"] += 1
            h = None
            if len(out["errors"]) < 8:
                out["errors"].append(f"{r['id']}: {e}")
        else:
            out["hashed" if h is not None else "flat"] += 1
        db.update("listings", {"image_hash": to_hex(h) if h is not None else None,
                               "image_hash_url": r["image_url"], "image_hashed_at": now.isoformat()},
                  {"id": f"eq.{r['id']}"})
    out["pending_after"] = len(todo) - out["tried"]
    return out


def summary_markdown(s: dict) -> str:
    L = [f"# ছবির হ্যাশ ({s['date']})", "",
         f"- বাকি ছিল: {s['pending_before']}, ছবি পাওয়া গেছে: {s['tried']}, হ্যাশ হলো: {s['hashed']}, "
         f"সমতল (ভরসাযোগ্য নয়): {s['flat']}, পড়া যায়নি: {s['unreadable']}, ফেচ ব্যর্থ: {s['fetch_errors']}",
         f"- এখনও বাকি: {s['pending_after']}"]
    if s["circuit_open"]:
        L.append("- ⚠️ টানা ব্লক, রান থেমেছে। কিছু ছবি পরের রানে হবে।")
    for e in s["errors"][:8]:
        L.append(f"  - {e}")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--limit", type=int, help="এই রানে সর্বোচ্চ কয়টা ছবি (ডিফল্ট কনফিগ থেকে)")
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(Path(args.config) if args.config else None)
    if not cfg["image"].get("enabled"):
        print("image.enabled = false, কিছু করার নেই")
        return 0
    db = SupabaseREST.from_env()
    client = PoliteClient(delay=cfg["image"]["delay_seconds"], jitter=0.3)
    s = run(db, client, cfg, args.limit)
    md = summary_markdown(s)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "image-hash-summary.md").write_text(md, encoding="utf-8")
    (OUT_DIR / "image-hash-summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
