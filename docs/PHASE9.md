# Phase 9: ক্যাটাগরি সম্প্রসারণ (১৫টা ক্যাটাগরি)

## এই ধাপে কী হয়েছে

| বিষয় | অবস্থা |
|---|---|
| ক্যাটাগরির কাঠামো | `config/categories.json`-এ ১৫টা। চালু ৩ (fashion, home, kitchen), বাকি ১২ বন্ধ (`enabled: false`) |
| Supabase সারি | `supabase/migrations/20261120000000_phase9.sql` নতুন ৮টার সারি দেয় (আবার চালানো নিরাপদ) |
| Daraz seed | `config/daraz.json`: যাচাই-করা URL যেখানে ছিল সেখানে বসেছে; বাকিগুলো খালি, অনুমানে বসানো হয়নি |
| Google Trends | `config/trends.json`: ১০৯ segment (আগে ৩৯, নতুন ৭০), ১৫ ক্যাটাগরিই কভার |
| ক্যাটাগরি-ভাগ | bags-footwear ও watches-jewellery আলাদা; `beauty-health` বিউটিতে থাকছে |
| Discovery রাউন্ড ২ | ১৪৭ slug, ১৫ group, ২৪০ রিকোয়েস্ট, ~২৫ মিনিট। **আপনি চালালে পরের ধাপ খুলবে** |
| ক্ষমতার হিসাব | ১৫ ক্যাটাগরি ও ক্যাটাগরিপ্রতি ৮ seed ধরলে ~১৫১০ প্রোডাক্ট, মাসে ~৭২৭ মিনিট (সীমা ২০০০) |

## ১৫ ক্যাটাগরির অবস্থা

| # | slug | অবস্থা | Daraz seed | Trends segment | Wave |
|---|---|---|---|---|---|
| 1 | fashion | চালু | ১০ | ১২ | ১ |
| 2 | electronics | বন্ধ | খালি, Discovery দরকার | ৭ | ২ |
| 3 | mobile-accessories | বন্ধ | খালি, Discovery দরকার | ৬ | ২ |
| 4 | home | চালু | ১০ | ১২ | ১ |
| 5 | beauty | বন্ধ | ২ (`beauty-health` ইত্যাদি) | ১০ | ২ |
| 6 | health-wellness | বন্ধ | খালি, Discovery দরকার | ৪ | ৩ |
| 7 | watches-jewellery | বন্ধ | ১ (`jewellery-fashion`) | ৪ | ৩ |
| 8 | bags-footwear | বন্ধ | ২ (`womens-bags`, `mens-sneakers`) | ৫ | ২ |
| 9 | baby | বন্ধ | ৪ | ৯ | ৩ |
| 10 | kitchen | চালু | ১২ | ১৫ | ১ |
| 11 | grocery | বন্ধ | খালি, Discovery দরকার | ৪ | ৪ |
| 12 | sports | বন্ধ | খালি, Discovery দরকার | ৮ | ৩ |
| 13 | automotive | বন্ধ | খালি, Discovery দরকার | ৪ | ৪ |
| 14 | islamic | বন্ধ | খালি, Discovery দরকার | ৫ | ২ |
| 15 | gifts-lifestyle | বন্ধ | খালি, Discovery দরকার | ৪ | ৩ |

Islamic Products ডিসেম্বরের মধ্যে চালু করতে চাইলে জানান (রমজান ফেব্রুয়ারির শুরুর দিকে, আনুমানিক)। এখন হিজাব, বোরকা, পাঞ্জাবির Trends segment fashion-এর ভেতরে। Islamic চালুর সময় ওগুলোর `category` `islamic`-এ বদলাব, তার আগে নয়। এখন বদলালে `islamic` বন্ধ থাকায় ওই তিন শব্দের Trends সংগ্রহ থেমে যেত, অথচ fashion-এর প্রোডাক্ট ওগুলোর ওপর নির্ভর করে।

## নতুন নিয়ম: বন্ধ ক্যাটাগরি Trends-এ ধরা হয় না

আগে Trends সব segment আনত। এখন `config/categories.json`-এ `enabled: false` ক্যাটাগরির শব্দ রোজকার ও সাপ্তাহিক রানে বাদ। কারণ Google-এর অনুরোধ ব্লকের ঝুঁকি বাড়ায়, আর Trends ১২ মাস পেছনের ডেটা দেয়, তাই ক্যাটাগরি চালুর পরে আনলে ইতিহাস হারায় না।

- নাম ধরে চালালে বন্ধ ক্যাটাগরিও চলে: `python -m trends.run_trends --category islamic --dry-run`, বা Actions → Trends Weekly → `category`।
- ক্যাটাগরির বৈধ তালিকা আর `trends/config.py`-এ হাতে লেখা নয়, `categories.json` থেকে আসে।

## নতুন ক্যাটাগরি চালু করার নিয়ম (প্রতি ক্যাটাগরিতে)

