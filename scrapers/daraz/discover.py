"""Daraz ক্যাটাগরি slug ডিসকভারি (শুধু পড়া, DB লাগে না)।

ক্যাটাগরি পেজ + ajax=true robots.txt-এ নিষিদ্ধ নয় (অডিটে যাচাই), আর JSON-এ আছে:
  mods.breadcrumb          -> উপরের ক্যাটাগরির slug
  mods.filter.filterItems  -> (type=category) উপ-ক্যাটাগরির slug ও নাম
  mainInfo.totalResults    -> মোট পণ্য
এগুলো থেকে কোন slug কাজের তা বের করে group (fashion/home/...)-ভিত্তিক seed প্রস্তাব করা হয়।
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from . import parse


def slug_of(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url if "//" in url else "//x" + url).path if url.startswith(("http", "//")) else url
    path = path.strip("/")
    if not path or "/" in path:
        return None
    return path.split("?")[0]


def summarize(slug: str, obj: dict) -> dict | None:
    """ajax JSON থেকে একটা ক্যাটাগরির সারসংক্ষেপ। আইটেম না থাকলে None।"""
    if not isinstance(obj, dict):
        return None
    raw = parse.find_listing_items(obj) or []
    items = [i for i in (parse.parse_listing_item(r) for r in raw) if i]
    if not items:
        return None
    mods = obj.get("mods") or {}
    crumbs = [{"slug": slug_of(b.get("url")), "title": b.get("title")}
              for b in (mods.get("breadcrumb") or []) if slug_of(b.get("url"))]
    children: list[dict] = []
    for fi in (mods.get("filter") or {}).get("filterItems") or []:
        if fi.get("type") == "category" or fi.get("uniqueName") == "category":
            for o in fi.get("options") or []:
                s = slug_of(o.get("url")) or o.get("value")
                if s and s != slug:
                    children.append({"slug": s, "title": o.get("title")})
    try:
        total = int((obj.get("mainInfo") or {}).get("totalResults"))
    except (TypeError, ValueError):
        total = None
    n = len(items)
    return {
        "slug": slug,
        "title": (crumbs[-1]["title"] if crumbs else None),
        "total_results": total,
        "items": n,
        "sold_pct": round(100 * sum(1 for i in items if i.get("sold_count") is not None) / n),
        "rating_pct": round(100 * sum(1 for i in items if i.get("rating_count") is not None) / n),
        "breadcrumb": crumbs,
        "children": children,
    }


def propose(found: dict[str, dict], group_keywords: dict[str, list[str]], min_total: int = 300,
            per_group: int = 8) -> dict[str, list[dict]]:
    """পাওয়া ক্যাটাগরি থেকে group অনুযায়ী seed প্রস্তাব: নামে কীওয়ার্ড মিললে ও পণ্য যথেষ্ট থাকলে।"""
    out: dict[str, list[dict]] = {g: [] for g in group_keywords}
    for slug, info in sorted(found.items(), key=lambda kv: -(kv[1].get("total_results") or 0)):
        total = info.get("total_results") or 0
        title = (info.get("title") or slug).lower().replace("-", " ")
        hay = f"{title} {slug.replace('-', ' ')}"
        if total < min_total:
            continue
        for g, kws in group_keywords.items():
            if len(out[g]) < per_group and any(re.search(r"\b" + re.escape(k.lower()), hay) for k in kws):
                out[g].append({"type": "category", "url": f"{parse.BASE}/{slug}/", "title": info.get("title"),
                               "total_results": total})
                break
    return out
