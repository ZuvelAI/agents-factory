-- Existing immutable evidence remains LEGACY/SCENARIOS; new runs identify their exact source.
alter table public.agent_publication_test_runs
  alter column onboarding_revision drop not null,
  add column source_kind text not null default 'LEGACY' check (source_kind in ('LEGACY','AGENT_CONFIGURATION')),
  add column run_kind text not null default 'SCENARIOS' check (run_kind in ('SCENARIOS','PREVIEW')),
  add column agent_instance_id uuid,
  add column draft_revision integer,
  add column company_revision integer,
  add column input_messages jsonb,
  add column requested_by uuid,
  add column request_key uuid,
  add constraint publication_run_origin check (
    (source_kind='LEGACY' and onboarding_revision is not null and agent_instance_id is null and draft_revision is null and company_revision is null and run_kind='SCENARIOS')
    or (source_kind='AGENT_CONFIGURATION' and onboarding_revision is null and agent_instance_id is not null and draft_revision>0 and company_revision>0 and draft_revision is not null and company_revision is not null and requested_by is not null and request_key is not null)
  ),
  add constraint publication_run_input check (
    (run_kind='SCENARIOS' and input_messages is null)
    or (run_kind='PREVIEW' and input_messages is not null and jsonb_typeof(input_messages)='array' and jsonb_array_length(input_messages) between 1 and 20)
  ),
  add constraint publication_run_request unique(tenant_id,requested_by,request_key),
  add constraint publication_run_candidate foreign key(tenant_id,version_id,agent_instance_id,draft_revision,company_revision,code_digest)
    references public.workspace_agent_candidates(tenant_id,version_id,agent_instance_id,draft_revision,company_revision,code_digest) on delete restrict;
create index publication_runs_agent_recent on public.agent_publication_test_runs(tenant_id,agent_instance_id,created_at desc,id desc);
