// ওয়াচলিস্ট/অ্যালার্ট পেজের ছোট সহায়ক। এক canonical প্রোডাক্টের একাধিক listing থাকতে পারে (ম্যাচিংয়ের পর)।
export type WithCanon = { canonical_product_id: number | null; sold_count?: number | null; id: number };

// প্রতি canonical প্রোডাক্টের জন্য একটাই listing: বেশি বিক্রির টা, সমান হলে ছোট id
export function pickPerCanonical<T extends WithCanon>(rows: T[]): Map<number, T> {
  const out = new Map<number, T>();
  for (const r of rows) {
    if (r.canonical_product_id === null) continue;
    const cur = out.get(r.canonical_product_id);
    const rs = r.sold_count ?? -1;
    const cs = cur ? cur.sold_count ?? -1 : -2;
    if (!cur || rs > cs || (rs === cs && r.id < cur.id)) out.set(r.canonical_product_id, r);
  }
  return out;
}

export const inList = (ids: number[]) => `in.(${ids.join(",")})`;
