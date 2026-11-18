"""config/trends.json লোড ও যাচাই। ভুল মান থাকলে রান শুরুতেই থামে।"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("fashion", "home", "kitchen")


class TrendsConfigError(ValueError):
    pass


def validate(cfg: dict) -> dict:
    s, se = cfg["settings"], cfg["seasonality"]
    if not s.get("anchor") or not isinstance(s["anchor"], str):
        raise TrendsConfigError("settings.anchor একটা সার্চ শব্দ হতে হবে")
    if not 1 <= s["batch_size"] <= 4:
        raise TrendsConfigError("settings.batch_size ১–৪ হতে হবে (Google একসাথে ৫টা শব্দ নেয়, একটা anchor)")
    if not 1 <= se["batch_size"] <= 5:
        raise TrendsConfigError("seasonality.batch_size ১–৫ হতে হবে")
    if s["norm_window_weeks"] < 8 or s["min_anchor_mean"] <= 0:
        raise TrendsConfigError("norm_window_weeks >= 8 এবং min_anchor_mean > 0 হতে হবে")
    if se["min_weeks"] <= se["lag_weeks"]:
        raise TrendsConfigError("seasonality.min_weeks অবশ্যই lag_weeks-এর চেয়ে বড় হতে হবে")
    seen: set[str] = set()
    terms: set[str] = set()
    for e in cfg["entries"]:
        for k in ("id", "category", "q", "match"):
            if not e.get(k):
                raise TrendsConfigError(f"entry-তে '{k}' দরকার: {e}")
        if e["id"] in seen:
            raise TrendsConfigError(f"entry id দুইবার: {e['id']}")
        seen.add(e["id"])
        if e["category"] not in CATEGORIES:
            raise TrendsConfigError(f"অজানা ক্যাটাগরি '{e['category']}' ({e['id']})")
        for t in (e["q"], e.get("bn")):
            if t:
                key = t.strip().lower()
                if key in terms:
                    raise TrendsConfigError(f"সার্চ শব্দ দুইবার: {t}")
                terms.add(key)
    if s["anchor"].strip().lower() in terms:
        raise TrendsConfigError("anchor কোনো entry-র শব্দ হতে পারবে না")
    return cfg


def load_config(path: Path | None = None) -> dict:
    p = Path(path) if path else ROOT / "config" / "trends.json"
    return validate(json.loads(p.read_text(encoding="utf-8")))
