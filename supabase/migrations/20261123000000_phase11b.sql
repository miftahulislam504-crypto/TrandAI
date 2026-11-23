-- Phase 11: YouTube Data API থেকে শব্দ-ভিত্তিক ভিডিও ট্রেন্ড (youtube_keyword_stats)
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run। আবার চালালে ক্ষতি নেই।
-- (YOUTUBE_API_KEY GitHub Secrets-এ দেওয়ার আগে এটা চালানো ভালো। না চালালে YouTube workflow ডাটাবেজে লিখতে গিয়ে থামবে)
--
-- এক সারি = একটা শব্দ একদিনে: গত window_days দিনে বাংলাদেশে ভিউ-অনুযায়ী শীর্ষ ভিডিওগুলোর সারাংশ।
-- এখন শুধু জমা হয়, স্কোরে ঢোকে না।

create table if not exists youtube_keyword_stats (
  id               bigserial primary key,
  group_key        text not null,                -- config/trends.json-এর entry id (ইংরেজি ও বাংলা শব্দ জোড়া বাঁধে)
  keyword          text not null,
  lang             text not null default 'en' check (lang in ('en', 'bn')),
  category         text,
  region           text not null default 'BD',
  fetched_on       date not null,
  window_days      int  not null check (window_days > 0),
  videos           int  not null check (videos >= 0),       -- পাওয়া ভিডিও (সর্বোচ্চ max_results)
  views_total      bigint check (views_total >= 0),          -- সংখ্যা লুকানো ভিডিও বাদে; null = কোনো ভিডিওর ভিউ জানা নেই
  views_median     bigint check (views_median >= 0),
  top_video_id     text,
  top_video_title  text,
  top_video_views  bigint check (top_video_views >= 0),
  top_channel      text,
  created_at       timestamptz not null default now(),
  unique (keyword, lang, region, fetched_on)
);
create index if not exists youtube_keyword_stats_group_idx on youtube_keyword_stats (group_key, fetched_on desc);

alter table youtube_keyword_stats enable row level security;
revoke all on youtube_keyword_stats from anon, authenticated;
