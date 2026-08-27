create table public.whatsapp_accounts (
  id uuid primary key,
  tenant_id uuid not null,
  provider text not null check (provider = 'meta'),
  waba_id text not null check (
    waba_id = btrim(waba_id) and length(waba_id) between 1 and 200
  ),
  phone_number_id text not null check (
    phone_number_id = btrim(phone_number_id)
    and length(phone_number_id) between 1 and 200
  ),
  status text not null default 'active' check (status in ('active', 'inactive')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint whatsapp_accounts_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict,
  constraint whatsapp_accounts_provider_phone_number_id_key
    unique (provider, phone_number_id),
  constraint whatsapp_accounts_tenant_id_id_key unique (tenant_id, id)
);

create table public.whatsapp_webhook_events (
  id uuid primary key,
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  whatsapp_message_id text not null check (
    whatsapp_message_id = btrim(whatsapp_message_id)
    and length(whatsapp_message_id) between 1 and 500
  ),
  sender_wa_id text not null check (
    sender_wa_id = btrim(sender_wa_id)
    and length(sender_wa_id) between 1 and 100
  ),
  message_type text not null check (
    message_type in (
      'text', 'audio', 'image', 'document', 'location', 'contacts', 'video'
    )
  ),
  provider_timestamp timestamptz not null,
  raw_payload jsonb not null,
  received_at timestamptz not null default now(),
  constraint whatsapp_webhook_events_account_fkey
    foreign key (tenant_id, whatsapp_account_id)
    references public.whatsapp_accounts(tenant_id, id) on delete restrict,
  constraint whatsapp_webhook_events_raw_payload_object_check
    check (jsonb_typeof(raw_payload) = 'object'),
  constraint whatsapp_webhook_events_tenant_message_key
    unique (tenant_id, whatsapp_message_id)
);

create index whatsapp_accounts_tenant_id_idx
on public.whatsapp_accounts (tenant_id);

create index whatsapp_accounts_active_mapping_idx
on public.whatsapp_accounts (waba_id, phone_number_id)
where provider = 'meta' and status = 'active';

create index whatsapp_webhook_events_account_idx
on public.whatsapp_webhook_events (tenant_id, whatsapp_account_id);

create function agents_factory_private.resolve_active_whatsapp_account(
  p_waba_id text,
  p_phone_number_id text
)
returns table (account_id uuid, tenant_id uuid)
language sql
stable
security definer
set search_path = ''
as $function$
  select account.id, account.tenant_id
  from public.whatsapp_accounts as account
  where account.provider = 'meta'
    and account.status = 'active'
    and account.waba_id = p_waba_id
    and account.phone_number_id = p_phone_number_id
  limit 1
$function$;

revoke all on function
  agents_factory_private.resolve_active_whatsapp_account(text, text)
from public, anon, authenticated, service_role, agents_factory_admin;

grant usage on schema agents_factory_private
to agents_factory_app;

grant execute on function
  agents_factory_private.resolve_active_whatsapp_account(text, text)
to agents_factory_app;

alter table public.whatsapp_accounts enable row level security;
alter table public.whatsapp_accounts force row level security;
alter table public.whatsapp_webhook_events enable row level security;
alter table public.whatsapp_webhook_events force row level security;

revoke all on table public.whatsapp_accounts
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

revoke all on table public.whatsapp_webhook_events
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

create policy whatsapp_accounts_app_select
on public.whatsapp_accounts for select
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy whatsapp_accounts_admin_select
on public.whatsapp_accounts for select
to agents_factory_admin
using (true);

create policy whatsapp_accounts_admin_insert
on public.whatsapp_accounts for insert
to agents_factory_admin
with check (true);

create policy whatsapp_accounts_admin_update
on public.whatsapp_accounts for update
to agents_factory_admin
using (true)
with check (true);

create policy whatsapp_webhook_events_app_select
on public.whatsapp_webhook_events for select
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy whatsapp_webhook_events_app_insert
on public.whatsapp_webhook_events for insert
to agents_factory_app
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy whatsapp_webhook_events_admin_select
on public.whatsapp_webhook_events for select
to agents_factory_admin
using (true);

grant select on table public.whatsapp_accounts
to agents_factory_app;

grant select, insert, update on table public.whatsapp_accounts
to agents_factory_admin;

grant select, insert on table public.whatsapp_webhook_events
to agents_factory_app;

grant select on table public.whatsapp_webhook_events
to agents_factory_admin;
