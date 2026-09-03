create table public.eval_runs (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  suite_digest text not null check (suite_digest ~ '^[0-9a-f]{64}$'),
  runner_version text not null,
  seed bigint not null,
  status text not null check (status in ('RUNNING','PASSED','FAILED','ERROR')),
  agent_spec_digest text not null check (agent_spec_digest ~ '^[0-9a-f]{64}$'),
  knowledge_digest text not null check (knowledge_digest ~ '^[0-9a-f]{64}$'),
  code_digest text not null check (code_digest ~ '^[0-9a-f]{64}$'),
  passed_cases integer not null default 0 check (passed_cases >= 0),
  failed_cases integer not null default 0 check (failed_cases >= 0),
  total_cost numeric check (total_cost is null or total_cost >= 0),
  total_latency_ms integer check (total_latency_ms is null or total_latency_ms >= 0),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  created_by_admin_id uuid not null,
  constraint eval_runs_tenant_id_id_key unique (tenant_id, id),
  constraint eval_runs_completion_check check (
    (status = 'RUNNING' and completed_at is null)
    or (status <> 'RUNNING' and completed_at is not null)
  )
);

create table public.eval_case_results (
  id uuid primary key,
  tenant_id uuid not null,
  eval_run_id uuid not null,
  case_id text not null check (case_id ~ '^[a-z0-9][a-z0-9._-]{2,99}$'),
  passed boolean not null,
  grader_results jsonb not null check (jsonb_typeof(grader_results) = 'array'),
  sanitized_observation jsonb not null check (
    jsonb_typeof(sanitized_observation) = 'object'
    and pg_column_size(sanitized_observation) <= 16384
  ),
  latency_ms integer not null check (latency_ms >= 0),
  created_at timestamptz not null default now(),
  constraint eval_case_results_run_fkey foreign key (tenant_id, eval_run_id)
    references public.eval_runs(tenant_id, id) on delete restrict,
  constraint eval_case_results_tenant_run_case_key
    unique (tenant_id, eval_run_id, case_id),
  constraint eval_case_results_tenant_id_id_key unique (tenant_id, id)
);

create table public.quality_gate_decisions (
  id uuid primary key,
  tenant_id uuid not null,
  eval_run_id uuid not null,
  agent_spec_digest text not null check (agent_spec_digest ~ '^[0-9a-f]{64}$'),
  knowledge_digest text not null check (knowledge_digest ~ '^[0-9a-f]{64}$'),
  code_digest text not null check (code_digest ~ '^[0-9a-f]{64}$'),
  passed boolean not null,
  hard_blockers text[] not null default '{}',
  thresholds jsonb not null default '{}'::jsonb check (jsonb_typeof(thresholds) = 'object'),
  decided_at timestamptz not null default now(),
  decided_by_admin_id uuid not null,
  constraint quality_gate_decisions_run_fkey foreign key (tenant_id, eval_run_id)
    references public.eval_runs(tenant_id, id) on delete restrict,
  constraint quality_gate_decisions_tenant_id_id_key unique (tenant_id, id),
  constraint quality_gate_decisions_result_check check (
    not passed or coalesce(array_length(hard_blockers, 1), 0) = 0
  )
);

create index eval_runs_version_idx on public.eval_runs (
  tenant_id, agent_spec_digest, knowledge_digest, code_digest, completed_at desc
);
create index quality_gate_exact_idx on public.quality_gate_decisions (
  tenant_id, agent_spec_digest, knowledge_digest, code_digest, decided_at desc
);

alter table public.agent_spec_deployments
add constraint agent_spec_deployments_quality_gate_fkey
foreign key (tenant_id, quality_gate_decision_id)
references public.quality_gate_decisions(tenant_id, id) on delete restrict;

create function agents_factory_private.validate_agent_spec_quality_gate()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $function$
begin
  if not exists (
    select 1 from public.quality_gate_decisions as decision
    where decision.tenant_id = new.tenant_id
      and decision.id = new.quality_gate_decision_id
      and decision.passed
      and decision.agent_spec_digest = new.agent_spec_digest
      and decision.knowledge_digest = new.knowledge_digest
      and decision.code_digest = new.code_digest
  ) then
    raise exception 'Deployment requires a passing exact-version Quality Gate'
      using errcode = '23514';
  end if;
  return new;
end
$function$;

create trigger agent_spec_deployments_quality_gate
before insert on public.agent_spec_deployments
for each row execute function
agents_factory_private.validate_agent_spec_quality_gate();

create trigger eval_case_results_immutable
before update or delete on public.eval_case_results
for each row execute function agents_factory_private.reject_agent_spec_deployment_mutation();
create trigger quality_gate_decisions_immutable
before update or delete on public.quality_gate_decisions
for each row execute function agents_factory_private.reject_agent_spec_deployment_mutation();

alter table public.eval_runs enable row level security;
alter table public.eval_runs force row level security;
alter table public.eval_case_results enable row level security;
alter table public.eval_case_results force row level security;
alter table public.quality_gate_decisions enable row level security;
alter table public.quality_gate_decisions force row level security;

revoke all on public.eval_runs, public.eval_case_results, public.quality_gate_decisions
from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;
grant select, insert, update on public.eval_runs to agents_factory_admin;
grant select, insert on public.eval_case_results, public.quality_gate_decisions
to agents_factory_admin;

create policy eval_runs_admin_select on public.eval_runs for select to agents_factory_admin
using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy eval_runs_admin_insert on public.eval_runs for insert to agents_factory_admin
with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy eval_runs_admin_update on public.eval_runs for update to agents_factory_admin
using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy eval_case_results_admin_select on public.eval_case_results for select to agents_factory_admin
using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy eval_case_results_admin_insert on public.eval_case_results for insert to agents_factory_admin
with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy quality_gate_decisions_admin_select on public.quality_gate_decisions for select to agents_factory_admin
using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy quality_gate_decisions_admin_insert on public.quality_gate_decisions for insert to agents_factory_admin
with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
