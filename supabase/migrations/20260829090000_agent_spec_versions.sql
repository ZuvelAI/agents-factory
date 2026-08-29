create table public.agent_instances (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  product text not null check (product = 'Agent Customer Service'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id)
);

create table public.agent_spec_versions (
  id uuid primary key,
  tenant_id uuid not null,
  agent_instance_id uuid not null,
  version_number integer not null check (version_number > 0),
  state text not null check (
    state in ('DRAFT', 'TEST', 'QUALITY_GATE', 'PRODUCTION')
  ),
  based_on_version_id uuid,
  configuration jsonb not null check (jsonb_typeof(configuration) = 'object'),
  compiled_spec jsonb check (
    compiled_spec is null or jsonb_typeof(compiled_spec) = 'object'
  ),
  compiled_digest text check (
    compiled_digest is null or compiled_digest ~ '^[0-9a-f]{64}$'
  ),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, agent_instance_id, id),
  unique (tenant_id, agent_instance_id, version_number),
  foreign key (tenant_id, agent_instance_id)
    references public.agent_instances(tenant_id, id) on delete restrict,
  foreign key (tenant_id, agent_instance_id, based_on_version_id)
    references public.agent_spec_versions(tenant_id, agent_instance_id, id)
    on delete restrict,
  check (based_on_version_id is null or based_on_version_id <> id),
  check (
    (state = 'DRAFT' and compiled_spec is null and compiled_digest is null)
    or
    (state <> 'DRAFT' and compiled_spec is not null and compiled_digest is not null)
  )
);

create table public.agent_spec_deployments (
  id uuid primary key,
  tenant_id uuid not null,
  agent_instance_id uuid not null,
  version_id uuid not null,
  action text not null check (action in ('PUBLISH', 'ROLLBACK')),
  replaced_version_id uuid,
  agent_spec_digest text not null check (
    agent_spec_digest ~ '^[0-9a-f]{64}$'
  ),
  knowledge_digest text not null check (
    knowledge_digest ~ '^[0-9a-f]{64}$'
  ),
  code_digest text not null check (code_digest ~ '^[0-9a-f]{64}$'),
  quality_gate_decision_id uuid not null,
  created_at timestamptz not null default now(),
  foreign key (tenant_id, agent_instance_id, version_id)
    references public.agent_spec_versions(tenant_id, agent_instance_id, id)
    on delete restrict,
  foreign key (tenant_id, agent_instance_id, replaced_version_id)
    references public.agent_spec_versions(tenant_id, agent_instance_id, id)
    on delete restrict
);

create index agent_spec_versions_instance_idx
on public.agent_spec_versions (tenant_id, agent_instance_id, version_number desc);

create index agent_spec_deployments_active_idx
on public.agent_spec_deployments (
  tenant_id, agent_instance_id, created_at desc, id desc
);

create function agents_factory_private.enforce_agent_spec_version_lifecycle()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $function$
begin
  if tg_op = 'INSERT' then
    if new.state <> 'DRAFT'
      or new.compiled_spec is not null
      or new.compiled_digest is not null then
      raise exception 'AgentSpec versions must begin as DRAFT'
        using errcode = '55000';
    end if;
    return new;
  end if;

  if tg_op = 'DELETE' then
    raise exception 'AgentSpec version history is immutable'
      using errcode = '55000';
  end if;

  if old.state = 'PRODUCTION' then
    raise exception 'Production AgentSpec versions are immutable'
      using errcode = '55000';
  end if;

  if row(
    new.id,
    new.tenant_id,
    new.agent_instance_id,
    new.version_number,
    new.based_on_version_id,
    new.configuration
  ) is distinct from row(
    old.id,
    old.tenant_id,
    old.agent_instance_id,
    old.version_number,
    old.based_on_version_id,
    old.configuration
  ) then
    raise exception 'AgentSpec configuration changes require a new Draft'
      using errcode = '55000';
  end if;

  if new.state <> old.state and not (
    (old.state = 'DRAFT' and new.state = 'TEST')
    or (old.state = 'TEST' and new.state = 'QUALITY_GATE')
    or (old.state = 'QUALITY_GATE' and new.state = 'PRODUCTION')
  ) then
    raise exception 'Invalid AgentSpec lifecycle transition'
      using errcode = '55000';
  end if;

  if old.state = 'DRAFT' and new.state = 'TEST' then
    if new.compiled_spec is null or new.compiled_digest is null then
      raise exception 'TEST requires a compiled AgentSpec'
        using errcode = '23514';
    end if;
  elsif row(new.compiled_spec, new.compiled_digest)
    is distinct from row(old.compiled_spec, old.compiled_digest) then
    raise exception 'Compiled AgentSpec content is immutable after TEST'
      using errcode = '55000';
  end if;

  return new;
