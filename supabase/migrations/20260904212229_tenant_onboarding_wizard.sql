create table public.tenant_onboarding_configs (
  tenant_id uuid primary key,
  revision integer not null default 1 check (revision > 0),
  configuration jsonb not null default '{}'::jsonb check (
    jsonb_typeof(configuration) = 'object'
  ),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint tenant_onboarding_configs_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict
);

alter table public.tenant_onboarding_configs enable row level security;
alter table public.tenant_onboarding_configs force row level security;

create policy tenant_onboarding_configs_admin_all
on public.tenant_onboarding_configs for all to agents_factory_admin
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
)
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);

create policy tenant_onboarding_configs_app_select
on public.tenant_onboarding_configs for select to agents_factory_app
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);

revoke all on table public.tenant_onboarding_configs
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

grant select on table public.tenant_onboarding_configs to agents_factory_app;
grant select, insert, update on table public.tenant_onboarding_configs
to agents_factory_admin;
