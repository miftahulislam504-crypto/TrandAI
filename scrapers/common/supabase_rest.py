"""Supabase PostgREST-এর ছোট ক্লায়েন্ট (service_role key দিয়ে, RLS বাইপাস করে)।

supabase-py ছাড়াই শুধু requests দিয়ে: select / insert / upsert / update / rpc।
"""
from __future__ import annotations

import os
from collections import defaultdict

import requests


class SupabaseError(Exception):
    pass


class SupabaseREST:
    def __init__(self, url: str, service_key: str, session: requests.Session | None = None,
                 timeout: float = 40):
        self.base = url.rstrip("/") + "/rest/v1"
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        })

    @classmethod
    def from_env(cls) -> "SupabaseREST":
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise SupabaseError("SUPABASE_URL ও SUPABASE_SERVICE_KEY env দরকার")
        return cls(url, key)

    def _request(self, method: str, path: str, params=None, body=None, prefer: str | None = None):
        headers = {"Prefer": prefer} if prefer else {}
        r = self.session.request(method, f"{self.base}/{path}", params=params, json=body,
                                 headers=headers, timeout=self.timeout)
        if r.status_code >= 300:
            raise SupabaseError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        if not r.text:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    # ---- পড়া
    def select(self, table: str, params: dict | None = None, page_size: int = 1000) -> list[dict]:
        """সব সারি আনে (১০০০ করে পেজ করে)।"""
        out: list[dict] = []
        offset = 0
        while True:
            p = dict(params or {})
            p["limit"], p["offset"] = page_size, offset
            rows = self._request("GET", table, params=p) or []
            out.extend(rows)
            if len(rows) < page_size:
                return out
            offset += page_size

    # ---- লেখা
    def insert(self, table: str, rows: list[dict], returning: bool = False) -> list[dict]:
        if not rows:
            return []
        prefer = "return=representation" if returning else "return=minimal"
        return self._request("POST", table, body=rows, prefer=prefer) or []

    def upsert(self, table: str, rows: list[dict], on_conflict: str,
               returning: bool = False, chunk: int = 200) -> list[dict]:
        """একই key-সেটের সারি একসাথে পাঠায়, যাতে অনুপস্থিত কলাম ভুলে null না হয়ে যায়।"""
        if not rows:
            return []
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            groups[tuple(sorted(r.keys()))].append(r)
        prefer = "resolution=merge-duplicates," + ("return=representation" if returning else "return=minimal")
        out: list[dict] = []
        for batch_rows in groups.values():
            for i in range(0, len(batch_rows), chunk):
                res = self._request("POST", table, params={"on_conflict": on_conflict},
                                    body=batch_rows[i:i + chunk], prefer=prefer)
                if returning and res:
                    out.extend(res)
        return out

    def update(self, table: str, values: dict, params: dict) -> None:
        self._request("PATCH", table, params=params, body=values, prefer="return=minimal")

    def rpc(self, fn: str, args: dict | None = None):
        return self._request("POST", f"rpc/{fn}", body=args or {})
