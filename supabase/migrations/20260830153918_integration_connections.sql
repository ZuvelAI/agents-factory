create table public.integration_connections (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  connector_name text not null check (connector_name in (
    'google_calendar', 'gmail', 'google_drive', 'google_sheets', 'woocommerce'
  )),
  auth_kind text not null check (auth_kind in ('OAUTH2', 'API_KEY')),
  status text not null default 'PENDING' check (status in (
    'PENDING', 'CONNECTED', 'REAUTH_REQUIRED', 'REVOKING', 'REVOKED'
  )),
  credential_secret_id uuid,
  requested_scopes text[] not null default '{}',
  granted_scopes text[] not null default '{}',
  authorization_version integer not null default 0 check (authorization_version >= 0),
  expires_at timestamptz,
  health_status text not null default 'UNKNOWN'
    check (health_status in ('UNKNOWN', 'HEALTHY', 'REAUTH_REQUIRED', 'ERROR')),
  last_health_checked_at timestamptz,
  last_error_code text check (last_error_code ~ '^[a-z][a-z0-9_]{0,119}$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id),
  foreign key (tenant_id, credential_secret_id)
    references public.secret_envelopes(tenant_id, id) on delete restrict,
  check (status <> 'CONNECTED' or credential_secret_id is not null),
  check (status <> 'REVOKED' or credential_secret_id is null),
  check ((connector_name = 'woocommerce') = (auth_kind = 'API_KEY'))
);

create index integration_connections_tenant_created_idx
on public.integration_connections (tenant_id, created_at, id);
create index integration_connections_secret_idx
on public.integration_connections (tenant_id, credential_secret_id)
where credential_secret_id is not null;

create table agents_factory_private.integration_oauth_states (
  state_digest text primary key check (state_digest ~ '^[a-f0-9]{64}$'),
  tenant_id uuid not null,
  connection_id uuid not null,
  admin_user_id uuid not null,
  admin_session_id uuid not null,
  authorization_version integer not null check (authorization_version > 0),
  verifier_secret_id uuid,
  code_challenge text not null check (code_challenge ~ '^[A-Za-z0-9_-]{43}$'),
  expires_at timestamptz not null,
  consumed_at timestamptz,
  created_at timestamptz not null default now(),
  foreign key (tenant_id, connection_id)
    references public.integration_connections(tenant_id, id) on delete cascade,
  foreign key (tenant_id, verifier_secret_id)
    references public.secret_envelopes(tenant_id, id) on delete restrict,
  check (expires_at > created_at)
);

create index integration_oauth_states_connection_idx
on agents_factory_private.integration_oauth_states (tenant_id, connection_id);
create index integration_oauth_states_secret_idx
on agents_factory_private.integration_oauth_states (tenant_id, verifier_secret_id)
where verifier_secret_id is not null;
create index integration_oauth_states_expiry_idx
on agents_factory_private.integration_oauth_states (expires_at)
where consumed_at is null;

alter table public.integration_connections enable row level security;
alter table public.integration_connections force row level security;
alter table agents_factory_private.integration_oauth_states enable row level security;
alter table agents_factory_private.integration_oauth_states force row level security;

revoke all on public.integration_connections,
  agents_factory_private.integration_oauth_states
from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;

create policy integration_connections_admin
on public.integration_connections for all to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy integration_connections_app_select
on public.integration_connections for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy integration_oauth_states_admin
on agents_factory_private.integration_oauth_states for all to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

grant select, insert, update, delete on public.integration_connections,
  agents_factory_private.integration_oauth_states to agents_factory_admin;
grant usage on schema agents_factory_private to agents_factory_admin;
grant select on public.integration_connections to agents_factory_app;
