alter table public.whatsapp_history_inbox
  add constraint whatsapp_history_inbox_tenant_id_key unique (tenant_id, id);

create table public.whatsapp_history_messages (
  id uuid primary key,
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  provider_message_id text not null check (
    provider_message_id = btrim(provider_message_id)
    and length(provider_message_id) between 1 and 500
  ),
  customer_wa_id text not null check (
    customer_wa_id = btrim(customer_wa_id)
    and length(customer_wa_id) between 1 and 100
  ),
  direction text not null check (direction in ('inbound', 'outbound')),
  content jsonb not null check (jsonb_typeof(content) = 'object'),
  provider_timestamp timestamptz not null,
  created_at timestamptz not null default now(),
  constraint whatsapp_history_messages_account_fkey foreign key (tenant_id, whatsapp_account_id)
    references public.whatsapp_accounts(tenant_id, id) on delete restrict,
  constraint whatsapp_history_messages_identity_key unique (tenant_id, whatsapp_account_id, provider_message_id)
);

create index whatsapp_history_messages_customer_time_idx
  on public.whatsapp_history_messages (tenant_id, whatsapp_account_id, customer_wa_id, provider_timestamp, id);

create table public.whatsapp_history_import_receipts (
  id uuid primary key,
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  inbox_id uuid not null,
  outcome text not null check (outcome in ('IMPORTED', 'DECLINED')),
  progress jsonb not null check (jsonb_typeof(progress) = 'array'),
  errors jsonb not null check (jsonb_typeof(errors) = 'array'),
  created_at timestamptz not null default now(),
  constraint whatsapp_history_import_receipts_account_fkey foreign key (tenant_id, whatsapp_account_id)
    references public.whatsapp_accounts(tenant_id, id) on delete restrict,
  constraint whatsapp_history_import_receipts_inbox_fkey foreign key (tenant_id, inbox_id)
    references public.whatsapp_history_inbox(tenant_id, id) on delete restrict,
  constraint whatsapp_history_import_receipts_inbox_key unique (tenant_id, inbox_id)
);

alter table public.whatsapp_history_messages enable row level security;
alter table public.whatsapp_history_messages force row level security;
alter table public.whatsapp_history_import_receipts enable row level security;
alter table public.whatsapp_history_import_receipts force row level security;

revoke all on public.whatsapp_history_messages from public, anon, authenticated, service_role,
  agents_factory_app, agents_factory_admin;
revoke all on public.whatsapp_history_import_receipts from public, anon, authenticated, service_role,
  agents_factory_app, agents_factory_admin;
grant select, insert on public.whatsapp_history_messages to agents_factory_app, agents_factory_admin;
grant select, insert on public.whatsapp_history_import_receipts to agents_factory_app, agents_factory_admin;

create policy whatsapp_history_messages_read on public.whatsapp_history_messages for select
to agents_factory_app, agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy whatsapp_history_messages_insert on public.whatsapp_history_messages for insert
to agents_factory_app, agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy whatsapp_history_import_receipts_read on public.whatsapp_history_import_receipts for select
to agents_factory_app, agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy whatsapp_history_import_receipts_insert on public.whatsapp_history_import_receipts for insert
to agents_factory_app, agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
