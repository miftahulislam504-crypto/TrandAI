-- Phase 5: রিভিউয়ের ফ্ল্যাগ, কেনা দাম (মার্জিন) ইনপুট
-- চালানোর উপায়: Supabase Dashboard -> SQL Editor -> পুরোটা পেস্ট করে Run। আবার চালালে ক্ষতি নেই।
-- (আগে phase1..phase4b চালানো থাকতে হবে। এটা না চালালেও স্কোরিং আগের মতো চলে, শুধু নতুন ফিচারগুলো কাজ করে না)

-- রিভিউয়ের টেক্সট বিশ্লেষণের ফল। যেমন {counterfeit}। suspected_fake কলাম আগে থেকেই আছে
alter table reviews add column if not exists flags text[];

-- আপনার কেনা দাম (প্রতি পিস)। canonical প্রোডাক্ট ধরে, তাই একাধিক সাইটের listing মিলে এক প্রোডাক্টের এক দাম
create table if not exists product_costs (
  canonical_product_id  bigint primary key references canonical_products(id) on delete cascade,
  unit_cost             numeric not null check (unit_cost >= 0),
  extra_cost            numeric not null default 0 check (extra_cost >= 0),   -- প্রতি পিসে প্যাকেজিং, ডেলিভারি ইত্যাদি
  note                  text,
  updated_at            timestamptz not null default now()
);
alter table product_costs enable row level security;
revoke all on product_costs from anon, authenticated;

create or replace function set_product_cost(p_canonical bigint, p_unit_cost numeric, p_extra_cost numeric default 0, p_note text default null)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from canonical_products where id = p_canonical) then
    raise exception 'প্রোডাক্ট % নেই', p_canonical;
  end if;
  insert into product_costs (canonical_product_id, unit_cost, extra_cost, note, updated_at)
  values (p_canonical, p_unit_cost, coalesce(p_extra_cost, 0), nullif(trim(p_note), ''), now())
  on conflict (canonical_product_id) do update
    set unit_cost = excluded.unit_cost, extra_cost = excluded.extra_cost, note = excluded.note, updated_at = now();
end $$;

create or replace function clear_product_cost(p_canonical bigint) returns void
language sql security definer set search_path = public as $$
  delete from product_costs where canonical_product_id = p_canonical;
$$;

revoke all on function set_product_cost(bigint, numeric, numeric, text) from public, anon, authenticated;
revoke all on function clear_product_cost(bigint) from public, anon, authenticated;
grant execute on function set_product_cost(bigint, numeric, numeric, text) to service_role;
grant execute on function clear_product_cost(bigint) to service_role;
