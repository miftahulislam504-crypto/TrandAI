"""Daraz ডেটার পার্সিং, শুধু pure ফাংশন (নেটওয়ার্ক ছাড়া), তাই সহজে টেস্ট করা যায়।

গুরুত্বপূর্ণ: Daraz-এর আসল JSON/HTML গঠন Phase 0 অডিটে যাচাই হয়নি। তাই প্রতিটা ফিল্ডের জন্য
একাধিক সম্ভাব্য key দেখা হয় (KEYS) এবং কোন ফিল্ড কীভাবে পাওয়া গেল তা `found_by`-এ লেখা হয়।
আসল রেসপন্সে key আলাদা হলে শুধু KEYS তালিকা বদলালেই চলবে।
"""
from __future__ import annotations

import hashlib
import html as htmllib
import json
import os
import re
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

BASE = os.environ.get("DARAZ_BASE_URL", "https://www.daraz.com.bd")  # env শুধু টেস্টের জন্য
BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# প্রতিটা ফিল্ডের সম্ভাব্য key, অগ্রাধিকার অনুযায়ী
KEYS = {
    "id": ["itemId", "nid", "item_id", "productId", "id"],
    "url": ["itemUrl", "productUrl", "detailUrl", "url"],
    "title": ["name", "title", "productTitle"],
    "price": ["price", "priceShow", "salePrice"],
    "original_price": ["originalPrice", "originalPriceShow", "marketPrice"],
    "rating": ["ratingScore", "averageRating", "avgRating", "rating"],
    "review_count": ["review", "reviews", "reviewCount", "ratingCount"],
    "sold": ["itemSoldCntShow", "soldCount", "soldCnt", "sold"],
    "seller": ["sellerName", "shopName", "storeName"],
    "brand": ["brandName", "brand"],
    "in_stock": ["inStock", "isInStock"],
    "image": ["image", "imageUrl", "img", "thumbnail", "pic", "mainImage"],
}
RATING_KEYS = ["ratingScore", "averageRating", "avgRating", "ratingValue"]
RATING_COUNT_KEYS = ["ratingCount", "rateCount", "reviewCount", "totalRating"]
SOLD_KEYS = ["itemSoldCntShow", "soldCount", "soldCnt", "soldQuantity"]


# ----------------------------------------------------------------- সংখ্যা/URL
def _clean(s) -> str:
    return str(s).translate(BN_DIGITS).replace(",", "").strip()


def parse_price(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d+(?:\.\d+)?", _clean(v))
    return float(m.group(0)) if m else None


def parse_count(v) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"\d+", _clean(v))
    return int(m.group(0)) if m else None


