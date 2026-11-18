-- Phase 3: Google Trends সংগ্রহের অতিরিক্ত কলাম
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run
-- (আগের তিনটা migration চালানো থাকতে হবে। আবার চালালে ক্ষতি নেই।)

alter table trend_keywords
  add column if not exists lang                   text not null default 'en',   -- en | bn
  add column if not exists group_key              text,                         -- config/trends.json-এর entry id (en ও bn জোড়া বাঁধে)
  add column if not exists is_active              boolean not null default true,
  add column if not exists last_fetched_on        date,
  add column if not exists last_status            text,                         -- ok | no_data | low_volume | error
  add column if not exists last_error             text,
  add column if not exists seasonal               boolean,                      -- ৫ বছরের ডেটা থেকে শনাক্ত (null = এখনও জানা নেই)
  add column if not exists seasonal_corr          numeric,
  add column if not exists yoy_log                numeric,                      -- ln(গত ৪ সপ্তাহ / গত বছরের একই ৪ সপ্তাহ)
  add column if not exists seasonality_checked_on date;

create index if not exists trend_keywords_group_idx on trend_keywords (group_key);

alter table trend_points
  add column if not exists raw_value     numeric,    -- Google-এর ০–১০০ মান, রিকোয়েস্টের নিজস্ব স্কেলে
  add column if not exists anchor_value  numeric,    -- একই সপ্তাহে একই রিকোয়েস্টে anchor-এর raw মান (যাচাইয়ের জন্য)
  add column if not exists fetched_on    date;

-- RLS আগের migration-এই চালু, নতুন টেবিল নেই, তাই এখানে বাড়তি কিছু লাগে না।
