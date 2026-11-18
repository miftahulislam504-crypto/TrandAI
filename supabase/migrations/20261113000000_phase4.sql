-- Phase 4: প্রোডাক্ট ম্যাচিং: রিভিউ কিউ টেবিল এবং মার্জ/স্প্লিট ফাংশন
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run
-- (আগের তিনটা migration চালানো থাকতে হবে। আবার চালালে ক্ষতি নেই।)

create table if not exists match_candidates (
  id           bigserial primary key,
  listing_a    bigint not null references listings(id) on delete cascade,
  listing_b    bigint not null references listings(id) on delete cascade,
  score        numeric not null,
  evidence     jsonb,
  -- pending = মানুষের সিদ্ধান্তের অপেক্ষায়, accepted/rejected = মানুষের সিদ্ধান্ত,
  -- auto = সিস্টেম নিজে মার্জ করেছে, stale = আর প্রাসঙ্গিক নয় (কিউতে দেখায় না)
  status       text not null default 'pending' check (status in ('pending', 'accepted', 'rejected', 'auto', 'stale')),
  created_at   timestamptz not null default now(),
  decided_at   timestamptz,
  decided_by   text,
  check (listing_a < listing_b),
  unique (listing_a, listing_b)
);
create index if not exists match_candidates_status_idx on match_candidates (status, score desc);

alter table match_candidates enable row level security;   -- কোনো policy নেই, শুধু service_role পড়তে-লিখতে পারে

-- দুই canonical product এক করে: loser-এর সব listing winner-এ যায়, loser মুছে যায়।
-- loser-এর স্কোর ইতিহাস মুছে যায় (cascade), winner-এর ইতিহাস থাকে। তাই সাধারণত কম id (পুরনো) winner।
create or replace function merge_canonicals(p_winner bigint, p_loser bigint) returns void
language plpgsql security definer set search_path = public as $$
begin
  if p_winner is null or p_loser is null or p_winner = p_loser then
    return;
  end if;
  if not exists (select 1 from canonical_products where id = p_winner)
     or not exists (select 1 from canonical_products where id = p_loser) then
    raise exception 'canonical product পাওয়া যায়নি: % / %', p_winner, p_loser;
  end if;
  update listings set canonical_product_id = p_winner where canonical_product_id = p_loser;
  update trend_keywords set canonical_product_id = p_winner where canonical_product_id = p_loser;
  update ad_observations set canonical_product_id = p_winner where canonical_product_id = p_loser;
  delete from canonical_products where id = p_loser;
end;
$$;

-- রিভিউ কিউর সিদ্ধান্ত: accept হলে মার্জ, reject হলে জোড়াটা চিরতরে বাদ (আর নিজে মার্জ হবে না)।
create or replace function decide_match(p_id bigint, p_accept boolean, p_by text default null) returns text
language plpgsql security definer set search_path = public as $$
declare
  c  match_candidates;
  ca bigint;
  cb bigint;
begin
  select * into c from match_candidates where id = p_id for update;
  if not found then
    raise exception 'match candidate % নেই', p_id;
  end if;
  if c.status in ('accepted', 'rejected') then
    return c.status;                                  -- আগেই সিদ্ধান্ত হয়ে গেছে
  end if;
  if p_accept then
    select canonical_product_id into ca from listings where id = c.listing_a;
    select canonical_product_id into cb from listings where id = c.listing_b;
    perform merge_canonicals(least(ca, cb), greatest(ca, cb));
  end if;
  update match_candidates
     set status = case when p_accept then 'accepted' else 'rejected' end,
         decided_at = now(), decided_by = p_by
   where id = p_id;
  return case when p_accept then 'accepted' else 'rejected' end;
end;
$$;

-- ভুল মার্জ ফেরানো: একটা listing-কে আলাদা নতুন প্রোডাক্ট বানায়, আর যে জোড়ায় মিলেছিল সেগুলো reject করে (আবার নিজে মার্জ হবে না)।
-- নতুন প্রোডাক্টের স্কোর পরের Score Daily থেকে শুরু হবে। ফেরত: নতুন canonical product-এর id।
create or replace function split_listing(p_listing bigint, p_by text default null) returns bigint
language plpgsql security definer set search_path = public as $$
declare
  l       listings;
  old_c   bigint;
  new_c   bigint;
begin
  select * into l from listings where id = p_listing;
  if not found then
    raise exception 'listing % নেই', p_listing;
  end if;
  old_c := l.canonical_product_id;
  if old_c is null or (select count(*) from listings where canonical_product_id = old_c) < 2 then
    return old_c;                                     -- আগে থেকেই একা, কিছু করার নেই
  end if;
  insert into canonical_products (name, brand, category_id)
  values (coalesce(l.title_raw, 'unknown'), l.brand_raw, l.category_id)
  returning id into new_c;
  update listings set canonical_product_id = new_c, match_confidence = null where id = p_listing;
  -- ওই listing আর বাকিদের মধ্যে যেসব জোড়া ছিল, সবগুলো reject (নতুন সারি বা আগেরটা বদলে)
  insert into match_candidates (listing_a, listing_b, score, status, decided_at, decided_by, evidence)
  select least(p_listing, o.id), greatest(p_listing, o.id), 0, 'rejected', now(), p_by, '{"note": "split_listing"}'::jsonb
  from listings o where o.canonical_product_id = old_c and o.id <> p_listing
  on conflict (listing_a, listing_b) do update
    set status = 'rejected', decided_at = now(), decided_by = excluded.decided_by;
  return new_c;
end;
$$;

revoke all on function merge_canonicals(bigint, bigint) from public, anon, authenticated;
revoke all on function decide_match(bigint, boolean, text) from public, anon, authenticated;
revoke all on function split_listing(bigint, text) from public, anon, authenticated;
grant execute on function merge_canonicals(bigint, bigint) to service_role;
grant execute on function decide_match(bigint, boolean, text) to service_role;
grant execute on function split_listing(bigint, text) to service_role;

-- রিভিউ কিউ দেখানোর ভিউ: জোড়ার দুই পাশের listing-এর সর্বশেষ তথ্যসহ
create or replace view match_queue with (security_invoker = true) as
select
  m.id, m.score, m.evidence, m.status, m.created_at,
  a.id as a_id, a.source as a_source, a.title_raw as a_title, a.url as a_url, a.price as a_price,
  a.rating_avg as a_rating, a.rating_count as a_rating_count, a.sold_count as a_sold, a.canonical_product_id as a_canonical,
  b.id as b_id, b.source as b_source, b.title_raw as b_title, b.url as b_url, b.price as b_price,
  b.rating_avg as b_rating, b.rating_count as b_rating_count, b.sold_count as b_sold, b.canonical_product_id as b_canonical
from match_candidates m
join listing_overview a on a.id = m.listing_a
join listing_overview b on b.id = m.listing_b;
