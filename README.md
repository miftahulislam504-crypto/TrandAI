# Market Research System

বাংলাদেশের ই-কমার্স প্ল্যাটফর্ম, Google Trends ও Facebook Ads Library থেকে ডেটা নিয়ে প্রতিটা প্রোডাক্টকে **Best / Mid / Don't** ট্যাগ দেওয়ার সিস্টেম।
শুরুর ক্যাটাগরি: ফ্যাশন, হোম, কিচেন। বিস্তারিত পরিকল্পনা: [docs/PLAN.md](docs/PLAN.md)

## এই ZIP-এ কী আছে (Phase 0 + 1 + 2 + 3 + 4)

অগ্রগতির পুরো হিসাব: **[progress.md](progress.md)** (কী হয়েছে, কী বাকি)

```
market-research/
├── README.md
├── progress.md                 # কতটুকু হয়েছে, কতটুকু বাকি
├── .github/workflows/
│   ├── source-audit.yml        # Phase 0: সোর্স অডিট
│   ├── daraz-smoke.yml         # Phase 1: Daraz স্মোক টেস্ট (ডাটাবেজ ছাড়া)
│   ├── daraz-daily.yml         # Phase 1: প্রতিদিনের স্ক্র্যাপ (রাত ২:০০)
│   ├── score-daily.yml         # Phase 2: প্রতিদিনের স্কোরিং (ভোর ৩:০০)
│   ├── match-daily.yml         # Phase 4: প্রতিদিনের প্রোডাক্ট ম্যাচিং (ভোর ২:৪০, স্কোরিংয়ের আগে)
│   ├── trends-smoke.yml        # Phase 3: Google Trends স্মোক টেস্ট (ডাটাবেজ ছাড়া)
│   └── trends-weekly.yml       # Phase 3: সাপ্তাহিক Trends সংগ্রহ (সোমবার ভোর ৪:০০)
├── config/
│   ├── daraz.json              # seed (সার্চ শব্দ/ক্যাটাগরি URL) ও রান সেটিংস
│   ├── categories.json         # প্রতি ক্যাটাগরির প্রোডাক্ট লক্ষ্য
│   ├── scoring.json            # স্কোরের ওজন, থ্রেশহোল্ড, গেট, মার্জিন, প্রতিযোগিতা, রেড ফ্ল্যাগ
│   ├── intel.json              # রিভিউ বিশ্লেষণের সীমা
│   ├── trends.json             # Phase 3: Google Trends কীওয়ার্ড (৩৯ segment) ও সেটিংস
│   ├── matching.json           # Phase 4: ম্যাচিংয়ের থ্রেশহোল্ড, ওজন, নয়েজ শব্দ
│   └── sources.json
├── docs/
│   ├── PLAN.md                 # বিস্তারিত পরিকল্পনা
│   ├── DECISIONS.md            # আপনার সিদ্ধান্ত
│   ├── SOURCE_AUDIT.md         # সোর্স অডিট
│   ├── PHASE1.md               # Phase 1 গাইড
│   ├── PHASE2.md               # Phase 2 গাইড: স্কোর কীভাবে হয়, যাচাই ও ক্যালিব্রেশন
│   ├── PHASE3.md               # Phase 3 গাইড: Google Trends কীভাবে কাজ করে, স্মোক টেস্ট, anchor
│   ├── PHASE4.md               # Phase 4 গাইড: ম্যাচিং কীভাবে কাজ করে, রিভিউ কিউ, ভুল মার্জ ফেরানো
│   ├── PHASE6.md               # Phase 6 গাইড: Facebook Ads Library চেক কীভাবে দেবেন, স্কোরে প্রভাব, স্বয়ংক্রিয় সংগ্রহের সিদ্ধান্ত
│   ├── PHASE7.md               # Phase 7 গাইড: ওয়াচলিস্ট, অ্যালার্ট, Telegram, ব্যাকটেস্ট, CSV, Data Health, নতুন ক্যাটাগরি
│   └── PHASE9.md               # Phase 9 গাইড: ১৫ ক্যাটাগরির অবস্থা, Discovery রাউন্ড ২, ক্যাটাগরি চালুর নিয়ম
├── scrapers/                   # HTTP ক্লায়েন্ট, Daraz adapter, রান, audit, ৫৮টা টেস্ট
├── scoring/                    # ইঞ্জিন, ট্যাগ, ব্যাখ্যা, মার্জিন/প্রতিযোগিতা, Ads Library সংকেত (ads.py), রানার, Google অংশ, ১৪৩টা টেস্ট
├── reviewintel/                # Phase 5: রিভিউ বিশ্লেষণ (নকল অভিযোগ, সন্দেহজনক রিভিউ, Groq সেন্টিমেন্ট ও key-পুল), ৫১টা টেস্ট
├── trends/                     # Phase 3: ক্লায়েন্ট, কীওয়ার্ড ম্যাপিং, নর্মালাইজেশন, রান, ৫৩টা টেস্ট
├── matching/                   # Phase 4: টাইটেল-পার্সিং, স্কোর, ছবির হ্যাশ, মার্জ পরিকল্পনা, রান, ৮১টা টেস্ট
├── alerts/                     # Phase 7: রোজ অ্যালার্ট (ট্যাগ বদল ইত্যাদি) ও Telegram
├── backtest/                   # Phase 7: ব্যাকটেস্ট ও ওজন-টিউনিং রিপোর্ট
├── tools/progress.py           # progress.md-এর টেবিল হালনাগাদ
├── tools/capacity.py           # GitHub Actions-এর মিনিটের আন্দাজ
├── supabase/migrations/
│   ├── 20261109000000_init.sql     # টেবিল, ইনডেক্স, RLS
│   ├── 20261110000000_phase1.sql   # ভিউ ও canonical ফাংশন
│   ├── 20261111000000_phase2.sql   # listing_scored ভিউ
│   ├── 20261112000000_phase3.sql   # Trends-এর অতিরিক্ত কলাম
│   ├── 20261113000000_phase4.sql   # match_candidates, merge/split ফাংশন, match_queue ভিউ
│   ├── 20261114000000_phase4b.sql  # ছবির URL ও হ্যাশের কলাম, match_queue-তে ছবি
│   ├── 20261115000000_phase5.sql   # reviews.flags, product_costs (কেনা দাম) ও দুটো ফাংশন
│   ├── 20261116000000_phase6.sql   # ad_checks (Ads Library হাতে-দেওয়া চেক) ও দুটো ফাংশন
│   ├── 20261117000000_phase7.sql   # watchlist, alerts, get_data_health, মার্জের ঘাটতি ঠিক, নতুন ক্যাটাগরির সারি
│   └── 20261120000000_phase9.sql   # Phase 9: আরও ৮টা ক্যাটাগরির সারি (মোট ১৫)
└── dashboard/                  # Next.js ড্যাশবোর্ড (Vercel-এ)
```

