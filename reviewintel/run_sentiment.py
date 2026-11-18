#!/usr/bin/env python3
"""রিভিউয়ের সেন্টিমেন্ট (-১/০/+১) ও টপিক Groq দিয়ে বের করে `reviews.sentiment` ও `reviews.topics`-এ লেখে।
রিপো রুট থেকে: python -m reviewintel.run_sentiment [--dry-run] [--limit N]

- শুধু যেসব রিভিউয়ের sentiment ফাঁকা এবং suspected_fake নয় (টোকেন বাঁচাতে), নতুনগুলো আগে
- একটা key-র সীমা শেষ হলে পরেরটা (reviewintel/groq_pool.py), সব শেষ হলে যতটুকু হয়েছে রেখে থামে, পরের রানে বাকিটা
- মডেল নাম বন্ধ হয়ে গেলে config-এর পরের মডেল। এই ধাপ ব্যর্থ হলেও স্কোরিং চলে, আর স্কোর এই ফলে বদলায় না (শুধু কারণে "বেশি অভিযোগ" ও ড্যাশবোর্ডে)
- রিভিউয়ের টেক্সট (প্রকাশ্য রিভিউ, রিভিউয়ারের নাম ছাড়া) Groq-এ যায়

env: SUPABASE_URL, SUPABASE_SERVICE_KEY, GROQ1, GROQ2, GROQ3... (বা GROQ_API_KEY_1..)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from scrapers.common.supabase_rest import SupabaseREST

from .config import load_config
from .groq_pool import (AllKeysExhausted, BadRequest, GroqError, GroqPool, ModelUnavailable, NoKeys, RequestTooLarge,
                        keys_from_env)

OUT_DIR = Path(os.environ.get("RUN_OUT", "run-output"))
CHUNK = 150

SYSTEM = """You classify e-commerce product reviews from Bangladesh. Reviews are written in Bangla, English or Banglish (Bangla in Latin letters).
Judge the review text; the star rating is only a hint and can be wrong.
For each review return:
- s: sentiment. -1 = negative (complaint, disappointment, warning others), 0 = neutral, mixed or unclear, 1 = positive.
- t: topics the review clearly expresses an opinion about, at most 3, only from this list: {topics}.
  quality = product quality or performance; price = value for money; delivery = shipping speed or courier; packaging = packing or damage in transit;
  size_fit = size, fit or dimensions; color = color or appearance; durability = lasts or breaks; authenticity = original, fake or copy claims;
  service = seller or support behaviour; description_match = matches photos or description.
