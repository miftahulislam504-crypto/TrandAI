-- Phase 6: Facebook Ads Library হাতে-দেওয়া চেক (ad_checks) ও তা রাখা/মোছার SQL ফাংশন
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run। আবার চালালে ক্ষতি নেই।
-- (আগে phase1..phase5 চালানো থাকতে হবে। এটা না চালালেও স্কোরিং আগের মতো চলে, শুধু বিজ্ঞাপন সংকেত কাজ করে না)
--
-- এক সারি = একটা শব্দ (বা একটা প্রোডাক্ট) একদিন Ads Library-তে খুঁজে যা দেখলেন তার সারাংশ।
-- আগের ad_observations টেবিল (প্রতিটা বিজ্ঞাপনের আলাদা সারি) অক্ষত আছে, স্বয়ংক্রিয় সংগ্রহ আসার জন্য রাখা। Phase 6 সেটা ব্যবহার করে না।

create table if not exists ad_checks (
  id                    bigserial primary key,
  keyword               text not null check (char_length(btrim(keyword)) between 1 and 80),
  keyword_norm          text not null,                       -- ছোট হাতের, বাড়তি ফাঁকা ছাড়া; একই শব্দ চেনার জন্য
  canonical_product_id  bigint references canonical_products(id) on delete cascade,  -- null = প্রোডাক্টের ধরনের (segment) চেক
  observed_on           date not null,
  active_ads            int  not null check (active_ads >= 0),   -- Ads Library-র ফলাফল সংখ্যা (সক্রিয় বিজ্ঞাপন)
  advertisers           int  check (advertisers >= 0),            -- দেখা অংশে আলাদা পেজ (সর্বনিম্ন সংখ্যা)
  oldest_start          date,                                     -- সবচেয়ে পুরনো সক্রিয় বিজ্ঞাপনের শুরুর তারিখ
  new_30d               int  check (new_30d >= 0),                -- গত ৩০ দিনে শুরু হওয়া বিজ্ঞাপন
  source                text not null default 'manual' check (source in ('manual', 'auto')),
  note                  text,
  created_at            timestamptz not null default now(),
  check (advertisers is null or advertisers <= active_ads),
  check (new_30d is null or new_30d <= active_ads),
  check (oldest_start is null or oldest_start <= observed_on)
);
create index if not exists ad_checks_kw_idx on ad_checks (keyword_norm, observed_on desc);
create index if not exists ad_checks_product_idx on ad_checks (canonical_product_id) where canonical_product_id is not null;

alter table ad_checks enable row level security;
revoke all on ad_checks from anon, authenticated;

-- একটা চেক রাখে। একই শব্দ + একই প্রোডাক্ট + একই তারিখে আবার দিলে আগেরটা বদলে যায়। ভুল ইনপুটে বাংলা বার্তায় থামে।
create or replace function record_ad_check(
  p_keyword text, p_active_ads int, p_advertisers int default null, p_oldest_start date default null,
  p_new_30d int default null, p_canonical bigint default null, p_note text default null, p_observed_on date default null
) returns bigint language plpgsql security definer set search_path = public as $$
declare
  v_day  date := coalesce(p_observed_on, (now() at time zone 'Asia/Dhaka')::date);
  v_norm text := lower(regexp_replace(btrim(coalesce(p_keyword, '')), '\s+', ' ', 'g'));
  v_id   bigint;
begin
  if v_norm = '' or char_length(v_norm) > 80 then
    raise exception 'শব্দ ১–৮০ অক্ষরের হতে হবে';
  end if;
  if p_active_ads is null or p_active_ads < 0 then
    raise exception 'বিজ্ঞাপন সংখ্যা ০ বা তার বেশি হতে হবে';
  end if;
  if p_advertisers is not null and (p_advertisers < 0 or p_advertisers > p_active_ads) then
    raise exception 'বিজ্ঞাপনদাতা সংখ্যা বিজ্ঞাপন সংখ্যার বেশি হতে পারে না';
  end if;
  if p_new_30d is not null and (p_new_30d < 0 or p_new_30d > p_active_ads) then
    raise exception 'গত ৩০ দিনের নতুন বিজ্ঞাপন মোট বিজ্ঞাপনের বেশি হতে পারে না';
  end if;
  if p_active_ads = 0 and (coalesce(p_advertisers, 0) > 0 or p_oldest_start is not null or coalesce(p_new_30d, 0) > 0) then
    raise exception 'বিজ্ঞাপন ০ হলে বিজ্ঞাপনদাতা, শুরুর তারিখ বা নতুন বিজ্ঞাপন দেওয়া যায় না';
  end if;
  if v_day > (now() at time zone 'Asia/Dhaka')::date then
    raise exception 'চেকের তারিখ ভবিষ্যতের হতে পারে না';
  end if;
  if p_oldest_start is not null and (p_oldest_start > v_day or p_oldest_start < date '2018-01-01') then
    raise exception 'সবচেয়ে পুরনো বিজ্ঞাপনের তারিখ ২০১৮-র পরে ও চেকের তারিখের আগে হতে হবে';
  end if;
  if p_canonical is not null and not exists (select 1 from canonical_products where id = p_canonical) then
    raise exception 'প্রোডাক্ট % নেই', p_canonical;
  end if;

  delete from ad_checks
   where keyword_norm = v_norm and observed_on = v_day and canonical_product_id is not distinct from p_canonical;
  insert into ad_checks (keyword, keyword_norm, canonical_product_id, observed_on, active_ads, advertisers, oldest_start, new_30d, note)
  values (regexp_replace(btrim(p_keyword), '\s+', ' ', 'g'), v_norm, p_canonical, v_day, p_active_ads, p_advertisers,
          p_oldest_start, p_new_30d, nullif(left(btrim(coalesce(p_note, '')), 200), ''))
  returning id into v_id;
  return v_id;
end $$;

create or replace function delete_ad_check(p_id bigint) returns void
language sql security definer set search_path = public as $$
  delete from ad_checks where id = p_id;
$$;

revoke all on function record_ad_check(text, int, int, date, int, bigint, text, date) from public, anon, authenticated;
revoke all on function delete_ad_check(bigint) from public, anon, authenticated;
grant execute on function record_ad_check(text, int, int, date, int, bigint, text, date) to service_role;
grant execute on function delete_ad_check(bigint) to service_role;
