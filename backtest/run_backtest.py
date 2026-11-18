"""ব্যাকটেস্ট ও ওজন-টিউনিং রিপোর্ট। শুধু পড়ে, ডাটাবেজ বা config বদলায় না।

ব্যবহার:
  python -m backtest.run_backtest                  # শেষ ১২০ দিনের স্কোর
  python -m backtest.run_backtest --days 200 --horizon 21

আউটপুট: run-output/backtest-report.md ও backtest-report.json (Actions-এ artifact + Summary)।
ডেটা কম থাকলে (config/backtest.json-এর min_*) টিউনিং চলে না, শুধু যা আছে তার গণনা দেখায়।
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from scoring.config import load_config as load_scoring_config
from scrapers.common.supabase_rest import SupabaseError, SupabaseREST

from .config import load_config
from .engine import (CORE, ScoreRow, Series, build_samples, category_spearman, flip_stats, sufficiency,
                     threshold_table, tier_table, tune)

OUT_DIR = Path(os.environ.get("RUN_OUT", "run-output"))
TIER_BN = {"best": "Best", "mid": "Mid", "dont": "Don't", "none": "ট্যাগ নেই"}


def bd_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=6)).date()


def _d(v) -> date:
    return date.fromisoformat(str(v)[:10])


def _f(v) -> Optional[float]:
    return None if v is None else float(v)


def load_data(db, since: date, horizon: int) -> dict:
    cats = {c["id"]: c["slug"] for c in db.select("categories", {"select": "id,slug"})}
    prod_cat = {p["id"]: cats.get(p["category_id"], "অজানা")
                for p in db.select("canonical_products", {"select": "id,category_id"})}
    score_rows = db.select("product_scores", {
        "scored_on": f"gte.{since.isoformat()}", "order": "scored_on.asc,canonical_product_id.asc",
        "select": "canonical_product_id,scored_on,tier,total," + ",".join(CORE)})
    scores = [ScoreRow(r["canonical_product_id"], _d(r["scored_on"]), prod_cat.get(r["canonical_product_id"], "অজানা"),
                       r.get("tier"), _f(r.get("total")), {k: _f(r.get(k)) for k in CORE}) for r in score_rows]
    listing_pid = {l["id"]: l["canonical_product_id"] for l in db.select(
        "listings", {"select": "id,canonical_product_id", "canonical_product_id": "not.is.null"})}
    snaps = db.select("listing_snapshots", {
        "captured_on": f"gte.{(since - timedelta(days=horizon + 7)).isoformat()}",
        "order": "listing_id.asc,captured_on.asc", "select": "listing_id,captured_on,sold_count,review_count"})
    sold_pts: dict[int, list] = defaultdict(list)
    rev_pts: dict[int, list] = defaultdict(list)
    last = None
    for s in snaps:
        day = _d(s["captured_on"])
        last = day if last is None or day > last else last
        if s.get("sold_count") is not None:
            sold_pts[s["listing_id"]].append((day, float(s["sold_count"])))
        if s.get("review_count") is not None:
            rev_pts[s["listing_id"]].append((day, float(s["review_count"])))
    sold: dict[int, list[Series]] = defaultdict(list)
    reviews: dict[int, list[Series]] = defaultdict(list)
    for lid, pts in sold_pts.items():
        if lid in listing_pid:
            sold[listing_pid[lid]].append(Series(pts))
    for lid, pts in rev_pts.items():
        if lid in listing_pid:
            reviews[listing_pid[lid]].append(Series(pts))
    hist: dict[int, list] = defaultdict(list)
    for s in scores:
        hist[s.pid].append((s.day, s.tier))
    return {"scores": scores, "sold": sold, "reviews": reviews, "last_snapshot": last, "history": hist}


def analyze(data: dict, bcfg: dict, scfg: dict) -> dict:
    last = data["last_snapshot"]
    samples = build_samples(data["scores"], data["sold"], data["reviews"], bcfg, last) if last else []
    sold_samples = [s for s in samples if s.basis == "sold"]
    ok, why = sufficiency(sold_samples, bcfg)
    ratio = bcfg["sustain_ratio"]
    out = {"horizon_days": bcfg["horizon_days"], "last_snapshot": last.isoformat() if last else None,
           "samples_total": len(samples), "samples_sold": len(sold_samples),
           "samples_review_only": len(samples) - len(sold_samples),
           "sufficient": ok, "insufficient_reasons": why,
           "tiers": tier_table(sold_samples, ratio), "thresholds": threshold_table(sold_samples, bcfg["thresholds"], ratio),
           "flips": flip_stats(data["history"]), "tuning": None, "overall_spearman": None}
    rho, n = category_spearman(sold_samples, [s.total for s in sold_samples], bcfg["min_category_samples"])
    out["overall_spearman"] = {"rho": None if rho is None else round(rho, 3), "n": n}
    if ok:
        out["tuning"] = tune(sold_samples, scfg["weights"], bcfg)
    return out


def _n(v, d=2):
    return "–" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))


def report_markdown(r: dict, today: date) -> str:
    L = [f"# ব্যাকটেস্ট রিপোর্ট — {today.isoformat()}", "",
         f"কোনো দিনের স্কোর/ট্যাগ ধরে তার পরের **{r['horizon_days']} দিনে** বিক্রি কেমন গেল। সর্বশেষ স্ন্যাপশট: {r['last_snapshot'] or 'নেই'}।",
         f"নমুনা: বিক্রির সংখ্যা ধরে {r['samples_sold']}টা (রিভিউ-ভিত্তিক {r['samples_review_only']}টা, এই রিপোর্টে ধরা হয়নি)।", ""]
    if not r["sufficient"]:
        L += ["## ⚠️ ডেটা এখনও যথেষ্ট নয়", ""] + [f"- {w}" for w in r["insufficient_reasons"]]
        L += ["", "টিউনিং চালানো হয়নি। নিচের সংখ্যাগুলো ছোট নমুনার, সিদ্ধান্তের ভিত্তি নয়।", ""]
    sp = r["overall_spearman"]
    L += [f"**স্কোর ও পরের বিক্রির র‍্যাংক-মিল (ক্যাটাগরি ধরে):** {_n(sp['rho'], 3)} ({sp['n']}টা নমুনায়; ০ = মিল নেই, ১ = পুরো মিল)", "",
          "## ট্যাগ অনুযায়ী ফল", "", "| ট্যাগ | নমুনা | প্রোডাক্ট | পরের দৈনিক বিক্রি (মধ্যমা) | পরের ÷ আগের (মধ্যমা) | টিকেছে |", "|---|---|---|---|---|---|"]
    for t in r["tiers"]:
        L.append(f"| {TIER_BN.get(t['tier'], t['tier'])} | {t['n']} | {t['products']} | {_n(t['median_fwd_rate'])} | "
                 f"{_n(t['median_ratio'])} | {_n(t['sustained_pct'], 1)}% ({t['sustained_n']}টায়) |")
    L += ["", "## স্কোরের সীমা ধরে (Best-এর ন্যূনতম স্কোর বাছতে)", "",
          "| স্কোর ≥ | নমুনা | প্রোডাক্ট | পরের দৈনিক বিক্রি (মধ্যমা) | টিকেছে |", "|---|---|---|---|---|"]
    for t in r["thresholds"]:
        L.append(f"| {t['min_score']:g} | {t['n']} | {t['products']} | {_n(t['median_fwd_rate'])} | {_n(t['sustained_pct'], 1)}% ({t['sustained_n']}টায়) |")
    fl = r["flips"]
    L += ["", "## ট্যাগের স্থিতিশীলতা", "",
          f"প্রতি প্রোডাক্টে ১৪ দিনে গড় ট্যাগ-বদল: **{_n(fl['changes_per_product_14d'], 3)}** ({fl['changes']}টা বদল, {fl['observed_product_days']} প্রোডাক্ট-দিনে)। "
          "০.৫-এর বেশি হলে ট্যাগ অস্থির (`tier_change_days` বাড়ান)।", ""]
    t = r["tuning"]
    L += ["## ওজন টিউনিং (শুধু সুপারিশ)", ""]
    if t is None:
        L += ["ডেটা যথেষ্ট নয়, চালানো হয়নি।", ""]
    else:
        cur = ", ".join(f"{k} {t['current'][k]}" for k in CORE)
        L += [f"বর্তমান: {cur}", f"- বর্তমান ওজনের মিল: আগের অংশে {_n(t['current_train'], 3)}, পরের (না-দেখা) অংশে {_n(t['current_test'], 3)} "
              f"(নমুনা {t['train_n']} / {t['test_n']})"]
        if t["best"]:
            best = ", ".join(f"{k} {t['best'][k]}" for k in CORE)
            L.append(f"- আগের অংশে সেরা ({t['candidates']}টা সংমিশ্রণ থেকে): {best} → আগের অংশে {_n(t['best_train'], 3)}, পরের অংশে {_n(t['best_test'], 3)}")
        L += [f"- **{'সুপারিশ আছে' if t['recommend'] else 'সুপারিশ নেই'}:** {t['reason']}", ""]
        if t["recommend"]:
            L += ["চাইলে `config/scoring.json`-এর `weights`-এ বসান (নিজে থেকে কিছু বদলায়নি):", "```json",
                  json.dumps({k: t["best"][k] for k in CORE}, indent=2), "```", ""]
    L += ["## সীমাবদ্ধতা", "",
          "- স্কোরের ডিমান্ড অংশ আগের বিক্রি থেকে বানানো, তাই পরের বিক্রির সাথে মিল কিছুটা স্বতঃসিদ্ধ। এটা প্রমাণ নয় যে প্রোডাক্ট আপনার জন্য লাভজনক হবে।",
          "- রিভিউ-মান ও খারাপ-রিভিউ ফ্যাক্টর 'ভালো প্রোডাক্ট' মাপে, বিক্রি-বৃদ্ধি নয়। শুধু বিক্রির সাথে মেলালে ওদের ওজন কমতে চায়, সেজন্য টিউনিং-এ প্রতিটা ফ্যাক্টরের ন্যূনতম ওজন বাঁধা।",
          "- নমুনা ছোট হলে বা মাত্র কয়েক সপ্তাহের ডেটায় ফল আকস্মিক হতে পারে। বদলানোর আগে কয়েক মাসের ডেটায় আবার চালান।",
          "- আপনার নিজের বিক্রির আসল ফল (কত বিক্রি হলো, কত লাভ) যোগ হলে এই মাপ আরও অর্থবহ হবে।", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--days", type=int, default=120, help="কত দিন পিছনের স্কোর ধরবে")
    ap.add_argument("--horizon", type=int, help="config-এর horizon_days বদলে দেয়")
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    bcfg = load_config(Path(args.config) if args.config else None)
    if args.horizon:
        bcfg = {**bcfg, "horizon_days": args.horizon}
    scfg = load_scoring_config()
    today = bd_today()
    try:
        data = load_data(SupabaseREST.from_env(), today - timedelta(days=args.days), bcfg["horizon_days"])
    except SupabaseError as e:
        print(f"ব্যাকটেস্ট ব্যর্থ: {e}", file=sys.stderr)
        return 1
    except requests.RequestException as e:
        print(f"ব্যাকটেস্ট ব্যর্থ: Supabase-এ পৌঁছানো যায়নি ({type(e).__name__})", file=sys.stderr)
        return 1
    result = analyze(data, bcfg, scfg)
    md = report_markdown(result, today)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "backtest-report.md").write_text(md, encoding="utf-8")
    (OUT_DIR / "backtest-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
