"""ভিডিও-তালিকা থেকে একটা শব্দের সারাংশ (বিশুদ্ধ ফাংশন)।

মনে রাখবেন: এটা \"গত N দিনের ভিউ-অনুযায়ী শীর্ষ ভিডিও\"-র সারাংশ, শব্দের মোট চাহিদা নয়। তুলনা চলে একই শব্দের আগের-পরের রানে,
আর শব্দ থেকে শব্দে (একই ধরনের সীমায় ধরা, তাই মোটামুটি)।
"""
from __future__ import annotations

import statistics


def summarize(videos: list[dict]) -> dict:
    viewed = [v for v in videos if v.get("views") is not None]
    views = [v["views"] for v in viewed]
    top = max(viewed, key=lambda v: v["views"]) if viewed else None
    return {
        "videos": len(videos),
        "views_total": sum(views) if views else None,
        "views_median": int(round(statistics.median(views))) if views else None,
        "top_video_id": top["id"] if top else None,
        "top_video_title": (top["title"] or "")[:200] if top else None,
        "top_video_views": top["views"] if top else None,
        "top_channel": (top["channel"] or "")[:120] if top else None,
    }