## এখন কী করবেন

1. রিপোতে ZIP-এর ফাইল পুশ করুন (`.github/workflows/` পাথ ঠিক আছে কি না দেখুন)।
2. Supabase-এ দশটা migration পরপর চালান (নতুন: `20261120000000_phase9.sql`)।
3. Actions → **Daraz Smoke Test** চালিয়ে Summary আমাকে পাঠান। আসল Daraz-এর ডেটার গঠন এখানেই প্রথম যাচাই হবে। বিস্তারিত: [docs/PHASE1.md](docs/PHASE1.md)
4. ঠিক থাকলে GitHub Secrets দিয়ে **Daraz Daily** চালু করুন, ড্যাশবোর্ড Vercel-এ ডিপ্লয় করুন।
5. Actions → **Trends Smoke Test** চালিয়ে Summary আমাকে পাঠান (৪২৯ এলেও পাঠান)। বিস্তারিত: [docs/PHASE3.md](docs/PHASE3.md)
6. ঠিক থাকলে **Trends Weekly** চালু করুন।
7. **Match Daily** চালু করুন (আরেকটা সোর্স এলে কাজে লাগবে, এখনও নিরাপদ)। ড্যাশবোর্ডে `/matches` পেজে কিউ দেখুন। বিস্তারিত: [docs/PHASE4.md](docs/PHASE4.md)
8. ১৪ দিন ডেটা জমলে **Score Daily** চালান ও `spotcheck.md` দিয়ে স্কোর যাচাই করুন। বিস্তারিত: [docs/PHASE2.md](docs/PHASE2.md)

## ফেজের অবস্থা

| ফেজ | কাজ | অবস্থা |
|---|---|---|
| 0 | সোর্স অডিট ও কাঠামো | কোড সম্পন্ন, আসল সাইটে অডিট বাকি |
| 1 | Daraz MVP | কোড সম্পন্ন, আসল Daraz-এ স্মোক টেস্ট বাকি |
| 2 | স্কোরিং v1 | কোড সম্পন্ন, আসল ডেটায় যাচাই ও ক্যালিব্রেশন বাকি |
| 3 | Google Trends | কোড সম্পন্ন, আসল Google-এ স্মোক টেস্ট বাকি (pytrends ব্লক হতে পারে) |
| 4 | অন্য সাইট + প্রোডাক্ট ম্যাচিং | ম্যাচিং কোড সম্পন্ন, অন্য সাইটের adapter বাকি |
| 5 | রিভিউ ইন্টেলিজেন্স, মার্জিন | কোড সম্পন্ন, আসল ডেটায় যাচাই বাকি |
| 6 | Facebook Ads Library | হাতে-দেওয়া চেক কোড সম্পন্ন (ওজন ০, শুধু তথ্য); স্বয়ংক্রিয় সংগ্রহ আপনার সিদ্ধান্তের অপেক্ষায়, বিস্তারিত: [docs/PHASE6.md](docs/PHASE6.md) |
| 7 | অ্যালার্ট, টিউনিং ও বিস্তার | ওয়াচলিস্ট/অ্যালার্ট, ব্যাকটেস্ট, CSV, Data Health, নতুন ক্যাটাগরির কাঠামো কোড সম্পন্ন; আসল ডেটা ও Telegram-এ যাচাই বাকি, বিস্তারিত: [docs/PHASE7.md](docs/PHASE7.md) |
| 7 | অ্যালার্ট, টিউনিং, বিস্তার | পরে |
| 8 | বই (Rokomari) | পরে |

