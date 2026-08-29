alter table public.knowledge_sources
add column configuration jsonb not null default '{}'::jsonb
check (jsonb_typeof(configuration) = 'object');

create table public.knowledge_ingestions (
  id uuid primary key,
  tenant_id uuid not null,
  source_id uuid not null,
  state text not null check (
    state in ('PENDING', 'PROCESSING', 'SUCCEEDED', 'FAILED')
  ),
  content_digest text check (
    content_digest is null or content_digest ~ '^[0-9a-f]{64}$'
  ),
  storage_path text check (
    storage_path is null or (
      storage_path = btrim(storage_path)
      and length(storage_path) between 1 and 1000
    )
  ),
  proposed_artifact_count integer not null default 0 check (
    proposed_artifact_count >= 0
  ),
  error_code text check (
    error_code is null or (
      error_code = btrim(error_code)
      and error_code ~ '^[a-z][a-z0-9_]{0,199}$'
    )
  ),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (tenant_id, id),
  unique (tenant_id, id, source_id),
  foreign key (tenant_id, source_id)
    references public.knowledge_sources(tenant_id, id) on delete restrict,
  check (
    (state in ('PENDING', 'PROCESSING') and completed_at is null)
    or (state in ('SUCCEEDED', 'FAILED') and completed_at is not null)
  ),
  check (
    state <> 'SUCCEEDED'
    or (content_digest is not null and storage_path is not null and error_code is null)
  ),
  check (state <> 'FAILED' or error_code is not null)
);

create table public.knowledge_ingestion_artifacts (
  id uuid primary key,
  tenant_id uuid not null,
  source_id uuid not null,
  ingestion_id uuid not null,
  artifact_type text not null check (artifact_type in ('FACT', 'DOCUMENT')),
  artifact_digest text not null check (artifact_digest ~ '^[0-9a-f]{64}$'),
  proposal jsonb not null check (jsonb_typeof(proposal) = 'object'),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, source_id, artifact_type, artifact_digest),
  foreign key (tenant_id, source_id)
    references public.knowledge_sources(tenant_id, id) on delete restrict,
  foreign key (tenant_id, ingestion_id, source_id)
    references public.knowledge_ingestions(tenant_id, id, source_id)
    on delete restrict
);

create index knowledge_ingestions_source_idx
on public.knowledge_ingestions (tenant_id, source_id, created_at desc);

create function agents_factory_private.enforce_knowledge_ingestion_lifecycle()
returns trigger
language plpgsql
set search_path = pg_catalog
as $function$
begin
  if tg_op = 'INSERT' then
    if new.state <> 'PENDING' or new.content_digest is not null
      or new.storage_path is not null or new.proposed_artifact_count <> 0
      or new.error_code is not null or new.completed_at is not null then
      raise exception 'Knowledge ingestions must begin as PENDING'
        using errcode = '55000';
    end if;
    return new;
  end if;
  if tg_op = 'DELETE' then
    raise exception 'Knowledge ingestion history is immutable'
      using errcode = '55000';
  end if;
  if row(new.id, new.tenant_id, new.source_id, new.created_at)
    is distinct from row(old.id, old.tenant_id, old.source_id, old.created_at) then
    raise exception 'Knowledge ingestion identity is immutable'
      using errcode = '55000';
  end if;
  if new.state <> old.state and not (
    (old.state = 'PENDING' and new.state = 'PROCESSING')
    or (old.state = 'PROCESSING' and new.state in ('SUCCEEDED', 'FAILED'))
  ) then
    raise exception 'Invalid Knowledge ingestion transition'
      using errcode = '55000';
  end if;
  if old.state in ('SUCCEEDED', 'FAILED') and new is distinct from old then
    raise exception 'Completed Knowledge ingestions are immutable'
      using errcode = '55000';
  end if;
  return new;
end
$function$;

revoke all on function
agents_factory_private.enforce_knowledge_ingestion_lifecycle()
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