Use an empty list when no topic is clear.
Respond with ONLY a JSON object: {{"results":[{{"i":0,"s":1,"t":["quality"]}}]}} with exactly one entry per review, using the same i as in the input."""


class SentimentError(Exception):
    pass


def fetch_pending(db, cfg: dict) -> list[dict]:
    sn = cfg["sentiment"]
    rows = db.select("reviews", {"select": "id,stars,body", "sentiment": "is.null", "suspected_fake": "eq.false",
                                 "body": "not.is.null", "order": "id.desc"})
    rows = [r for r in rows if len((r["body"] or "").strip()) >= sn["min_chars"]]
    return rows[: sn["max_reviews_per_run"]]


def build_messages(batch: list[dict], cfg: dict) -> list[dict]:
    sn = cfg["sentiment"]
    items = [{"i": i, "stars": r.get("stars"), "text": (r["body"] or "").strip()[: sn["max_chars_per_review"]]} for i, r in enumerate(batch)]
    return [{"role": "system", "content": SYSTEM.format(topics=", ".join(sn["topics"]))},
            {"role": "user", "content": "Reviews (JSON):\n" + json.dumps(items, ensure_ascii=False)}]


def parse_results(content: str, n: int, topics: list[str]) -> dict[int, tuple[int, tuple[str, ...]]]:
    """মডেলের লেখা থেকে {index: (sentiment, topics)}। অবৈধ সারি বাদ (পরের রানে আবার হবে), অচেনা টপিক বাদ।"""
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise SentimentError("JSON পাওয়া যায়নি")
        try:
            data = json.loads(m.group(0))
        except ValueError as e:
            raise SentimentError("JSON ভাঙা") from e
    rows = data.get("results") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise SentimentError("results তালিকা নেই")
    allowed = set(topics)
    out: dict[int, tuple[int, tuple[str, ...]]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        i, s = r.get("i"), r.get("s")
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < n or i in out:
            continue
        if isinstance(s, bool) or s not in (-1, 0, 1):
            continue
        t = r.get("t") or []
        t = [x for x in dict.fromkeys(t if isinstance(t, list) else []) if isinstance(x, str) and x in allowed][:3]
        out[i] = (int(s), tuple(sorted(t)))
    return out


class Runner:
    def __init__(self, db, pool: GroqPool, cfg: dict, dry_run: bool = False, clock: Callable[[], float] = time.monotonic):
        self.db, self.pool, self.cfg, self.dry_run, self.clock = db, pool, cfg, dry_run, clock
        sn = cfg["sentiment"]
        self.models = list(sn["models"])
        self.use_extras = True
        self.requests = 0
        self.started = self.clock()
        self.stop: Optional[str] = None
        self.model_used: Counter = Counter()
        self.failed_batches = 0
        self.results: dict[int, tuple[int, tuple[str, ...], dict]] = {}

    # ---- একটা ব্যাচ
    def _payload(self, model: str, batch: list[dict]) -> dict:
        sn = self.cfg["sentiment"]
        p = {"model": model, "messages": build_messages(batch, self.cfg), "temperature": 0,
             "max_completion_tokens": sn["max_output_tokens"], "response_format": {"type": "json_object"}}
        if self.use_extras and sn.get("reasoning_effort") and model.startswith("openai/gpt-oss"):
            p["reasoning_effort"] = sn["reasoning_effort"]
        return p

    def _limits_hit(self) -> Optional[str]:
        sn = self.cfg["sentiment"]
        if self.requests >= sn["max_requests_per_run"]:
            return "request_cap"
        if self.clock() - self.started > sn["max_runtime_seconds"]:
            return "time"
        return None

    def classify(self, batch: list[dict]) -> dict[int, tuple[int, tuple[str, ...]]]:
        """ব্যাচ -> {index: (s, topics)}। ব্যর্থ হলে ব্যাচ আধা করে চেষ্টা। থামার কারণ হলে self.stop বসে ও খালি ফেরত।"""
        if self.stop or not batch:
            return {}
        why = self._limits_hit()
        if why:
            self.stop = why
            return {}
        while self.models:
            self.requests += 1
            try:
                resp = self.pool.call(self._payload(self.models[0], batch))
            except AllKeysExhausted:
                self.stop = "keys_exhausted"
                return {}
            except NoKeys:
                self.stop = "no_keys"
                return {}
            except ModelUnavailable:
                self.pool._note(f"মডেল {self.models[0]} পাওয়া যায়নি, পরেরটা")
                self.models.pop(0)
                continue
            except RequestTooLarge:
                return self._split(batch)
            except BadRequest as e:
                if self.use_extras and "reasoning" in str(e).lower():
                    self.use_extras = False        # এই মডেল reasoning_effort নেয় না: ছাড়া চেষ্টা
                    continue
                self.pool._note(f"BadRequest: {str(e)[:120]}")
                return self._split(batch)
            except GroqError as e:
                self.pool._note(f"GroqError: {str(e)[:120]}")
                self.failed_batches += 1
                return {}
            try:
                content = resp["choices"][0]["message"]["content"]
                parsed = parse_results(content, len(batch), self.cfg["sentiment"]["topics"])
            except (KeyError, IndexError, TypeError, SentimentError) as e:
                self.pool._note(f"উত্তর পড়া গেল না ({type(e).__name__}), ব্যাচ আধা করছি")
                return self._split(batch)
            self.model_used[self.models[0]] += 1
            return parsed
        self.stop = "no_model"
        return {}

    def _split(self, batch: list[dict]) -> dict[int, tuple[int, tuple[str, ...]]]:
        if len(batch) == 1:
            self.failed_batches += 1
            return {}
        mid = len(batch) // 2
        out: dict[int, tuple[int, tuple[str, ...]]] = {}
        for off, part in ((0, batch[:mid]), (mid, batch[mid:])):
            for i, v in self.classify(part).items():
                out[off + i] = v
        return out

    # ---- পুরো রান
    def run(self, rows: list[dict]) -> None:
        size = self.cfg["sentiment"]["batch_size"]
        for i in range(0, len(rows), size):
            batch = rows[i:i + size]
            got = self.classify(batch)
            for idx, (s, t) in got.items():
                self.results[batch[idx]["id"]] = (s, t, batch[idx])
            if got and not self.dry_run:
                self._write({batch[idx]["id"]: v for idx, v in got.items()})
            if self.stop:
                break

    def _write(self, got: dict[int, tuple[int, tuple[str, ...]]]) -> None:
        groups: dict[tuple, list[int]] = defaultdict(list)
        for rid, (s, t) in got.items():
            groups[(s, t)].append(rid)
        for (s, t), ids in groups.items():
            for j in range(0, len(ids), CHUNK):
                part = ids[j:j + CHUNK]
                self.db.update("reviews", {"sentiment": s, "topics": list(t)}, {"id": "in.(" + ",".join(str(x) for x in part) + ")"})


def summarize(runner: Runner, pending: int, dry_run: bool) -> dict:
    res = runner.results
    sent = Counter(s for s, _, _ in res.values())
    topics = Counter(t for _, ts, _ in res.values() for t in ts)
    mismatch = sum(1 for s, _, r in res.values() if (r.get("stars") or 0) >= 4 and s == -1 or (r.get("stars") or 9) <= 2 and s == 1)
    sample = [{"id": rid, "stars": r.get("stars"), "s": s, "t": list(t), "text": (r["body"] or "").strip()[:110]}
              for rid, (s, t, r) in list(res.items())[:8]]
    return {"date": date.today().isoformat(), "dry_run": dry_run, "pending": pending, "classified": len(res),
            "sentiment": {"neg": sent.get(-1, 0), "neutral": sent.get(0, 0), "pos": sent.get(1, 0)}, "topics": dict(topics),
            "star_text_mismatch": mismatch, "requests": runner.requests, "failed_batches": runner.failed_batches,
            "stop": runner.stop or "done", "models": dict(runner.model_used), "keys": runner.pool.usage(),
            "events": runner.pool.events[-12:], "sample": sample}


STOP_TEXT = {"done": "শেষ", "keys_exhausted": "সব key-র সীমা শেষ (বাকিটা পরের রানে)", "time": "সময়সীমা শেষ (বাকিটা পরের রানে)",
             "request_cap": "রান প্রতি অনুরোধের সীমা (বাকিটা পরের রানে)", "no_model": "কোনো মডেল পাওয়া গেল না, config/intel.json-এর models দেখুন",
             "no_keys": "কোনো Groq key নেই"}


def summary_markdown(s: dict) -> str:
    sn = s["sentiment"]
    L = [f"# রিভিউ সেন্টিমেন্ট ({s['date']}{', dry-run' if s['dry_run'] else ''})", "",
         f"- বাকি ছিল: {s['pending']}, এবার হয়েছে: {s['classified']} (নেগেটিভ {sn['neg']}, নিরপেক্ষ {sn['neutral']}, পজিটিভ {sn['pos']})",
         f"- থামার কারণ: {STOP_TEXT.get(s['stop'], s['stop'])}; অনুরোধ {s['requests']}, ব্যর্থ ব্যাচ {s['failed_batches']}",
         f"- তারকা ও লেখা উল্টো (৪-৫★ অথচ নেগেটিভ, বা ১-২★ অথচ পজিটিভ): {s['star_text_mismatch']}"]
    if s["models"]:
        L.append("- মডেল: " + ", ".join(f"{k} ×{v}" for k, v in s["models"].items()))
    if s["topics"]:
        L.append("- টপিক: " + ", ".join(f"{k} {v}" for k, v in sorted(s["topics"].items(), key=lambda x: -x[1])))
    L += ["", "## key-ভিত্তিক ব্যবহার", ""] + [f"- {k['key']}: {k['state']}, অনুরোধ {k['requests']}, টোকেন {k['tokens']}, ৪২৯ {k['rate_limited']}" + (f" ({k['why']})" if k["why"] else "") for k in s["keys"]]
    if s["events"]:
        L += ["", "## ঘটনা", ""] + [f"- {e}" for e in s["events"]]
    if s["sample"]:
        L += ["", "## নমুনা (ভুল হলে জানান)", ""] + [f"- #{x['id']} {x['stars']}★ → {x['s']:+d} {x['t']} {x['text']}" for x in s["sample"]]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Groq-কে ডাকে, কিন্তু ডাটাবেজে লেখে না")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(Path(args.config) if args.config else None)
    sn = cfg["sentiment"]
    if args.limit:
        sn["max_reviews_per_run"] = args.limit
    if not sn["enabled"]:
        print("sentiment.enabled = false, কিছু করার নেই")
        return 0
    keys = keys_from_env()
    if not keys:
        print("কোনো Groq key নেই (env GROQ1, GROQ2, GROQ3 সেট করুন), এই ধাপ বাদ।")
        return 0
    dry = args.dry_run or os.environ.get("DRY_RUN") == "true"
    db = SupabaseREST.from_env()
    pool = GroqPool(keys, max_wait=sn["max_wait_seconds"], timeout=sn["request_timeout_seconds"])
    pending_rows = fetch_pending(db, cfg)
    runner = Runner(db, pool, cfg, dry_run=dry)
    runner.run(pending_rows)
    s = summarize(runner, len(pending_rows), dry)
    md = summary_markdown(s)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "review-sentiment.md").write_text(md, encoding="utf-8")
    (OUT_DIR / "review-sentiment.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
