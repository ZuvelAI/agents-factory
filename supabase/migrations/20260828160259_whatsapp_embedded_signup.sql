alter table public.secret_envelopes
add constraint secret_envelopes_tenant_id_id_key unique (tenant_id, id);

alter table public.whatsapp_accounts
add column access_token_secret_id uuid,
add column business_id text check (
  business_id is null or (
    business_id = btrim(business_id) and length(business_id) between 1 and 200
  )
),
add column mode text not null default 'API_ONLY'
  check (mode in ('API_ONLY', 'COEXISTENCE')),
add column coexistence_eligibility text not null default 'UNKNOWN'
  check (coexistence_eligibility in ('ELIGIBLE', 'INELIGIBLE', 'UNKNOWN')),
add column granted_scopes jsonb not null default '[]'::jsonb
  check (jsonb_typeof(granted_scopes) = 'array'),
add column health_status text not null default 'UNKNOWN'
  check (health_status in ('HEALTHY', 'REAUTH_REQUIRED', 'ERROR', 'UNKNOWN')),
add column last_health_checked_at timestamptz,
add column last_error_code text,
add column token_expires_at timestamptz,
add column verified_at timestamptz,
add constraint whatsapp_accounts_access_token_secret_fkey
  foreign key (tenant_id, access_token_secret_id)
  references public.secret_envelopes(tenant_id, id) on delete restrict,
add constraint whatsapp_accounts_coexistence_mode_check check (
  mode <> 'COEXISTENCE' or coexistence_eligibility = 'ELIGIBLE'
);

create unique index whatsapp_accounts_access_token_secret_idx
on public.whatsapp_accounts (tenant_id, access_token_secret_id)
where access_token_secret_id is not null;

create table agents_factory_private.whatsapp_signup_states (
  state_digest text primary key check (length(state_digest) = 64),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  admin_user_id uuid not null,
  admin_session_id uuid not null,
  expires_at timestamptz not null,
  consumed_at timestamptz,
  created_at timestamptz not null default now(),
  check (expires_at > created_at)
);

create index whatsapp_signup_states_expiry_idx
on agents_factory_private.whatsapp_signup_states (expires_at)
where consumed_at is null;

revoke all on table agents_factory_private.whatsapp_signup_states
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

grant select, insert, update, delete
on table agents_factory_private.whatsapp_signup_states
to agents_factory_admin;

create policy secret_envelopes_admin_select
on public.secret_envelopes for select
to agents_factory_admin
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy secret_envelopes_admin_insert
on public.secret_envelopes for insert
to agents_factory_admin
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy secret_envelopes_admin_delete
on public.secret_envelopes for delete
to agents_factory_admin
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

grant select, insert, delete on table public.secret_envelopes
to agents_factory_admin;
