"""ভদ্র HTTP ক্লায়েন্ট।

- প্রতিটা রিকোয়েস্টের আগে বিরতি (delay + র‍্যান্ডম jitter)
- robots.txt অনুযায়ী নিষিদ্ধ URL ফেচ করে না (RobotsDisallowed)
- ব্লক/রেট-লিমিট ধরলে BlockedError; টানা block_limit বার হলে CircuitOpen
  (তখন বাকি সব রিকোয়েস্ট বন্ধ, সাইটকে চাপ না দিয়ে রান থেমে যায়)
- ৫xx ও নেটওয়ার্ক ত্রুটিতে সীমিত retry
"""
from __future__ import annotations

import random
import time
from typing import Callable

import requests

from .robots import UA_TOKEN, RobotsCache

DEFAULT_UA = f"Mozilla/5.0 (compatible; MarketResearchBot/0.1; personal market research; +{UA_TOKEN})"

# শক্ত ব্লক মার্কার (generic "captcha" ইচ্ছে করে বাদ: স্বাভাবিক পেজেও থাকতে পারে)
BLOCK_MARKERS = ("x5secdata", "_____tmd_____", "unusual traffic", "just a moment",
                 "slide to verify", "access denied")


class FetchError(Exception):
    pass


class RobotsDisallowed(FetchError):
    pass


class BlockedError(FetchError):
    pass


class CircuitOpen(FetchError):
    pass


def looks_blocked(status: int, text: str) -> bool:
    if status in (403, 429):
        return True
    head = text[:20_000].lower()
    return status == 200 and len(text) < 50_000 and any(m in head for m in BLOCK_MARKERS)


class PoliteClient:
    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        delay: float = 3.0,
        jitter: float = 1.5,
        timeout: float = 25,
        max_retries: int = 2,
        block_limit: int = 3,
        respect_robots: bool = True,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ):
        self.delay, self.jitter, self.timeout = delay, jitter, timeout
        self.max_retries, self.block_limit = max_retries, block_limit
        self._sleep, self._rand = sleep, rand
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
        })
        self._robots = RobotsCache(self._fetch_robots) if respect_robots else None
        self._first = True
        self.stats = {"requests": 0, "ok": 0, "blocked": 0, "robots_skipped": 0, "errors": 0}
        self._consecutive_blocks = 0

    # ---- ভেতরের সাহায্যকারী
    def _wait(self) -> None:
        if self._first:
            self._first = False
            return
        self._sleep(self.delay + self.jitter * self._rand())

    def _fetch_robots(self, url: str):
        self._wait()
        try:
            r = self.session.get(url, timeout=self.timeout)
        except requests.RequestException:
            return None, ""
        return r.status_code, r.text[:50_000] if r.status_code == 200 else ""

    @staticmethod
    def _full_url(url: str, params) -> str:
        return requests.Request("GET", url, params=params).prepare().url

    # ---- পাবলিক API
    @property
    def circuit_open(self) -> bool:
        return self._consecutive_blocks >= self.block_limit

    def get(self, url: str, params=None, headers=None) -> requests.Response:
        if self.circuit_open:
            raise CircuitOpen(f"টানা {self._consecutive_blocks}বার ব্লক, রান থামানো হয়েছে")
        full = self._full_url(url, params)
        if self._robots is not None and not self._robots.allowed(full):
            self.stats["robots_skipped"] += 1
            raise RobotsDisallowed(full)

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._wait()
            self.stats["requests"] += 1
            try:
                r = self.session.get(url, params=params, headers=headers,
                                     timeout=self.timeout, allow_redirects=True)
            except requests.RequestException as e:
                last_err = e
                self.stats["errors"] += 1
                self._sleep(2 ** attempt)
                continue
            if "charset" not in r.headers.get("Content-Type", "").lower():
                r.encoding = "utf-8"
            if looks_blocked(r.status_code, r.text):
                self.stats["blocked"] += 1
                self._consecutive_blocks += 1
                raise BlockedError(f"HTTP {r.status_code} ব্লক/রেট-লিমিট: {full}")
            if r.status_code >= 500:
                last_err = FetchError(f"HTTP {r.status_code}")
                self.stats["errors"] += 1
                self._sleep(2 ** attempt)
                continue
            self._consecutive_blocks = 0
            self.stats["ok"] += 1
            return r
        raise FetchError(f"{full}: {last_err}")

    def get_bytes(self, url: str, max_bytes: int = 3_000_000, headers=None) -> bytes:
        """বাইনারি (ছবি) ফেচ। একই বিরতি, robots ও ব্লক-সুরক্ষা। max_bytes-এর বড় হলে FetchError।
        টেক্সট ডিকোড বা ব্লক-মার্কার খোঁজা হয় না (ছবিতে অর্থহীন), শুধু HTTP স্ট্যাটাস দেখা হয়।"""
        if self.circuit_open:
            raise CircuitOpen(f"টানা {self._consecutive_blocks}বার ব্লক, রান থামানো হয়েছে")
        if self._robots is not None and not self._robots.allowed(url):
            self.stats["robots_skipped"] += 1
            raise RobotsDisallowed(url)
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._wait()
            self.stats["requests"] += 1
            try:
                r = self.session.get(url, headers={"Accept": "image/*,*/*;q=0.5", **(headers or {})},
                                     timeout=self.timeout, allow_redirects=True, stream=True)
                try:
                    status = r.status_code
                    if status in (403, 429):
                        self.stats["blocked"] += 1
                        self._consecutive_blocks += 1
                        raise BlockedError(f"HTTP {status} ব্লক/রেট-লিমিট: {url}")
                    if status >= 500:
                        last_err = FetchError(f"HTTP {status}")
                        self.stats["errors"] += 1
                        self._sleep(2 ** attempt)
                        continue
                    if status != 200:
                        raise FetchError(f"HTTP {status}: {url}")
                    body = b""
                    for chunk in r.iter_content(65536):
                        body += chunk
                        if len(body) > max_bytes:
                            raise FetchError(f"ছবি {max_bytes} বাইটের বড়: {url}")
                finally:
                    r.close()
            except requests.RequestException as e:
                last_err = e
                self.stats["errors"] += 1
                self._sleep(2 ** attempt)
                continue
            self._consecutive_blocks = 0
            self.stats["ok"] += 1
            return body
        raise FetchError(f"{url}: {last_err}")

    def get_json(self, url: str, params=None, headers=None):
        r = self.get(url, params=params, headers=headers)
        try:
            return r.json()
        except ValueError as e:
            raise FetchError(f"JSON নয়: {self._full_url(url, params)} ({e})") from e