1. Discovery-র ফল থেকে `config/daraz.json`-এ ওই ক্যাটাগরির seed বসানো (আমি, artifact পেলে)।
2. Daraz Daily হাতে চালান, `category` ঘরে ওই slug (বন্ধ ক্যাটাগরিও নাম ধরে চলে)। রিপোর্টে আইটেম সংখ্যা, সোল্ড-কাউন্ট কভারেজ (~৯০% আশা) দেখুন।
3. `python tools/capacity.py` চালিয়ে মিনিট দেখুন।
4. ঠিক থাকলে `config/categories.json`-এ `enabled: true` ও `total_target_products` যোগফল ঠিক করুন (`tools/capacity.py` যোগফল মেলে কি না বলে)।
5. bags-footwear বা watches-jewellery চালালে **একই কমিটে** fashion থেকে ওই URL সরান।
6. পরের Trends Weekly রানে ওই ক্যাটাগরির শব্দ নিজে ধরা হবে। ফল দেখুন, `no_data` বেশি হলে শব্দ বদলাব।
7. ক্যাটাগরির স্কোর বণ্টন যাচাই। প্রোডাক্ট কম হলে `percentile` মোড অস্থির হতে পারে।

## যা এখনও বাকি (Phase 9)

- Discovery রাউন্ড ২ চালানো ও artifact পাঠানো (আপনি), তারপর seed বসানো (আমি)।
- Wave ১ প্রোডাক্ট সংখ্যা বাড়ানো, Wave ২-৪ ক্যাটাগরি ধরে স্মোক ও চালু।
- ওষুধ ও নিয়ন্ত্রিত পণ্যের সীমারেখা (health-wellness, grocery), বিক্রির বিধিনিষেধ আপনি দেখবেন।
- Islamic-এর সিজন (রমজান, ঈদ, কোরবানি) Trends সিজনালে যাচাই।

## টেস্ট

- স্ক্র্যাপার ৮৩ (নতুন ১১: কনফিগের মিল, migration সারি, seed সংঘাত, Discovery-র group-ক্রম)।
- Trends ৬১ (৬টা বাদ, আসল Google লাগে) (নতুন ৮: বন্ধ ক্যাটাগরি বাদ, নাম ধরলে চলে, নতুন segment-এর টাইটেল-মিল)।
- স্কোরিং ১৪৩, ম্যাচিং ৮১, রিভিউ ইন্টেলিজেন্স ৫১, অ্যালার্ট ৩৬, ব্যাকটেস্ট ২৬, tools ১৭: কোনোটা ভাঙেনি।
- ড্যাশবোর্ডে কোনো বদল নেই।
- **আসল Daraz, আসল Google ও আসল Supabase-এ চালাইনি।** নতুন migration আসল PostgreSQL-এ চালাইনি (আমার এনভায়রনমেন্টে PostgreSQL নেই); এটা সরল `insert ... on conflict do nothing`, তবু Supabase-এ চালানোর পর `/health`-এ ক্যাটাগরি দেখে নিন।

## Discovery রাউন্ড ২-এর ফল (২০২৬-১১-২০) ও রাউন্ড ৩

- ১৪৭টা slug-এর মধ্যে ২৭টা কাজ করেছে। ~৭০টা অনুমানের slug Daraz-এ নেই (JSON-এর বদলে HTML ফেরত)।
- `watches`, `mens-watches`, `womens-watches`-এ টানা ৩ ব্লক, রান থেমেছে। তাই তালিকার শেষের ৪৭টা (ব্যাগ-জুতা, হেলথ, গিফট, গ্রোসারি, অটোমোটিভ) চেষ্টাই হয়নি।
- seed বসেছে: electronics ৪, mobile-accessories ১, beauty ৭, sports ৬, bags-footwear ৩, baby ৮ (সব বন্ধ ক্যাটাগরি)।
- এখনও ফাঁকা: islamic, health-wellness, grocery, automotive, gifts-lifestyle, watches-jewellery (১)। রাউন্ড ৩ এগুলোর জন্য।
- রাউন্ড ৩: ৬৬টা slug Daraz-এর মেনু থেকে, বাজেট ১২৫। চালানোর আগে ২-৩ ঘণ্টা অপেক্ষা।

## রাউন্ড ৩-এর ফল (২০২৬-১১-২১)

- ১০১টা ক্যাটাগরি যাচাই, ব্লক নেই। সব ১৫ ক্যাটাগরিতে এখন অন্তত ১টা যাচাই-করা seed।
- সোল্ড/রেটিং কভারেজ কম হওয়ায় বাদ: auto-parts-spares, motorcycle-parts-spares, tires-tubes, laptop-bag, women-muslim-wear-accessories, pancake-waffle-mixes, kids-watches-wsj, dresses-jumpsuits।
- পরের ধাপ: Wave ২ স্মোক টেস্ট (Islamic আগে, রমজানের আগে ডেটা জমাতে)।

## সব ক্যাটাগরি একসাথে চালু (২০২৬-১১-২১)

- ১৫টাই `enabled: true`, লক্ষ্য ১৫১০ প্রোডাক্ট, রোজ ~১৭৫ অনুরোধ।
- বাকি: Supabase migration চালানো, প্রথম রান লগ দেখা, health-wellness-এর পণ্য পর্যালোচনা।
