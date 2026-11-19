#!/usr/bin/env python3
"""Daraz ক্যাটাগরি ডিসকভারি রান: python -m scrapers.run_discover
config/daraz_candidates.json-এর slug থেকে শুরু করে ব্রেডক্রাম্ব ও উপ-ক্যাটাগরি ধরে এগোয়।
আউটপুট (run-output/): daraz-categories.json, daraz-categories.md, daraz-seeds-proposed.json
"""
from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path

from scrapers.common.http import CircuitOpen, FetchError, PoliteClient
from scrapers.daraz import parse
from scrapers.daraz.discover import propose, summarize

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path(os.environ.get("RUN_OUT", "run-output"))


def crawl(client, cfg: dict) -> tuple[dict, list[str]]:
    queue = deque(cfg["start"])
    seen: set[str] = set()
    found: dict[str, dict] = {}
    log: list[str] = []
    budget = cfg.get("max_requests", 60)
    per_parent = cfg.get("children_per_parent", 12)
    while queue and budget > 0:
        slug = queue.popleft()
        if slug in seen:
            continue
        seen.add(slug)
        budget -= 1
        try:
            obj = client.get_json(f"{parse.BASE}/{slug}/", params={"ajax": "true", "page": 1, "sort": "popularity"})
        except CircuitOpen as e:
            log.append(f"থামানো হলো: {e}")
            break
        except FetchError as e:
            log.append(f"✗ {slug}: {str(e)[:120]}")
            continue
        info = summarize(slug, obj)
        if not info:
            log.append(f"✗ {slug}: আইটেম নেই")
            continue
        found[slug] = info
        log.append(f"✓ {slug}: {info['total_results']} পণ্য, সোল্ড {info['sold_pct']}%")
        for b in info["breadcrumb"]:                       # উপরের ক্যাটাগরি
            if b["slug"] and b["slug"] not in seen:
                queue.append(b["slug"])
        for c in info["children"][:per_parent]:            # উপ-ক্যাটাগরি
            if c["slug"] not in seen:
                queue.append(c["slug"])
    return found, log


def main() -> int:
    cfg = json.loads((ROOT / "config" / "daraz_candidates.json").read_text(encoding="utf-8"))
    settings = json.loads((ROOT / "config" / "daraz.json").read_text(encoding="utf-8")).get("settings", {})
    client = PoliteClient(delay=settings.get("delay_seconds", 3.0), jitter=settings.get("jitter_seconds", 1.5),
                          block_limit=settings.get("block_limit", 3))
    found, log = crawl(client, cfg)
    proposed = propose(found, cfg["group_keywords"], cfg.get("min_total_results", 300))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "daraz-categories.json").write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "daraz-seeds-proposed.json").write_text(json.dumps(proposed, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# Daraz ক্যাটাগরি ডিসকভারি", "", f"কাজের ক্যাটাগরি: {len(found)}টা", "", "## প্রস্তাবিত seed (group অনুযায়ী)", ""]
    for g, rows in proposed.items():
        md.append(f"### {g} ({len(rows)}টা)")
        md += [f"- `{r['url']}` — {r['title']} ({r['total_results']} পণ্য)" for r in rows] or ["- কিছু মেলেনি"]
        md.append("")
    md += ["## সব পাওয়া ক্যাটাগরি", "", "| slug | নাম | পণ্য | সোল্ড% | রেটিং% |", "|---|---|---|---|---|"]
    for s, i in sorted(found.items(), key=lambda kv: -(kv[1]["total_results"] or 0)):
        md.append(f"| {s} | {i['title']} | {i['total_results']} | {i['sold_pct']} | {i['rating_pct']} |")
    md += ["", "## লগ", ""] + [f"- {l}" for l in log]
    (OUT_DIR / "daraz-categories.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:40]))
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
