export type Tier = "best" | "mid" | "dont" | null;

export const TIER_LABEL: Record<string, string> = { best: "Best", mid: "Mid", dont: "Don't" };

// কনফিডেন্স low বা provisional হলে ট্যাগের পাশে "?" দেখায়, যাতে অনিশ্চিত ট্যাগ নিশ্চিত মনে না হয়।
export function tierText(tier: string | null, confidence: string | null, provisional: string | null): string {
  if (!tier) return "স্কোর হয়নি";
  const base = TIER_LABEL[tier] ?? tier;
  if (provisional) return `${base} (${TIER_LABEL[provisional] ?? provisional}?)`;
  return confidence === "low" ? `${base}?` : base;
}

export const FACTOR_LABEL: Record<string, string> = {
  demand: "ডিমান্ড (বিক্রি)",
  trend: "ট্রেন্ড (বিক্রির গতি + Google)",
  review_quality: "রিভিউ মান",
  bad_review: "খারাপ রিভিউ (কম = ভালো)",
  ads_signal: "বিজ্ঞাপন সংকেত (Facebook Ads Library, হাতে-দেওয়া)",
  margin: "মার্জিন (আপনার কেনা দামে)",
  competition: "প্রতিযোগিতা (ট্র্যাক করা সেলার, কম = ভালো)",
};

export const TOPIC_BN: Record<string, string> = {
  quality: "মান", price: "দাম", delivery: "ডেলিভারি", packaging: "প্যাকেজিং", size_fit: "সাইজ/ফিট", color: "রং",
  durability: "টেকসইতা", authenticity: "আসল-নকল", service: "সেলারের সার্ভিস", description_match: "বর্ণনার সাথে মিল",
};

// কনফিগে না থাকলে (পুরনো স্কোর) এই ডিফল্ট দেখায়। আসল ওজন reasons.weights থেকে আসে
// এই তিনটার ডিফল্ট ওজন ০: স্কোরে ঢোকে না, শুধু তথ্য। config/scoring.json-এ ওজন বাড়ালে ঢোকে।
export const OPTIONAL_FACTORS = ["ads_signal", "margin", "competition"];

export const FACTOR_WEIGHT: Record<string, number> = {
  demand: 30, trend: 25, review_quality: 20, bad_review: 15, ads_signal: 0, margin: 0, competition: 0,
};
