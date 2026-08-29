create table public.knowledge_proposals (
  id uuid primary key,
  tenant_id uuid not null,
  ingestion_artifact_id uuid not null,
  ingestion_id uuid not null,
  source_id uuid not null,
  revision integer not null default 1 check (revision > 0),
  artifact_type text not null check (artifact_type in ('FACT', 'DOCUMENT')),
  state text not null default 'PROPOSED' check (
    state in ('PROPOSED', 'APPROVED', 'EDITED', 'REJECTED')
  ),
  proposed_payload jsonb not null check (jsonb_typeof(proposed_payload) = 'object'),
  decision_payload jsonb check (
    decision_payload is null or jsonb_typeof(decision_payload) = 'object'
  ),
  proposed_by text not null default 'NORMALIZER' check (
    proposed_by in ('NORMALIZER', 'AI')
  ),
  model_metadata jsonb not null default '{}'::jsonb check (
    jsonb_typeof(model_metadata) = 'object'
  ),
  content_digest text not null check (content_digest ~ '^[0-9a-f]{64}$'),
  decided_by_admin_id uuid,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, ingestion_artifact_id, revision),
  foreign key (tenant_id, ingestion_artifact_id)
    references public.knowledge_ingestion_artifacts(tenant_id, id) on delete restrict,
  foreign key (tenant_id, ingestion_id)
    references public.knowledge_ingestions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id)
    references public.knowledge_sources(tenant_id, id) on delete restrict,
  check (
    (state = 'PROPOSED' and decided_by_admin_id is null and decided_at is null)
    or (state <> 'PROPOSED' and decided_by_admin_id is not null and decided_at is not null)
  )
);

create table public.knowledge_conflicts (
  id uuid primary key,
  tenant_id uuid not null,
  proposal_id uuid not null,
  fact_key text,
  critical boolean not null,
  proposed_authority text not null check (
    proposed_authority in ('AUTHORITATIVE', 'SECONDARY', 'REFERENCE')
  ),
  existing_authority text not null check (
    existing_authority in ('AUTHORITATIVE', 'SECONDARY', 'REFERENCE')
  ),
  existing_fact_id uuid,
  state text not null default 'OPEN' check (state in ('OPEN', 'RESOLVED')),
  resolution text check (resolution in ('APPROVED', 'EDITED', 'REJECTED')),
  details jsonb not null default '{}'::jsonb check (jsonb_typeof(details) = 'object'),
  resolved_by_admin_id uuid,
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, proposal_id, existing_fact_id),
  foreign key (tenant_id, proposal_id)
    references public.knowledge_proposals(tenant_id, id) on delete restrict,
  foreign key (tenant_id, existing_fact_id)
    references public.structured_facts(tenant_id, id) on delete restrict,
  check (
    (state = 'OPEN' and resolution is null and resolved_at is null)
    or (state = 'RESOLVED' and resolution is not null and resolved_at is not null)
  )
);

create table public.knowledge_source_diffs (
  id uuid primary key,
  tenant_id uuid not null,
  source_id uuid not null,
  ingestion_id uuid not null,
  draft_version_id uuid not null,
  previous_digest text,
  current_digest text not null check (current_digest ~ '^[0-9a-f]{64}$'),
  state text not null default 'DETECTED' check (state in ('DETECTED', 'REVIEWED')),
  summary jsonb not null default '{}'::jsonb check (jsonb_typeof(summary) = 'object'),
  reviewed_by_admin_id uuid,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, ingestion_id),
  foreign key (tenant_id, source_id)
    references public.knowledge_sources(tenant_id, id) on delete restrict,
  foreign key (tenant_id, ingestion_id)
    references public.knowledge_ingestions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, draft_version_id)
    references public.knowledge_versions(tenant_id, id) on delete restrict
);

create table public.knowledge_eval_evidence (
  id uuid primary key,
  tenant_id uuid not null,
  knowledge_version_id uuid not null,
  knowledge_digest text not null check (knowledge_digest ~ '^[0-9a-f]{64}$'),
  suite_digest text not null check (suite_digest ~ '^[0-9a-f]{64}$'),
  runner_version text not null check (length(runner_version) between 1 and 100),
  passed boolean not null,
  passed_cases integer not null check (passed_cases >= 0),
  failed_cases integer not null check (failed_cases >= 0),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, knowledge_version_id, knowledge_digest, suite_digest),
  foreign key (tenant_id, knowledge_version_id)
    references public.knowledge_versions(tenant_id, id) on delete restrict
);

create index knowledge_proposals_review_idx
on public.knowledge_proposals (tenant_id, state, created_at);
create index knowledge_conflicts_open_idx
on public.knowledge_conflicts (tenant_id, proposal_id) where state = 'OPEN';
create index knowledge_source_diffs_review_idx
on public.knowledge_source_diffs (tenant_id, state, created_at);

create function agents_factory_private.create_proposal_from_ingestion_artifact()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  insert into public.knowledge_proposals (
    id, tenant_id, ingestion_artifact_id, ingestion_id, source_id,
    artifact_type, proposed_payload, content_digest
  ) values (
    new.id, new.tenant_id, new.id, new.ingestion_id, new.source_id,
    new.artifact_type, new.proposal, new.artifact_digest
  ) on conflict (tenant_id, ingestion_artifact_id, revision) do nothing;
  return new;
end
$function$;

revoke all on function
agents_factory_private.create_proposal_from_ingestion_artifact()
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

create trigger knowledge_ingestion_artifacts_create_proposal
after insert on public.knowledge_ingestion_artifacts
for each row execute function
agents_factory_private.create_proposal_from_ingestion_artifact();

