-- Phase 1: ড্যাশবোর্ডের ভিউ + listing থেকে canonical product বানানোর ফাংশন
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run
-- (আগে 20261109000000_init.sql চালানো থাকতে হবে)

-- ১:১ canonical product: কোন listing থেকে তৈরি হয়েছে তা মনে রাখার কলাম
alter table canonical_products add column if not exists seed_listing_id bigint unique;

-- যেসব listing-এর canonical product নেই, তাদের জন্য একটা করে বানায় ও যুক্ত করে।
-- Phase 4-এ প্রোডাক্ট ম্যাচিং এসে এগুলো মার্জ করবে।
create or replace function link_listings_to_canonical() returns integer
language plpgsql security definer set search_path = public as $$
declare
  n integer;
begin
  insert into canonical_products (name, brand, category_id, seed_listing_id)
  select coalesce(l.title_raw, 'unknown'), l.brand_raw, l.category_id, l.id
  from listings l
  where l.canonical_product_id is null
  on conflict (seed_listing_id) do nothing;

  update listings l
  set canonical_product_id = cp.id
  from canonical_products cp
  where cp.seed_listing_id = l.id and l.canonical_product_id is null;

  get diagnostics n = row_count;
  return n;
end;
$$;

revoke all on function link_listings_to_canonical() from public, anon, authenticated;
grant execute on function link_listings_to_canonical() to service_role;

-- ড্যাশবোর্ডের জন্য: প্রতিটা listing-এর সর্বশেষ স্ন্যাপশট + ৭ দিন আগের তুলনা
create or replace view listing_overview with (security_invoker = true) as
select
  l.id,
  s.slug                as source,
  l.external_id,
  l.canonical_product_id,
  l.url,
  l.title_raw,
  l.brand_raw,
  l.seller_name,
  c.slug                as category,
  l.first_seen_at,
  l.last_seen_at,
  l.is_active,
  cur.captured_on,
  cur.price,
  cur.original_price,
  cur.rating_avg,
  cur.rating_count,
  cur.review_count,
  cur.sold_count,
  cur.in_stock,
  prev.captured_on      as prev_captured_on,
  case when cur.sold_count is not null and prev.sold_count is not null
       then cur.sold_count - prev.sold_count end           as sold_delta_7d,
  case when cur.review_count is not null and prev.review_count is not null
       then cur.review_count - prev.review_count end       as review_delta_7d,
  case when cur.price is not null and prev.price is not null
       then cur.price - prev.price end                     as price_delta_7d
from listings l
join sources s on s.id = l.source_id
left join categories c on c.id = l.category_id
left join lateral (
  select x.* from listing_snapshots x
  where x.listing_id = l.id
  order by x.captured_on desc limit 1
) cur on true
left join lateral (
  select x.* from listing_snapshots x
  where x.listing_id = l.id and cur.captured_on is not null
    and x.captured_on <= cur.captured_on - 7
  order by x.captured_on desc limit 1
) prev on true;

-- ভিউ যেন anon/authenticated পড়তে না পারে (সার্ভার-সাইড service_role ছাড়া কেউ নয়)
revoke all on listing_overview from anon, authenticated;
