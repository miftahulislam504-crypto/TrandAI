# সোর্স রোডম্যাপ: কোথায় কীভাবে রিসার্চ চলে

## এখন কোথায় চলছে
- **স্ক্র্যাপিং:** GitHub Actions (Daraz Daily রাত ২টা BDT, Trends Weekly, Match/Score Daily)
- **ডেটা:** Supabase (PostgreSQL)
- **দেখা:** Next.js ড্যাশবোর্ড (Vercel)
- **আসলে চালু কোড আছে:** Daraz, Google Trends। Facebook Ads Library আধা-ম্যানুয়াল (/ads)
- **আসল সাইটে একটাও রান যাচাই হয়নি।** সব স্মোক টেস্ট আপনার চালানোর অপেক্ষায়

## আপনার তালিকা: কোনটা কীভাবে
| ধরন | সোর্স | পদ্ধতি |
|---|---|---|
| নিজের স্ক্র্যাপার (অডিট পাস করলে) | Daraz, Cartup, Othoba, AjkerDeal, PriyoShop, Bagdoom, Pickaboo, Chaldal, Shajgoj, Aarong, Bikroy, Rokomari (+Electronics) | অডিট workflow আগে, adapter পরে |
| অফিসিয়াল API | YouTube (Data API v3), Google Trends (pytrends ঝুঁকিসহ) | auto |
| হাতে ইনপুট | Facebook Ad Library, Facebook Marketplace, Instagram, TikTok Creative Center, Pinterest Trends, Similarweb (ফ্রি) | ড্যাশবোর্ডের ম্যানুয়াল ফর্ম |
| বাদ বা পেইড-এক্সপোর্ট | Exploding Topics, Minea, Dropship.io, Pipiads | পেইড, API নেই, বাংলাদেশ কভারেজ দুর্বল। কিনলে CSV আপলোড |
| অজানা | Infoneen | লিংক লাগবে |

## পরের ধাপ
1. Actions → Source Audit (Phase 0) চালান (এখন ১৩টা সাইট), Summary পাঠান
2. রিপোর্ট দেখে প্রতি সাইটের Go / ফলব্যাক / বাদ ঠিক হবে
3. Go সাইটের adapter লেখা হবে (ফেজ ৪, ৮, ৯)
4. YouTube API key নিলে ফেজ ১০-এ যোগ হবে
