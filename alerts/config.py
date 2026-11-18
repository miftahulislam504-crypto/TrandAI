"""config/alerts.json লোড ও যাচাই। ভুল মান থাকলে রান শুরুতেই থামে।"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIERS = ("best", "mid", "dont")


class AlertsConfigError(ValueError):
    pass


def _num(cfg: dict, path: str, lo: float, hi: float) -> float:
    cur = cfg
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            raise AlertsConfigError(f"{path} নেই")
        cur = cur[k]
    if isinstance(cur, bool) or not isinstance(cur, (int, float)) or not lo <= cur <= hi:
        raise AlertsConfigError(f"{path} {lo}–{hi}-এর মধ্যে একটা সংখ্যা হতে হবে (পেয়েছি: {cur!r})")
    return cur


def validate(cfg: dict) -> dict:
    _num(cfg, "score_move.points", 1, 100)
    _num(cfg, "score_move.days", 1, 60)
    _num(cfg, "score_move.max_gap_days", 1, 90)
    if cfg["score_move"]["max_gap_days"] < cfg["score_move"]["days"]:
        raise AlertsConfigError("score_move.max_gap_days অবশ্যই days-এর সমান বা বেশি হতে হবে")
    _num(cfg, "price_move.pct", 1, 500)
    _num(cfg, "redflag.min_count", 1, 1000)
    _num(cfg, "keep_days", 7, 3650)
    _num(cfg, "telegram.max_items", 1, 40)
    d = cfg.get("discovery")
    if not isinstance(d, dict) or not isinstance(d.get("enabled"), bool):
        raise AlertsConfigError("discovery.enabled true/false হতে হবে")
    if not isinstance(d.get("tiers"), list) or not d["tiers"] or any(t not in TIERS for t in d["tiers"]):
        raise AlertsConfigError(f"discovery.tiers {list(TIERS)}-এর অংশ হতে হবে")
    if not isinstance(cfg["telegram"].get("enabled"), bool):
        raise AlertsConfigError("telegram.enabled true/false হতে হবে")
    return cfg


def load_config(path: Path | None = None) -> dict:
    p = Path(path) if path else ROOT / "config" / "alerts.json"
    return validate(json.loads(p.read_text(encoding="utf-8")))
