#!/usr/bin/env python3
"""Phase 0: source probe.

প্রতিটা সোর্সের কয়েকটা পাবলিক পেজে একটা করে GET পাঠিয়ে দেখে:
  1. robots.txt অনুযায়ী পেজটা ফেচ করা যায় কি না (না গেলে ফেচ করা হয় না)
  2. বট-চ্যালেঞ্জ বা ব্লকের চিহ্ন আছে কি না
  3. ডেটা কোথায় আছে: JSON-LD, __NEXT_DATA__, ইনলাইন JSON, নাকি আলাদা JSON endpoint
  4. সোল্ড / রেটিং / রিভিউ / দাম সংক্রান্ত key বা টেক্সট আছে কি না

রিপোর্ট লেখা হয় AUDIT_OUT (ডিফল্ট: audit-output/) ফোল্ডারে।
Env: AUDIT_TARGETS, AUDIT_OUT, AUDIT_USER_AGENT, AUDIT_DELAY (সেকেন্ড, ডিফল্ট 4)
"""
from __future__ import annotations

import html as htmllib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

HERE = Path(__file__).resolve().parent
TARGETS_PATH = Path(os.environ.get("AUDIT_TARGETS", HERE / "targets.json"))
OUT_DIR = Path(os.environ.get("AUDIT_OUT", "audit-output"))
UA_TOKEN = "marketresearchaudit"
USER_AGENT = os.environ.get(
    "AUDIT_USER_AGENT",
    "Mozilla/5.0 (compatible; MarketResearchAudit/0.1; personal market research)",
)
DELAY = float(os.environ.get("AUDIT_DELAY", "4"))
TIMEOUT = 25
SAMPLE_BYTES = 300_000
MAX_TEXT = 2_000_000

BOT_MARKERS = [
    "captcha", "access denied", "just a moment", "cf-chl", "unusual traffic",
    "x5secdata", "_____tmd_____", "slide to verify", "baxia",
]
STATE_MARKERS = [
    "__NEXT_DATA__", "self.__next_f", "window.pageData", "__moduleData__",
    "window.__INITIAL_STATE__", "window.__NUXT__", "__APOLLO_STATE__",
]
KEY_PATTERNS = {
    "sold": re.compile(r'\\?"([A-Za-z_]*[Ss]old[A-Za-z_]*)\\?"\s*:'),
    "rating": re.compile(r'\\?"([A-Za-z_]*[Rr]ating[A-Za-z_]*)\\?"\s*:'),
    "review": re.compile(r'\\?"([A-Za-z_]*[Rr]eview[A-Za-z_]*)\\?"\s*:'),
    "price": re.compile(r'\\?"([A-Za-z_]*[Pp]rice[A-Za-z_]*)\\?"\s*:'),
}
TEXT_PATTERNS = {
    "price_text": re.compile(r"(?:৳|Tk\.?|BDT)\s?\d[\d,]*"),
    "sold_text": re.compile(
        r"(?<![\w.])\d[\d.,]*\s?[KkMm]?\+?\s?(?:sold|Sold|SOLD)\b"
        r"|[০-৯\d][০-৯\d.,]*\s*(?:টি\s*)?বিক্রি"
    ),
    "rating_count_text": re.compile(
        r"(?:Ratings?|Reviews?)\s*\(?\s*\d+|\(\s*\d+\s*(?:ratings?|reviews?)\s*\)", re.I
    ),
}
LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)
NEXT_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S
)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


# ---------------------------------------------------------------- robots.txt
def parse_robots(text: str) -> dict[str, list[tuple[str, str]]]:
    """robots.txt থেকে {user-agent: [(allow|disallow, pattern), ...]} বানায়।"""
    groups: dict[str, list[tuple[str, str]]] = {}
    current: list[str] = []
    last_was_ua = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if not last_was_ua:
                current = []
            current.append(value.lower())
            groups.setdefault(value.lower(), [])
            last_was_ua = True
        elif key in ("allow", "disallow"):
            last_was_ua = False
            for ua in current:
                groups[ua].append((key, value))
        else:
            last_was_ua = False
    return groups