insert into public.knowledge_proposals (
  id, tenant_id, ingestion_artifact_id, ingestion_id, source_id,
  artifact_type, proposed_payload, content_digest
)
select
  artifact.id, artifact.tenant_id, artifact.id, artifact.ingestion_id,
  artifact.source_id, artifact.artifact_type, artifact.proposal,
  artifact.artifact_digest
from public.knowledge_ingestion_artifacts as artifact
on conflict (tenant_id, ingestion_artifact_id, revision) do nothing;

create function agents_factory_private.record_knowledge_source_diff(
  p_id uuid,
  p_tenant_id uuid,
  p_source_id uuid,
  p_ingestion_id uuid,
  p_current_digest text,
  p_summary jsonb
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_tenant_id uuid;
  v_previous_digest text;
  v_base_version_id uuid;
  v_draft_version_id uuid;
  v_diff_id uuid;
  v_version_number integer;
begin
  v_tenant_id := nullif(current_setting('app.tenant_id', true), '')::uuid;
  if v_tenant_id is null or v_tenant_id <> p_tenant_id then
    raise exception 'tenant context is required' using errcode = '42501';
  end if;
  if not exists (
    select 1 from public.knowledge_ingestions as ingestion
    where ingestion.tenant_id = v_tenant_id
      and ingestion.id = p_ingestion_id
      and ingestion.source_id = p_source_id
      and ingestion.state = 'SUCCEEDED'
      and ingestion.content_digest = p_current_digest
  ) then
    raise exception 'completed ingestion digest is required' using errcode = '23503';
  end if;
  select diff.id into v_diff_id
  from public.knowledge_source_diffs as diff
  where diff.tenant_id = v_tenant_id and diff.ingestion_id = p_ingestion_id;
  if v_diff_id is not null then
    return v_diff_id;
  end if;

  select version.content_digest into v_previous_digest
  from public.knowledge_source_versions as version
  where version.tenant_id = v_tenant_id and version.source_id = p_source_id
  order by version.version_number desc limit 1;
  if v_previous_digest = p_current_digest then
    return null;
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('knowledge:' || v_tenant_id::text, 0)
  );
  select version.id into v_base_version_id
  from public.knowledge_versions as version
  where version.tenant_id = v_tenant_id
    and version.state in ('TEST', 'PRODUCTION')
  order by version.version_number desc limit 1;
  select coalesce(max(version.version_number), 0) + 1 into v_version_number
  from public.knowledge_versions as version
  where version.tenant_id = v_tenant_id;

  v_draft_version_id := p_id;
  insert into public.knowledge_versions (
    id, tenant_id, name, version_number, state, based_on_version_id
  ) values (
    v_draft_version_id, v_tenant_id,
    'Source change ' || p_ingestion_id::text,
    v_version_number, 'DRAFT', v_base_version_id
  );
  if v_base_version_id is not null then
    insert into public.knowledge_version_members (
      id, tenant_id, knowledge_version_id, structured_fact_id, document_id, position
    )
    select
      pg_catalog.gen_random_uuid(), member.tenant_id, v_draft_version_id,
      member.structured_fact_id, member.document_id, member.position
    from public.knowledge_version_members as member
    where member.tenant_id = v_tenant_id
      and member.knowledge_version_id = v_base_version_id
    order by member.position;
  end if;
  v_diff_id := p_id;
  insert into public.knowledge_source_diffs (
    id, tenant_id, source_id, ingestion_id, draft_version_id,
    previous_digest, current_digest, summary
  ) values (
    v_diff_id, v_tenant_id, p_source_id, p_ingestion_id,
    v_draft_version_id, v_previous_digest, p_current_digest, p_summary
  );
  return v_diff_id;
end
$function$;

revoke all on function agents_factory_private.record_knowledge_source_diff(
  uuid, uuid, uuid, uuid, text, jsonb
)
from public, anon, authenticated, service_role, agents_factory_admin;
grant execute on function agents_factory_private.record_knowledge_source_diff(
  uuid, uuid, uuid, uuid, text, jsonb
)
to agents_factory_app, agents_factory_admin;

alter table public.knowledge_proposals enable row level security;
alter table public.knowledge_proposals force row level security;
alter table public.knowledge_conflicts enable row level security;
alter table public.knowledge_conflicts force row level security;
alter table public.knowledge_source_diffs enable row level security;
alter table public.knowledge_source_diffs force row level security;
alter table public.knowledge_eval_evidence enable row level security;
alter table public.knowledge_eval_evidence force row level security;

create policy knowledge_proposals_admin_all
on public.knowledge_proposals for all to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_proposals_app_select
on public.knowledge_proposals for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_conflicts_admin_all
on public.knowledge_conflicts for all to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_conflicts_app_select
on public.knowledge_conflicts for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_source_diffs_admin_all
on public.knowledge_source_diffs for all to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_source_diffs_app_select
on public.knowledge_source_diffs for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_eval_evidence_admin_all
on public.knowledge_eval_evidence for all to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_eval_evidence_app_select
on public.knowledge_eval_evidence for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

revoke all on table public.knowledge_proposals, public.knowledge_conflicts,
  public.knowledge_source_diffs, public.knowledge_eval_evidence
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;
grant select, insert, update on table public.knowledge_proposals,
  public.knowledge_conflicts, public.knowledge_source_diffs,
  public.knowledge_eval_evidence to agents_factory_admin;
grant select on table public.knowledge_proposals, public.knowledge_conflicts,
  public.knowledge_source_diffs, public.knowledge_eval_evidence
to agents_factory_app;
