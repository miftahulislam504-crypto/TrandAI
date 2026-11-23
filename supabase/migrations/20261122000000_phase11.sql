-- Phase 11: হাতে-দেওয়া সিগন্যাল (manual_signals) ও তা রাখা/মোছার SQL ফাংশন (ড্যাশবোর্ডের /signals পেজ)
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run। আবার চালালে ক্ষতি নেই।
-- (আগে phase1..phase9 চালানো থাকতে হবে। এটা না চালালে স্কোরিং আগের মতো চলে, শুধু /signals সেভ হয় না)
--
-- এক সারি = একটা সোর্সে (TikTok Creative Center, Pinterest Trends, Infoneen, Similarweb, YouTube) একদিন হাতে দেখা একটা মান।
-- এখন এটা শুধু রাখা ও দেখানোর জন্য, স্কোরে ঢোকে না (ওজন ঠিক করার আগে আসল ডেটা জমুক)।
-- Meta Ads Library এখানে নয়: ওটা আগের মতো /ads (ad_checks) দিয়ে যায়।

create table if not exists manual_signals (
  id                    bigserial primary key,
  source                text not null check (source in
                          ('tiktok_creative_center', 'pinterest_trends', 'infoneen', 'similarweb', 'youtube', 'other')),
  keyword               text check (keyword is null or char_length(btrim(keyword)) between 1 and 80),
  keyword_norm          text,                                  -- ছোট হাতের, বাড়তি ফাঁকা ছাড়া
  canonical_product_id  bigint references canonical_products(id) on delete cascade,  -- null = শব্দ/ধরনের সিগন্যাল
  observed_on           date not null,
  value                 numeric check (value is null or abs(value) < 1000000000000),
  unit                  text check (unit is null or char_length(unit) <= 24),   -- যেমন ভিউ, সার্চ/মাস, ভিজিট, %
  link                  text check (link is null or (link ~* '^https?://[^\s]+$' and char_length(link) <= 500)),
  note                  text check (note is null or char_length(note) <= 200),
  created_at            timestamptz not null default now(),
  check (keyword is not null or canonical_product_id is not null),   -- শব্দ বা প্রোডাক্ট, একটা লাগবেই
  check (value is not null or note is not null)                      -- মান বা নোট, একটা লাগবেই
);
create index if not exists manual_signals_kw_idx on manual_signals (keyword_norm, observed_on desc);
create index if not exists manual_signals_src_idx on manual_signals (source, observed_on desc);
create index if not exists manual_signals_product_idx on manual_signals (canonical_product_id) where canonical_product_id is not null;

alter table manual_signals enable row level security;
revoke all on manual_signals from anon, authenticated;

-- একটা সিগন্যাল রাখে। একই সোর্স + শব্দ/প্রোডাক্ট + তারিখ + একক আবার দিলে আগেরটা বদলে যায়। ভুল ইনপুটে বাংলা বার্তায় থামে।
create or replace function record_manual_signal(
  p_source text, p_keyword text default null, p_value numeric default null, p_unit text default null,
  p_link text default null, p_note text default null, p_canonical bigint default null, p_observed_on date default null
) returns bigint language plpgsql security definer set search_path = public as $$
declare
  v_day  date := coalesce(p_observed_on, (now() at time zone 'Asia/Dhaka')::date);
  v_kw   text := nullif(regexp_replace(btrim(coalesce(p_keyword, '')), '\s+', ' ', 'g'), '');
  v_norm text := lower(v_kw);
  v_unit text := nullif(left(btrim(coalesce(p_unit, '')), 24), '');
  v_link text := nullif(btrim(coalesce(p_link, '')), '');
  v_note text := nullif(left(btrim(coalesce(p_note, '')), 200), '');
  v_id   bigint;
begin
  if p_source is null or p_source not in ('tiktok_creative_center', 'pinterest_trends', 'infoneen', 'similarweb', 'youtube', 'other') then
    raise exception 'সোর্স ঠিক নয়';
  end if;
  if v_kw is null and p_canonical is null then
    raise exception 'শব্দ বা প্রোডাক্ট দিতে হবে';
  end if;
  if v_kw is not null and char_length(v_kw) > 80 then
    raise exception 'শব্দ ১–৮০ অক্ষরের হতে হবে';
  end if;
  if p_value is null and v_note is null then
    raise exception 'মান বা নোট, অন্তত একটা দিতে হবে';
  end if;
  if p_value is not null and abs(p_value) >= 1000000000000 then
    raise exception 'মান অস্বাভাবিক বড়';
  end if;
  if v_link is not null and (v_link !~* '^https?://[^\s]+$' or char_length(v_link) > 500) then
    raise exception 'লিংক http:// বা https:// দিয়ে শুরু হতে হবে (সর্বোচ্চ ৫০০ অক্ষর)';
  end if;
  if v_day > (now() at time zone 'Asia/Dhaka')::date then
    raise exception 'তারিখ ভবিষ্যতের হতে পারে না';
  end if;
  if v_day < date '2018-01-01' then
    raise exception 'তারিখ ২০১৮-র আগের হতে পারে না';
  end if;
  if p_canonical is not null and not exists (select 1 from canonical_products where id = p_canonical) then
    raise exception 'প্রোডাক্ট % নেই', p_canonical;
  end if;

  delete from manual_signals
   where source = p_source and observed_on = v_day
     and keyword_norm is not distinct from v_norm
     and canonical_product_id is not distinct from p_canonical
     and unit is not distinct from v_unit;
  insert into manual_signals (source, keyword, keyword_norm, canonical_product_id, observed_on, value, unit, link, note)
  values (p_source, v_kw, v_norm, p_canonical, v_day, p_value, v_unit, v_link, v_note)
  returning id into v_id;
  return v_id;
end $$;

create or replace function delete_manual_signal(p_id bigint) returns void
language sql security definer set search_path = public as $$
  delete from manual_signals where id = p_id;
$$;

revoke all on function record_manual_signal(text, text, numeric, text, text, text, bigint, date) from public, anon, authenticated;
revoke all on function delete_manual_signal(bigint) from public, anon, authenticated;
grant execute on function record_manual_signal(text, text, numeric, text, text, text, bigint, date) to service_role;
grant execute on function delete_manual_signal(bigint) to service_role;
