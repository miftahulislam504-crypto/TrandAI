#!/usr/bin/env python3
"""Google Trends সংগ্রহ। রিপো রুট থেকে: python -m trends.run_trends [অপশন]

  --smoke        ২টা রিকোয়েস্ট, DB লাগে না। Google এই মেশিন থেকে ডেটা দেয় কি না, anchor ঠিক কি না দেখায়।
  --dry-run      সংগ্রহ হয় কিন্তু DB-তে কিছু লেখে না (DB env না থাকলেও চলে)
  --category c   শুধু এই ক্যাটাগরি (fashion / home / kitchen)
  --force        সম্প্রতি আনা শব্দও আবার আনে (ডিফল্টে refresh_days-এর মধ্যে আনা শব্দ বাদ, তাই আংশিক রান আবার চালালে বাকিটা থেকে শুরু হয়)
  --max-batches N  এক রানে সর্বোচ্চ N টা রিকোয়েস্ট-ব্যাচ (সীমা দিয়ে পরীক্ষার জন্য)
  --no-seasonality ৫ বছরের সিজনালিটি ধাপ বাদ
  --config path  অন্য কনফিগ

env: SUPABASE_URL, SUPABASE_SERVICE_KEY (smoke ও dry-run ছাড়া)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .config import load_config
from .fetcher import CircuitOpen, FetchFailed, Fetcher, PytrendsClient, TrendsClient
from .keywords import build_terms
from .normalize import complete, normalize_batch, seasonality

OUT_DIR = Path(os.environ.get("RUN_OUT", "run-output"))


def bd_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=6)).date()


def chunks(xs: list, n: int):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _d(v) -> Optional[date]:
    return date.fromisoformat(v[:10]) if v else None


# ------------------------------------------------------------------ কোন শব্দ আনতে হবে
def pick_stale(terms: list[dict], existing: dict[str, dict], today: date, refresh_days: int, force: bool) -> list[dict]:
    """শেষ সফল আনার পর refresh_days না গেলে শব্দটা বাদ। 'error' বা কখনও না আনা শব্দ সবসময় আসে।"""
    if force:
        return list(terms)
    out = []
    for t in terms:
        row = existing.get(t["keyword"])
        last = _d(row.get("last_fetched_on")) if row else None
        if row and last and row.get("last_status") in ("ok", "no_data", "low_volume") \
                and (today - last).days < refresh_days:
            continue
        out.append(t)
    return out


def pick_seasonality(terms: list[dict], statuses: dict[str, str], checked: dict[str, Optional[date]],
                     today: date, refresh_days: int, force: bool) -> list[dict]:
    out = []
    for t in terms:
        if statuses.get(t["keyword"]) != "ok":
            continue
        last = checked.get(t["keyword"])
        if force or last is None or (today - last).days >= refresh_days:
            out.append(t)
    return out


# ------------------------------------------------------------------ মূল রান
def run(db, client: TrendsClient, cfg: dict, today: date, only_category: Optional[str] = None,
        dry_run: bool = False, force: bool = False, max_batches: Optional[int] = None,
        do_seasonality: bool = True, sleep=None, rand=None) -> dict:
    s = cfg["settings"]
    geo = s["geo"]
    kw = {} if sleep is None else {"sleep": sleep}
    if rand is not None:
        kw["rand"] = rand
    fetcher = Fetcher(client, s, **kw)
    write = db is not None and not dry_run

    terms = build_terms(cfg, only_category)
    existing: dict[str, dict] = {}
    cat_ids: dict[str, int] = {}
    if db is not None:
        cat_ids = {c["slug"]: c["id"] for c in db.select("categories", {"select": "id,slug"})}
        existing = {r["keyword"]: r for r in db.select("trend_keywords", {
            "geo": f"eq.{geo}",
            "select": "id,keyword,last_fetched_on,last_status,seasonality_checked_on"})}
    todo = pick_stale(terms, existing, today, s["refresh_days"], force)

    summary: dict = {"date": today.isoformat(), "terms_total": len(terms), "terms_selected": len(todo),
                     "skipped_fresh": len(terms) - len(todo), "statuses": {}, "batches": 0, "errors": [],
                     "anchor_means": [], "circuit_open": False, "seasonality": {"updated": 0, "batches": 0},
                     "dry_run": dry_run, "written_points": 0}
    status_of: dict[str, str] = {t["keyword"]: (existing.get(t["keyword"]) or {}).get("last_status") or "" for t in terms}

    # keyword সারি নিশ্চিত করা, id পাওয়া
    ids: dict[str, int] = {k: r["id"] for k, r in existing.items()}
    if write and todo:
        rows = [{"keyword": t["keyword"], "geo": geo, "lang": t["lang"], "group_key": t["group_key"],
                 "category_id": cat_ids.get(t["category"]), "is_active": True} for t in todo]
        for r in db.upsert("trend_keywords", rows, "keyword,geo", returning=True):
            ids[r["keyword"]] = r["id"]

    # ---- ধাপ ১: ১২ মাসের সাপ্তাহিক সিরিজ (anchor সহ)
    batches = list(chunks(todo, s["batch_size"]))
    if max_batches is not None:
        batches = batches[:max_batches]
    attempted: list[str] = []
    for batch in batches:
        names = [t["keyword"] for t in batch]
        try:
            raw = fetcher.get([s["anchor"]] + names, s["timeframe"])
        except CircuitOpen as e:
            summary["circuit_open"] = True
            summary["errors"].append(str(e))
            break
        except FetchFailed as e:
            summary["errors"].append(str(e)[:300])
            _mark(db, write, geo, names, "error", err=str(e)[:200])
            for n in names:
                status_of[n] = "error"
            attempted += names
            continue
        summary["batches"] += 1
        attempted += names
        res = normalize_batch(raw, s["anchor"], s)
        if not res.ok:
            summary["errors"].append(f"anchor সমস্যা ({res.error}): {names}")
            _mark(db, write, geo, names, "error", err=res.error)
            for n in names:
                status_of[n] = "error"
            continue
        summary["anchor_means"].append(round(res.anchor_mean, 2))
        point_rows = []
        for n in names:
            kr = res.keywords[n]
            status_of[n] = kr.status
            if kr.status == "ok" and n in ids:
                point_rows += [{"keyword_id": ids[n], "week_start": d.isoformat(), "value": norm,
                                "raw_value": rv, "anchor_value": av, "fetched_on": today.isoformat()}
                               for d, rv, av, norm in kr.points]
        if write:
            _mark(db, True, geo, names, None, statuses={n: res.keywords[n].status for n in names}, today=today)
            if point_rows:
                db.upsert("trend_points", point_rows, "keyword_id,week_start")
        summary["written_points"] += len(point_rows) if write else 0
    for n in attempted:
        st = status_of[n] or "unknown"
        summary["statuses"][st] = summary["statuses"].get(st, 0) + 1

    # ---- ধাপ ২: সিজনালিটি (৫ বছর, মাসে একবার)
    se = cfg["seasonality"]
    if do_seasonality and se["enabled"] and not summary["circuit_open"]:
        checked = {k: _d(r.get("seasonality_checked_on")) for k, r in existing.items()}
        stale = pick_seasonality(terms, status_of, checked, today, se["refresh_days"], force)
        sbatches = list(chunks(stale, se["batch_size"]))
        if max_batches is not None:
            sbatches = sbatches[:max_batches]
        for batch in sbatches:
            names = [t["keyword"] for t in batch]
            try:
                raw = fetcher.get(names, se["timeframe"])
            except CircuitOpen as e:
                summary["circuit_open"] = True
                summary["errors"].append(str(e))
                break
            except FetchFailed as e:
                summary["errors"].append(f"সিজনালিটি: {str(e)[:250]}")
                continue
            summary["seasonality"]["batches"] += 1
            rows = []
            for n in names:
                sr = seasonality(raw.get(n, []), cfg)
                rows.append({"keyword": n, "geo": geo, "seasonal": None if sr is None else sr["seasonal"],
                             "seasonal_corr": None if sr is None else sr["corr"],
                             "yoy_log": None if sr is None else sr["yoy_log"],
                             "seasonality_checked_on": today.isoformat()})
            if write:
                db.upsert("trend_keywords", rows, "keyword,geo")
            summary["seasonality"]["updated"] += len(rows)

    summary["requests"] = dict(fetcher.stats)
    _diagnose(summary, s)
    return summary


def _mark(db, write: bool, geo: str, names: list[str], status: Optional[str], err: Optional[str] = None,
          statuses: Optional[dict] = None, today: Optional[date] = None) -> None:
    if not write:
        return
    rows = []
    for n in names:
        st = statuses[n] if statuses else status
        row = {"keyword": n, "geo": geo, "last_status": st, "last_error": err}
        if st != "error":  # ব্যর্থ হলে last_fetched_on বদলায় না, তাই পরের রানে আবার চেষ্টা হয়
            row["last_fetched_on"] = (today or date.today()).isoformat()
        rows.append(row)
    db.upsert("trend_keywords", rows, "keyword,geo")  # upsert কী-সেট অনুযায়ী নিজে ভাগ করে


def _diagnose(summary: dict, s: dict) -> None:
    """সংখ্যা দেখে কী ঠিক করতে হবে তার ইঙ্গিত।"""
    st = summary["statuses"]
    attempted = sum(st.values())
    weak = st.get("low_volume", 0) + st.get("no_data", 0)
    hints = []
    if attempted >= 4 and weak / attempted >= 0.5:
        hints.append(f"আনা শব্দের {round(100 * weak / attempted)}% low_volume/no_data। anchor '{s['anchor']}' সম্ভবত অন্য শব্দের তুলনায় "
                     "অনেক বড়, ফলে বাকিরা ছোট দেখাচ্ছে। smoke টেস্ট চালিয়ে ছোট ভলিউমের anchor বেছে config/trends.json-এ বদলান।")
    if any("anchor সমস্যা (anchor_low)" in e for e in summary["errors"]):
        hints.append(f"anchor '{s['anchor']}'-এর ভলিউম খুব কম। বড় ভলিউমের anchor দিন।")
    if summary["circuit_open"]:
        hints.append("টানা রেট-লিমিটে রান থেমেছে। কিছুক্ষণ পরে আবার চালালে বাকি শব্দ থেকে শুরু হবে।")
    summary["hints"] = hints


# ------------------------------------------------------------------ smoke
def smoke(client: TrendsClient, cfg: dict, sleep=None, rand=None) -> dict:
    s = cfg["settings"]
    kw = {} if sleep is None else {"sleep": sleep}
    if rand is not None:
        kw["rand"] = rand
    fetcher = Fetcher(client, s, **kw)
    out: dict = {"anchor": s["anchor"], "probe": None, "pipeline": None, "errors": []}

    probe = cfg["smoke"]["probe_terms"][:5]
    try:
        raw = fetcher.get(probe, s["timeframe"])
        rows = []
        for t in probe:
            ser = complete(raw.get(t, []))
            rows.append({"term": t, "weeks": len(ser), "mean": round(sum(v for _, v in ser) / len(ser), 1) if ser else 0,
                         "peak": max((v for _, v in ser), default=0), "nonzero": sum(1 for _, v in ser if v > 0)})
        out["probe"] = rows
        usable = sorted((r for r in rows if r["mean"] > 0), key=lambda r: r["mean"])
        out["suggested_anchor"] = usable[len(usable) // 2]["term"] if usable else None
    except FetchFailed as e:
        out["errors"].append(f"probe: {str(e)[:300]}")
        out["circuit_open"] = isinstance(e, CircuitOpen)
        return out

    sample = [t["keyword"] for t in build_terms(cfg)[:4]]
    try:
        raw = fetcher.get([s["anchor"]] + sample, s["timeframe"])
        res = normalize_batch(raw, s["anchor"], s)
        out["pipeline"] = {"ok": res.ok, "error": res.error,
                           "anchor_mean": None if res.anchor_mean is None else round(res.anchor_mean, 2),
                           "keywords": {k: {"status": v.status, "peak_raw": v.peak_raw, "nonzero_weeks": v.nonzero_weeks,
                                            "mean_norm": None if v.mean_norm is None else round(v.mean_norm, 1)}
                                        for k, v in res.keywords.items()}}
    except FetchFailed as e:
        out["errors"].append(f"pipeline: {str(e)[:300]}")
    out["requests"] = dict(fetcher.stats)
    return out


def smoke_markdown(o: dict) -> str:
    L = ["# Google Trends স্মোক রিপোর্ট", "", f"- anchor (কনফিগে): `{o['anchor']}`"]
    for e in o["errors"]:
        L.append(f"- ❌ {e}")
    if o["probe"]:
        L += ["", "## ধাপ ১: ভলিউমের তুলনা (একই রিকোয়েস্টে ৫টা শব্দ)", "",
              "| শব্দ | সপ্তাহ | গড় | সর্বোচ্চ | অশূন্য সপ্তাহ |", "|---|---|---|---|---|"]
        for r in o["probe"]:
            L.append(f"| {r['term']} | {r['weeks']} | {r['mean']} | {r['peak']} | {r['nonzero']} |")
        if o.get("suggested_anchor"):
            L.append(f"\nমাঝারি ভলিউমের শব্দ (anchor-এর প্রার্থী): **{o['suggested_anchor']}**")
    if o["pipeline"]:
        p = o["pipeline"]
        L += ["", "## ধাপ ২: আসল পাইপলাইনের পরীক্ষা (anchor + ৪টা শব্দ)", ""]
        if not p["ok"]:
            L.append(f"- ❌ anchor ব্যর্থ: {p['error']} (anchor গড় {p['anchor_mean']})")
        else:
            L += [f"- anchor-এর গড় (শেষ ৫২ সপ্তাহ): {p['anchor_mean']}", "",
                  "| শব্দ | অবস্থা | সর্বোচ্চ (raw) | অশূন্য সপ্তাহ | নর্মালাইজড গড় |", "|---|---|---|---|---|"]
            for k, v in p["keywords"].items():
                L.append(f"| {k} | {v['status']} | {v['peak_raw']} | {v['nonzero_weeks']} | {v['mean_norm']} |")
    L += ["", "**কীভাবে পড়বেন:** `ok` = শব্দটা ব্যবহারযোগ্য। বেশিরভাগ `low_volume` হলে anchor খুব বড়, ধাপ ১-এর মাঝারি শব্দটা anchor করুন। "
          "রিপোর্টে ত্রুটি (৪২৯ ইত্যাদি) থাকলে Google এই IP থেকে ডেটা দিচ্ছে না, সেটা আমাকে জানান।"]
    return "\n".join(L)


def summary_markdown(o: dict) -> str:
    L = [f"# Trends রান ({o['date']}{', dry-run' if o['dry_run'] else ''})", "",
         f"- মোট শব্দ: {o['terms_total']}, এবার আনতে বাছা: {o['terms_selected']}, সদ্য আনা বলে বাদ: {o['skipped_fresh']}",
         f"- রিকোয়েস্ট: {o['requests']}", f"- ব্যাচ সফল: {o['batches']}"]
    if o["statuses"]:
        L.append("- শব্দের অবস্থা: " + ", ".join(f"{k} {v}" for k, v in sorted(o["statuses"].items())))
    if o["anchor_means"]:
        L.append(f"- anchor-এর গড় (ব্যাচ অনুযায়ী): {o['anchor_means']}")
    L.append(f"- সিজনালিটি: {o['seasonality']['updated']}টা শব্দ ({o['seasonality']['batches']} ব্যাচ)")
    if not o["dry_run"]:
        L.append(f"- লেখা পয়েন্ট: {o['written_points']}")
    for h in o.get("hints", []):
        L.append(f"- ⚠️ {h}")
    for e in o["errors"][:10]:
        L.append(f"- ত্রুটি: {e}")
    return "\n".join(L)


def _emit(md: str, js: dict, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.md").write_text(md, encoding="utf-8")
    (OUT_DIR / f"{name}.json").write_text(json.dumps(js, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--category")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-batches", type=int)
    ap.add_argument("--no-seasonality", action="store_true")
    ap.add_argument("--config")
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config) if args.config else None)
    s = cfg["settings"]
    try:
        client = PytrendsClient(geo=s["geo"], hl=s["hl"], tz=s["tz"])
    except FetchFailed as e:
        md = f"# Google Trends\n\n- ❌ ক্লায়েন্ট চালু হয়নি: {e}\n- সম্ভবত Google এই IP-কে ব্লক করেছে বা pytrends ভেঙেছে।"
        _emit(md, {"error": str(e)}, "trends-summary")
        return 1

    if args.smoke:
        o = smoke(client, cfg)
        _emit(smoke_markdown(o), o, "trends-smoke")
        return 0 if o["probe"] else 1

    db = None
    if not args.dry_run:
        from scrapers.common.supabase_rest import SupabaseREST
        db = SupabaseREST.from_env()
    elif os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        from scrapers.common.supabase_rest import SupabaseREST
        db = SupabaseREST.from_env()
    o = run(db, client, cfg, bd_today(), args.category, args.dry_run, args.force, args.max_batches,
            not args.no_seasonality)
    _emit(summary_markdown(o), o, "trends-summary")
    # আংশিক রান ঠিক আছে (পরের রানে চলবে); চেষ্টা হয়েছে অথচ একটা শব্দও আসেনি হলেই লাল
    tried = sum(o["statuses"].values())
    got = sum(o["statuses"].get(k, 0) for k in ("ok", "low_volume", "no_data"))
    return 1 if tried and not got else 0


if __name__ == "__main__":
    sys.exit(main())
