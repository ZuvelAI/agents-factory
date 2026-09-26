create table public.whatsapp_sync_requests (
  id uuid primary key,
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  sync_type text not null check (sync_type in ('smb_app_state_sync', 'history')),
  state text not null check (state in ('UNKNOWN', 'ACCEPTED')),
  request_id text check (request_id is null or length(request_id) between 1 and 500),
  reserved_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint whatsapp_sync_requests_id_state_check check (
    (state = 'UNKNOWN' and request_id is null)
    or (state = 'ACCEPTED' and request_id is not null)
  ),
  constraint whatsapp_sync_requests_account_fkey foreign key (tenant_id, whatsapp_account_id)
    references public.whatsapp_accounts(tenant_id, id) on delete restrict,
  constraint whatsapp_sync_requests_once_key unique (tenant_id, whatsapp_account_id, sync_type)
);

alter table public.whatsapp_sync_requests enable row level security;
alter table public.whatsapp_sync_requests force row level security;
revoke all on public.whatsapp_sync_requests from public, anon, authenticated, service_role,
  agents_factory_app, agents_factory_admin;
grant select, insert on public.whatsapp_sync_requests to agents_factory_app, agents_factory_admin;
grant update (state, request_id, updated_at) on public.whatsapp_sync_requests
  to agents_factory_app, agents_factory_admin;

create policy whatsapp_sync_requests_read on public.whatsapp_sync_requests for select
to agents_factory_app, agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy whatsapp_sync_requests_insert on public.whatsapp_sync_requests for insert
to agents_factory_app, agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy whatsapp_sync_requests_update on public.whatsapp_sync_requests for update
to agents_factory_app, agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
