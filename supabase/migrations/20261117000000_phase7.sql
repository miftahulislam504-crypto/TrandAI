-- Phase 7: ওয়াচলিস্ট, অ্যালার্ট, Data Health, নতুন ক্যাটাগরির সারি
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run। আবার চালালে ক্ষতি নেই।
-- (আগে phase1..phase6 চালানো থাকতে হবে। এটা না চালালেও স্কোরিং আগের মতো চলে, শুধু নতুন ফিচারগুলো কাজ করে না)

-- ------------------------------------------------------------------ ওয়াচলিস্ট
-- আপনি যে প্রোডাক্ট নজরে রাখতে চান। canonical প্রোডাক্ট ধরে, তাই একাধিক সাইটের listing মিলে এক সারি
create table if not exists watchlist (
  canonical_product_id  bigint primary key references canonical_products(id) on delete cascade,
  note                  text,
  added_at              timestamptz not null default now()
);
alter table watchlist enable row level security;
revoke all on watchlist from anon, authenticated;

create or replace function set_watch(p_canonical bigint, p_on boolean, p_note text default null)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  if p_canonical is null or not exists (select 1 from canonical_products where id = p_canonical) then
    raise exception 'প্রোডাক্ট % নেই', p_canonical;
  end if;
  if coalesce(p_on, false) then
    insert into watchlist (canonical_product_id, note)
    values (p_canonical, nullif(left(btrim(coalesce(p_note, '')), 200), ''))
    on conflict (canonical_product_id) do update
      set note = coalesce(excluded.note, watchlist.note);
    return true;
  end if;
  delete from watchlist where canonical_product_id = p_canonical;
  return false;
end $$;

-- ------------------------------------------------------------------- অ্যালার্ট
-- রোজ Score Daily-র পরে alerts.run_alerts লেখে। একই প্রোডাক্ট + ধরন + দিনে একটাই সারি (আবার চালালে নকল হয় না)
create table if not exists alerts (
  id                    bigserial primary key,
  canonical_product_id  bigint not null references canonical_products(id) on delete cascade,
  kind                  text not null check (kind in ('tier_change', 'score_move', 'price_move', 'redflag')),
  created_on            date not null,
  watched               boolean not null default false,     -- তৈরির সময় প্রোডাক্টটা ওয়াচলিস্টে ছিল কি না
  severity              text not null default 'info' check (severity in ('good', 'warn', 'info')),
  title                 text not null,
  detail                jsonb,
  seen_at               timestamptz,
  notified_at           timestamptz,                         -- Telegram-এ গেছে কি না (দুবার পাঠানো আটকাতে)
  created_at            timestamptz not null default now(),
  unique (canonical_product_id, kind, created_on)
);
create index if not exists alerts_unseen_idx on alerts (created_on desc) where seen_at is null;
create index if not exists alerts_product_idx on alerts (canonical_product_id, created_on desc);
alter table alerts enable row level security;
revoke all on alerts from anon, authenticated;

-- ids null হলে সব না-দেখা অ্যালার্ট "দেখা হয়েছে" হয়। ফেরত: কয়টা বদলাল
create or replace function mark_alerts_seen(p_ids bigint[] default null) returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  update alerts set seen_at = now() where seen_at is null and (p_ids is null or id = any(p_ids));
  get diagnostics n = row_count;
  return n;
end $$;

create or replace function mark_alerts_notified(p_ids bigint[]) returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  if p_ids is null or cardinality(p_ids) = 0 then return 0; end if;
  update alerts set notified_at = now() where notified_at is null and id = any(p_ids);
  get diagnostics n = row_count;
  return n;
end $$;

-- পুরনো অ্যালার্ট মোছে (ডিফল্ট ৬০ দিন)। ফেরত: কয়টা মুছল
create or replace function prune_alerts(p_keep_days integer default 60) returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  if p_keep_days is null or p_keep_days < 7 then
    raise exception 'কমপক্ষে ৭ দিনের অ্যালার্ট রাখতে হবে';
  end if;
  delete from alerts where created_on < (now() at time zone 'Asia/Dhaka')::date - p_keep_days;
  get diagnostics n = row_count;
  return n;
end $$;

