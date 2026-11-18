"""robots.txt পার্সার ও ক্যাশ। সব স্ক্র্যাপার ফেচের আগে এটা দিয়ে অনুমতি যাচাই করে।

নিয়ম (Google-এর মতো): সবচেয়ে লম্বা মিল জেতে, সমান হলে Allow জেতে। * ও $ সাপোর্টেড।
robots.txt-এর HTTP স্ট্যাটাস: 200 = পার্স, 4xx = নিষেধ নেই, 5xx/নেটওয়ার্ক ত্রুটি = সাবধানতায় নিষেধ ধরা।
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

UA_TOKEN = "marketresearchbot"


def parse_robots(text: str) -> dict[str, list[tuple[str, str]]]:
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


class RobotsCache:
    """হোস্ট ধরে robots.txt একবার আনে। fetch = ফাংশন(url) -> (status|None, text)।"""

    def __init__(self, fetch, ua_token: str = UA_TOKEN):
        self._fetch = fetch
        self._ua = ua_token
        self._cache: dict[str, tuple[str, dict | None]] = {}

    def _load(self, scheme: str, host: str):
        key = f"{scheme}://{host}"
        if key not in self._cache:
            status, text = self._fetch(f"{key}/robots.txt")
            if status == 200:
                self._cache[key] = ("rules", parse_robots(text))
            elif status is not None and 400 <= status < 500:
                self._cache[key] = ("open", None)
            else:
                self._cache[key] = ("closed", None)
        return self._cache[key]

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        mode, groups = self._load(p.scheme, p.netloc)
        if mode == "open":
            return True
        if mode == "closed":
            return False
        path = p.path or "/"
        if p.query:
            path += "?" + p.query
        return robots_allowed(groups, path, self._ua)
