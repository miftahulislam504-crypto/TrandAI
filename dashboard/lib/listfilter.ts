// প্রোডাক্ট তালিকার ফিল্টার/সর্ট (হোম পেজ ও CSV এক্সপোর্ট একই নিয়ম ব্যবহার করে, যাতে যা দেখছেন তা-ই নামে)।
export const SORTS: Record<string, string> = {
  score: "স্কোর",
  sold_delta_7d: "৭ দিনে বিক্রি বৃদ্ধি",
  sold_count: "মোট বিক্রি",
  review_delta_7d: "৭ দিনে রিভিউ বৃদ্ধি",
  review_count: "রিভিউ সংখ্যা",
  rating_avg: "রেটিং",
  price: "দাম",
  first_seen_at: "নতুন",
};
export const TIERS: Record<string, string> = { best: "Best", mid: "Mid", dont: "Don't", "best?": "সম্ভাব্য Best" };

export type ListQuery = { sort: string; tier: string; q: string; category: string; page: number };

export function parseListQuery(sp: Record<string, string | undefined>): ListQuery {
  return {
    sort: sp.sort && SORTS[sp.sort] ? sp.sort : "score",
    tier: sp.tier && TIERS[sp.tier] ? sp.tier : "",
    q: (sp.q || "").trim().slice(0, 60).replace(/[*,()]/g, " ").trim(),
    category: /^[a-z0-9_-]{1,40}$/.test(sp.category || "") ? (sp.category as string) : "",
    page: Math.max(1, Number(sp.page) || 1),
  };
}

export function listParams(q: ListQuery, select: string, limit: number, offset: number): Record<string, string> {
  const params: Record<string, string> = {
    select, is_active: "eq.true",
    order: `${q.sort}.${q.sort === "price" ? "asc" : "desc"}.nullslast`,
    limit: String(limit), offset: String(offset),
  };
  if (q.category) params.category = `eq.${q.category}`;
  if (q.tier === "best?") params["reasons->>provisional_tier"] = "eq.best";
  else if (q.tier) params.tier = `eq.${q.tier}`;
  if (q.q) params.title_raw = `ilike.*${q.q}*`;
  return params;
}
