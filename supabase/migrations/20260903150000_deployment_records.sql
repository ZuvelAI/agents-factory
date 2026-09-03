create table public.deployment_records (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  environment text not null check (environment in ('STAGING','PRODUCTION')),
  release_version text not null check (release_version ~ '^[a-zA-Z0-9._-]{7,100}$'),
  backend_image_digest text not null,
  control_plane_image_digest text not null,
  migration_version text not null,
  status text not null check (
    status in ('PENDING','MIGRATING','PROMOTING','HEALTHY','FAILED','ROLLED_BACK')
  ),
  quality_gate_decision_id uuid not null,
  rollback_from_id uuid,
  correlation_id uuid not null,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  created_by_admin_id uuid not null,
  updated_at timestamptz not null default now(),
  constraint deployment_records_tenant_id_id_key unique (tenant_id,id),
  constraint deployment_records_quality_gate_fkey
    foreign key (tenant_id,quality_gate_decision_id)
    references public.quality_gate_decisions(tenant_id,id) on delete restrict,
  constraint deployment_records_rollback_fkey
    foreign key (tenant_id,rollback_from_id)
    references public.deployment_records(tenant_id,id) on delete restrict
);

create index deployment_records_environment_idx
on public.deployment_records (tenant_id,environment,started_at desc,id desc);

alter table public.deployment_records enable row level security;
alter table public.deployment_records force row level security;
revoke all on public.deployment_records
from public,anon,authenticated,service_role,agents_factory_app,agents_factory_admin;
grant select,insert,update on public.deployment_records to agents_factory_admin;
create policy deployment_records_admin_select on public.deployment_records for select to agents_factory_admin
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy deployment_records_admin_insert on public.deployment_records for insert to agents_factory_admin
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy deployment_records_admin_update on public.deployment_records for update to agents_factory_admin
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