end
$function$;

create trigger agent_spec_versions_lifecycle_guard
before insert or update or delete on public.agent_spec_versions
for each row execute function
agents_factory_private.enforce_agent_spec_version_lifecycle();

create function agents_factory_private.validate_agent_spec_deployment()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $function$
begin
  if not exists (
    select 1
    from public.agent_spec_versions as version
    where version.tenant_id = new.tenant_id
      and version.agent_instance_id = new.agent_instance_id
      and version.id = new.version_id
      and version.state = 'PRODUCTION'
      and version.compiled_digest = new.agent_spec_digest
      and version.configuration #>> '{knowledge,digest}' = new.knowledge_digest
      and version.configuration ->> 'code_digest' = new.code_digest
  ) then
    raise exception 'Deployment must reference an exact Production AgentSpec'
      using errcode = '23514';
  end if;
  return new;
end
$function$;

create trigger agent_spec_deployments_exact_version
before insert on public.agent_spec_deployments
for each row execute function
agents_factory_private.validate_agent_spec_deployment();

create function agents_factory_private.reject_agent_spec_deployment_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $function$
begin
  raise exception 'AgentSpec deployment history is append-only'
    using errcode = '55000';
end
$function$;

create trigger agent_spec_deployments_append_only
before update or delete or truncate on public.agent_spec_deployments
for each statement execute function
agents_factory_private.reject_agent_spec_deployment_mutation();

alter table public.agent_instances enable row level security;
alter table public.agent_instances force row level security;
alter table public.agent_spec_versions enable row level security;
alter table public.agent_spec_versions force row level security;
alter table public.agent_spec_deployments enable row level security;
alter table public.agent_spec_deployments force row level security;

create policy agent_instances_app_select
on public.agent_instances for select to agents_factory_app
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy agent_instances_admin_all
on public.agent_instances for all to agents_factory_admin
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
)
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);

create policy agent_spec_versions_app_select
on public.agent_spec_versions for select to agents_factory_app
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy agent_spec_versions_admin_all
on public.agent_spec_versions for all to agents_factory_admin
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
)
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);

create policy agent_spec_deployments_app_select
on public.agent_spec_deployments for select to agents_factory_app
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy agent_spec_deployments_admin_select
on public.agent_spec_deployments for select to agents_factory_admin
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy agent_spec_deployments_admin_insert
on public.agent_spec_deployments for insert to agents_factory_admin
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);

revoke all on table public.agent_instances from public, anon, authenticated,
  service_role, agents_factory_app, agents_factory_admin;
revoke all on table public.agent_spec_versions from public, anon, authenticated,
  service_role, agents_factory_app, agents_factory_admin;
revoke all on table public.agent_spec_deployments from public, anon, authenticated,
  service_role, agents_factory_app, agents_factory_admin;

grant select on table public.agent_instances, public.agent_spec_versions,
  public.agent_spec_deployments to agents_factory_app;
grant select, insert, update on table public.agent_instances,
  public.agent_spec_versions to agents_factory_admin;
grant select, insert on table public.agent_spec_deployments
to agents_factory_admin;
