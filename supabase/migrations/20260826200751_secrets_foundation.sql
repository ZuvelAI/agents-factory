create table public.secret_envelopes (
  id uuid primary key,
  tenant_id uuid not null,
  purpose text not null check (
    purpose = btrim(purpose)
    and length(purpose) between 1 and 200
  ),
  record_context text not null check (
    record_context = btrim(record_context)
    and length(record_context) between 1 and 500
  ),
  ciphertext bytea not null check (octet_length(ciphertext) >= 16),
  wrapped_data_key bytea not null check (octet_length(wrapped_data_key) = 48),
  payload_nonce bytea not null check (octet_length(payload_nonce) = 12),
  key_nonce bytea not null check (octet_length(key_nonce) = 12),
  algorithm text not null check (algorithm = 'AES-256-GCM'),
  format_version smallint not null check (format_version = 1),
  key_id text not null check (
    key_id = btrim(key_id)
    and length(key_id) between 1 and 200
  ),
  key_version integer not null check (key_version > 0),
  created_at timestamptz not null default now(),
  constraint secret_envelopes_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict,
  constraint secret_envelopes_key_nonce_key
    unique (key_id, key_version, key_nonce)
);

create index secret_envelopes_tenant_id_id_idx
on public.secret_envelopes (tenant_id, id);

alter table public.secret_envelopes enable row level security;
alter table public.secret_envelopes force row level security;

revoke all on table public.secret_envelopes
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

create policy secret_envelopes_app_select
on public.secret_envelopes for select
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy secret_envelopes_app_insert
on public.secret_envelopes for insert
to agents_factory_app
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy secret_envelopes_app_delete
on public.secret_envelopes for delete
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

grant select, insert, delete on table public.secret_envelopes
to agents_factory_app;