create trigger knowledge_ingestions_lifecycle_guard
before insert or update or delete on public.knowledge_ingestions
for each row execute function
agents_factory_private.enforce_knowledge_ingestion_lifecycle();

create trigger knowledge_ingestion_artifacts_append_only
before update or delete or truncate on public.knowledge_ingestion_artifacts
for each statement execute function
agents_factory_private.reject_knowledge_append_only_mutation();

create function agents_factory_private.append_knowledge_ingestion_artifact(
  p_id uuid,
  p_tenant_id uuid,
  p_source_id uuid,
  p_ingestion_id uuid,
  p_artifact_type text,
  p_artifact_digest text,
  p_proposal jsonb
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_tenant_id uuid;
  v_artifact_id uuid;
begin
  v_tenant_id := nullif(current_setting('app.tenant_id', true), '')::uuid;
  if v_tenant_id is null or v_tenant_id <> p_tenant_id then
    raise exception 'tenant context is required' using errcode = '42501';
  end if;
  if p_artifact_type not in ('FACT', 'DOCUMENT')
    or p_artifact_digest !~ '^[0-9a-f]{64}$'
    or jsonb_typeof(p_proposal) <> 'object' then
    raise exception 'invalid Knowledge ingestion artifact'
      using errcode = '22023';
  end if;
  if not exists (
    select 1 from public.knowledge_ingestions as ingestion
    where ingestion.tenant_id = v_tenant_id
      and ingestion.id = p_ingestion_id
      and ingestion.source_id = p_source_id
      and ingestion.state = 'PROCESSING'
  ) then
    raise exception 'processing Knowledge ingestion not found'
      using errcode = '23503';
  end if;

  insert into public.knowledge_ingestion_artifacts (
    id, tenant_id, source_id, ingestion_id, artifact_type,
    artifact_digest, proposal
  ) values (
    p_id, v_tenant_id, p_source_id, p_ingestion_id, p_artifact_type,
    p_artifact_digest, p_proposal
  )
  on conflict (tenant_id, source_id, artifact_type, artifact_digest)
  do nothing
  returning id into v_artifact_id;

  if v_artifact_id is null then
    select artifact.id into v_artifact_id
    from public.knowledge_ingestion_artifacts as artifact
    where artifact.tenant_id = v_tenant_id
      and artifact.source_id = p_source_id
      and artifact.artifact_type = p_artifact_type
      and artifact.artifact_digest = p_artifact_digest;
  end if;
  return v_artifact_id;
end
$function$;

revoke all on function
agents_factory_private.append_knowledge_ingestion_artifact(
  uuid, uuid, uuid, uuid, text, text, jsonb
)
from public, anon, authenticated, service_role, agents_factory_admin;

grant execute on function
agents_factory_private.append_knowledge_ingestion_artifact(
  uuid, uuid, uuid, uuid, text, text, jsonb
)
to agents_factory_app;

alter table public.knowledge_ingestions enable row level security;
alter table public.knowledge_ingestions force row level security;
alter table public.knowledge_ingestion_artifacts enable row level security;
alter table public.knowledge_ingestion_artifacts force row level security;

create policy knowledge_ingestions_app_select
on public.knowledge_ingestions for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_ingestions_app_update
on public.knowledge_ingestions for update to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_ingestions_admin_all
on public.knowledge_ingestions for all to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy knowledge_ingestion_artifacts_app_select
on public.knowledge_ingestion_artifacts for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_ingestion_artifacts_admin_select
on public.knowledge_ingestion_artifacts for select to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

revoke all on table public.knowledge_ingestions,
  public.knowledge_ingestion_artifacts
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

grant select, update on table public.knowledge_ingestions
to agents_factory_app;
grant select, insert, update on table public.knowledge_ingestions
to agents_factory_admin;
grant select on table public.knowledge_ingestion_artifacts
to agents_factory_app;
grant select on table public.knowledge_ingestion_artifacts
to agents_factory_admin;
