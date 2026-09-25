create table public.whatsapp_contacts (
  id uuid primary key,
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  customer_wa_id text not null check (
    customer_wa_id = btrim(customer_wa_id) and length(customer_wa_id) between 1 and 100
  ),
  full_name text check (length(full_name) <= 1000),
  first_name text check (length(first_name) <= 1000),
  is_deleted boolean not null default false,
  provider_timestamp timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint whatsapp_contacts_account_fkey foreign key (tenant_id, whatsapp_account_id)
    references public.whatsapp_accounts(tenant_id, id) on delete restrict,
  constraint whatsapp_contacts_identity_key unique (tenant_id, whatsapp_account_id, customer_wa_id),
  constraint whatsapp_contacts_removed_names_check check (
    not is_deleted or (full_name is null and first_name is null)
  )
);

alter table public.whatsapp_contacts enable row level security;
alter table public.whatsapp_contacts force row level security;

revoke all on public.whatsapp_contacts from public, anon, authenticated, service_role,
  agents_factory_app, agents_factory_admin;
grant select, insert on public.whatsapp_contacts to agents_factory_app, agents_factory_admin;
grant update (full_name, first_name, is_deleted, provider_timestamp, updated_at)
  on public.whatsapp_contacts to agents_factory_app, agents_factory_admin;

create policy whatsapp_contacts_read on public.whatsapp_contacts for select
to agents_factory_app, agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy whatsapp_contacts_insert on public.whatsapp_contacts for insert
to agents_factory_app, agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy whatsapp_contacts_update on public.whatsapp_contacts for update
to agents_factory_app, agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
