"""Othoba (nopCommerce, Wolmart থিম) লিস্টিং-কার্ড পার্সার: বিশুদ্ধ ফাংশন, নেটওয়ার্ক ছাড়া।

যাচাই হয়েছে শুধু অডিটের হোমপেজ-নমুনার কার্ডে (২০২৬-১১-২৩)। ক্যাটাগরি লিস্টিং পেজের কার্ড-মার্কআপ ও পেজিনেশন
এখনও আসল পেজে দেখা হয়নি (দেখুন `scrapers/audit/adapter_probe.py`), তাই এটা এখনও কোনো রানে জোড়া নেই।
সোল্ড-কাউন্ট সাইটে নেই; রেটিং আছে তারার চওড়া (width:88% = ৪.৪/৫) ও \"(5 reviews)\" সংখ্যা।
"""
from __future__ import annotations

import re
from typing import Optional

BASE = "https://www.othoba.com"
_CARD_OPEN = re.compile(r'<div class="([^"]*)"')
_HREF = r'href=(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))'
_NAME = re.compile(r'<h4 class="?product-name"?>\s*<a ' + r'[^>]*?' + _HREF + r'[^>]*>(.*?)</a>', re.S)
_NEW = re.compile(r'<ins class="?new-price"?>(.*?)</ins>', re.S)
_OLD = re.compile(r'<del class="?old-price"?>(.*?)</del>', re.S)
_WIDTH = re.compile(r'class="?ratings"?\s+style="?width:\s*([\d.]+)%')
_REVIEWS = re.compile(r'\((\d+)\s*reviews?\)', re.I)
_IMG = re.compile(r'data-src="?(https?://[^\s">]+)')
_ID = (re.compile(r'productPrice_(\d+)'), re.compile(r'countdown_container_(\d+)'), re.compile(r'compareproducts/add/(\d+)'))
_BN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def money(text: Optional[str]) -> Optional[float]:
    """\"Tk 2,805\" / \"৳427.50\" → 2805.0 / 427.5; পাওয়া না গেলে None।"""
    if not text:
        return None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text.translate(_BN))
    return float(m.group(0).replace(",", "")) if m else None


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip().replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')


def _abs(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith(("http://", "https://")):
        return href
    return f"{BASE}/{href.lstrip('/')}"


def parse_cards(html: str) -> list[dict]:
    """পেজের সব পণ্য-কার্ড (class-এ `product` টোকেন থাকা div) → আইটেম-তালিকা; একই পণ্য একবার।"""
    starts = [m.start() for m in _CARD_OPEN.finditer(html) if "product" in m.group(1).split()]
    out, seen = [], set()
    for i, st in enumerate(starts):
        card = html[st: starts[i + 1] if i + 1 < len(starts) else len(html)]
        name = _NAME.search(card)
        if not name:
            continue                                   # product-media / action ইত্যাদি, নাম নেই
        href = name.group(1) or name.group(2) or name.group(3)
        title = _text(name.group(4))
        price = money(_NEW.search(card).group(1)) if _NEW.search(card) else None
        if not title or not href or price is None:
            continue                                   # দাম ছাড়া কার্ড (ব্যানার/স্টক-শেষ) নেয় না
        ext = next((m.group(1) for rx in _ID for m in [rx.search(card)] if m), None) or href.strip("/").split("/")[-1]
        if ext in seen:
            continue
        seen.add(ext)
        w = _WIDTH.search(card)
        rv = _REVIEWS.search(card)
        img = _IMG.search(card)
        old = money(_OLD.search(card).group(1)) if _OLD.search(card) else None
        out.append({
            "external_id": ext, "title": title, "url": _abs(href), "price": price,
            "original_price": old if old and old > price else None,
            "rating_avg": round(float(w.group(1)) / 20, 2) if w and float(w.group(1)) > 0 else None,
            "rating_count": int(rv.group(1)) if rv else None, "review_count": int(rv.group(1)) if rv else None,
            "sold_count": None, "seller_name": None, "brand": None, "in_stock": None,
            "image_url": img.group(1) if img else None, "category_ids": [],
        })
    return out
