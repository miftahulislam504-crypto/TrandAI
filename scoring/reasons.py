"""প্রতিটা স্কোরের ব্যাখ্যা বাংলায়। `summary` = ট্যাগের মূল কারণ (সর্বোচ্চ ৩), `notes` = ডেটার সীমাবদ্ধতা।"""
from __future__ import annotations

from typing import Optional

from .features import Features

TOPIC_BN = {"quality": "মান", "price": "দাম", "delivery": "ডেলিভারি", "packaging": "প্যাকেজিং", "size_fit": "সাইজ/ফিট",
            "color": "রং", "durability": "টেকসইতা", "authenticity": "আসল-নকল", "service": "সেলারের সার্ভিস", "description_match": "বর্ণনার সাথে মিল"}

GATE_NAMES = {
    "rating_count": "রেটিং সংখ্যা কম",
    "adj_rating": "রেটিং যথেষ্ট নয়",
    "bad_ratio": "খারাপ রিভিউ বেশি",
    "demand": "বিক্রি যথেষ্ট নয়",
    "counterfeit": "নকল/ডুপ্লিকেট অভিযোগ আছে",
    "margin": "মার্জিন কম",
}


def _top_phrase(v: float) -> str:
    if v >= 50:
        return f"ক্যাটাগরির শীর্ষ {max(1, round(100 - v))}%"
    return f"ক্যাটাগরির নিচের {max(1, round(v))}%"


