"""Bagdoom (Active eCommerce CMS) হোমপেজ-কার্ড পার্সার: বিশুদ্ধ ফাংশন, নেটওয়ার্ক ছাড়া।

যাচাই হয়েছে শুধু অডিটের হোমপেজ-নমুনার কার্ডে (২০২৬-১১-২৩)। ক্যাটাগরি লিস্টিং পেজের কার্ড আলাদা হতে পারে (আমি দেখিনি;
`scrapers/audit/adapter_probe.py` দেখাবে), তাই এটা এখনও কোনো রানে জোড়া নেই। হোমপেজের কার্ডে রেটিং/সোল্ড নেই।
"""
from __future__ import annotations

import re
from typing import Optional

from scrapers.othoba.parse import money

BASE = "https://www.bagdoom.com"
_NAME = re.compile(r'<a class="[^"]*text-truncate-2[^"]*"\s+href="(https?://[^"]*?/product/([^"/?#]+))"[^>]*>(.*?)</a>', re.S)
_PRICE = re.compile(r"<!-- Price -->\s*<div[^>]*>(.*?)</div>", re.S)
_SPAN = re.compile(r"<span[^>]*>(.*?)</span>", re.S)
_DEL = re.compile(r"<del[^>]*>(.*?)</del>", re.S)
_IMG = re.compile(r'<img[^>]*product-main-image[^>]*data-src="(https?://[^"]+)"')


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip().replace("&amp;", "&")


def parse_cards(html: str) -> list[dict]:
    out, seen = [], set()
    for m in _NAME.finditer(html):
        url, slug, title = m.group(1), m.group(2), _text(m.group(3))
        if slug in seen or not title:
            continue
        tail = html[m.end(): m.end() + 900]
        pm = _PRICE.search(tail)
        span = _SPAN.search(pm.group(1)) if pm else None
        price: Optional[float] = money(span.group(1)) if span else None
        if price is None:
            continue
        seen.add(slug)
        old = money(_DEL.search(pm.group(1)).group(1)) if _DEL.search(pm.group(1)) else None
        imgs = _IMG.findall(html[max(0, m.start() - 2600): m.start()])
        out.append({
            "external_id": slug, "title": title, "url": url, "price": price,
            "original_price": old if old and old > price else None,
            "rating_avg": None, "rating_count": None, "review_count": None, "sold_count": None,
            "seller_name": None, "brand": None, "in_stock": None,
            "image_url": imgs[-1] if imgs else None, "category_ids": [],
        })
    return out
