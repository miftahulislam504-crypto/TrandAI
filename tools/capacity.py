#!/usr/bin/env python3
"""GitHub Actions-এর মিনিট ও অনুরোধের আন্দাজ: ক্যাটাগরি/প্রোডাক্ট বাড়ানোর আগে দেখে নিন।

ব্যবহার:
  python tools/capacity.py                       # চালু ক্যাটাগরি ধরে
  python tools/capacity.py --include-disabled    # বন্ধগুলোও চালু ধরলে কী হতো
  python tools/capacity.py --page-size 40 --budget 2000 --sec-per-request 5

মডেল (run_daraz.py-র আসল ধাপ ধরে):
  ডিসকভারি = প্রতি seed-এ ceil(per_seed / page_size) পাতা (সর্বোচ্চ max_pages_per_seed)
  ডিটেইল   = সর্বোচ্চ detail_limit  (নতুন বা ব্র্যান্ড-হীন আইটেমের জন্য, রোজ)
  রিভিউ    = সর্বোচ্চ reviews_limit × reviews_max_pages
  প্রতি অনুরোধে সময় = delay + jitter/2 + আসল উত্তরের সময় (--sec-per-request, ডিফল্ট delay+jitter/2+১.৫)
অনুমান: page-size (Daraz এক পাতায় কয়টা আইটেম দেয়) ও উত্তরের সময় আমি আসল Daraz থেকে মাপিনি।
Daraz Smoke Test-এর রিপোর্টে আসল সংখ্যা মিলিয়ে `--page-size` ঠিক করুন। প্রাইভেট রিপোতে ফ্রি মিনিটের সীমা
GitHub-এর বর্তমান নিয়ম থেকে নিজে একবার দেখে নিন (ডিফল্ট ২০০০/মাস ধরা, --budget দিয়ে বদলান; পাবলিক রিপোতে সাধারণত সীমা নেই)।
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# রোজকার অন্য কাজ (ম্যাচিং, স্কোরিং+অ্যালার্ট; প্রতিটা জবের সেটআপ ও রান) মিনিটে, মোটামুটি
OTHER_JOBS_MIN_PER_DAY = 6.0
# সাপ্তাহিক Trends, মাসে মোটামুটি
TRENDS_MIN_PER_MONTH = 4 * 12.0


def seed_pages(per_seed: int, page_size: int, max_pages: int) -> int:
    return max(1, min(max_pages, math.ceil(per_seed / page_size)))


def estimate(daraz_cfg: dict, cats_cfg: dict, page_size: int = 40, include_disabled: bool = False,
             sec_per_request: float | None = None, scale: float = 1.0) -> dict:
    s = daraz_cfg["settings"]
    delay, jitter = s.get("delay_seconds", 3.0), s.get("jitter_seconds", 1.5)
    per_req = sec_per_request if sec_per_request is not None else delay + jitter / 2 + 1.5
    max_pages = s.get("max_pages_per_seed", 6)
    cats, discovery, products = [], 0, 0
    for c in cats_cfg["categories"]:
        if c.get("enabled", True) is False and not include_disabled:
            continue
        seeds = daraz_cfg["seeds"].get(c["slug"]) or []
        target = math.ceil(c["target_products"] * scale)
        if not seeds:
            cats.append({"slug": c["slug"], "target": target, "seeds": 0, "requests": 0, "note": "কোনো seed নেই"})
            continue
        per_seed = max(10, math.ceil(target / len(seeds)))
        reqs = len(seeds) * seed_pages(per_seed, page_size, max_pages)
        capped = per_seed > page_size * max_pages       # seed পিছু যত আইটেম চাই, পাতার সীমায় তা আসে না
        cats.append({"slug": c["slug"], "target": target, "seeds": len(seeds), "per_seed": per_seed, "requests": reqs,
                     "note": "max_pages_per_seed-এর সীমায় লক্ষ্যে পৌঁছাবে না" if capped else ""})
        discovery += reqs
        products += target
    details = s.get("detail_limit", 30) or 0
    reviews = (s.get("reviews_limit", 20) or 0) * s.get("reviews_max_pages", 2)
    total_req = discovery + details + reviews
    scrape_min = total_req * per_req / 60
    per_day = scrape_min + OTHER_JOBS_MIN_PER_DAY
    per_month = per_day * 30 + TRENDS_MIN_PER_MONTH
    return {"categories": cats, "products": products, "discovery_requests": discovery, "detail_requests": details,
            "review_requests": reviews, "total_requests": total_req, "sec_per_request": round(per_req, 2),
            "detail_fill_days": math.ceil(products / details) if details else None,
            "scrape_minutes_per_day": round(scrape_min, 1), "minutes_per_day": round(per_day, 1),
            "minutes_per_month": round(per_month), "page_size": page_size}


def check_total(cats_cfg: dict) -> str | None:
    on = sum(c["target_products"] for c in cats_cfg["categories"] if c.get("enabled", True) is not False)
    declared = cats_cfg.get("total_target_products")
    return None if declared == on else f"categories.json-এর total_target_products={declared}, কিন্তু চালু ক্যাটাগরির যোগফল {on}"


def report(daraz_cfg: dict, cats_cfg: dict, page_size: int, include_disabled: bool, budget: int,
           sec_per_request: float | None) -> str:
    base = estimate(daraz_cfg, cats_cfg, page_size, include_disabled, sec_per_request)
    L = ["# ক্ষমতার আন্দাজ (GitHub Actions)", "",
         f"ধরা হয়েছে: Daraz এক পাতায় {page_size}টা আইটেম, প্রতি অনুরোধে ~{base['sec_per_request']} সেকেন্ড, মাসিক সীমা {budget} মিনিট।",
         "এগুলো অনুমান; Daraz Smoke Test-এর পর আসল সংখ্যা বসিয়ে আবার চালান।", "",
         "| ক্যাটাগরি | লক্ষ্য | seed | অনুরোধ | মন্তব্য |", "|---|---|---|---|---|"]
    for c in base["categories"]:
        L.append(f"| {c['slug']} | {c['target']} | {c['seeds']} | {c['requests']} | {c['note']} |")
    L += ["", f"- মোট প্রোডাক্ট লক্ষ্য: **{base['products']}**",
          f"- রোজ অনুরোধ: {base['total_requests']} (ডিসকভারি {base['discovery_requests']} + ডিটেইল {base['detail_requests']} + রিভিউ {base['review_requests']})",
          f"- রোজ ~{base['minutes_per_day']} মিনিট, মাসে **~{base['minutes_per_month']} মিনিট** (সীমা {budget})",
          f"- প্রথমবার সব প্রোডাক্টের ডিটেইল (ব্র্যান্ড, ছবি) ভরতে ~{base['detail_fill_days']} দিন লাগবে (রোজ detail_limit-টা করে)। "
          "অনুরোধ-সংখ্যা প্রোডাক্ট বাড়ার সাথে প্রায় বাড়ে না, কিন্তু প্রোডাক্ট বাড়ালে ডিটেইল ও রিভিউ ভরতে সময় বেশি লাগে।", "",
          "## প্রোডাক্ট সংখ্যা বাড়ালে (সব ক্যাটাগরির লক্ষ্য একই হারে)", "",
          "| গুণ | প্রোডাক্ট | অনুরোধ/দিন | মিনিট/মাস | সীমার মধ্যে? |", "|---|---|---|---|---|"]
    for k in (1, 1.5, 2, 3, 5):
        e = estimate(daraz_cfg, cats_cfg, page_size, include_disabled, sec_per_request, scale=k)
        ok = "হ্যাঁ" if e["minutes_per_month"] <= budget else "না"
        L.append(f"| ×{k:g} | {e['products']} | {e['total_requests']} | {e['minutes_per_month']} | {ok} |")
    warn = check_total(cats_cfg)
    if warn:
        L += ["", f"⚠️ {warn}"]
    if base["minutes_per_month"] > budget:
        L += ["", f"⚠️ এই সেটিংয়ে মাসে ~{base['minutes_per_month']} মিনিট লাগবে, সীমা {budget}। ক্যাটাগরি ভাগ করে আলাদা workflow-এ চালান, "
                  "delay কমান (ব্লকের ঝুঁকি বাড়ে), বা রিপো পাবলিক/Render cron-এ সরান।"]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--page-size", type=int, default=40)
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--sec-per-request", type=float)
    ap.add_argument("--include-disabled", action="store_true")
    args = ap.parse_args(argv)
    if args.page_size < 1 or args.budget < 1 or (args.sec_per_request is not None and args.sec_per_request <= 0):
        print("page-size, budget ও sec-per-request ধনাত্মক হতে হবে", file=sys.stderr)
        return 2
    daraz = json.loads((ROOT / "config" / "daraz.json").read_text(encoding="utf-8"))
    cats = json.loads((ROOT / "config" / "categories.json").read_text(encoding="utf-8"))
    print(report(daraz, cats, args.page_size, args.include_disabled, args.budget, args.sec_per_request))
    return 0


if __name__ == "__main__":
    sys.exit(main())
