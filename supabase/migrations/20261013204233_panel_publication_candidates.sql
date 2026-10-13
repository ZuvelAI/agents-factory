alter table public.agent_spec_versions add constraint agent_spec_versions_tenant_id_id_key unique(tenant_id,id);
create table public.panel_agent_candidates (
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  onboarding_revision integer not null check(onboarding_revision > 0),
  code_digest text not null check(code_digest ~ '^[0-9a-f]{64}$'),
  version_id uuid not null,
  created_at timestamptz not null default now(),
  primary key(tenant_id, onboarding_revision, code_digest),
  unique(tenant_id,version_id),
  foreign key(tenant_id,version_id) references public.agent_spec_versions(tenant_id,id) on delete restrict
);
alter table public.panel_agent_candidates enable row level security;
alter table public.panel_agent_candidates force row level security;
create policy panel_candidates_read on public.panel_agent_candidates for select
to agents_factory_admin, agents_factory_app
using(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy panel_candidates_insert on public.panel_agent_candidates for insert
to agents_factory_admin
with check(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
revoke all on public.panel_agent_candidates from public,anon,authenticated,service_role,agents_factory_admin,agents_factory_app;
grant select,insert on public.panel_agent_candidates to agents_factory_admin;
grant select on public.panel_agent_candidates to agents_factory_app;
