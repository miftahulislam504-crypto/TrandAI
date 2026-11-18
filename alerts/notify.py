"""অ্যালার্টের সারাংশ বানানো ও (ঐচ্ছিক) Telegram-এ পাঠানো।

TELEGRAM_BOT_TOKEN ও TELEGRAM_CHAT_ID না থাকলে পাঠানো বাদ, অ্যালার্ট শুধু ড্যাশবোর্ডে থাকে।
টোকেন URL-এ থাকে, তাই ত্রুটির বার্তায় URL বা রিকোয়েস্টের বিস্তারিত কখনও দেখানো হয় না (লগে টোকেন ফাঁস আটকাতে)।
"""
from __future__ import annotations

import os
from typing import Optional

import requests

LIMIT = 3900  # Telegram-এর সীমা ৪০৯৬ অক্ষর, কিছু জায়গা রেখে
ICON = {"good": "🟢", "warn": "🔴", "info": "⚪"}
SEV_ORDER = {"warn": 0, "good": 1, "info": 2}


class NotifyError(Exception):
    pass


def build_digest(rows: list[dict], dashboard_url: Optional[str], max_items: int) -> str:
    """ওয়াচলিস্টের অ্যালার্ট আগে, তারপর সতর্কতা (🔴), ভালো খবর (🟢), তথ্য (⚪)।"""
    ordered = sorted(rows, key=lambda r: (not r.get("watched"), SEV_ORDER.get(r.get("severity"), 3), r.get("id", 0)))
    shown, rest = ordered[:max_items], ordered[max_items:]
    lines = [f"🔔 নতুন অ্যালার্ট: {len(rows)}টা"]
    for r in shown:
        lines.append(f"{'⭐ ' if r.get('watched') else ''}{ICON.get(r.get('severity'), '⚪')} {r['title']}")
    if rest:
        lines.append(f"…আরও {len(rest)}টা ড্যাশবোর্ডে")
    if dashboard_url:
        lines.append(dashboard_url.rstrip("/") + "/alerts")
    text = "\n".join(lines)
    return text if len(text) <= LIMIT else text[: LIMIT - 1] + "…"


def credentials() -> Optional[tuple[str, str]]:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return (token, chat) if token and chat else None


def send_telegram(text: str, token: str, chat_id: str, session: Optional[requests.Session] = None,
                  timeout: float = 20) -> None:
    s = session or requests.Session()
    try:
        r = s.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=timeout)
    except requests.RequestException as e:
        raise NotifyError(f"Telegram-এ পৌঁছানো যায়নি ({type(e).__name__})") from None
    if r.status_code != 200:
        desc = ""
        try:
            desc = str(r.json().get("description", ""))[:120]
        except ValueError:
            pass
        raise NotifyError(f"Telegram HTTP {r.status_code}" + (f": {desc}" if desc else ""))
