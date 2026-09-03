create table public.privacy_jobs (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  operation text not null check (operation in ('DELETE','EXPORT','REVOKE_INTEGRATIONS')),
  subject_type text not null check (subject_type in ('CONVERSATION','CUSTOMER','TENANT')),
  subject_ref text not null check (subject_ref=btrim(subject_ref) and length(subject_ref) between 1 and 300),
  status text not null default 'REQUESTED' check (
    status in ('REQUESTED','STARTED','COMPLETED','FAILED','HELD')
  ),
  legal_hold boolean not null default false,
  idempotency_key text not null check (length(idempotency_key) between 16 and 200),
  result_manifest jsonb not null default '{}'::jsonb check (
    jsonb_typeof(result_manifest)='object' and pg_column_size(result_manifest)<=16384
  ),
  error_code text,
  requested_by_admin_id uuid not null,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  constraint privacy_jobs_tenant_id_id_key unique (tenant_id,id),
  constraint privacy_jobs_tenant_idempotency_key unique (tenant_id,idempotency_key),
  constraint privacy_jobs_lifecycle_check check (
    (status='REQUESTED' and started_at is null and completed_at is null)
    or (status='STARTED' and started_at is not null and completed_at is null)
    or (status in ('COMPLETED','FAILED','HELD') and completed_at is not null)
  )
);

create index privacy_jobs_pending_idx
on public.privacy_jobs (tenant_id,status,requested_at,id)
where status in ('REQUESTED','STARTED');

alter table public.privacy_jobs enable row level security;
alter table public.privacy_jobs force row level security;
revoke all on public.privacy_jobs
from public,anon,authenticated,service_role,agents_factory_app,agents_factory_admin,
  agents_factory_retention;
grant select,insert,update on public.privacy_jobs to agents_factory_admin;
grant select,update on public.privacy_jobs to agents_factory_retention;

create policy privacy_jobs_admin_select on public.privacy_jobs for select to agents_factory_admin
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy privacy_jobs_admin_insert on public.privacy_jobs for insert to agents_factory_admin
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy privacy_jobs_admin_update on public.privacy_jobs for update to agents_factory_admin
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy privacy_jobs_retention_select on public.privacy_jobs for select to agents_factory_retention
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy privacy_jobs_retention_update on public.privacy_jobs for update to agents_factory_retention
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);

grant update (customer_wa_id) on public.conversations to agents_factory_retention;
grant select on public.conversations,public.actions,public.cases,public.media_evidence
to agents_factory_retention;
grant select,update on public.integration_connections to agents_factory_retention;
create policy conversations_retention_minimize
on public.conversations for update to agents_factory_retention
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy integration_connections_retention_select
on public.integration_connections for select to agents_factory_retention
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy integration_connections_retention_update
on public.integration_connections for update to agents_factory_retention
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
