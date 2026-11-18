#!/usr/bin/env python3
"""Google Trends probe.

এই মেশিন (GitHub Actions runner) থেকে pytrends দিয়ে Google Trends-এর ডেটা আনা যায় কি না দেখে।
ইংরেজি ও বাংলা দুই ধরনের কীওয়ার্ড, geo=BD। কাজ না করলেও রিপোর্ট লেখে, ক্র্যাশ করে না।
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path(os.environ.get("AUDIT_OUT", "audit-output"))
TESTS = [
    ("english_2_keywords", ["kitchen organizer", "air fryer"]),
    ("bangla_1_keyword", ["এয়ার ফ্রায়ার"]),
]


def run() -> dict:
    result: dict = {
        "started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "pytrends_import": False,
        "tests": {},
    }
    try:
        from pytrends.request import TrendReq
    except Exception as e:  # noqa: BLE001
        result["import_error"] = f"{type(e).__name__}: {e}"[:300]
        return result
    result["pytrends_import"] = True

    try:
        pt = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
    except Exception as e:  # noqa: BLE001
        result["init_error"] = f"{type(e).__name__}: {e}"[:300]
        return result

    for name, keywords in TESTS:
        entry: dict = {"keywords": keywords}
        try:
            pt.build_payload(keywords, timeframe="today 3-m", geo="BD")
            df = pt.interest_over_time()
            entry["rows"] = int(len(df))
            if len(df):
                last = df.iloc[-1]
                entry["last_row"] = {str(k): (v.item() if hasattr(v, "item") else str(v))
                                     for k, v in last.items()}
                entry["all_zero"] = bool((df[keywords].sum() == 0).all())
            else:
                entry["note"] = "ডেটা ফাঁকা (কম সার্চ ভলিউমে এমন হয়)"
        except Exception as e:  # noqa: BLE001
            entry["error"] = f"{type(e).__name__}: {e}"[:300]
        result["tests"][name] = entry
        time.sleep(8)
    return result


def to_markdown(res: dict) -> str:
    lines = ["# Google Trends Probe", "", f"চালানো হয়েছে: {res['started_utc']} UTC", ""]
    if not res["pytrends_import"]:
        lines.append(f"- pytrends ইম্পোর্ট ব্যর্থ: {res.get('import_error')}")
        return "\n".join(lines)
    if "init_error" in res:
        lines.append(f"- শুরুতেই ব্যর্থ: {res['init_error']}")
        return "\n".join(lines)
    for name, t in res["tests"].items():
        lines.append(f"## {name}")
        lines.append(f"- কীওয়ার্ড: {t['keywords']}")
        if "error" in t:
            lines.append(f"- ত্রুটি: {t['error']}")
        else:
            lines.append(f"- সারি: {t.get('rows')}, সব শূন্য: {t.get('all_zero')}")
            if "last_row" in t:
                lines.append(f"- শেষ সারি: {t['last_row']}")
            if "note" in t:
                lines.append(f"- নোট: {t['note']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res = run()
    (OUT_DIR / "trends-report.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "trends-report.md").write_text(to_markdown(res), encoding="utf-8")
    print(to_markdown(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