def _rule_regex(pattern: str) -> re.Pattern:
    escaped = re.escape(pattern).replace(r"\*", ".*")
    if escaped.endswith(r"\$"):
        escaped = escaped[:-2] + "$"
    return re.compile("^" + escaped)


def robots_allowed(groups: dict, path_with_query: str, ua_token: str = UA_TOKEN) -> bool:
    """Google-এর নিয়ম: সবচেয়ে লম্বা মিল জেতে, সমান হলে Allow জেতে। * ও $ সাপোর্টেড।"""
    rules = groups.get(ua_token.lower()) or groups.get("*") or []
    best: tuple[int, bool] | None = None
    for kind, pattern in rules:
        if pattern == "":
            continue
        if _rule_regex(pattern).match(path_with_query):
            cand = (len(pattern), kind == "allow")
            if best is None or cand[0] > best[0] or (cand[0] == best[0] and cand[1]):
                best = cand
    return True if best is None else best[1]


def load_robots(session: requests.Session, base_url: str, source_id: str) -> dict:
    url = base_url.rstrip("/") + "/robots.txt"
    time.sleep(DELAY)
    try:
        r = session.get(url, timeout=TIMEOUT)
    except requests.RequestException as e:
        return {"url": url, "status": None, "groups": None, "text": "",
                "error": f"{type(e).__name__}: {e}"[:200]}
    text = r.text[:20_000] if r.status_code == 200 else ""
    groups = parse_robots(text) if r.status_code == 200 else None
    (OUT_DIR / "robots" / f"{source_id}.txt").write_text(
        f"# HTTP {r.status_code} {url}\n{text}", encoding="utf-8"
    )
    return {"url": url, "status": r.status_code, "groups": groups, "text": text}


def robots_decision(robots: dict, url: str) -> str:
    status = robots["status"]
    if status is None or status >= 500:
        return "unknown"
    if status != 200:  # 4xx: robots.txt নেই, নিষেধ নেই
        return "allowed"
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return "allowed" if robots_allowed(robots["groups"], path) else "disallowed"


# ------------------------------------------------------------------ analysis
def visible_text(html_text: str) -> str:
    t = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", html_text, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", htmllib.unescape(t))


def find_keys(text: str, kind: str) -> list[str]:
    found: list[str] = []
    for m in KEY_PATTERNS[kind].finditer(text):
        key = m.group(1)
        if kind == "sold" and re.search(r"sold_?out", key, re.I):
            continue
        if key not in found:
            found.append(key)
        if len(found) >= 15:
            break
    return found


def first_match(rx: re.Pattern, text: str) -> str | None:
    m = rx.search(text)
    return m.group(0).strip()[:60] if m else None


def _flatten_ld(node, out: list) -> None:
    if isinstance(node, list):
        for x in node:
            _flatten_ld(x, out)
    elif isinstance(node, dict):
        out.append(node)
        graph = node.get("@graph")
        if isinstance(graph, list):
            _flatten_ld(graph, out)


def parse_json_ld(html_text: str) -> list[dict]:
    nodes: list[dict] = []
    for m in LD_RE.finditer(html_text):
        try:
            _flatten_ld(json.loads(m.group(1).strip()), nodes)
        except ValueError:
            continue
    return [
        {
            "type": n.get("@type"),
            "keys": sorted(k for k in n if not k.startswith("@"))[:25],
            "has_aggregateRating": "aggregateRating" in n,
            "has_offers": "offers" in n,
        }
        for n in nodes
    ][:10]


def parse_next_data(html_text: str) -> dict | None:
    m = NEXT_RE.search(html_text)
    if not m:
        return None
    info: dict = {"bytes": len(m.group(1))}
    try:
        data = json.loads(m.group(1))
        props = (data.get("props") or {}).get("pageProps") or {}
        info["page_props_keys"] = list(props.keys())[:20] if isinstance(props, dict) else []
    except ValueError:
        info["parse_error"] = True
    return info


