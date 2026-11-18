"""Daraz adapter: লিস্টিং ডিসকভারি, প্রোডাক্ট ডিটেইল, রিভিউ।

লিস্টিংয়ের ডেটা কোথা থেকে আসবে সেটা অডিটে যাচাই হয়নি, তাই কৌশল পরপর চেষ্টা হয়:
  "ajax": পেজ URL + ajax=true (JSON ফেরত দেওয়ার কথা)
  "html": সাধারণ পেজের HTML-এ এমবেডেড window.pageData
যেটা প্রথম আইটেম দেয় সেটাই বাকি পেজগুলোর জন্য ব্যবহার হয়। সব রিকোয়েস্ট PoliteClient দিয়ে,
অর্থাৎ robots.txt মানা হয় এবং ব্লক ধরা পড়লে রান নিজেই থামে।
"""
from __future__ import annotations

import os

from ..common.http import BlockedError, CircuitOpen, FetchError, PoliteClient, RobotsDisallowed
from . import parse

BASE = parse.BASE
REVIEWS_URL = os.environ.get("DARAZ_REVIEWS_URL", "https://my.daraz.com.bd/pdp/review/getReviewList")


class DarazAdapter:
    def __init__(self, client: PoliteClient, strategy_order=("ajax", "html"), sort: str | None = "popularity"):
        self.client = client
        self.strategy_order = list(strategy_order)
        self.sort = sort

    # ------------------------------------------------------------- লিস্টিং
    def _listing_target(self, seed: dict, page: int, ajax: bool) -> tuple[str, dict]:
        if seed.get("type") == "keyword":
            url, params = f"{BASE}/catalog/", {"q": seed["q"]}
        else:
            url, params = seed["url"].rstrip("/") + "/", {}
        if ajax:
            params["ajax"] = "true"
        params["page"] = page
        if self.sort:
            params["sort"] = self.sort
        return url, params

    def fetch_listing_page(self, seed: dict, page: int) -> dict:
        notes: list[str] = []
        for strategy in self.strategy_order:
            url, params = self._listing_target(seed, page, ajax=(strategy == "ajax"))
            try:
                if strategy == "ajax":
                    obj = self.client.get_json(url, params=params)
                else:
                    obj = parse.extract_page_data(self.client.get(url, params=params).text)
            except CircuitOpen:
                raise
            except RobotsDisallowed:
                notes.append(f"{strategy}: robots.txt নিষেধ করেছে")
                continue
            except BlockedError as e:
                notes.append(f"{strategy}: ব্লক ({e})")
                continue
            except FetchError as e:
                notes.append(f"{strategy}: ত্রুটি ({e})")
                continue
            raw_items = parse.find_listing_items(obj) if obj else []
            items = [i for i in (parse.parse_listing_item(r) for r in raw_items) if i]
            if items:
                return {"items": items, "meta": parse.listing_meta(obj), "strategy": strategy,
                        "notes": notes, "raw_keys": sorted(raw_items[0].keys())}
            notes.append(f"{strategy}: কোনো আইটেম পাওয়া যায়নি")
        return {"items": [], "meta": {}, "strategy": None, "notes": notes, "raw_keys": []}

    def discover(self, seed: dict, limit: int, max_pages: int = 10) -> tuple[list[dict], dict]:
        """একটা seed থেকে সর্বোচ্চ limit টা আইটেম। (items, diagnostics) ফেরত দেয়।"""
        seen: dict[str, dict] = {}
        diag = {"seed": seed, "pages": 0, "strategy": None, "notes": [], "raw_keys": [], "total_results": None}
        for page in range(1, max_pages + 1):
            res = self.fetch_listing_page(seed, page)
            diag["notes"] += [f"p{page} {n}" for n in res["notes"]]
            if not res["items"]:
                break
            diag["pages"] += 1
            if diag["strategy"] is None:
                diag["strategy"] = res["strategy"]
                diag["raw_keys"] = res["raw_keys"]
                diag["total_results"] = res["meta"].get("total_results")
                self.strategy_order = [res["strategy"]]  # সফল কৌশলেই থাকি
            new = 0
            for it in res["items"]:
                if it["external_id"] not in seen:
                    seen[it["external_id"]] = it
                    new += 1
            if len(seen) >= limit or new == 0:
                break
        return list(seen.values())[:limit], diag

    # ---------------------------------------------------------- প্রোডাক্ট ডিটেইল
    def fetch_product(self, url: str) -> dict:
        r = self.client.get(url)
        out = parse.parse_product_html(r.text)
        out["url"] = parse.normalize_url(url)
        out["external_id"] = parse.item_id_from_url(url)
        return out

    # ------------------------------------------------------------------ রিভিউ
    def fetch_reviews(self, external_id: str, page: int = 1, page_size: int = 20):
        obj = self.client.get_json(REVIEWS_URL, params={
            "itemId": external_id, "pageSize": page_size, "filter": 0, "sort": 0, "pageNo": page})
        return parse.parse_reviews_payload(obj)
