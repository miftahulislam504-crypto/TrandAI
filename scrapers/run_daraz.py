#!/usr/bin/env python3
"""Daraz রান। রিপো রুট থেকে চালান: python -m scrapers.run_daraz [অপশন]

মোড:
  --smoke    ১টা seed, ১ পেজ, ১টা প্রোডাক্ট পেজ, ১ বার রিভিউ। DB লাগে না। কী ফিল্ড পাওয়া যাচ্ছে তার রিপোর্ট দেয়।
  --dry-run  পুরো ডিসকভারি চলে কিন্তু DB-তে কিছু লেখে না।
  (কিছু না দিলে) পুরো রান: SUPABASE_URL ও SUPABASE_SERVICE_KEY env লাগবে।
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scrapers.common.http import RobotsDisallowed, CircuitOpen, FetchError, PoliteClient
from scrapers.common.supabase_rest import SupabaseError, SupabaseREST
from scrapers.daraz import parse
from scrapers.daraz.adapter import DarazAdapter

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path(os.environ.get("RUN_OUT", "run-output"))
COVERAGE_FIELDS = ["url", "title", "price", "original_price", "rating_avg", "rating_count",
                   "sold_count", "seller_name", "brand", "in_stock"]


def bd_today(now: datetime) -> str:
    """বাংলাদেশের তারিখ (UTC+6)। স্ন্যাপশটের captured_on এটাই।"""
    return (now + timedelta(hours=6)).date().isoformat()


def load_config(root: Path = ROOT) -> tuple[dict, dict]:
    daraz = json.loads((root / "config" / "daraz.json").read_text(encoding="utf-8"))
    cats = json.loads((root / "config" / "categories.json").read_text(encoding="utf-8"))
    return daraz, cats


def build_adapter(settings: dict) -> DarazAdapter:
    client = PoliteClient(delay=settings.get("delay_seconds", 3.0),
                          jitter=settings.get("jitter_seconds", 1.5),
                          block_limit=settings.get("block_limit", 3))
    return DarazAdapter(client, strategy_order=settings.get("strategy_order", ["ajax", "html"]),
                        sort=settings.get("sort"))


# ------------------------------------------------------------------ ডিসকভারি
def coverage(items: list[dict]) -> dict:
    n = len(items)
    return {f: {"count": sum(1 for i in items if i.get(f) is not None),
                "pct": round(100 * sum(1 for i in items if i.get(f) is not None) / n) if n else 0}
            for f in COVERAGE_FIELDS}


def collect(adapter: DarazAdapter, daraz_cfg: dict, cats_cfg: dict, only: str | None = None,
            smoke: bool = False, max_pages: int | None = None):
    """সব ক্যাটাগরির আইটেম জড়ো করে। ফেরত: ({slug: [item]}, diagnostics, errors, circuit_open)।"""
    s = daraz_cfg["settings"]
    pages = max_pages or s.get("max_pages_per_seed", 6)
    by_cat: dict[str, list[dict]] = {}
    diags: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    circuit = False

    for cat in cats_cfg["categories"]:
        slug = cat["slug"]
        if only and slug != only:
            continue
        if not only and cat.get("enabled", True) is False:
            continue                       # বন্ধ ক্যাটাগরি রোজকার রানে নয়; --category দিয়ে নাম ধরলে চলে (স্মোক টেস্টের জন্য)
        seeds = daraz_cfg["seeds"].get(slug) or []
        if not seeds:
            errors.append(f"{slug}: কোনো seed নেই")
            continue
        if smoke:
            seeds, per_seed, pages = seeds[:1], 20, 1
        else:
            per_seed = max(10, math.ceil(cat["target_products"] / len(seeds)))
        items: list[dict] = []
        for seed in seeds:
            try:
                found, diag = adapter.discover(seed, per_seed, pages)
            except CircuitOpen as e:
                errors.append(f"{slug}: {e}")
                circuit = True
                break
            except Exception as e:  # noqa: BLE001 - একটা seed ব্যর্থ হলে বাকিগুলো চলবে
                errors.append(f"{slug} {seed}: {type(e).__name__}: {e}")
                continue
            diags.append({"category": slug, **diag, "found": len(found)})
            if not found:
                errors.append(f"{slug} {seed}: আইটেম নেই ({'; '.join(diag['notes']) or 'কারণ অজানা'})")
            for it in found:
                if it["external_id"] not in seen:
                    seen.add(it["external_id"])
                    items.append(it)
        by_cat[slug] = items[: cat["target_products"]]
        if circuit or smoke:
            break
    return by_cat, diags, errors, circuit


# ----------------------------------------------------------------- DB সারি
def listing_row(item: dict, source_id: int, category_id: int | None, now_iso: str) -> dict:
    row = {"source_id": source_id, "external_id": item["external_id"],
           "url": item.get("url") or f"{parse.BASE}/products/-i{item['external_id']}.html",
           "last_seen_at": now_iso, "is_active": True}
    for col, key in (("title_raw", "title"), ("brand_raw", "brand"), ("seller_name", "seller_name")):
        if item.get(key):
            row[col] = item[key]
    if item.get("image_url"):
        row["image_url"] = item["image_url"]
    if category_id:
        row["category_id"] = category_id
    return row


def snapshot_row(item: dict, listing_id: int, captured_on: str) -> dict:
    row = {"listing_id": listing_id, "captured_on": captured_on}
    for col in ("price", "original_price", "rating_avg", "rating_count", "review_count",
                "sold_count", "in_stock"):
        if item.get(col) is not None:
            row[col] = item[col]
    return row


# ------------------------------------------------------------------ পুরো রান
def run_pipeline(db, adapter: DarazAdapter, daraz_cfg: dict, cats_cfg: dict, now: datetime,
                 only: str | None = None, max_pages: int | None = None,
                 detail_limit: int | None = None, reviews_limit: int | None = None) -> dict:
    s = daraz_cfg["settings"]
    detail_limit = s.get("detail_limit", 30) if detail_limit is None else detail_limit
    reviews_limit = s.get("reviews_limit", 20) if reviews_limit is None else reviews_limit
    now_iso, today = now.isoformat(), bd_today(now)

    src = db.select("sources", {"slug": "eq.daraz", "select": "id"})
    if not src:
        raise SupabaseError("sources টেবিলে 'daraz' নেই। migration চালানো হয়েছে কি?")
    source_id = src[0]["id"]
    cat_ids = {c["slug"]: c["id"] for c in db.select("categories", {"select": "id,slug"})}
    run_id = db.insert("scrape_runs", [{"source_id": source_id, "started_at": now_iso}], returning=True)[0]["id"]

    summary: dict = {"run_id": run_id, "date": today, "listings": 0, "snapshots": 0, "details": 0,
                     "reviews": 0, "errors": [], "notes": [], "circuit_open": False, "coverage": {}, "diags": []}
    status = "failed"
    try:
        by_cat, diags, errors, circuit = collect(adapter, daraz_cfg, cats_cfg, only, False, max_pages)
        summary.update(diags=diags, circuit_open=circuit)
        summary["errors"] += errors

        existing = {r["external_id"]: r for r in db.select(
            "listing_overview", {"source": "eq.daraz", "select": "id,external_id,review_count,brand_raw"})}

        all_items: list[tuple[str, dict]] = [(slug, it) for slug, its in by_cat.items() for it in its]
        summary["coverage"] = coverage([it for _, it in all_items])

        rows = [listing_row(it, source_id, cat_ids.get(slug), now_iso) for slug, it in all_items]
        res = db.upsert("listings", rows, "source_id,external_id", returning=True)
        id_by_ext = {r["external_id"]: r["id"] for r in res}
        summary["listings"] = len(id_by_ext)
        if id_by_ext:
            db.rpc("link_listings_to_canonical")

        snaps = [snapshot_row(it, id_by_ext[it["external_id"]], today)
                 for _, it in all_items if it["external_id"] in id_by_ext]
        db.upsert("listing_snapshots", snaps, "listing_id,captured_on")
        summary["snapshots"] = len(snaps)

        # ---- ডিটেইল: নতুন বা ব্র্যান্ড-হীন আইটেম, সীমা পর্যন্ত
        if not circuit and detail_limit:
            wanted = [it for _, it in all_items
                      if it["external_id"] not in existing or not existing[it["external_id"]].get("brand_raw")]
            patches: list[dict] = []
            for it in wanted[:detail_limit]:
                if not it.get("url"):
                    continue
                try:
                    d = adapter.fetch_product(it["url"])
                except CircuitOpen as e:
                    summary["errors"].append(f"ডিটেইল: {e}")
                    summary["circuit_open"] = True
                    break
                except FetchError as e:
                    summary["errors"].append(f"ডিটেইল {it['external_id']}: {e}")
                    continue
                lid = id_by_ext.get(it["external_id"])
                patch = {"listing_id": lid, "captured_on": today}
                for col in ("rating_avg", "rating_count", "sold_count", "price", "original_price"):
                    if it.get(col) is None and d.get(col) is not None:  # শুধু ফাঁকা ঘর ভরে
                        patch[col] = d[col]
                if len(patch) > 2:
                    patches.append(patch)
                extra = {}
                if d.get("brand") and not it.get("brand"):
                    extra["brand"] = d["brand"]
                if d.get("image_url") and not it.get("image_url"):
                    extra["image_url"] = d["image_url"]
                if extra:
                    db.upsert("listings", [listing_row({**it, **extra}, source_id, None, now_iso)],
                              "source_id,external_id")
                summary["details"] += 1
            db.upsert("listing_snapshots", patches, "listing_id,captured_on")

        # ---- রিভিউ: যেগুলোর রিভিউ সংখ্যা বেড়েছে
        if not summary["circuit_open"] and reviews_limit:
            cand = []
            for _, it in all_items:
                prev = (existing.get(it["external_id"]) or {}).get("review_count") or 0
                cur = it.get("review_count") or 0
                if cur > prev:
                    cand.append((cur - prev, it))
            cand.sort(key=lambda x: -x[0])
            for _, it in cand[:reviews_limit]:
                lid = id_by_ext.get(it["external_id"])
                try:
                    for page in range(1, s.get("reviews_max_pages", 2) + 1):
                        revs, _ = adapter.fetch_reviews(it["external_id"], page)
                        if not revs:
                            break
                        db.upsert("reviews", [{"listing_id": lid, **r} for r in revs],
                                  "listing_id,external_review_id")
                        summary["reviews"] += len(revs)
                except RobotsDisallowed:
                    # রিভিউ API-র হোস্টের robots.txt অনুমতি দেয়নি: ত্রুটি নয়, সিদ্ধান্ত। একবার জানিয়ে বাকি রিভিউ ধাপ বাদ
                    summary["notes"].append("রিভিউ বাদ: রিভিউ API-র robots.txt অনুমতি দেয়নি (রেটিং গড়/সংখ্যা লিস্টিং থেকে আসছে)")
                    break
                except CircuitOpen as e:
                    summary["errors"].append(f"রিভিউ: {e}")
                    summary["circuit_open"] = True
                    break
                except FetchError as e:
                    summary["errors"].append(f"রিভিউ {it['external_id']}: {e}")

        cutoff = (now - timedelta(days=s.get("inactive_after_days", 30))).isoformat()
        db.update("listings", {"is_active": False},
                  {"source_id": f"eq.{source_id}", "is_active": "eq.true", "last_seen_at": f"lt.{cutoff}"})
        status = "failed" if summary["snapshots"] == 0 else ("partial" if summary["errors"] else "ok")
    except Exception as e:  # noqa: BLE001 - রান-রো আপডেট করতে হবে
        summary["errors"].append(f"মারাত্মক ত্রুটি: {type(e).__name__}: {e}")
        status = "failed"
        raise
    finally:
        try:
            db.update("scrape_runs", {
                "finished_at": datetime.now(timezone.utc).isoformat(), "status": status,
                "items_ok": summary["snapshots"], "items_failed": len(summary["errors"]),
                "error": "; ".join(summary["errors"])[:1000] or None}, {"id": f"eq.{run_id}"})
        except Exception:  # noqa: BLE001
            pass
    summary["status"] = status
    return summary


# ----------------------------------------------------------------- স্মোক টেস্ট
def run_smoke(adapter: DarazAdapter, daraz_cfg: dict, cats_cfg: dict, only: str | None = None) -> dict:
    by_cat, diags, errors, circuit = collect(adapter, daraz_cfg, cats_cfg, only, smoke=True)
    items = [it for its in by_cat.values() for it in its]
    out: dict = {"diags": diags, "errors": errors, "coverage": coverage(items),
                 "sample_item": items[0] if items else None, "product": None, "reviews": None,
                 "client_stats": adapter.client.stats}
    if items and not circuit:
        first = items[0]
        if first.get("url"):
            try:
                p = adapter.fetch_product(first["url"])
                out["product"] = {k: v for k, v in p.items()}
            except FetchError as e:
                out["product"] = {"error": f"{type(e).__name__}: {e}"}
        try:
            revs, meta = adapter.fetch_reviews(first["external_id"], 1, 5)
            out["reviews"] = {"count": len(revs), "meta": meta, "sample": revs[:1]}
        except FetchError as e:
            out["reviews"] = {"error": f"{type(e).__name__}: {e}"}
    out["client_stats"] = adapter.client.stats
    return out


def smoke_markdown(r: dict) -> str:
    L = ["# Daraz Smoke Test", ""]
    st = r["client_stats"]
    L.append(f"রিকোয়েস্ট: {st['requests']}, সফল: {st['ok']}, ব্লক: {st['blocked']}, "
             f"robots নিষেধ: {st['robots_skipped']}, ত্রুটি: {st['errors']}")
    kw = [d for d in r["diags"] if isinstance(d.get("seed"), dict) and d["seed"].get("type") == "keyword"]
    if kw:
        L += ["", "> ⚠️ **পুরনো কনফিগ:** `config/daraz.json`-এ কীওয়ার্ড seed আছে। Daraz robots.txt `/catalog/` (সার্চ) নিষিদ্ধ করেছে, "
              "তাই এগুলো কখনো চলবে না। রিপোতে সর্বশেষ `config/daraz.json` (ক্যাটাগরি URL seed সহ) বসিয়ে কমিট করুন।"]
    L += ["", "## লিস্টিং ডিসকভারি", ""]
    for d in r["diags"]:
        L.append(f"- {d['category']} / {d['seed']}: কৌশল `{d['strategy']}`, পাওয়া {d['found']}, "
                 f"মোট ফলাফল {d['total_results']}")
        if d["raw_keys"]:
            L.append(f"  - আইটেমের key: {', '.join(d['raw_keys'])}")
        for n in d["notes"]:
            L.append(f"  - নোট: {n}")
    for e in r["errors"]:
        L.append(f"- সমস্যা: {e}")
    L += ["", "## ফিল্ড কভারেজ (লিস্টিং থেকে)", "", "| ফিল্ড | আছে | % |", "|---|---|---|"]
    for f, c in r["coverage"].items():
        L.append(f"| {f} | {c['count']} | {c['pct']}% |")
    if r["sample_item"]:
        L += ["", "## প্রথম আইটেম", "", "```json", json.dumps(r["sample_item"], ensure_ascii=False, indent=1), "```"]
    L += ["", "## প্রোডাক্ট পেজ", "", "```json", json.dumps(r["product"], ensure_ascii=False, indent=1, default=str), "```"]
    L += ["", "## রিভিউ", "", "```json", json.dumps(r["reviews"], ensure_ascii=False, indent=1, default=str), "```"]
    return "\n".join(L)


def run_markdown(s: dict) -> str:
    L = ["# Daraz রান", "", f"- স্ট্যাটাস: **{s['status']}** (run #{s['run_id']}, তারিখ {s['date']})",
         f"- listings: {s['listings']}, স্ন্যাপশট: {s['snapshots']}, ডিটেইল: {s['details']}, রিভিউ: {s['reviews']}"]
    if s["circuit_open"]:
        L.append("- রান মাঝপথে থেমেছে (টানা ব্লক)")
    L += ["", "| ফিল্ড | % |", "|---|---|"] + [f"| {f} | {c['pct']}% |" for f, c in s["coverage"].items()]
    if s.get("notes"):
        L += ["", "## নোট"] + [f"- {n}" for n in s["notes"]]
    if s["errors"]:
        L += ["", "## সমস্যা"] + [f"- {e}" for e in s["errors"][:30]]
    return "\n".join(L)


def write_outputs(name: str, data: dict, md: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT_DIR / f"{name}.md").write_text(md, encoding="utf-8")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)


def missing_secrets_markdown(err: str) -> str:
    return "\n".join([
        "# Daraz Daily: শুরু করা যায়নি", "",
        f"কারণ: {err}", "",
        "**সমাধান:** GitHub রিপো -> Settings -> Secrets and variables -> Actions -> New repository secret:",
        "- `SUPABASE_URL` (Supabase প্রজেক্টের URL)",
        "- `SUPABASE_SERVICE_KEY` (service_role key)",
        "- `REVIEWER_HASH_SALT` (যেকোনো লম্বা র‍্যান্ডম লেখা)", "",
        "ডাটাবেজ ছাড়া শুধু দেখতে চাইলে workflow চালানোর সময় `dry_run` টিক দিন।",
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--category", help="শুধু এই ক্যাটাগরি (fashion/home/kitchen)")
    ap.add_argument("--max-pages", type=int)
    ap.add_argument("--detail-limit", type=int)
    ap.add_argument("--reviews-limit", type=int)
    args = ap.parse_args(argv)

    daraz_cfg, cats_cfg = load_config()
    adapter = build_adapter(daraz_cfg["settings"])

    if args.smoke:
        res = run_smoke(adapter, daraz_cfg, cats_cfg, args.category)
        write_outputs("smoke-report", res, smoke_markdown(res))
        return 0 if res["sample_item"] else 1

    if args.dry_run:
        by_cat, diags, errors, circuit = collect(adapter, daraz_cfg, cats_cfg, args.category, False, args.max_pages)
        items = [it for its in by_cat.values() for it in its]
        res = {"diags": diags, "errors": errors, "coverage": coverage(items), "sample_item": items[0] if items else None,
               "product": None, "reviews": None, "client_stats": adapter.client.stats}
        write_outputs("dry-run-report", res, smoke_markdown(res))
        return 0 if items else 1

    try:
        db = SupabaseREST.from_env()
    except SupabaseError as e:
        write_outputs("run-summary", {"status": "failed", "error": str(e)}, missing_secrets_markdown(str(e)))
        return 1
    now = datetime.now(timezone.utc)
    summary = run_pipeline(db, adapter, daraz_cfg, cats_cfg, now, args.category, args.max_pages,
                           args.detail_limit, args.reviews_limit)
    write_outputs("run-summary", summary, run_markdown(summary))
    return 0 if summary["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