-- ------------------------------------------------- মার্জে ওয়াচলিস্ট/কেনা দাম/Ads চেক হারানো আটকানো
-- আগের merge_canonicals শুধু listing, trend_keywords, ad_observations সরাত; loser মোছার সাথে loser-এর কেনা দাম
-- (product_costs) ও প্রোডাক্ট-নির্দিষ্ট ad_checks cascade-এ মুছে যেত। এখন সেগুলো winner-এ যায়।
-- winner-এর নিজের কেনা দাম থাকলে সেটাই থাকে।
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
  if to_regclass('public.product_costs') is not null then
    update product_costs set canonical_product_id = p_winner
     where canonical_product_id = p_loser
       and not exists (select 1 from product_costs w where w.canonical_product_id = p_winner);
  end if;
  if to_regclass('public.ad_checks') is not null then
    update ad_checks set canonical_product_id = p_winner where canonical_product_id = p_loser;
  end if;
  insert into watchlist (canonical_product_id, note)
  select p_winner, w.note from watchlist w where w.canonical_product_id = p_loser
  on conflict (canonical_product_id) do nothing;
  delete from canonical_products where id = p_loser;
end;
$$;

-- --------------------------------------------------------------------- Data Health
-- ড্যাশবোর্ডের /health পেজের জন্য এক ডাকে সব সংখ্যা (শুধু পড়ে, কিছু বদলায় না)। ভালো/খারাপের বিচার ড্যাশবোর্ডের কোডে।
-- কোনো টেবিল (যেমন ad_checks) না থাকলে সেই অংশ null, বাকিগুলো চলে।
create or replace function get_data_health() returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  today date := (now() at time zone 'Asia/Dhaka')::date;
  out   jsonb := jsonb_build_object('today', today);
  v     jsonb;
begin
  -- সোর্স ধরে স্ক্র্যাপ রান (শেষ ১৪ দিন)। যে সোর্সে কখনও রান হয়নি তা দেখানো হয় না
  select coalesce(jsonb_agg(t.j order by t.j ->> 'slug'), '[]'::jsonb) into v from (
    select jsonb_build_object(
      'slug', s.slug, 'name', s.name,
      'runs_14d',     count(r.id),
      'ok_14d',       count(r.id) filter (where r.status = 'ok'),
      'partial_14d',  count(r.id) filter (where r.status = 'partial'),
      'failed_14d',   count(r.id) filter (where r.status = 'failed'),
      'unfinished_14d', count(r.id) filter (where r.status is null),
      'items_ok_14d', coalesce(sum(r.items_ok), 0),
      'items_failed_14d', coalesce(sum(r.items_failed), 0),
      'last_run_at',  max(r.started_at),
      'last_ok_at',   max(r.started_at) filter (where r.status = 'ok'),
      'last_error',   (select e.error from scrape_runs e
                        where e.source_id = s.id and e.error is not null
                        order by e.started_at desc limit 1)
    ) as j
    from sources s
    left join scrape_runs r on r.source_id = s.id and r.started_at >= now() - interval '14 days'
    where exists (select 1 from scrape_runs x where x.source_id = s.id)
    group by s.id
  ) t;
  out := out || jsonb_build_object('sources', v);

  -- স্ন্যাপশট: কত দিন টানা ডেটা, কয়টা সক্রিয় listing আজ-গতকাল ধরা পড়েছে, বিক্রির সংখ্যা কত %-এ আছে
  select jsonb_build_object(
    'first_on', (select min(captured_on) from listing_snapshots),
    'latest_on', (select max(captured_on) from listing_snapshots),
    'days_with_data_30d', (select count(distinct captured_on) from listing_snapshots where captured_on >= today - 29),
    'streak_days', coalesce((
      with d as (select distinct captured_on from listing_snapshots),
           g as (select captured_on, captured_on - (row_number() over (order by captured_on))::int as grp from d)
      select count(*) from g where grp = (select grp from g order by captured_on desc limit 1)
    ), 0),
    'active_listings', (select count(*) from listings where is_active),
    'fresh_listings', (select count(distinct ls.listing_id) from listing_snapshots ls
                        join listings l on l.id = ls.listing_id and l.is_active
                        where ls.captured_on >= today - 1),
    'fresh_with_sold', (select count(distinct ls.listing_id) from listing_snapshots ls
                         join listings l on l.id = ls.listing_id and l.is_active
                         where ls.captured_on >= today - 1 and ls.sold_count is not null),
    'listings_by_category', coalesce((
      select jsonb_object_agg(coalesce(c.slug, 'অজানা'), n) from (
        select l.category_id, count(*) as n from listings l where l.is_active group by l.category_id
      ) q left join categories c on c.id = q.category_id), '{}'::jsonb)
  ) into v;
  out := out || jsonb_build_object('snapshots', v);

  -- স্কোর: সর্বশেষ দিনের ট্যাগ বণ্টন আর ১৪ দিনে ট্যাগ বদলের হার (flip rate)
  select jsonb_build_object(
    'latest_on', (select max(scored_on) from product_scores),
    'scored_latest', (select count(*) from product_scores where scored_on = (select max(scored_on) from product_scores)),
    'tiers_latest', coalesce((
      select jsonb_object_agg(coalesce(tier, 'none'), n) from (
        select tier, count(*) as n from product_scores
        where scored_on = (select max(scored_on) from product_scores) group by tier) q), '{}'::jsonb),
    'confidence_latest', coalesce((
      select jsonb_object_agg(coalesce(confidence, 'none'), n) from (
        select confidence, count(*) as n from product_scores
        where scored_on = (select max(scored_on) from product_scores) group by confidence) q), '{}'::jsonb),
    'products_14d', (select count(distinct canonical_product_id) from product_scores where scored_on >= today - 14),
    'tier_changes_14d', coalesce((
      select count(*) from (
        select tier, lag(tier) over (partition by canonical_product_id order by scored_on) as prev
        from product_scores where scored_on >= today - 15) q
      where prev is not null and tier is distinct from prev), 0)
  ) into v;
  out := out || jsonb_build_object('scores', v);

  -- Google Trends
  select jsonb_build_object(
    'latest_week', (select max(week_start) from trend_points),
    'keywords_total', (select count(*) from trend_keywords),
    'keywords_fresh', (select count(distinct keyword_id) from trend_points where week_start >= today - 35)
  ) into v;
  out := out || jsonb_build_object('trends', v);

  -- রিভিউ
  select jsonb_build_object(
    'total', count(*),
    'with_sentiment', count(*) filter (where sentiment is not null),
    'suspected_fake', count(*) filter (where suspected_fake)
  ) into v from reviews;
  out := out || jsonb_build_object('reviews', v);

  -- ঐচ্ছিক টেবিল: না থাকলে null
  begin
    select jsonb_build_object('last_on', max(observed_on),
                              'checks_45d', count(*) filter (where observed_on >= today - 45))
      into v from ad_checks;
    out := out || jsonb_build_object('ads', v);
  exception when undefined_table then
    out := out || jsonb_build_object('ads', null);
  end;
  begin
    select jsonb_build_object('pending', count(*) filter (where status = 'pending')) into v from match_candidates;
    out := out || jsonb_build_object('matching', v);
  exception when undefined_table then
    out := out || jsonb_build_object('matching', null);
  end;
  select jsonb_build_object('unseen', count(*) filter (where seen_at is null),
                            'last_on', max(created_on)) into v from alerts;
  out := out || jsonb_build_object('alerts', v);
  out := out || jsonb_build_object('watchlist', (select count(*) from watchlist));
  return out;
