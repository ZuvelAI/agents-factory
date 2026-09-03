do $block$
begin
  if not exists (select 1 from pg_roles where rolname='agents_factory_key_rotation') then
    create role agents_factory_key_rotation nologin nobypassrls;
  end if;
end
$block$;

create table public.secret_rotation_runs (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  old_key_version integer not null check (old_key_version>0),
  new_key_version integer not null check (new_key_version>old_key_version),
  status text not null check (status in ('RUNNING','COMPLETED','FAILED')),
  rotated_count integer not null default 0 check (rotated_count>=0),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  error_code text,
  constraint secret_rotation_runs_tenant_id_id_key unique (tenant_id,id)
);

alter table public.secret_rotation_runs enable row level security;
alter table public.secret_rotation_runs force row level security;
revoke all on public.secret_rotation_runs
from public,anon,authenticated,service_role,agents_factory_app,agents_factory_admin,
  agents_factory_key_rotation;
grant select on public.secret_envelopes to agents_factory_key_rotation;
grant update (wrapped_data_key,key_nonce,key_id,key_version)
on public.secret_envelopes to agents_factory_key_rotation;
grant select,insert,update on public.secret_rotation_runs to agents_factory_key_rotation;
grant select on public.secret_rotation_runs to agents_factory_admin;

create policy secret_envelopes_key_rotation_select
on public.secret_envelopes for select to agents_factory_key_rotation
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy secret_envelopes_key_rotation_update
on public.secret_envelopes for update to agents_factory_key_rotation
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy secret_rotation_runs_rotation_select
on public.secret_rotation_runs for select to agents_factory_key_rotation
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy secret_rotation_runs_rotation_insert
on public.secret_rotation_runs for insert to agents_factory_key_rotation
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy secret_rotation_runs_rotation_update
on public.secret_rotation_runs for update to agents_factory_key_rotation
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy secret_rotation_runs_admin_select
on public.secret_rotation_runs for select to agents_factory_admin
using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