def build_reasons(r, f: Features, gates: dict, provisional: Optional[str], cfg: dict) -> dict:
    cands: list[tuple[float, str]] = []
    fac, det = r.factors, r.detail

    # ---- কঠিন Don't কারণ (সবচেয়ে জোরালো)
    rq = det.get("review_quality") or {}
    br = det.get("bad_review") or {}
    for h in gates.get("hard_dont", []):
        if h == "low_rating":
            cands.append((100, f"রেটিং খুব কম: {rq.get('adj_rating')} ({rq.get('rating_count')}টি রেটিং)"))
        elif h == "many_bad_reviews":
            cands.append((100, f"খারাপ রিভিউ অনেক: {round(br.get('raw_ratio', 0) * 100)}% "
                               f"({br.get('n')}টির মধ্যে {br.get('bad')}টা)"))
        elif h == "falling_sales":
            cands.append((100, f"টানা {cfg['dont']['falling_weeks']} সপ্তাহ ধরে সাপ্তাহিক বিক্রি কমছে"))

    # ---- ফ্যাক্টরভিত্তিক কারণ
    v = fac.get("demand")
    if v is not None and (v >= 65 or v <= 40):
        d = det["demand"]
        head = "বিক্রি বেশি" if v >= 65 else "বিক্রি কম"
        if d["basis"] == "sold" and d.get("velocity") is not None:
            gain = round(d["velocity"] * d["velocity_days"])
            body = f"শেষ {d['velocity_days']} দিনে +{gain}টা"
        elif d["basis"] == "sold":
            body = f"মোট বিক্রি {round(d['lifetime'])}টা"
        else:
            head = head.replace("বিক্রি", "রিভিউ সংখ্যা")
            body = f"{round(d['lifetime'])}টা (বিক্রির তথ্য নেই)"
        cands.append((abs(v - 50), f"{head}: {body} ({_top_phrase(v)})"))

    v = fac.get("trend")
    t = det.get("trend")
    if v is not None and t and (v >= 65 or v <= 40):
        days = cfg["trend"]["recent_days"]
        word = "বাড়ছে" if v >= 65 else "কমছে"
        cands.append((abs(v - 50), f"বিক্রির গতি {word}: দিনে {t['recent']:.1f}টা (আগের {days} দিনে {t['prior']:.1f}টা)"))

    gd = det.get("google") or {}
    if gd.get("status") == "ok":
        gs = gd["score"]
        if gs >= 65 or gs <= 40:
            word = "বাড়ছে" if gs >= 65 else "কমছে"
            base = f"গত {gd['recent_weeks']} সপ্তাহ বনাম আগের {gd['prior_weeks']} সপ্তাহ: {gd['momentum_pct']:+d}%"
            if gd["seasonal"] and gd.get("yoy_pct") is not None:
                base += f", গত বছরের একই সময়ের চেয়ে {gd['yoy_pct']:+d}%"
            cands.append((abs(gs - 50), f"Google-এ '{gd['label']}' সার্চ {word}: {base}"))

    v = fac.get("review_quality")
    if v is not None and (v >= 65 or v <= 40):
        word = "ভালো" if v >= 65 else "কম"
        cands.append((abs(v - 50), f"রেটিং {word}: {rq.get('adj_rating')} ({rq.get('rating_count')}টি রেটিং)"))

    v = fac.get("bad_review")
    if v is not None and (v >= 85 or v <= 50):
        word = "কম" if v >= 85 else "বেশি"
        cands.append((abs(v - 50), f"খারাপ রিভিউ {word}: {round(br['raw_ratio'] * 100)}% "
                                   f"({br['n']}টি নমুনার মধ্যে {br['bad']}টা)"))

    # ---- রিভিউয়ের অভিযোগের টপিক (Groq সেন্টিমেন্ট)। স্কোর বদলায় না, শুধু কারণ
    cm = det.get("complaints") or {}
    top = [(t, n) for t, n in (cm.get("topics") or {}).items() if n >= cfg["sentiment_notes"]["min_count"]][:3]
    if top:
        cands.append((60, "রিভিউয়ে বেশি অভিযোগ: " + ", ".join(f"{TOPIC_BN.get(t, t)} ({n}টি)" for t, n in top)))

    # ---- রেড ফ্ল্যাগ ও ব্যবসার দিক
    if gates.get("counterfeit") is False:
        cf = det.get("counterfeit") or {}
        cands.append((95, f"⚠️ নকল/ডুপ্লিকেট অভিযোগ: {cf.get('of')}টি রিভিউয়ের মধ্যে {cf.get('n')}টায়"))
    mg = det.get("margin") or {}
    if mg:
        if mg["margin_pct"] <= 0:
            cands.append((90, f"এই দামে লোকসান: বাজারে সর্বনিম্ন ৳{mg['price']:g}, আপনার খরচ ৳{mg['unit_cost'] + mg['extra_cost']:g}"
                              f" (ন্যূনতম বিক্রয়মূল্য ৳{mg['break_even_price']:g})"))
        else:
            v = fac.get("margin")
            if v is not None and (v >= 65 or v <= 40):
                word = "ভালো" if v >= 65 else "কম"
                cands.append((abs(v - 50), f"মার্জিন {word}: {mg['margin_pct']:g}% (প্রতি পিসে প্রায় ৳{mg['profit']:g} লাভ)"))
    cp = det.get("competition") or {}
    v = fac.get("competition")
    # শুধু \"ভিড় বেশি\" বলা হয়: \"১ সেলার\" মানে আমরা এক সেলারই ট্র্যাক করেছি, বাজারে আর কেউ নেই তা নয়, তাই সেটা সুখবর হিসেবে দেখানো হয় না
    if cp and v is not None and v <= 30:
        unit = "সেলার" if cp["by"] == "seller" else "listing"
        cands.append((abs(v - 50) * 0.8, f"প্রতিযোগিতা বেশি: ট্র্যাক করা {cp['sellers']}টি {unit}"))

    # ---- Facebook Ads Library (হাতে-দেওয়া চেক)
    ad = det.get("ads") or {}
    if ad.get("status") == "ok":
        v = fac.get("ads_signal")
        facts = f"{ad['active_ads']}টা সক্রিয় বিজ্ঞাপন"
        if ad.get("advertisers") is not None:
            facts += f", কমপক্ষে {ad['advertisers']}টা আলাদা পেজ"
        if ad.get("longest_days") is not None:
            facts += f", সবচেয়ে পুরনোটা {ad['longest_days']} দিন ধরে চলছে"
        if v is not None and (v >= 65 or v <= 30):
            word = "জোরালো" if v >= 65 else "দুর্বল"
            cands.append((abs(v - 50), f"বিজ্ঞাপনে বাজার-সমর্থন {word}: '{ad['keyword']}' শব্দে {facts}"))
        if ad.get("crowded"):
            cands.append((55, f"📢 বিজ্ঞাপনে ভিড়: '{ad['keyword']}' শব্দে {facts}"))

    cands.sort(key=lambda x: -x[0])
    summary = [text for _, text in cands[:3]]

    # ---- নোট
    notes: list[str] = []
    min_hist = cfg["min_history_days_for_velocity"]
    if f.history_days < min_hist:
        notes.append(f"ইতিহাস মাত্র {f.history_days} দিনের, বিক্রির গতি ও ট্রেন্ড ধরা হয়নি")
    if f.basis == "review":
        notes.append("সোর্সে বিক্রির সংখ্যা নেই, রিভিউ সংখ্যা দিয়ে আন্দাজ করা হয়েছে")
    if f.basis is None:
        notes.append("বিক্রি বা রিভিউ সংখ্যার কোনো ডেটা নেই")
    if fac.get("bad_review") is None:
        notes.append("খারাপ রিভিউ মাপার মতো রিভিউ নমুনা নেই")
    if "all" in (det.get("pool_scope") or {}).values():
        notes.append("ক্যাটাগরিতে তুলনার প্রোডাক্ট কম, সব ক্যাটাগরির সাথে তুলনা করা হয়েছে")
    if provisional:
        label = "Best" if provisional == "best" else "Don't"
        notes.append(f"স্কোর {label}-এর মতো, কিন্তু ডেটা নিশ্চিত নয় (কনফিডেন্স {r.confidence}), তাই আপাতত Mid")
    elif r.raw_tier == "mid" and r.total is not None and r.total >= cfg["best"]["min_score"]:
        failed = [GATE_NAMES[k] for k, val in gates.items() if k in GATE_NAMES and val is False]
        if failed:
            notes.append("স্কোর ভালো, কিন্তু Best-এর শর্ত পূরণ হয়নি: " + ", ".join(failed))
    if r.tier is not None and r.raw_tier != r.tier:
        notes.append(f"আজকের হিসাবে {r.raw_tier}, কিন্তু ট্যাগ বদলাতে টানা {cfg['tier_change_days']} দিন একই থাকতে হয়; আগের ট্যাগ রাখা হয়েছে")

    # সবচেয়ে কম জরুরি নোট, তাই শেষে (notes[:4] কাটলে এটাই বাদ যায়)
    if gd.get("status") == "ok":
        notes.append(f"Google Trends '{gd['label']}' ধরনের সার্চ ইন্টারেস্ট, এই প্রোডাক্টের নিজস্ব নয়"
                     + (" (মৌসুমি শব্দ, ট্রেন্ড সাবধানে পড়ুন)" if gd["seasonal"] else ""))
    elif gd.get("status") == "stale":
        notes.append("Google Trends ডেটা পুরনো, ট্রেন্ডে ধরা হয়নি")
    if ad.get("status") == "ok":
        who = "এই প্রোডাক্টের নিজস্ব চেক" if ad["level"] == "product" else "প্রোডাক্টের ধরনের শব্দের চেক, এই প্রোডাক্টের নিজস্ব নয়"
        wt = "" if cfg["weights"].get("ads_signal", 0) > 0 else ", স্কোরে ওজন ০ (শুধু তথ্য)"
        notes.append(f"Facebook Ads Library চেক হাতে-দেওয়া ({ad['observed_on']}), {who}{wt}")
    elif ad.get("status") == "stale":
        notes.append(f"Facebook Ads Library চেক পুরনো ({ad['observed_on']}), ধরা হয়নি")

    return {
        "summary": summary,
        "notes": notes[:4],
        "raw_tier": r.raw_tier,
        "provisional_tier": provisional,
        "available_weight": r.available_weight,
        "factors": {k: (None if val is None else round(val, 1)) for k, val in fac.items()},
        "gates": gates,
        "weights": cfg["weights"],
        "detail": det,
    }
