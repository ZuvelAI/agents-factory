-- Live sender profiles are separate from the synced phonebook: receiving a
-- profile must not make a new sender ineligible for their first welcome.
create table public.whatsapp_contact_profiles (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  customer_wa_id text not null check (length(customer_wa_id) between 1 and 100),
  profile_name text check (length(profile_name) between 1 and 1000),
  username text check (length(username) between 1 and 200),
  phone_number text check (phone_number ~ '^\+[1-9][0-9]{6,14}$'),
  provider_timestamp timestamptz not null,
  updated_at timestamptz not null default now(),
  unique (tenant_id, whatsapp_account_id, customer_wa_id),
  foreign key (tenant_id, whatsapp_account_id)
    references public.whatsapp_accounts(tenant_id, id) on delete restrict
);

alter table public.whatsapp_contact_profiles enable row level security;
alter table public.whatsapp_contact_profiles force row level security;
revoke all on public.whatsapp_contact_profiles from public, anon, authenticated,
  service_role, agents_factory_app, agents_factory_admin;
grant select, insert on public.whatsapp_contact_profiles to agents_factory_app, agents_factory_admin;
grant update (profile_name, username, phone_number, provider_timestamp, updated_at)
  on public.whatsapp_contact_profiles to agents_factory_app, agents_factory_admin;

create policy contact_profiles_read on public.whatsapp_contact_profiles for select
to agents_factory_app, agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy contact_profiles_insert on public.whatsapp_contact_profiles for insert
to agents_factory_app, agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy contact_profiles_update on public.whatsapp_contact_profiles for update
to agents_factory_app, agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