def find_item_list(obj, path: str = "$", depth: int = 0):
    """প্রথম যে list-এ কমপক্ষে ২টা dict আছে তার (path, list) ফেরত দেয়।"""
    if depth > 7:
        return None
    if isinstance(obj, list):
        if len(obj) >= 2 and all(isinstance(x, dict) for x in obj[:3]):
            return path, obj
        for i, x in enumerate(obj[:3]):
            r = find_item_list(x, f"{path}[{i}]", depth + 1)
            if r:
                return r
    elif isinstance(obj, dict):
        for k, v in obj.items():
            r = find_item_list(v, f"{path}.{k}", depth + 1)
            if r:
                return r
    return None


def json_summary(obj) -> dict:
    summary: dict = {"top_keys": list(obj.keys())[:20] if isinstance(obj, dict) else "list"}
    found = find_item_list(obj)
    if found:
        path, items = found
        keys = sorted(items[0].keys())
        summary.update({
            "item_list_path": path,
            "item_count": len(items),
            "item_keys": keys[:60],
            "item_key_hits": {
                kind: [k for k in keys if kind in k.lower()]
                for kind in ("sold", "rating", "review", "price")
            },
        })
    return summary


def analyze(content_type: str, text: str) -> dict:
    out: dict = {}
    stripped = text.lstrip()
    is_json = "json" in (content_type or "").lower() or stripped[:1] in ("{", "[")
    if is_json:
        try:
            out["kind"] = "json"
            out["json"] = json_summary(json.loads(text))
            out["keys"] = {k: find_keys(text, k) for k in KEY_PATTERNS}
            return out
        except ValueError:
            out.pop("json", None)
    out["kind"] = "html"
    m = TITLE_RE.search(text)
    out["title"] = htmllib.unescape(m.group(1)).strip()[:120] if m else None
    out["state_markers"] = [mk for mk in STATE_MARKERS if mk in text]
    out["json_ld"] = parse_json_ld(text)
    out["next_data"] = parse_next_data(text)
    out["keys"] = {k: find_keys(text, k) for k in KEY_PATTERNS}
    vis = visible_text(text)
    out["visible"] = {name: first_match(rx, vis) for name, rx in TEXT_PATTERNS.items()}
    return out


def detect_block(status: int, text: str) -> list[str]:
    flags = []
    if status in (401, 403, 429, 503):
        flags.append(f"http_{status}")
    low = text[:200_000].lower()
    flags += [m for m in BOT_MARKERS if m in low]
    return flags


# --------------------------------------------------------------------- probe
def probe_page(session: requests.Session, src: dict, page: dict, robots: dict) -> dict:
    url = page["url"]
    rec: dict = {"source": src["id"], "label": page["label"], "url": url,
                 "robots": robots_decision(robots, url), "fetched": False}
    if rec["robots"] != "allowed":
        detail = f"HTTP {robots['status']}" if robots.get("status") else robots.get("error", "")
        rec["skipped_reason"] = f"robots={rec['robots']}" + (f" ({detail})" if detail else "")
        return rec
    time.sleep(DELAY)
    t0 = time.time()
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as e:
        rec["error"] = f"{type(e).__name__}: {e}"[:200]
        rec["elapsed_s"] = round(time.time() - t0, 2)
        return rec
    if "charset" not in r.headers.get("Content-Type", "").lower():
        r.encoding = "utf-8"  # charset না থাকলে requests ISO-8859-1 ধরে, বাংলা ভেঙে যায়
    text = r.text[:MAX_TEXT]
    rec.update({
        "fetched": True,
        "status": r.status_code,
        "final_url": r.url,
        "elapsed_s": round(time.time() - t0, 2),
        "bytes": len(r.content),
        "content_type": r.headers.get("Content-Type", ""),
        "bot_signals": detect_block(r.status_code, text),
    })
    rec.update(analyze(rec["content_type"], text))
    ext = "json" if rec.get("kind") == "json" else "html"
    (OUT_DIR / "samples" / f"{src['id']}__{page['label']}.{ext}").write_text(
        text[:SAMPLE_BYTES], encoding="utf-8", errors="replace"
    )
    return rec


# -------------------------------------------------------------------- report
def _flag(v) -> str:
    return "হ্যাঁ" if v else "না"


