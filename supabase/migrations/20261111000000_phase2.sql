-- Phase 2: সর্বশেষ স্কোরসহ listing ভিউ (ড্যাশবোর্ডের জন্য)
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run
-- (আগের দুটো migration চালানো থাকতে হবে)

create or replace view listing_scored with (security_invoker = true) as
select
  o.*,
  sc.scored_on,
  sc.total       as score,
  sc.tier,
  sc.confidence,
  sc.demand,
  sc.trend,
  sc.review_quality,
  sc.bad_review,
  sc.reasons,
  sc.reasons ->> 'provisional_tier' as provisional_tier
from listing_overview o
left join lateral (
  select p.*
  from product_scores p
  where p.canonical_product_id = o.canonical_product_id
  order by p.scored_on desc
  limit 1
) sc on true;

revoke all on listing_scored from anon, authenticated;
