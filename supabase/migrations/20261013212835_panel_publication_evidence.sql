create table public.agent_publication_test_runs (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  version_id uuid not null,
  onboarding_revision integer not null check(onboarding_revision>0),
  agent_spec_digest text not null check(agent_spec_digest ~ '^[0-9a-f]{64}$'),
  knowledge_digest text not null check(knowledge_digest ~ '^[0-9a-f]{64}$'),
  code_digest text not null check(code_digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now()+interval '24 hours'),
  unique(tenant_id,id),
  foreign key(tenant_id,version_id) references public.agent_spec_versions(tenant_id,id) on delete restrict
);
create table public.agent_publication_test_results (
  run_id uuid primary key,
  tenant_id uuid not null,
  result jsonb not null check(jsonb_typeof(result)='object'),
  created_at timestamptz not null default now(),
  foreign key(tenant_id,run_id) references public.agent_publication_test_runs(tenant_id,id) on delete restrict
);
create table public.agent_publication_reviews (
  id uuid primary key,
  run_id uuid not null unique,
  tenant_id uuid not null,
  reviewer_id uuid not null,
  approved boolean not null,
  created_at timestamptz not null default now(),
  foreign key(tenant_id,run_id) references public.agent_publication_test_runs(tenant_id,id) on delete restrict
);
alter table public.agent_publication_test_runs enable row level security;
alter table public.agent_publication_test_runs force row level security;
alter table public.agent_publication_test_results enable row level security;
alter table public.agent_publication_test_results force row level security;
alter table public.agent_publication_reviews enable row level security;
alter table public.agent_publication_reviews force row level security;

create policy publication_runs_select on public.agent_publication_test_runs for select to agents_factory_admin,agents_factory_app
using(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy publication_runs_insert on public.agent_publication_test_runs for insert to agents_factory_admin
with check(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy publication_results_select on public.agent_publication_test_results for select to agents_factory_admin,agents_factory_app
using(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy publication_results_insert on public.agent_publication_test_results for insert to agents_factory_app
with check(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy publication_reviews_select on public.agent_publication_reviews for select to agents_factory_admin,agents_factory_app
using(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy publication_reviews_insert on public.agent_publication_reviews for insert to agents_factory_admin
with check(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
revoke all on public.agent_publication_test_runs,public.agent_publication_test_results,public.agent_publication_reviews
from public,anon,authenticated,service_role,agents_factory_admin,agents_factory_app;
grant select on public.agent_publication_test_runs,public.agent_publication_test_results,public.agent_publication_reviews
to agents_factory_admin,agents_factory_app;
grant insert on public.agent_publication_test_runs,public.agent_publication_reviews to agents_factory_admin;
grant insert on public.agent_publication_test_results to agents_factory_app;
create trigger publication_runs_immutable before update or delete on public.agent_publication_test_runs
for each row execute function agents_factory_private.reject_approved_knowledge_mutation();
create trigger publication_results_immutable before update or delete on public.agent_publication_test_results
for each row execute function agents_factory_private.reject_approved_knowledge_mutation();
create trigger publication_reviews_immutable before update or delete on public.agent_publication_reviews
for each row execute function agents_factory_private.reject_approved_knowledge_mutation();
