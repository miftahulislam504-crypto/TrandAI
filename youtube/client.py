"""YouTube Data API v3-এর ছোট ক্লায়েন্ট (অফিসিয়াল API, শুধু requests)।

নিয়ম: key URL-এর query-তে যায়, তাই ত্রুটির বার্তায় কখনো URL বা মূল exception আসে না (key ফাঁস ঠেকাতে)।
খরচ (কোটা): search.list ১০০ ইউনিট, videos.list ১ ইউনিট। বিনামূল্যে সীমা দিনে ১০,০০০ ইউনিট।
"""
from __future__ import annotations

import time
from typing import Callable

import requests

API = "https://www.googleapis.com/youtube/v3"
_QUOTA = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"}
_KEY = {"keyInvalid", "API_KEY_INVALID", "accessNotConfigured", "ipRefererBlocked", "forbidden", "badRequest"}


class YouTubeError(Exception):
    pass


class QuotaExceeded(YouTubeError):
    """দৈনিক কোটা শেষ: রান থামাতে হবে, আজ আর চেষ্টা বৃথা।"""


class KeyRejected(YouTubeError):
    """key ভুল, বন্ধ, বা API চালু নেই: রান থামাতে হবে।"""


def _reason(r: requests.Response) -> str:
    try:
        errs = (r.json().get("error") or {}).get("errors") or []
        return str(errs[0].get("reason", "")) if errs else ""
    except (ValueError, AttributeError, IndexError):
        return ""


class YouTubeClient:
    def __init__(self, api_key: str, session: requests.Session | None = None, timeout: float = 20,
                 retries: int = 2, sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise KeyRejected("YOUTUBE_API_KEY ফাঁকা")
        self._key = api_key
        self.session = session or requests.Session()
        self.timeout, self.retries, self.sleep = timeout, retries, sleep

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(self.retries + 1):
            try:
                r = self.session.get(f"{API}/{path}", params={**params, "key": self._key}, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt < self.retries:
                    self.sleep(2 ** attempt)
                    continue
                raise YouTubeError(f"নেটওয়ার্ক ত্রুটি ({type(e).__name__})") from None  # মূল বার্তায় URL (key সহ) থাকে
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    raise YouTubeError("উত্তর JSON নয়") from None
            reason = _reason(r)
            if r.status_code in (400, 401, 403) and reason in _QUOTA:
                raise QuotaExceeded(f"দৈনিক কোটা শেষ ({reason})")
            if r.status_code in (400, 401, 403) and (reason in _KEY or r.status_code == 401):
                raise KeyRejected(f"key গ্রহণ হয়নি বা YouTube Data API v3 চালু নেই (HTTP {r.status_code}, {reason or 'কারণ নেই'})")
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                self.sleep(2 ** attempt)
                continue
            raise YouTubeError(f"HTTP {r.status_code} {reason}".strip())
        raise YouTubeError("অজানা ত্রুটি")  # পৌঁছানোর কথা নয়

    def search(self, q: str, published_after: str, region: str, max_results: int,
               lang: str | None = None, order: str = "viewCount") -> list[str]:
        """শব্দে গত-সময়ের ভিডিও-আইডি (published_after RFC 3339, যেমন 2026-10-23T00:00:00Z)। খরচ ১০০ ইউনিট।"""
        params = {"part": "snippet", "type": "video", "q": q, "regionCode": region,
                  "publishedAfter": published_after, "maxResults": max(1, min(int(max_results), 50)), "order": order}
        if lang:
            params["relevanceLanguage"] = lang
        data = self._get("search", params)
        return [it["id"]["videoId"] for it in data.get("items", []) if isinstance(it.get("id"), dict) and it["id"].get("videoId")]

    def videos(self, ids: list[str]) -> list[dict]:
        """ভিডিওর শিরোনাম, চ্যানেল, ভিউ (লুকানো থাকলে views = None)। খরচ ১ ইউনিট (একসাথে ≤ ৫০)।"""
        if not ids:
            return []
        data = self._get("videos", {"part": "snippet,statistics", "id": ",".join(ids[:50]), "maxResults": 50})
        out = []
        for it in data.get("items", []):
            sn, st = it.get("snippet") or {}, it.get("statistics") or {}
            vc = st.get("viewCount")
            out.append({"id": it.get("id"), "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                        "published_at": sn.get("publishedAt"), "views": int(vc) if str(vc).isdigit() else None})
        return out
