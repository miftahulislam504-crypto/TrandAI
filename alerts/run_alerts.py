"""রোজ Score Daily-র পরে চালানো হয়: আজকের স্কোর আগের দিনগুলোর সাথে মিলিয়ে অ্যালার্ট বানায়, Telegram-এ পাঠায় (ঐচ্ছিক)।

ব্যবহার:
  python -m alerts.run_alerts                 # আজকের (বাংলাদেশ) স্কোর ধরে
  python -m alerts.run_alerts --dry-run       # কিছু না লিখে শুধু দেখুন
  python -m alerts.run_alerts --date 2026-11-20 --no-notify

লাগে: SUPABASE_URL, SUPABASE_SERVICE_KEY, Phase 7 migration (20261117000000_phase7.sql)।
ঐচ্ছিক: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DASHBOARD_URL (বার্তায় /alerts লিংক)।
একই দিনে আবার চালালে নকল অ্যালার্ট হয় না, আর যেটা Telegram-এ গেছে সেটা দুবার যায় না।
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from scrapers.common.supabase_rest import SupabaseError, SupabaseREST

from .config import load_config
from .detect import Score, detect, price_moves
from .notify import NotifyError, build_digest, credentials, send_telegram

OUT_DIR = Path(os.environ.get("RUN_OUT", "run-output"))
CHUNK = 150
KIND_BN = {"tier_change": "ট্যাগ বদল", "score_move": "স্কোর সরেছে", "price_move": "বাজারদর বদল", "redflag": "নকল অভিযোগ"}


def bd_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=6)).date()


def _in(ids: list[int]) -> str:
    return "in.(" + ",".join(str(i) for i in ids) + ")"


def _chunks(ids: list[int]):
    for i in range(0, len(ids), CHUNK):
        yield ids[i:i + CHUNK]


def _score(r: dict) -> Score:
    try:
        cf = int(r.get("cf_n") or 0)
    except (TypeError, ValueError):
        cf = 0
    return Score(pid=r["canonical_product_id"], scored_on=date.fromisoformat(r["scored_on"][:10]), tier=r.get("tier"),
                 total=None if r.get("total") is None else float(r["total"]), confidence=r.get("confidence"),
                 counterfeit_n=cf)


def fetch_scores(db, today: date, cfg: dict) -> tuple[dict[int, Score], dict[int, list[Score]]]:
    back = max(cfg["score_move"]["max_gap_days"], 10) + 1
    rows = db.select("product_scores", {
        "scored_on": f"gte.{(today - timedelta(days=back)).isoformat()}",
        "order": "scored_on.desc,canonical_product_id.asc",
        "select": "canonical_product_id,scored_on,tier,total,confidence,cf_n:reasons->detail->counterfeit->>n"})
    cur: dict[int, Score] = {}
    hist: dict[int, list[Score]] = {}
    for r in rows:
        s = _score(r)
        if s.scored_on == today:
            cur[s.pid] = s
        elif s.scored_on < today:
            hist.setdefault(s.pid, []).append(s)   # order desc: নতুন -> পুরনো
    return cur, hist


def fetch_watch(db) -> set[int]:
    return {r["canonical_product_id"] for r in db.select("watchlist", {"select": "canonical_product_id"})}


def fetch_price_pct(db, watch: set[int]) -> dict[int, float]:
    rows: list[dict] = []
    for part in _chunks(sorted(watch)):
        rows += db.select("listing_overview", {
            "select": "canonical_product_id,price,price_delta_7d", "is_active": "eq.true",
            "price_delta_7d": "not.is.null", "canonical_product_id": _in(part)})
    return price_moves(rows)


def fetch_names(db, pids: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for part in _chunks(sorted(pids)):
        for r in db.select("canonical_products", {"select": "id,name", "id": _in(part)}):
            out[r["id"]] = r["name"]
    return out


def make_alerts(db, cfg: dict, today: date) -> tuple[list[dict], dict]:
    cur, hist = fetch_scores(db, today, cfg)
    info = {"scored_today": len(cur), "watch": 0}
    if not cur:
        return [], info
    watch = fetch_watch(db) & set(cur)
    info["watch"] = len(watch)
    price_pct = fetch_price_pct(db, watch) if watch else {}
    first = detect(cur, hist, watch, price_pct, {}, cfg, today)       # কোন প্রোডাক্টে অ্যালার্ট হবে জানতে
    names = fetch_names(db, sorted({a["canonical_product_id"] for a in first}))
    return detect(cur, hist, watch, price_pct, names, cfg, today), info  # নাম বসিয়ে চূড়ান্ত


def summary_markdown(today: date, dry: bool, info: dict, alerts: list[dict], notify_note: str, pruned: Optional[int]) -> str:
    kinds = Counter(a["kind"] for a in alerts)
    L = [f"## অ্যালার্ট রান — {today.isoformat()}{' (dry-run, কিছু লেখা হয়নি)' if dry else ''}", "",
         f"- আজ স্কোর হয়েছে: {info.get('scored_today', 0)}টা প্রোডাক্ট",
         f"- ওয়াচলিস্টে (আজ স্কোর-হওয়া): {info.get('watch', 0)}টা",
         f"- নতুন অ্যালার্ট: {len(alerts)}টা" + ("" if not kinds else " (" + ", ".join(
             f"{KIND_BN[k]} {n}" for k, n in kinds.items()) + ")"),
         f"- Telegram: {notify_note}"]
    if pruned:
        L.append(f"- পুরনো অ্যালার্ট মোছা হয়েছে: {pruned}টা")
    if alerts:
        L += ["", "| ধরন | ওয়াচলিস্ট | বার্তা |", "|---|---|---|"]
        L += [f"| {KIND_BN[a['kind']]} | {'⭐' if a['watched'] else ''} | {a['title']} |" for a in alerts[:40]]
        if len(alerts) > 40:
            L.append(f"\n…আরও {len(alerts) - 40}টা")
    return "\n".join(L) + "\n"


def notify_pending(db, cfg: dict, today: date, dry: bool, no_notify: bool) -> str:
    if no_notify or not cfg["telegram"]["enabled"]:
        return "বন্ধ (config বা --no-notify)"
    creds = credentials()
    if not creds:
        return "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID দেওয়া নেই, বাদ"
    if dry:  # অ্যালার্ট লেখা হয়নি, তাই ডাটাবেজে পাঠানোর মতো সারিও নেই; শুধু জানিয়ে দিই
        return "dry-run: পাঠানো হয়নি"
    rows = db.select("alerts", {"select": "id,title,severity,watched,created_on", "notified_at": "is.null",
                                "created_on": f"gte.{(today - timedelta(days=2)).isoformat()}", "order": "id.asc"})
    if not rows:
        return "পাঠানোর মতো নতুন অ্যালার্ট নেই"
    try:
        send_telegram(build_digest(rows, os.environ.get("DASHBOARD_URL"), cfg["telegram"]["max_items"]), *creds)
    except NotifyError as e:
        return f"ব্যর্থ: {e} (অ্যালার্ট ড্যাশবোর্ডে আছে, পরের রানে আবার চেষ্টা হবে)"
    db.rpc("mark_alerts_notified", {"p_ids": [r["id"] for r in rows]})
    return f"{len(rows)}টা পাঠানো হয়েছে"


def run(db, cfg: dict, today: date, dry: bool = False, no_notify: bool = False) -> dict:
    alerts, info = make_alerts(db, cfg, today)
    if not dry and alerts:
        db.upsert("alerts", alerts, "canonical_product_id,kind,created_on")
    note = notify_pending(db, cfg, today, dry, no_notify)
    pruned = None if dry else db.rpc("prune_alerts", {"p_keep_days": cfg["keep_days"]})
    return {"alerts": alerts, "info": info, "notify": note, "pruned": pruned,
            "markdown": summary_markdown(today, dry, info, alerts, note, pruned)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(Path(args.config) if args.config else None)
    today = date.fromisoformat(args.date) if args.date else bd_today()
    try:
        out = run(SupabaseREST.from_env(), cfg, today, args.dry_run, args.no_notify)
    except SupabaseError as e:
        hint = " (Phase 7 migration 20261117000000_phase7.sql চালিয়েছেন?)" if "404" in str(e) or "PGRST" in str(e) else ""
        print(f"অ্যালার্ট রান ব্যর্থ: {e}{hint}", file=sys.stderr)
        return 1
    except requests.RequestException as e:
        print(f"অ্যালার্ট রান ব্যর্থ: Supabase-এ পৌঁছানো যায়নি ({type(e).__name__})", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "alerts-summary.md").write_text(out["markdown"], encoding="utf-8")
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(out["markdown"] + "\n")
    print(out["markdown"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
