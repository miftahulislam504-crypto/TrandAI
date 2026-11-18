"""Groq API-র একাধিক key-র পুল: একটার সীমা শেষ হলে আরেকটায় যায়।

নিয়ম (আপনার চাওয়া অনুযায়ী): আগের key যতক্ষণ কাজ করে ততক্ষণ সেটাই ব্যবহার, সীমায় ঠেকলে পরেরটা, ঘুরিয়ে ঘুরিয়ে (round-robin) নয়।
- key-র নাম env থেকে: GROQ1, GROQ2, GROQ3... (বা GROQ_API_KEY_1.., বা একটা GROQ_API_KEY)। ক্রম সংখ্যা ধরে
- ৪২৯ (সীমা): `retry-after` বড় (> max_wait) হলে বা বার্তায় "per day" (TPD/RPD) থাকলে ওই key আজকের মতো শেষ।
  ছোট হলে (মিনিটের সীমা, TPM/RPM) ওই key কিছুক্ষণ বিশ্রামে, ততক্ষণ পরের key। সব key বিশ্রামে থাকলে সবচেয়ে কম অপেক্ষার টুকু ঘুমিয়ে আবার
- ৪০১/৪০৩: key ভুল বা বাতিল, রানের বাকি সময় বাদ
- ৫xx/নেটওয়ার্ক ত্রুটি: একই key-তে কয়েকবার, তারপর কিছুক্ষণ বিশ্রামে
- key কখনও লগ বা ত্রুটির বার্তায় আসে না (নাম "GROQ1" ইত্যাদি দেখায়)

গুরুত্বপূর্ণ: Groq-এর সীমা প্রতি অর্গানাইজেশনের (অ্যাকাউন্টের), প্রতি key-র নয়। একই অ্যাকাউন্টের দুই key মিলে ক্ষমতা বাড়ে না।
key আলাদা অ্যাকাউন্টের হলেই আলাদা সীমা। কয়েকটা ফ্রি অ্যাকাউন্ট Groq-এর শর্তে চলে কি না, আমি যাচাই করিনি, আপনি দেখে নিন।
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

API_URL = os.environ.get("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")   # env শুধু টেস্টের জন্য
_KEY_ENV = re.compile(r"^GROQ(?:_API_KEY)?_?(\d+)$")


class GroqError(Exception):
    pass


class NoKeys(GroqError):
    pass


class AllKeysExhausted(GroqError):
    pass


class ModelUnavailable(GroqError):
    pass


class RequestTooLarge(GroqError):
    pass


class BadRequest(GroqError):
    pass


def keys_from_env(env: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    """[(নাম, key)]। GROQ1/GROQ_API_KEY_1 ক্রম ধরে, তারপর GROQ_API_KEY। ফাঁকা বা একই মানের key বাদ।"""
    env = os.environ if env is None else env
    numbered = []
    for name, val in env.items():
        m = _KEY_ENV.match(name)
        if m and (val or "").strip():
            numbered.append((int(m.group(1)), name, val.strip()))
    numbered.sort()
    out, seen = [], set()
    for _, name, val in numbered:
        if val not in seen:
            seen.add(val)
            out.append((name, val))
    single = (env.get("GROQ_API_KEY") or "").strip()
    if single and single not in seen:
        out.append(("GROQ_API_KEY", single))
    return out


@dataclass
class KeyState:
    name: str
    key: str
    exhausted: bool = False
    invalid: bool = False
    cool_until: float = 0.0
    requests: int = 0
    tokens: int = 0
    rate_limited: int = 0
    why: str = ""


def _default_post(url, headers, payload, timeout):
    import requests
    return requests.post(url, headers=headers, json=payload, timeout=timeout)


class GroqPool:
    def __init__(self, keys: list[tuple[str, str]], post: Callable = _default_post, now: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, max_wait: float = 70.0, timeout: float = 60.0, transient_retries: int = 2):
        if not keys:
            raise NoKeys("কোনো Groq key নেই (env GROQ1, GROQ2... সেট করুন)")
        self.states = [KeyState(n, k) for n, k in keys]
        self._post, self._now, self._sleep = post, now, sleep
        self.max_wait, self.timeout, self.transient_retries = max_wait, timeout, transient_retries
        self.events: list[str] = []

    # ---------------------------------------------------------------- অবস্থা
    def usable(self) -> list[KeyState]:
        return [s for s in self.states if not s.exhausted and not s.invalid]

    def _scrub(self, text: str) -> str:
        for s in self.states:
            text = text.replace(s.key, s.name)
        return text[:300]

    def _note(self, msg: str) -> None:
        self.events.append(self._scrub(msg))

    # ---------------------------------------------------------------- ডাক
    def call(self, payload: dict) -> dict:
        """সফল হলে Groq-এর JSON উত্তর। সব key শেষ হলে AllKeysExhausted। মডেল নেই হলে ModelUnavailable।"""
        for _ in range(8 * len(self.states) + 12):
            usable = self.usable()
            if not usable:
                raise AllKeysExhausted("সব Groq key-র সীমা শেষ বা অচল")
            now = self._now()
            ready = [s for s in usable if s.cool_until <= now]
            if not ready:
                wait = min(s.cool_until for s in usable) - now
                if wait > self.max_wait:
                    raise AllKeysExhausted(f"সব key বিশ্রামে, অপেক্ষা {wait:.0f}s (> {self.max_wait:.0f}s)")
                self._sleep(wait + 0.5)
                continue
            st = ready[0]
            res = self._try(st, payload)
            if res is not None:
                return res
        raise GroqError("অনেকবার চেষ্টা করেও উত্তর পাওয়া গেল না")

    def _try(self, st: KeyState, payload: dict) -> Optional[dict]:
        """একটা key-তে একটা ডাক। সফল হলে উত্তর, নইলে None (key-র অবস্থা বদলে গেছে, ডাকটা আবার হবে)।"""
        headers = {"Authorization": f"Bearer {st.key}", "Content-Type": "application/json"}
        for attempt in range(self.transient_retries + 1):
            st.requests += 1
            try:
                r = self._post(API_URL, headers, payload, self.timeout)
            except Exception as e:  # নেটওয়ার্ক/টাইমআউট
                self._note(f"{st.name}: নেটওয়ার্ক ত্রুটি {type(e).__name__}")
                self._sleep(min(2 ** attempt, 5))
                continue
            status = r.status_code
            if status == 200:
                try:
                    data = r.json()
                except ValueError:
                    self._note(f"{st.name}: JSON নয় এমন উত্তর")
                    continue
                st.tokens += int(((data.get("usage") or {}).get("total_tokens")) or 0)
                return data
            msg = self._error_message(r)
            if status == 429:
                st.rate_limited += 1
                ra = self._retry_after(r)
                daily = re.search(r"per day|\bTPD\b|\bRPD\b", msg, re.I) is not None
                if daily or ra > self.max_wait:
                    st.exhausted, st.why = True, "আজকের সীমা শেষ" if daily else f"retry-after {ra:.0f}s"
                    self._note(f"{st.name}: {st.why}, পরের key-তে যাচ্ছি")
                else:
                    st.cool_until = self._now() + max(ra, 1.0) + 0.5
                    self._note(f"{st.name}: মিনিটের সীমা, {max(ra, 1.0):.0f}s বিশ্রাম")
                return None
            if status in (401, 403):
                st.invalid, st.why = True, f"HTTP {status}"
                self._note(f"{st.name}: key অচল (HTTP {status})")
                return None
            if status == 413:
                raise RequestTooLarge(msg)
            if status >= 500:
                self._note(f"{st.name}: HTTP {status}")
                self._sleep(min(2 ** attempt, 5))
                continue
            low = msg.lower()
            if status in (400, 404) and "model" in low and any(w in low for w in ("decommission", "not found", "does not exist", "not_found", "no longer")):
                raise ModelUnavailable(msg)
            raise BadRequest(f"HTTP {status}: {msg}")
        st.cool_until = self._now() + 30.0     # বারবার ব্যর্থ: ৩০s বিশ্রাম, ততক্ষণ পরের key
        self._note(f"{st.name}: বারবার ব্যর্থ, ৩০s বিশ্রাম")
        return None

    def _error_message(self, r) -> str:
        try:
            body = r.json()
            err = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict):
                return self._scrub(" ".join(str(err.get(k, "")) for k in ("code", "message")).strip())
        except Exception:
            pass
        return self._scrub(getattr(r, "text", "") or "")

    @staticmethod
    def _retry_after(r) -> float:
        h = getattr(r, "headers", {}) or {}
        v = h.get("retry-after") or h.get("Retry-After") or ""
        try:
            return float(v)
        except ValueError:
            return 0.0

    def usage(self) -> list[dict]:
        return [{"key": s.name, "requests": s.requests, "tokens": s.tokens, "rate_limited": s.rate_limited,
                 "state": "অচল" if s.invalid else ("শেষ" if s.exhausted else "চলছে"), "why": s.why} for s in self.states]
