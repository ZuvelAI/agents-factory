-- Editable configuration is independent of immutable runtime snapshots.
create table public.company_profiles (
  tenant_id uuid primary key references public.tenants(id) on delete restrict,
  revision integer not null check (revision > 0),
  configuration jsonb not null check (jsonb_typeof(configuration) = 'object'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.agent_configuration_drafts (
  tenant_id uuid not null references public.company_profiles(tenant_id) on delete restrict,
  agent_instance_id uuid not null,
  revision integer not null check (revision > 0),
  company_revision integer not null check (company_revision > 0),
  company_snapshot jsonb not null check (jsonb_typeof(company_snapshot) = 'object'),
  configuration jsonb not null check (jsonb_typeof(configuration) = 'object'),
  provenance jsonb not null check (jsonb_typeof(provenance) = 'object'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (tenant_id, agent_instance_id),
  foreign key (tenant_id, agent_instance_id)
    references public.agent_instances(tenant_id, id) on delete restrict
);

alter table public.company_profiles enable row level security;
alter table public.company_profiles force row level security;
alter table public.agent_configuration_drafts enable row level security;
alter table public.agent_configuration_drafts force row level security;

create policy company_profiles_admin on public.company_profiles
  for all to agents_factory_admin
  using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
  with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy agent_configuration_drafts_admin on public.agent_configuration_drafts
  for all to agents_factory_admin
  using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
  with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

revoke all on public.company_profiles, public.agent_configuration_drafts
  from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;
grant select, insert, update on public.company_profiles, public.agent_configuration_drafts
  to agents_factory_admin;
