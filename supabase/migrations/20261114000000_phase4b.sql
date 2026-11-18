-- Phase 4 (ছবির মিল): listing-এ ছবির URL ও ছবির 64-বিট dHash
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run
-- (আগে 20261113000000_phase4.sql চালানো থাকতে হবে। আবার চালালে ক্ষতি নেই)

alter table listings add column if not exists image_url text;
-- 16 অক্ষরের hex (64 বিট)। null = এখনও হ্যাশ হয়নি, বা ছবিটা এত সমতল যে হ্যাশ ভরসাযোগ্য নয়
alter table listings add column if not exists image_hash text;
-- যে URL থেকে হ্যাশ বের হয়েছে। image_url বদলালে এটা না মেলায় আবার হ্যাশ হয়
alter table listings add column if not exists image_hash_url text;
alter table listings add column if not exists image_hashed_at timestamptz;

-- রিভিউ কিউতে দুই পাশের ছবি দেখানোর জন্য (নতুন কলাম শেষে, তাই আগের কলাম অক্ষত)
create or replace view match_queue with (security_invoker = true) as
select
  m.id, m.score, m.evidence, m.status, m.created_at,
  a.id as a_id, a.source as a_source, a.title_raw as a_title, a.url as a_url, a.price as a_price,
  a.rating_avg as a_rating, a.rating_count as a_rating_count, a.sold_count as a_sold, a.canonical_product_id as a_canonical,
  b.id as b_id, b.source as b_source, b.title_raw as b_title, b.url as b_url, b.price as b_price,
  b.rating_avg as b_rating, b.rating_count as b_rating_count, b.sold_count as b_sold, b.canonical_product_id as b_canonical,
  la.image_url as a_image,
  lb.image_url as b_image
from match_candidates m
join listing_overview a on a.id = m.listing_a
join listing_overview b on b.id = m.listing_b
join listings la on la.id = m.listing_a
join listings lb on lb.id = m.listing_b;

revoke all on match_queue from anon, authenticated;