def parse_sold(v) -> int | None:
    """"1.2K sold" -> 1200, "10 sold" -> 10, "২ হাজার" নয় (শুধু K/M), "১২ বিক্রি" -> 12।"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"(\d+(?:\.\d+)?)\s*([KkMm])?", _clean(v))
    if not m:
        return None
    n = float(m.group(1))
    mult = {"k": 1_000, "m": 1_000_000}.get((m.group(2) or "").lower(), 1)
    return int(round(n * mult))


def parse_rating(v) -> float | None:
    f = parse_price(v)
    return round(f, 3) if f is not None and 0 <= f <= 5 else None


def normalize_url(u) -> str | None:
    if not u or not isinstance(u, str):
        return None
    full = urljoin(BASE + "/", "https:" + u if u.startswith("//") else u)
    p = urlparse(full)
    return f"{p.scheme}://{p.netloc}{p.path}"  # query/fragment বাদ


def item_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"-i(\d+)(?:-s\d+)?\.html", url)
    return m.group(1) if m else None


def normalize_image_url(v) -> str | None:
    """ছবির URL পরিষ্কার: `//cdn/...` -> https, শুধু http(s), তালিকা হলে প্রথমটা, query রাখা হয় (সাইজ/ফরম্যাট সেখানে থাকতে পারে)।"""
    if isinstance(v, (list, tuple)):
        v = next((x for x in v if x), None)
    if isinstance(v, dict):
        v = first_present(v, ["url", "src", "image"])
    if not v or not isinstance(v, str):
        return None
    v = v.strip()
    if v.startswith("//"):
        v = "https:" + v
    if not v.lower().startswith(("http://", "https://")) or len(v) > 1000:
        return None
    return v


def first_present(d: dict, keys: list[str]):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


# --------------------------------------------------------------------- লিস্টিং
def parse_listing_item(raw: dict) -> dict | None:
    """একটা listing আইটেম (raw dict) -> সাধারণ ফরম্যাট। id না পেলে None।"""
    url = normalize_url(first_present(raw, KEYS["url"]))
    ext = first_present(raw, KEYS["id"])
    ext = str(ext) if ext is not None else item_id_from_url(url)
    if not ext:
        return None
    price = parse_price(raw.get("price"))
    if price is None:
        price = parse_price(first_present(raw, KEYS["price"]))
    count = parse_count(first_present(raw, KEYS["review_count"]))
    in_stock = first_present(raw, KEYS["in_stock"])
    cats = raw.get("categories")
    return {
        "external_id": ext,
        "url": url,
        "title": first_present(raw, KEYS["title"]),
        "price": price,
        "original_price": parse_price(first_present(raw, KEYS["original_price"])),
        "rating_avg": parse_rating(first_present(raw, KEYS["rating"])),
        "rating_count": count,
        "review_count": count,
        "sold_count": parse_sold(first_present(raw, KEYS["sold"])),
        "seller_name": first_present(raw, KEYS["seller"]),
        "brand": first_present(raw, KEYS["brand"]),
        "in_stock": in_stock if isinstance(in_stock, bool) else None,
        "category_ids": cats if isinstance(cats, list) else None,
        "image_url": normalize_image_url(first_present(raw, KEYS["image"]) or raw.get("thumbs")),
    }


def _find_dict_lists(obj, pred, path="$", depth=0):
    if depth > 8:
        return
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj[:3]) and pred(obj[0]):
            yield path, obj
        else:
            for i, x in enumerate(obj[:3]):
                yield from _find_dict_lists(x, pred, f"{path}[{i}]", depth + 1)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _find_dict_lists(v, pred, f"{path}.{k}", depth + 1)


def find_listing_items(obj) -> list[dict]:
    """JSON থেকে আইটেমের তালিকা: আগে mods.listItems, না পেলে id-জাতীয় key-ওয়ালা প্রথম list।"""
    if isinstance(obj, dict):
        items = (obj.get("mods") or {}).get("listItems")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    for _, lst in _find_dict_lists(obj, lambda d: any(k in d for k in ("itemId", "nid"))):
        return lst
    return []


def listing_meta(obj) -> dict:
    info = (obj.get("mainInfo") or {}) if isinstance(obj, dict) else {}
    return {"total_results": parse_count(info.get("totalResults")),
            "page_size": parse_count(info.get("pageSize"))}


def extract_json_after(text: str, marker: str):
    """text-এ `marker =` এর পরের প্রথম JSON মান পার্স করে (JSON-সুসংগত হলে)। না পেলে None।"""
    for m in re.finditer(re.escape(marker) + r"\s*=\s*", text):
        i = m.end()
        while i < len(text) and text[i] not in "{[":
            if not text[i].isspace():
                break
            i += 1
        if i < len(text) and text[i] in "{[":
            try:
                obj, _ = json.JSONDecoder().raw_decode(text, i)
                return obj
            except ValueError:
                continue
    return None


def extract_page_data(html: str):
    for marker in ("window.pageData", "__moduleData__", "window.__INITIAL_STATE__"):
        obj = extract_json_after(html, marker)
        if obj:
            return obj
    return None


# ------------------------------------------------------------------ প্রোডাক্ট পেজ
LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def visible_text(html: str) -> str:
    t = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", htmllib.unescape(t))


def find_first_value(text: str, keys: list[str]):
    """raw টেক্সটে "key": value খোঁজে (escape করা JSON-ও চলে)। (key, value) ফেরত দেয়।"""
    for key in keys:
        m = re.search(r'\\?"' + re.escape(key) + r'\\?"\s*:\s*(?:\\?"([^"\\]*)\\?"|(-?\d+(?:\.\d+)?))', text)
        if m:
            return key, (m.group(1) if m.group(1) is not None else m.group(2))
    return None, None


def _ld_product(html: str) -> dict | None:
    for m in LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else [data]
        flat = []
        for n in nodes:
            if isinstance(n, dict):
                flat.append(n)
                if isinstance(n.get("@graph"), list):
                    flat += [x for x in n["@graph"] if isinstance(x, dict)]
        for n in flat:
            t = n.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                return n
    return None


def parse_product_html(html: str) -> dict:
    """প্রোডাক্ট পেজ থেকে যা পাওয়া যায়। কোন ফিল্ড কোন কৌশলে এল তা found_by-তে।"""
    out: dict = {}
    found: dict[str, str] = {}

    def put(field, value, how):
        if value is not None and field not in out:
            out[field], found[field] = value, how

    ld = _ld_product(html)
    if ld:
        agg = ld.get("aggregateRating") or {}
        offers = ld.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        brand = ld.get("brand")
        put("title", ld.get("name"), "json_ld")
        put("brand", brand.get("name") if isinstance(brand, dict) else brand, "json_ld")
        put("rating_avg", parse_rating(agg.get("ratingValue")), "json_ld")
        put("rating_count", parse_count(agg.get("ratingCount") or agg.get("reviewCount")), "json_ld")
        put("price", parse_price(offers.get("price") or offers.get("lowPrice")), "json_ld")
        put("image_url", normalize_image_url(ld.get("image")), "json_ld")

    m = OG_IMAGE_RE.search(html)
    put("image_url", normalize_image_url(htmllib.unescape(m.group(1) or m.group(2))) if m else None, "og_image")

    k, v = find_first_value(html, RATING_KEYS)
    put("rating_avg", parse_rating(v), f"inline_json:{k}")
    k, v = find_first_value(html, RATING_COUNT_KEYS)
    put("rating_count", parse_count(v), f"inline_json:{k}")
    k, v = find_first_value(html, SOLD_KEYS)
    put("sold_count", parse_sold(v), f"inline_json:{k}")

    vis = visible_text(html)
    m = re.search(r"Ratings?\s+(\d[\d,]*)", vis)
    put("rating_count", parse_count(m.group(1)) if m else None, "text")
    prices = [parse_price(p) for p in re.findall(r"৳\s*([\d,]+(?:\.\d+)?)", vis)]
    prices = [p for p in prices if p is not None]
    if prices:
        put("price", prices[0], "text")
        bigger = [p for p in prices[1:4] if p > prices[0]]
        put("original_price", bigger[0] if bigger else None, "text")
    m = re.search(r"Positive Seller Ratings\s*(\d+)\s*%", vis)
    put("seller_positive_pct", int(m.group(1)) if m else None, "text")
    m = re.search(r"Ship on Time\s*(\d+)\s*%", vis)
    put("ship_on_time_pct", int(m.group(1)) if m else None, "text")
    m = re.search(r"(\d[\d.,]*\s?[KkMm]?)\+?\s+[Ss]old\b", vis)
    put("sold_count", parse_sold(m.group(1)) if m else None, "text")

    if "title" not in out:
        tm = TITLE_RE.search(html)
        if tm:
            title = htmllib.unescape(tm.group(1)).split("|")[0].strip()
            put("title", title or None, "title_tag")
    out["found_by"] = found
    return out


# --------------------------------------------------------------------- রিভিউ
BN_RE = re.compile(r"[\u0980-\u09FF]")
DATE_FORMATS = ("%d %b %Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y", "%d %B %Y")


def parse_date(v) -> date | None:
    if not v:
        return None
    s = str(v).strip()[:25]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def detect_lang(text: str | None) -> str | None:
    if not text:
        return None
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    bn = len(BN_RE.findall(text))
    return "bn" if bn / len(letters) > 0.3 else "en"


def hash_reviewer(name) -> str | None:
    if not name:
        return None
    salt = os.environ.get("REVIEWER_HASH_SALT", "mrs")
    return hashlib.sha256((salt + str(name)).encode("utf-8")).hexdigest()[:16]


def parse_review_item(raw: dict) -> dict | None:
    rid = first_present(raw, ["reviewRateId", "reviewId", "id"])
    stars = parse_count(first_present(raw, ["rating", "star", "stars"]))
    if rid is None or stars is None or not 1 <= stars <= 5:
        return None
    body = first_present(raw, ["reviewContent", "content", "reviewText"])
    when = parse_date(first_present(raw, ["reviewTime", "createTime", "reviewDate"]))
    return {
        "external_review_id": str(rid),
        "stars": stars,
        "body": body if isinstance(body, str) else None,
        "lang": detect_lang(body if isinstance(body, str) else None),
        "reviewed_at": when.isoformat() if when else None,
        "reviewer_hash": hash_reviewer(first_present(raw, ["buyerName", "userName", "nickName"])),
    }


def parse_reviews_payload(obj) -> tuple[list[dict], dict]:
    items: list[dict] = []
    if isinstance(obj, dict):
        model = obj.get("model") if isinstance(obj.get("model"), dict) else obj
        if isinstance(model.get("items"), list):
            items = [x for x in model["items"] if isinstance(x, dict)]
    if not items:
        for _, lst in _find_dict_lists(obj, lambda d: "reviewContent" in d or "reviewRateId" in d):
            items = lst
            break
    reviews = [r for r in (parse_review_item(x) for x in items) if r]
    paging = {}
    if isinstance(obj, dict) and isinstance(obj.get("model"), dict):
        paging = obj["model"].get("paging") or {}
    return reviews, {"total_pages": parse_count(paging.get("totalPages")),
                     "total_items": parse_count(paging.get("totalItems"))}
