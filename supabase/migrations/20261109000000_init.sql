-- Market Research System: প্রাথমিক স্কিমা (খসড়া, Phase 1-এ ব্যবহার শুরু হবে)
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run

-- ---------------------------------------------------------------- sources
create table if not exists sources (
  id              serial primary key,
  slug            text unique not null,          -- daraz, cartup, othoba ...
  name            text not null,
  base_url        text,
  has_sold_count  boolean,                       -- null = এখনও অজানা (Phase 0 অডিটের পর ঠিক হবে)
  is_active       boolean not null default true
);

create table if not exists categories (
  id         serial primary key,
  slug       text unique not null,
  name       text not null,
  parent_id  int references categories(id)
);

-- ------------------------------------------------------ canonical products
create table if not exists canonical_products (
  id           bigserial primary key,
  name         text not null,
  brand        text,
  model        text,
  isbn         text,                             -- বইয়ের জন্য
  category_id  int references categories(id),
  created_at   timestamptz not null default now()
);

-- ----------------------------------------------------------------- listings
create table if not exists listings (
  id                    bigserial primary key,
  source_id             int not null references sources(id),
  external_id           text not null,           -- প্ল্যাটফর্মের নিজস্ব product id
  url                   text not null,
  title_raw             text,
  brand_raw             text,
  seller_name           text,
  category_id           int references categories(id),
  canonical_product_id  bigint references canonical_products(id),
  match_confidence      numeric,
  first_seen_at         timestamptz not null default now(),
  last_seen_at          timestamptz,
  is_active             boolean not null default true,
  unique (source_id, external_id)
);
create index if not exists listings_canonical_idx on listings (canonical_product_id);
create index if not exists listings_category_idx on listings (category_id);

create table if not exists listing_snapshots (
  listing_id      bigint not null references listings(id) on delete cascade,
  captured_on     date not null,
  price           numeric,
  original_price  numeric,
  rating_avg      numeric,
  rating_count    int,
  review_count    int,
  sold_count      int,                           -- null মানে সোর্সে নেই
  in_stock        boolean,
  primary key (listing_id, captured_on)
);
create index if not exists snapshots_date_idx on listing_snapshots (captured_on);

-- ------------------------------------------------------------------ reviews
create table if not exists reviews (
  id                  bigserial primary key,
  listing_id          bigint not null references listings(id) on delete cascade,
  external_review_id  text,
  stars               smallint check (stars between 1 and 5),
  body                text,
  lang                text,                      -- bn, en, banglish
  reviewed_at         date,
  reviewer_hash       text,                      -- নাম নয়, হ্যাশ
  suspected_fake      boolean not null default false,
  sentiment           smallint check (sentiment between -1 and 1),
  topics              text[],
  unique (listing_id, external_review_id)
);
create index if not exists reviews_listing_date_idx on reviews (listing_id, reviewed_at);

-- ------------------------------------------------------------ google trends
create table if not exists trend_keywords (
  id                    serial primary key,
  keyword               text not null,
  geo                   text not null default 'BD',
  canonical_product_id  bigint references canonical_products(id),
  category_id           int references categories(id),
  unique (keyword, geo)
);

create table if not exists trend_points (
  keyword_id  int not null references trend_keywords(id) on delete cascade,
  week_start  date not null,
  value       numeric,                           -- anchor কীওয়ার্ড দিয়ে নর্মালাইজড
  primary key (keyword_id, week_start)
);

-- ---------------------------------------------------------- facebook ads
create table if not exists ad_observations (
  id                    bigserial primary key,
  canonical_product_id  bigint references canonical_products(id),
  keyword               text,
  page_name             text,
  ad_library_id         text,
  ad_start_date         date,
  destination_url       text,
  observed_on           date not null,
  is_active             boolean,
  unique (ad_library_id, observed_on)
);

-- ------------------------------------------------------------------ scores
create table if not exists product_scores (
  canonical_product_id  bigint not null references canonical_products(id) on delete cascade,
  scored_on             date not null,
  demand                numeric,
  trend                 numeric,
  review_quality        numeric,
  bad_review            numeric,
  ads_signal            numeric,
  total                 numeric,
  tier                  text check (tier in ('best', 'mid', 'dont')),
  confidence            text check (confidence in ('high', 'medium', 'low')),
  reasons               jsonb,
  primary key (canonical_product_id, scored_on)
);
create index if not exists scores_tier_idx on product_scores (scored_on, tier);

-- ------------------------------------------------------------- scrape runs
create table if not exists scrape_runs (
  id            bigserial primary key,
  source_id     int references sources(id),
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  status        text check (status in ('ok', 'partial', 'failed')),
  items_ok      int,
  items_failed  int,
  error         text
);

-- -------------------------------------------------------------------- seed
insert into sources (slug, name, base_url) values
  ('daraz',     'Daraz',     'https://www.daraz.com.bd'),
  ('cartup',    'Cartup',    'https://cartup.com'),
  ('othoba',    'Othoba',    'https://www.othoba.com'),
  ('bagdoom',   'Bagdoom',   'https://www.bagdoom.com'),
  ('ajkerdeal', 'AjkerDeal', 'https://www.ajkerdeal.com'),
  ('priyoshop', 'PriyoShop', 'https://www.priyoshop.com'),
  ('rokomari',  'Rokomari',  'https://www.rokomari.com')
on conflict (slug) do nothing;

insert into categories (slug, name) values
  ('fashion', 'ফ্যাশন'),
  ('home',    'হোম'),
  ('kitchen', 'কিচেন')
on conflict (slug) do nothing;

-- ---------------------------------------------------------------- security
-- Supabase-এ public স্কিমার টেবিল anon key দিয়ে পাবলিকলি পড়া যায়, যদি RLS বন্ধ থাকে।
-- তাই সব টেবিলে RLS চালু, কোনো policy নেই: anon/authenticated কিছুই দেখতে পাবে না।
-- স্ক্র্যাপার ও ড্যাশবোর্ডের সার্ভার-সাইড কোড service_role key ব্যবহার করবে (RLS বাইপাস করে)।
-- service_role key কখনও ব্রাউজার কোডে বা পাবলিক রিপোতে দেবেন না।
alter table sources            enable row level security;
alter table categories         enable row level security;
alter table canonical_products enable row level security;
alter table listings           enable row level security;
alter table listing_snapshots  enable row level security;
alter table reviews            enable row level security;
alter table trend_keywords     enable row level security;
alter table trend_points       enable row level security;
alter table ad_observations    enable row level security;
alter table product_scores     enable row level security;
alter table scrape_runs        enable row level security;
