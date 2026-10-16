-- Provenance of immutable candidates prepared from a per-instance editing draft.
create table public.workspace_agent_candidates (
  tenant_id uuid not null,
  agent_instance_id uuid not null,
  draft_revision integer not null check (draft_revision > 0),
  company_revision integer not null check (company_revision > 0),
  source_digest text not null check (source_digest ~ '^[0-9a-f]{64}$'),
  code_digest text not null check (code_digest ~ '^[0-9a-f]{64}$'),
  version_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (tenant_id, agent_instance_id, draft_revision, code_digest),
  unique (tenant_id, version_id),
  unique (tenant_id, version_id, agent_instance_id, draft_revision, company_revision, code_digest),
  foreign key (tenant_id, agent_instance_id)
    references public.agent_instances(tenant_id, id) on delete restrict,
  foreign key (tenant_id, agent_instance_id, version_id)
    references public.agent_spec_versions(tenant_id, agent_instance_id, id) on delete restrict
);
alter table public.workspace_agent_candidates enable row level security;
alter table public.workspace_agent_candidates force row level security;
create policy workspace_candidates_read on public.workspace_agent_candidates
  for select to agents_factory_admin, agents_factory_app
  using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy workspace_candidates_insert on public.workspace_agent_candidates
  for insert to agents_factory_admin
  with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
revoke all on public.workspace_agent_candidates
  from public, anon, authenticated, service_role, agents_factory_admin, agents_factory_app;
grant select, insert on public.workspace_agent_candidates to agents_factory_admin;
grant select on public.workspace_agent_candidates to agents_factory_app;
create trigger workspace_candidates_immutable before update or delete on public.workspace_agent_candidates
  for each row execute function agents_factory_private.reject_approved_knowledge_mutation();