end $$;

-- ------------------------------------------------------------ নতুন ক্যাটাগরির সারি
-- এগুলো config/categories.json-এ প্রথমে বন্ধ (enabled: false) থাকে; সারি থাকলে চালু করার সময় আলাদা কিছু করতে হয় না
insert into categories (slug, name) values
  ('electronics', 'ইলেকট্রনিক্স ও গ্যাজেট'),
  ('beauty',      'বিউটি ও পার্সোনাল কেয়ার'),
  ('baby',        'বেবি ও কিডস'),
  ('sports',      'স্পোর্টস ও ফিটনেস')
on conflict (slug) do nothing;

-- ------------------------------------------------------------------- অনুমতি
revoke all on function set_watch(bigint, boolean, text) from public, anon, authenticated;
revoke all on function mark_alerts_seen(bigint[]) from public, anon, authenticated;
revoke all on function mark_alerts_notified(bigint[]) from public, anon, authenticated;
revoke all on function prune_alerts(integer) from public, anon, authenticated;
revoke all on function merge_canonicals(bigint, bigint) from public, anon, authenticated;
revoke all on function get_data_health() from public, anon, authenticated;
grant execute on function set_watch(bigint, boolean, text) to service_role;
grant execute on function mark_alerts_seen(bigint[]) to service_role;
grant execute on function mark_alerts_notified(bigint[]) to service_role;
grant execute on function prune_alerts(integer) to service_role;
grant execute on function merge_canonicals(bigint, bigint) to service_role;
grant execute on function get_data_health() to service_role;
