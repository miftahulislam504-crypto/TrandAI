"""Google Trends সংগ্রহের স্তর: বদলযোগ্য ক্লায়েন্ট + ব্যাকঅফ + টানা ব্লকে থামা।

ক্লায়েন্টের চুক্তি (যেকোনো বাস্তবায়ন চলবে): interest(keywords, timeframe) -> {keyword: [(সপ্তাহ, মান, অসম্পূর্ণ_কি)]}
রেট-লিমিটে RateLimited, অন্য ব্যর্থতায় FetchFailed ছুঁড়তে হবে।

ডিফল্ট বাস্তবায়ন PytrendsClient। সতর্কতা: pytrends আর্কাইভ করা (শেষ রিলিজ 4.9.2, ২০২৩), Google প্রায়ই ৪২৯ দেয়,
বিশেষ করে GitHub Actions-এর মতো শেয়ার্ড IP থেকে। কাজ না করলে এই ফাইলে অন্য ক্লায়েন্ট (যেমন পরে অফিসিয়াল Trends API
alpha, বা ভাড়া নেওয়া সার্ভিস) বসানো যাবে, বাকি কোড বদলাতে হবে না।
"""
from __future__ import annotations

import random
import time
from datetime import date
from typing import Callable, Protocol

from .normalize import RawPoint


class FetchFailed(Exception):
    pass


class RateLimited(FetchFailed):
    pass


class CircuitOpen(FetchFailed):
    pass


class TrendsClient(Protocol):
    def interest(self, keywords: list[str], timeframe: str) -> dict[str, list[RawPoint]]: ...


class PytrendsClient:
    def __init__(self, geo: str = "BD", hl: str = "en-US", tz: int = 360, timeout=(10, 30)):
        try:
            from pytrends.request import TrendReq
        except Exception as e:  # noqa: BLE001
            raise FetchFailed(f"pytrends ইম্পোর্ট হয়নি: {e}") from e
        self.geo = geo
        try:
            # retries/backoff ইচ্ছে করে দেওয়া হয়নি: pytrends 4.9.2 নতুন urllib3-তে ভেঙে যায়, ব্যাকঅফ আমরা নিজে করি
            self._pt = TrendReq(hl=hl, tz=tz, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            raise self._wrap(e) from e

    @staticmethod
    def _wrap(e: Exception) -> FetchFailed:
        text = f"{type(e).__name__}: {e}"[:300]
        if type(e).__name__ == "TooManyRequestsError" or "429" in text:
            return RateLimited(text)
        return FetchFailed(text)

    def interest(self, keywords: list[str], timeframe: str) -> dict[str, list[RawPoint]]:
        try:
            self._pt.build_payload(keywords, timeframe=timeframe, geo=self.geo)
            df = self._pt.interest_over_time()
        except Exception as e:  # noqa: BLE001
            raise self._wrap(e) from e
        out: dict[str, list[RawPoint]] = {k: [] for k in keywords}
        if df is None or len(df) == 0:
            return out
        partial = df["isPartial"] if "isPartial" in df else None
        for i, ts in enumerate(df.index):
            day = ts.date() if hasattr(ts, "date") else ts
            is_partial = bool(partial.iloc[i]) if partial is not None else False
            for k in keywords:
                if k in df:
                    out[k].append((day, float(df[k].iloc[i]), is_partial))
        return out


class Fetcher:
    """রিকোয়েস্টের মাঝে বিরতি, ব্যর্থ হলে ব্যাকঅফসহ retry, টানা block_limit বার রেট-লিমিটে CircuitOpen।"""

    def __init__(self, client: TrendsClient, settings: dict,
                 sleep: Callable[[float], None] = time.sleep, rand: Callable[[], float] = random.random):
        self.client, self.s = client, settings
        self._sleep, self._rand = sleep, rand
        self._first = True
        self._consecutive_limits = 0
        self.stats = {"requests": 0, "ok": 0, "rate_limited": 0, "failed": 0}

    @property
    def circuit_open(self) -> bool:
        return self._consecutive_limits >= self.s["block_limit"]

    def _wait(self) -> None:
        if self._first:
            self._first = False
            return
        self._sleep(self.s["delay_seconds"] + self.s["jitter_seconds"] * self._rand())

    def get(self, keywords: list[str], timeframe: str) -> dict[str, list[RawPoint]]:
        if self.circuit_open:
            raise CircuitOpen(f"টানা {self._consecutive_limits}বার রেট-লিমিট, রান থামানো হয়েছে")
        last: Exception | None = None
        for attempt in range(self.s["max_retries"] + 1):
            self._wait()
            self.stats["requests"] += 1
            try:
                data = self.client.interest(keywords, timeframe)
            except RateLimited as e:
                last = e
                self.stats["rate_limited"] += 1
                self._consecutive_limits += 1
                if self.circuit_open:
                    raise CircuitOpen(f"টানা {self._consecutive_limits}বার রেট-লিমিট ({e}), রান থামানো হয়েছে") from e
                self._sleep(self.s["backoff_seconds"] * (2 ** attempt))
                continue
            except FetchFailed as e:
                last = e
                self.stats["failed"] += 1
                self._sleep(5 * (attempt + 1))
                continue
            self._consecutive_limits = 0
            self.stats["ok"] += 1
            return data
        raise FetchFailed(f"{keywords}: {last}")
