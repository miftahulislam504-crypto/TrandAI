#!/usr/bin/env python3
"""progress.md-এর সারসংক্ষেপ টেবিল চেকলিস্ট গুনে নিজে হালনাগাদ করে।

ব্যবহার:
  python tools/progress.py            # progress.md-এর টেবিল আপডেট করে
  python tools/progress.py --check    # টেবিল পুরনো হলে exit 1 (CI-তে কাজে লাগে)

নিয়ম: "## Phase N ..." শিরোনামের নিচের `- [x]` / `- [ ]` লাইন গোনা হয়।
% = চেকলিস্টের আইটেম গণনা, কাজের আকার বা সময়ের মাপ নয়।
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

START, END = "<!-- progress:summary:start -->", "<!-- progress:summary:end -->"
PHASE_RE = re.compile(r"^## (Phase \d+)\s*[—:-]*\s*(.*)$")
ITEM_RE = re.compile(r"^\s*- \[( |x|X)\] ")


def parse(text: str) -> list[dict]:
    phases: list[dict] = []
    cur = None
    for line in text.splitlines():
        m = PHASE_RE.match(line)
        if m:
            cur = {"id": m.group(1), "title": m.group(2).strip(), "done": 0, "total": 0}
            phases.append(cur)
            continue
        if line.startswith("## "):
            cur = None
            continue
        im = ITEM_RE.match(line)
        if cur is not None and im:
            cur["total"] += 1
            cur["done"] += im.group(1) in ("x", "X")
    return phases


def bar(done: int, total: int, width: int = 10) -> str:
    filled = round(width * done / total) if total else 0
    return "█" * filled + "░" * (width - filled)


def status(done: int, total: int) -> str:
    if total and done == total:
        return "সম্পন্ন"
    return "শুরু হয়নি" if done == 0 else "চলছে"


def render(phases: list[dict]) -> str:
    lines = ["| ফেজ | হয়েছে | বাকি | অগ্রগতি | অবস্থা |", "|---|---|---|---|---|"]
    for p in phases:
        pct = round(100 * p["done"] / p["total"]) if p["total"] else 0
        lines.append(f"| {p['id']}: {p['title']} | {p['done']} | {p['total'] - p['done']} | "
                     f"{bar(p['done'], p['total'])} {pct}% | {status(p['done'], p['total'])} |")
    d, t = sum(p["done"] for p in phases), sum(p["total"] for p in phases)
    pct = round(100 * d / t) if t else 0
    lines.append(f"| **মোট** | **{d}** | **{t - d}** | **{bar(d, t)} {pct}%** | |")
    return "\n".join(lines)


def update(text: str) -> str:
    if START not in text or END not in text:
        raise ValueError(f"progress.md-তে {START} ও {END} মার্কার লাগবে")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n{render(parse(text))}\n{END}{tail}"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    paths = [a for a in argv if not a.startswith("--")]
    path = Path(paths[0]) if paths else Path(__file__).resolve().parents[1] / "progress.md"
    text = path.read_text(encoding="utf-8")
    new = update(text)
    if check:
        if new != text:
            print("progress.md-এর টেবিল পুরনো: python tools/progress.py চালান", file=sys.stderr)
            return 1
        return 0
    path.write_text(new, encoding="utf-8")
    print(render(parse(new)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
