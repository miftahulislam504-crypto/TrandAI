"""YouTube ট্রেন্ড সংগ্রহ (অফিসিয়াল YouTube Data API v3)।

প্রতিটা শব্দে (config/trends.json-এর চালু ক্যাটাগরির ইংরেজি ও বাংলা শব্দ) গত N দিনে বাংলাদেশে ভিউ-অনুযায়ী শীর্ষ ভিডিও
খুঁজে ভিডিও-সংখ্যা, মোট ও মধ্য ভিউ, শীর্ষ ভিডিও `youtube_keyword_stats`-এ রাখে। আগের রানের সাথে তুলনায় বোঝা যায় কোন শব্দে
ভিডিও-আগ্রহ বাড়ছে। এখন শুধু জমা হয়, স্কোরে ঢোকে না।

কোটা: একটা শব্দে ১০১ ইউনিট (search ১০০ + videos ১); দিনে বিনামূল্যে ১০,০০০। তাই প্রতি রানে `max_keywords_per_run` শব্দ,
আর `refresh_days`-এর মধ্যে আনা শব্দ বাদ। কোটা শেষ হলে বা key ভুল হলে রান নিজে থামে।

ব্যবহার:
  YOUTUBE_API_KEY=... python -m youtube.run_youtube [--dry-run] [--force] [--category kitchen] [--limit 5]
key না থাকলে রান বাদ যায় (exit 0), ওয়ার্কফ্লো লাল হয় না।
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from trends.config import enabled_categories, load_config as load_trends_config
from trends.keywords import build_terms

from .client import KeyRejected, QuotaExceeded, YouTubeClient, YouTubeError
from .stats import summarize

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "youtube.json"
TABLE = "youtube_keyword_stats"


class YouTubeConfigError(ValueError):
    pass


def load_config(path: Path = CONFIG) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    s = cfg.get("settings") or {}
    for k in ("region", "window_days", "max_results", "order", "refresh_days", "max_keywords_per_run",
              "quota_budget", "search_cost", "videos_cost", "sleep_seconds"):
        if k not in s:
            raise YouTubeConfigError(f"settings.{k} নেই")
    if not (isinstance(s["region"], str) and len(s["region"]) == 2):
        raise YouTubeConfigError("settings.region দুই অক্ষরের দেশ-কোড হতে হবে (BD)")
    if s["order"] not in ("viewCount", "relevance", "date", "rating"):
        raise YouTubeConfigError("settings.order viewCount/relevance/date/rating-এর একটা হতে হবে")
    if not 1 <= s["window_days"] <= 365 or not 1 <= s["max_results"] <= 50:
        raise YouTubeConfigError("window_days ১–৩৬৫ এবং max_results ১–৫০ হতে হবে")
    if s["refresh_days"] < 1 or s["max_keywords_per_run"] < 1 or s["sleep_seconds"] < 0:
        raise YouTubeConfigError("refresh_days ও max_keywords_per_run ≥ ১, sleep_seconds ≥ ০ হতে হবে")
    if s["search_cost"] < 1 or s["videos_cost"] < 0 or s["quota_budget"] < s["search_cost"] + s["videos_cost"]:
        raise YouTubeConfigError("quota_budget অন্তত একটা শব্দের খরচের (search_cost + videos_cost) সমান হতে হবে")
    return cfg


def bd_today(now: Optional[datetime] = None) -> date:
    return ((now or datetime.now(timezone.utc)) + timedelta(hours=6)).date()


def pick_due(terms: list[dict], fetched: set[tuple[str, str]], force: bool) -> list[dict]:
    """সদ্য আনা (keyword, lang) বাদ; তালিকার ক্রম বজায় থাকে (সীমা ধরলে পরের রানে বাকিগুলো আসে)।"""
    return list(terms) if force else [t for t in terms if (t["keyword"], t["lang"]) not in fetched]


def run(db, client: YouTubeClient, cfg: dict, trends_cfg: dict, now: datetime, only_category: Optional[str] = None,
        dry_run: bool = False, force: bool = False, limit: Optional[int] = None,
        enabled: Optional[set[str]] = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    s = cfg["settings"]
    today = bd_today(now)
    terms = build_terms(trends_cfg, only_category, None, enabled)
    fetched: set[tuple[str, str]] = set()
    if db is not None and not force:
        cutoff = (today - timedelta(days=s["refresh_days"])).isoformat()
        rows = db.select(TABLE, {"select": "keyword,lang,fetched_on", "region": f"eq.{s['region']}", "fetched_on": f"gt.{cutoff}"})
        fetched = {(r["keyword"], r["lang"]) for r in rows}
    due = pick_due(terms, fetched, force)
    cap = min(s["max_keywords_per_run"], limit) if limit else s["max_keywords_per_run"]
    summary: dict = {"date": today.isoformat(), "terms_total": len(terms), "due": len(due), "tried": 0, "saved": 0,
                     "quota_used": 0, "stopped": None, "errors": [], "results": [], "dry_run": dry_run}
    published_after = (now - timedelta(days=s["window_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    per_term = s["search_cost"] + s["videos_cost"]
    out_rows: list[dict] = []

    for t in due[:cap]:
        if summary["quota_used"] + per_term > s["quota_budget"]:
            summary["stopped"] = "quota_budget"
            break
        try:
            ids = client.search(t["keyword"], published_after, s["region"], s["max_results"],
                                "bn" if t["lang"] == "bn" else "en", s["order"])
            summary["quota_used"] += s["search_cost"]
            vids = client.videos(ids)
            if ids:
                summary["quota_used"] += s["videos_cost"]
        except QuotaExceeded as e:
            summary["stopped"] = "quota_exceeded"
            summary["errors"].append(str(e))
            break
        except KeyRejected as e:
            summary["stopped"] = "key_rejected"
            summary["errors"].append(str(e))
            break
        except YouTubeError as e:
            summary["tried"] += 1
            summary["errors"].append(f"{t['keyword']}: {e}")
            continue
        summary["tried"] += 1
        st = summarize(vids)
        out_rows.append({"group_key": t["group_key"], "keyword": t["keyword"], "lang": t["lang"], "category": t["category"],
                         "region": s["region"], "fetched_on": today.isoformat(), "window_days": s["window_days"], **st})
        summary["results"].append({"keyword": t["keyword"], "lang": t["lang"], "category": t["category"], **st})
        if s["sleep_seconds"]:
            sleep(s["sleep_seconds"])

    if out_rows and not dry_run and db is not None:
        db.upsert(TABLE, out_rows, "keyword,lang,region,fetched_on")
        summary["saved"] = len(out_rows)
    return summary


def summary_markdown(o: dict) -> str:
    L = [f"# YouTube ট্রেন্ড সংগ্রহ ({o['date']})", ""]
    L.append(f"- শব্দ মোট {o['terms_total']}টা, আনার বাকি {o['due']}টা; এই রানে চেষ্টা {o['tried']}টা, সেভ {o['saved']}টা"
             + (" (ড্রাই-রান, ডাটাবেজে লেখা হয়নি)" if o["dry_run"] else ""))
    L.append(f"- কোটা খরচ ~{o['quota_used']} ইউনিট (বিনামূল্যে সীমা ১০,০০০/দিন)")
    if o["stopped"]:
        L.append(f"- **থেমেছে:** {o['stopped']}")
    for e in o["errors"][:10]:
        L.append(f"- ত্রুটি: {e}")
    if o["results"]:
        L += ["", "| শব্দ | ভাষা | ভিডিও | মধ্য ভিউ | শীর্ষ ভিডিওর ভিউ |", "|---|---|---|---|---|"]
        for r in sorted(o["results"], key=lambda x: -(x["views_median"] or 0))[:40]:
            L.append(f"| {r['keyword']} | {r['lang']} | {r['videos']} | {r['views_median'] if r['views_median'] is not None else '–'} "
                     f"| {r['top_video_views'] if r['top_video_views'] is not None else '–'} |")
    return "\n".join(L) + "\n"


def _emit(md: str, js: dict) -> None:
    out = ROOT / "run-output"
    out.mkdir(exist_ok=True)
    (out / "youtube-summary.md").write_text(md, encoding="utf-8")
    (out / "youtube-summary.json").write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write(md)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="YouTube Data API v3 থেকে ক্যাটাগরি-শব্দের ভিডিও ট্রেন্ড")
    ap.add_argument("--dry-run", action="store_true", help="ডাটাবেজে না লিখে শুধু দেখুন (কোটা খরচ হয়)")
    ap.add_argument("--force", action="store_true", help="সদ্য আনা শব্দও আবার আনুন")
    ap.add_argument("--category", help="শুধু এই ক্যাটাগরি (বন্ধ হলেও চলে)")
    ap.add_argument("--limit", type=int, help="এই রানে সর্বোচ্চ এত শব্দ (config-এর সীমার ভেতরে)")
    args = ap.parse_args(argv)

    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        print("YOUTUBE_API_KEY সেট নেই, YouTube সংগ্রহ বাদ। (GitHub Secrets-এ YOUTUBE_API_KEY দিন, Google Cloud-এ YouTube Data API v3 চালু করে)")
        return 0
    cfg, trends_cfg = load_config(), load_trends_config()
    db = None
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        from scrapers.common.supabase_rest import SupabaseREST
        db = SupabaseREST.from_env()
    elif not args.dry_run:
        print("SUPABASE_URL ও SUPABASE_SERVICE_KEY দরকার (শুধু দেখতে চাইলে --dry-run)")
        return 1
    o = run(db, YouTubeClient(key), cfg, trends_cfg, datetime.now(timezone.utc), args.category, args.dry_run, args.force,
            args.limit, enabled=None if args.category else enabled_categories())
    _emit(summary_markdown(o), o)
    # চেষ্টা হয়েছে অথচ একটাও আসেনি, বা key ভুল হলে লাল; কোটা শেষ হওয়া ঠিক আছে (পরের দিন চলবে)
    if o["stopped"] == "key_rejected":
        return 1
    return 1 if o["tried"] and not o["results"] and o["stopped"] != "quota_exceeded" else 0


if __name__ == "__main__":
    sys.exit(main())
