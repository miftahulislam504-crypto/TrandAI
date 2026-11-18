"""config/backtest.json লোড ও যাচাই।"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BacktestConfigError(ValueError):
    pass


def _chk(cond: bool, msg: str) -> None:
    if not cond:
        raise BacktestConfigError(msg)


def _isnum(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(cfg: dict) -> dict:
    for k, lo, hi in (("horizon_days", 3, 90), ("step_days", 1, 60), ("snapshot_tolerance_days", 0, 14),
                      ("min_samples", 10, 100000), ("min_products", 5, 100000), ("min_distinct_dates", 2, 100),
                      ("min_category_samples", 5, 100000)):
        _chk(isinstance(cfg.get(k), int) and not isinstance(cfg[k], bool) and lo <= cfg[k] <= hi,
             f"{k} {lo}–{hi}-এর মধ্যে পূর্ণসংখ্যা হতে হবে")
    _chk(_isnum(cfg.get("sustain_ratio")) and 0 < cfg["sustain_ratio"] <= 1.5, "sustain_ratio 0–1.5-এর মধ্যে হতে হবে")
    th = cfg.get("thresholds")
    _chk(isinstance(th, list) and th and all(_isnum(x) and 0 <= x <= 100 for x in th), "thresholds ০–১০০-এর সংখ্যার তালিকা হতে হবে")
    t = cfg.get("tune", {})
    _chk(isinstance(t.get("step"), int) and 1 <= t["step"] <= 25 and 100 % t["step"] == 0, "tune.step ১–২৫ এবং ১০০-র ভাজক হতে হবে")
    _chk(isinstance(t.get("weight_min"), int) and isinstance(t.get("weight_max"), int)
         and 0 <= t["weight_min"] <= t["weight_max"] <= 100, "tune.weight_min/max ০–১০০, min <= max হতে হবে")
    _chk(4 * t["weight_min"] <= 100 <= 4 * t["weight_max"], "tune.weight_min×৪ <= ১০০ <= weight_max×৪ হতে হবে, নইলে কোনো সমাধান নেই")
    _chk(_isnum(t.get("test_share")) and 0.1 <= t["test_share"] <= 0.6, "tune.test_share ০.১–০.৬ হতে হবে")
    _chk(_isnum(t.get("min_gain")) and 0 <= t["min_gain"] <= 1, "tune.min_gain ০–১ হতে হবে")
    return cfg


def load_config(path: Path | None = None) -> dict:
    p = Path(path) if path else ROOT / "config" / "backtest.json"
    return validate(json.loads(p.read_text(encoding="utf-8")))
