"""config/intel.json লোড ও যাচাই।"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = json.loads((ROOT / "config" / "intel.json").read_text(encoding="utf-8"))


class IntelConfigError(ValueError):
    pass


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: Path | None = None, override: dict | None = None) -> dict:
    cfg = DEFAULTS
    if path is not None:
        cfg = _merge(cfg, json.loads(Path(path).read_text(encoding="utf-8")))
    cfg = _merge(cfg, override or {})
    f = cfg["fake_reviews"]
    if f["dup_min_count"] < 2 or f["dup_long_count"] < 2 or f["dup_min_len"] < 5 or f["dup_long_len"] < f["dup_min_len"]:
        raise IntelConfigError("fake_reviews: dup_*_count >= 2, dup_min_len >= 5, dup_long_len >= dup_min_len হতে হবে")
    if f["burst_min"] < 3 or f["burst_ratio"] < 1 or f["burst_min_days"] < 2 or f["repeat_reviewer_min"] < 2:
        raise IntelConfigError("fake_reviews: burst_min >= 3, burst_ratio >= 1, burst_min_days >= 2, repeat_reviewer_min >= 2 হতে হবে")
    sn = cfg["sentiment"]
    if not sn["models"] or any(not isinstance(m, str) or not m for m in sn["models"]):
        raise IntelConfigError("sentiment.models-এ অন্তত একটা মডেল নাম লাগবে")
    if not 1 <= sn["batch_size"] <= 40 or sn["max_chars_per_review"] < 50 or sn["max_output_tokens"] < 200:
        raise IntelConfigError("sentiment: batch_size 1..40, max_chars_per_review >= 50, max_output_tokens >= 200 হতে হবে")
    if sn["max_reviews_per_run"] < 1 or sn["max_requests_per_run"] < 1 or sn["max_wait_seconds"] < 1 or not sn["topics"]:
        raise IntelConfigError("sentiment: max_*_per_run >= 1, max_wait_seconds >= 1 এবং topics ফাঁকা নয় হতে হবে")
    return cfg
