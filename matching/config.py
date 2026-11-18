"""config/matching.json লোড ও যাচাই।"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MatchConfigError(ValueError):
    pass


def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def validate(cfg: dict) -> dict:
    t = cfg["thresholds"]
    if not 0 < t["review"] < t["auto"] <= 1:
        raise MatchConfigError("thresholds: 0 < review < auto <= 1 হতে হবে")
    w = cfg["weights"]
    if w["title"] <= 0 or w["price"] < 0:
        raise MatchConfigError("weights.title > 0 এবং weights.price >= 0 হতে হবে")
    p = cfg["price"]
    if not 0 < p["zero_score_ratio"] < p["full_score_ratio"] <= 1:
        raise MatchConfigError("price: 0 < zero_score_ratio < full_score_ratio <= 1 হতে হবে")
    if cfg["same_source"] not in ("review", "auto", "never"):
        raise MatchConfigError("same_source: review | auto | never")
    if cfg["max_cluster_size"] < 2 or cfg["unit_tolerance"] < 0:
        raise MatchConfigError("max_cluster_size >= 2 এবং unit_tolerance >= 0 হতে হবে")
    im = cfg.get("image") or {}
    if im.get("enabled"):
        if not 0 <= im["strong_dist"] <= im["near_dist"] <= 20:
            raise MatchConfigError("image: 0 <= strong_dist <= near_dist <= 20 হতে হবে")
        if not 0 <= im["near_bonus"] <= im["strong_bonus"] <= 0.5:
            raise MatchConfigError("image: 0 <= near_bonus <= strong_bonus <= 0.5 হতে হবে")
        if not 0 <= im["auto_title_floor"] <= 1 or im["max_hash_group"] < 2 or not 0 <= im["min_bits"] <= 32:
            raise MatchConfigError("image: auto_title_floor 0..1, max_hash_group >= 2, min_bits 0..32 হতে হবে")
    return cfg


def load_config(path: Path | None = None, override: dict | None = None) -> dict:
    cfg = json.loads((Path(path) if path else ROOT / "config" / "matching.json").read_text(encoding="utf-8"))
    if override:
        cfg = _merge(copy.deepcopy(cfg), override)
    return validate(cfg)
