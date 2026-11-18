"""স্কোরিং কনফিগ লোড ও যাচাই। ভুল মান থাকলে রান শুরুতেই থামে, চুপচাপ ভুল স্কোর দেয় না।"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORS = ("demand", "trend", "review_quality", "bad_review", "ads_signal", "margin", "competition")
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}

DEFAULTS = json.loads((ROOT / "config" / "scoring.json").read_text(encoding="utf-8"))


class ConfigError(ValueError):
    pass


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def validate(cfg: dict) -> dict:
    w = cfg["weights"]
    if set(w) != set(FACTORS):
        raise ConfigError(f"weights-এ ঠিক এই ফ্যাক্টরগুলো থাকতে হবে: {FACTORS}")
    if any((not isinstance(v, (int, float))) or v < 0 for v in w.values()) or sum(w.values()) <= 0:
        raise ConfigError("weights অ-ঋণাত্মক সংখ্যা হতে হবে এবং যোগফল ০-র বেশি")
    if cfg["tier_mode"] not in ("absolute", "percentile"):
        raise ConfigError("tier_mode হবে absolute অথবা percentile")
    if cfg["best"]["min_score"] <= cfg["dont"]["max_score"]:
        raise ConfigError("best.min_score অবশ্যই dont.max_score-এর চেয়ে বড় হতে হবে")
    if cfg["best"]["percentile_top"] + cfg["dont"]["percentile_bottom"] >= 100:
        raise ConfigError("percentile_top + percentile_bottom ১০০-র কম হতে হবে")
    rq = cfg["review_quality"]
    if not (1 <= rq["floor"] < rq["ceiling"] <= 5):
        raise ConfigError("review_quality: 1 <= floor < ceiling <= 5 হতে হবে")
    if not 0 <= rq["recent_weight"] <= 1 or not 0 <= cfg["demand"]["velocity_share"] <= 1:
        raise ConfigError("recent_weight ও velocity_share ০ থেকে ১-এর মধ্যে হতে হবে")
    if cfg["best"]["min_confidence"] not in CONFIDENCE_ORDER:
        raise ConfigError("best.min_confidence হবে low/medium/high")
    if cfg["tier_change_days"] < 1 or cfg["history_days"] < 2 * cfg["trend"]["recent_days"]:
        raise ConfigError("tier_change_days >= 1 এবং history_days >= 2 * trend.recent_days হতে হবে")
    g = cfg["trend"]["google"]
    if not 0 <= g["share"] <= 1 or not 0 <= g["seasonal_yoy_weight"] <= 1:
        raise ConfigError("trend.google.share ও seasonal_yoy_weight ০ থেকে ১-এর মধ্যে হতে হবে")
    if g["momentum_weight"] < 0 or g["position_weight"] < 0 or g["momentum_weight"] + g["position_weight"] <= 0:
        raise ConfigError("trend.google momentum_weight/position_weight অ-ঋণাত্মক ও যোগফল ০-র বেশি হতে হবে")
    if g["recent_weeks"] < 1 or g["prior_weeks"] < 1 or g["year_weeks"] < g["recent_weeks"] + g["prior_weeks"]:
        raise ConfigError("trend.google: recent_weeks, prior_weeks >= 1 এবং year_weeks >= recent_weeks + prior_weeks")
    if g["span"] <= 0 or g["smoothing_share"] < 0 or g["min_weeks"] < g["recent_weeks"] + g["prior_weeks"]:
        raise ConfigError("trend.google: span > 0, smoothing_share >= 0, min_weeks >= recent_weeks + prior_weeks")
    if cfg["sentiment_notes"]["min_count"] < 1:
        raise ConfigError("sentiment_notes.min_count >= 1 হতে হবে")
    m, c, rf = cfg["margin"], cfg["competition"], cfg["red_flags"]
    if not (0 <= m["platform_fee_pct"] < 100 and 0 <= m["return_rate_pct"] < 100 and m["floor_pct"] < m["ceiling_pct"]):
        raise ConfigError("margin: fee/return 0..100 এর কম এবং floor_pct < ceiling_pct হতে হবে")
    if c["saturated_sellers"] < 2:
        raise ConfigError("competition.saturated_sellers >= 2 হতে হবে")
    if rf["counterfeit"]["min_count"] < 1 or not 0 <= rf["counterfeit"]["min_ratio"] <= 1:
        raise ConfigError("red_flags.counterfeit: min_count >= 1, min_ratio 0..1 হতে হবে")
    a = cfg["ads"]
    cw, gr = a["component_weights"], a["growth"]
    if a["max_age_days"] < 1 or a["full_advertisers"] < 1 or a["full_ads"] < 1:
        raise ConfigError("ads: max_age_days, full_advertisers, full_ads >= 1 হতে হবে")
    if not 0 <= a["longevity_floor_days"] < a["longevity_full_days"]:
        raise ConfigError("ads: 0 <= longevity_floor_days < longevity_full_days হতে হবে")
    if set(cw) != {"breadth", "longevity", "growth"} or any(v < 0 for v in cw.values()) or cw["breadth"] <= 0:
        raise ConfigError("ads.component_weights-এ breadth, longevity, growth থাকতে হবে, অ-ঋণাত্মক, আর breadth > 0")
    if not 1 <= gr["min_gap_days"] <= gr["max_gap_days"] or gr["smoothing_ads"] < 0 or gr["span"] <= 0 or not 0 < gr["new_share_neutral"] < 1:
        raise ConfigError("ads.growth: 1 <= min_gap_days <= max_gap_days, smoothing_ads >= 0, span > 0, 0 < new_share_neutral < 1 হতে হবে")
    if a["crowded_advertisers"] < 2 or a["crowded_ads"] < 2:
        raise ConfigError("ads.crowded_advertisers ও crowded_ads >= 2 হতে হবে")
    return cfg


def load_config(path: Path | None = None, override: dict | None = None) -> dict:
    cfg = DEFAULTS
    if path is not None:
        cfg = _merge(cfg, json.loads(Path(path).read_text(encoding="utf-8")))
    if override:
        cfg = _merge(cfg, override)
    return validate(copy.deepcopy(cfg))
