create table public.whatsapp_history_inbox (
  id uuid primary key,
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  payload_digest text not null check (payload_digest ~ '^[0-9a-f]{64}$'),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  received_at timestamptz not null default now(),
  constraint whatsapp_history_inbox_account_fkey foreign key (tenant_id, whatsapp_account_id)
    references public.whatsapp_accounts(tenant_id, id) on delete restrict,
  constraint whatsapp_history_inbox_dedup_key unique (tenant_id, whatsapp_account_id, payload_digest)
);

alter table public.whatsapp_history_inbox enable row level security;
alter table public.whatsapp_history_inbox force row level security;
revoke all on public.whatsapp_history_inbox from public, anon, authenticated, service_role,
  agents_factory_app, agents_factory_admin;
grant select, insert on public.whatsapp_history_inbox to agents_factory_app, agents_factory_admin;

create policy whatsapp_history_inbox_read on public.whatsapp_history_inbox for select
to agents_factory_app, agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy whatsapp_history_inbox_insert on public.whatsapp_history_inbox for insert
to agents_factory_app, agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