def build_markdown(records: list[dict], started: str) -> str:
    lines = [
        "# Source Audit Report",
        "",
        f"চালানো হয়েছে: {started} UTC",
        "",
        "## সারসংক্ষেপ",
        "",
        "| সোর্স / পেজ | HTTP | robots | বট সিগন্যাল | সোল্ড | রেটিং |",
        "|---|---|---|---|---|---|",
    ]
    for r in records:
        keys = r.get("keys") or {}
        vis = r.get("visible") or {}
        sold = bool(keys.get("sold") or vis.get("sold_text"))
        rating = bool(keys.get("rating") or vis.get("rating_count_text"))
        if r["fetched"]:
            lines.append(
                f"| {r['source']} / {r['label']} | {r['status']} | {r['robots']} | "
                f"{', '.join(r['bot_signals']) or '-'} | {_flag(sold)} | {_flag(rating)} |"
            )
        else:
            why = (r.get("skipped_reason") or r.get("error", ""))[:70]
            lines.append(f"| {r['source']} / {r['label']} | ফেচ হয়নি | {r['robots']} | {why} | - | - |")
    lines += ["", "## বিস্তারিত", ""]
    for r in records:
        lines.append(f"### {r['source']} / {r['label']}")
        lines.append(f"- URL: {r['url']}")
        lines.append(f"- robots: {r['robots']}")
        if not r["fetched"]:
            lines.append(f"- ফেচ হয়নি: {r.get('skipped_reason') or r.get('error')}")
            lines.append("")
            continue
        lines.append(f"- HTTP {r['status']}, {r['bytes']} bytes, {r['elapsed_s']}s, {r['content_type']}")
        if r["final_url"] != r["url"]:
            lines.append(f"- রিডাইরেক্ট: {r['final_url']}")
        if r["bot_signals"]:
            lines.append(f"- বট সিগন্যাল (মার্কার মানেই ব্লক নয়): {', '.join(r['bot_signals'])}")
        if r["kind"] == "json":
            js = r["json"]
            lines.append(f"- JSON top keys: {js.get('top_keys')}")
            if "item_list_path" in js:
                lines.append(f"- আইটেম তালিকা: `{js['item_list_path']}` ({js['item_count']}টা)")
                lines.append(f"- আইটেমের key: {', '.join(js['item_keys'])}")
                lines.append(f"- মূল key মিল: {js['item_key_hits']}")
        else:
            lines.append(f"- title: {r.get('title')}")
            lines.append(f"- স্টেট মার্কার: {r.get('state_markers') or 'নেই'}")
            ld = r.get("json_ld") or []
            lines.append(f"- JSON-LD: {[(x['type'], 'rating' if x['has_aggregateRating'] else '-') for x in ld] or 'নেই'}")
            nd = r.get("next_data")
            lines.append(f"- __NEXT_DATA__: {nd if nd else 'নেই'}")
            lines.append(f"- দৃশ্যমান টেক্সটে: {r.get('visible')}")
        keys = r.get("keys") or {}
        for kind in ("sold", "rating", "review", "price"):
            if keys.get(kind):
                lines.append(f"- `{kind}` key: {', '.join(keys[kind])}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    if not TARGETS_PATH.exists():
        print(f"targets ফাইল নেই: {TARGETS_PATH}", file=sys.stderr)
        return 1
    cfg = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    for sub in ("samples", "robots"):
        (OUT_DIR / sub).mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
    })
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    records: list[dict] = []
    for src in cfg["sources"]:
        print(f"== {src['id']}", flush=True)
        robots = load_robots(session, src["base_url"], src["id"])
        for page in src["pages"]:
            rec = probe_page(session, src, page, robots)
            print(f"   {page['label']}: robots={rec['robots']} status={rec.get('status')}", flush=True)
            records.append(rec)

    (OUT_DIR / "audit-report.json").write_text(
        json.dumps({"started_utc": started, "user_agent": USER_AGENT, "records": records},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT_DIR / "audit-report.md").write_text(build_markdown(records, started), encoding="utf-8")
    print(f"রিপোর্ট: {OUT_DIR / 'audit-report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
