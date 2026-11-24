"""স্পর্শকাতর বা নিয়ন্ত্রিত পণ্য ধরা (বিশুদ্ধ ফাংশন, config/sensitive.json থেকে নিয়ম)।

ব্যবহার: `match(title, category)` → None (ঠিক আছে) বা {"rule", "label", "hit"}। `split(items, category)` → (রাখা, বাদ)।
সংগ্রহ (run_daraz.collect) ও স্কোরিং (run_scoring.fetch_products) দুই জায়গাতেই এটা চলে, একই নিয়মে।
ইংরেজি শব্দ পুরো-শব্দ মিলে (\"tablet\" মেলে, \"tabletop\" মেলে না); বাংলা শব্দ টুকরো মিলে (বাংলায় শব্দের সীমা ঠিক করা কঠিন)।
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "sensitive.json"
_BN = re.compile(r"[\u0980-\u09FF]")


class SensitiveConfigError(ValueError):
    pass


def validate(cfg: dict) -> dict:
    if not isinstance(cfg.get("rules"), list):
        raise SensitiveConfigError("rules তালিকা নেই")
    scope = cfg.get("scope_categories")
    if not isinstance(scope, list) or not all(isinstance(s, str) for s in scope):
        raise SensitiveConfigError("scope_categories স্ট্রিংয়ের তালিকা হতে হবে")
    ids: set[str] = set()
    for r in cfg["rules"]:
        rid = r.get("id")
        if not rid or rid in ids:
            raise SensitiveConfigError(f"নিয়মের id ফাঁকা বা ডুপ্লিকেট: {rid!r}")
        ids.add(rid)
        if not r.get("label"):
            raise SensitiveConfigError(f"{rid}: label লাগবে")
        cats = r.get("categories", "scope")
        if cats not in ("scope", "all") and not (isinstance(cats, list) and all(isinstance(c, str) for c in cats)):
            raise SensitiveConfigError(f"{rid}: categories scope, all বা তালিকা হতে হবে")
        if not r.get("phrases") and not r.get("regex"):
            raise SensitiveConfigError(f"{rid}: phrases বা regex লাগবে")
        for rx in r.get("regex", []):
            try:
                re.compile(rx)
            except re.error as e:
                raise SensitiveConfigError(f"{rid}: regex ভুল ({rx}): {e}") from None
    return cfg


def load_rules(path: Path = CONFIG) -> dict:
    return validate(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def _default() -> dict:
    return load_rules()


def _phrase_re(p: str) -> re.Pattern:
    q = re.escape(p.strip())
    if _BN.search(p):
        return re.compile(q)                                   # বাংলা: টুকরো মিল
    return re.compile(rf"(?<![a-z0-9]){q}(?![a-z0-9])", re.I)  # ইংরেজি: পুরো শব্দ


def _compile(cfg: dict) -> list[dict]:
    out = []
    for r in cfg["rules"]:
        out.append({
            "id": r["id"], "label": r["label"], "categories": r.get("categories", "scope"),
            "phrases": [(p, _phrase_re(p)) for p in r.get("phrases", [])],
            "regex": [re.compile(x, re.I) for x in r.get("regex", [])],
            "allow": [_phrase_re(a) for a in r.get("allow", [])],
        })
    return out


_COMPILED: dict[int, list[dict]] = {}


def _rules(cfg: dict) -> list[dict]:
    k = id(cfg)
    if k not in _COMPILED:
        _COMPILED.clear()
        _COMPILED[k] = _compile(cfg)
    return _COMPILED[k]


def match(title: Optional[str], category: Optional[str], cfg: Optional[dict] = None) -> Optional[dict]:
    cfg = cfg if cfg is not None else _default()
    if not cfg.get("enabled", True) or not title:
        return None
    scope = set(cfg.get("scope_categories", []))
    for r in _rules(cfg):
        cats = r["categories"]
        if cats == "scope" and category not in scope:
            continue
        if isinstance(cats, list) and category not in cats:
            continue
        hit = next((p for p, rx in r["phrases"] if rx.search(title)), None)
        if hit is None:
            m = next((rx.search(title) for rx in r["regex"] if rx.search(title)), None)
            hit = m.group(0) if m else None
        if hit is None:
            continue
        if any(a.search(title) for a in r["allow"]):
            continue
        return {"rule": r["id"], "label": r["label"], "hit": hit}
    return None


def split(items: Iterable[dict], category: Optional[str], cfg: Optional[dict] = None,
          title_key: str = "title") -> tuple[list[dict], list[dict]]:
    """(রাখা আইটেম, বাদ আইটেম); বাদ আইটেমে `_sensitive` = match-এর ফল যোগ হয়।"""
    kept, dropped = [], []
    for it in items:
        m = match(it.get(title_key), category, cfg)
        if m:
            dropped.append({**it, "_sensitive": m})
        else:
            kept.append(it)
    return kept, dropped


def summarize_dropped(dropped: list[dict], title_key: str = "title", examples: int = 12) -> dict:
    by_rule: dict[str, int] = {}
    for d in dropped:
        by_rule[d["_sensitive"]["rule"]] = by_rule.get(d["_sensitive"]["rule"], 0) + 1
    ex = [{"rule": d["_sensitive"]["rule"], "hit": d["_sensitive"]["hit"], "title": (d.get(title_key) or "")[:80]}
          for d in dropped[:examples]]
    return {"count": len(dropped), "by_rule": by_rule, "examples": ex}