সংখ্যায় হিসাব `progress.md`-এ।

## টেস্টের অবস্থা

- মোট ৪০৫টা টেস্ট পাস: স্ক্র্যাপার ৫৮, স্কোরিং ১৪৩, Trends ৫৩ (৬টা বাদ, আসল Google লাগে), ম্যাচিং ৮১, রিভিউ ইন্টেলিজেন্স ৫১, progress টুল ৫, ড্যাশবোর্ডের Ads ইনপুট পার্সার ১৪ (`cd dashboard && npm test`)।
- নকল Daraz সার্ভার → আসল PostgreSQL ও PostgREST → স্কোরিং → ড্যাশবোর্ড, পুরো পথ লোকালি চালানো হয়েছে। এর মধ্যে আছে দুই দিনের স্ক্র্যাপ, ৪ দিনের ট্যাগ-স্থিতিশীলতা, লগইন, ফিল্টার, স্কোর ব্রেকডাউন।
- **আসল Daraz এখনও পরীক্ষা হয়নি।** আমার এনভায়রনমেন্ট থেকে ঢোকা যায় না। লিস্টিং JSON-এর key, রিভিউ endpoint ও robots.txt স্মোক টেস্টে যাচাই হবে। আসল ডেটায় স্কোরের বণ্টনও এখনও অজানা।
- **Phase 3 (Google Trends) আসল Google-এর বিরুদ্ধে চালানো হয়নি।** আমার এনভায়রনমেন্ট থেকে trends.google.com-এ ঢোকা যায় না। আসল `pytrends` কোড নকল Google রেসপন্স দিয়ে চালানো হয়েছে (পার্সিং ও ৪২৯ ধরা যাচাই)। Trends-এর সংগ্রহ-রান শুধু নকল ডেটাবেজে চালানো, তবে migration ৪টাই (phase3 সহ) আসল PostgreSQL 16-এ চলেছে।
- **Phase 4 (ম্যাচিং):** migration, SQL ফাংশন (মার্জ, স্প্লিট, সিদ্ধান্ত), ম্যাচিং রান, স্কোরিং ও ড্যাশবোর্ডের `/matches` পেজ আসল PostgreSQL + PostgREST-এ চালানো হয়েছে, accept/reject ড্যাশবোর্ডের ফর্ম থেকে। ছবির হ্যাশ ও ছবি-সহ ম্যাচিংও আসল PostgreSQL 16 + PostgREST-এ লোকাল ছবির সার্ভার দিয়ে চালানো। কিন্তু ডেটা আমার বানানো ৭-৮টা listing, আসল Daraz বা অন্য সাইটের নয়, তাই থ্রেশহোল্ড আসল ডেটায় যাচাই হয়নি।
- **Phase 5:** সাতটা migration আসল PostgreSQL 16-এ চলেছে (নতুনটা দুইবার)। রিভিউ বিশ্লেষণ, কেনা দাম বসানো (SQL ফাংশন), স্কোরিং ও ড্যাশবোর্ডের পণ্য-পেজ (`next build` + `next start`, সেভ/মুছুন/ভুল ইনপুট/লগইন ছাড়া অনুরোধ) আসল PostgREST-এর বিরুদ্ধে চালানো। ডেটা আমার বানানো; আসল Daraz রিভিউ টেক্সট ও আসল কেনা দামে নয়।
- **Phase 6:** আটটা migration আসল PostgreSQL 16-এ চলেছে (নতুনটা দুইবার)। `record_ad_check`/`delete_ad_check`-এর সব ভুল-ইনপুট, অনুমতি (`anon`/`authenticated` বন্ধ) ও cascade, REST দিয়ে চেক সেভ, স্কোরিং (ওজন ০ ও ২০), আর ড্যাশবোর্ড (`next build` + `next start`) দিয়ে `/ads` ও পণ্য-পেজের সেভ/মুছুন/ভুল ইনপুট/বাইরের redirect আটকানো আসল PostgREST-এর বিরুদ্ধে চালানো। ডেটা আমার বানানো; **আসল Facebook Ads Library পেজ আমি দেখিনি**, তাই `/ads`-এর নির্দেশনা ও ফ্যাক্টরের সংখ্যা অযাচাইকৃত।
- **Phase 7:** নয়টা migration আসল PostgreSQL 16-এ চলেছে (নতুনটা দুইবার)। অ্যালার্ট ও ব্যাকটেস্ট রানার আসল PostgREST-এর বিরুদ্ধে, ড্যাশবোর্ডের নতুন পেজ, CSV ও সেভ-অ্যাকশন `next build` + `next start` দিয়ে চালানো। ডেটা আমার বানানো; **আসল Daraz, আসল Telegram ও আসল Supabase-এ চালাইনি।** পাইথন টেস্ট ৪৬৮টা, ড্যাশবোর্ড ৩৯টা পাস।
