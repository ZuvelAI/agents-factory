do $roles$
begin
  if not exists (select 1 from pg_roles where rolname = 'agents_factory_app') then
    execute 'create role agents_factory_app login nosuperuser nocreatedb nocreaterole noreplication nobypassrls password null';
  else
    execute 'alter role agents_factory_app with login nosuperuser nocreatedb nocreaterole noreplication nobypassrls password null';
  end if;

  if not exists (select 1 from pg_roles where rolname = 'agents_factory_admin') then
    execute 'create role agents_factory_admin login nosuperuser nocreatedb nocreaterole noreplication nobypassrls password null';
  else
    execute 'alter role agents_factory_admin with login nosuperuser nocreatedb nocreaterole noreplication nobypassrls password null';
  end if;
end
$roles$;

revoke all on schema public from public, anon, authenticated, service_role;
grant usage on schema public to agents_factory_app, agents_factory_admin;

create schema if not exists agents_factory_private;
revoke all on schema agents_factory_private from public, anon, authenticated, service_role;

create table public.tenants (
  id uuid primary key,
  slug text not null unique check (slug = lower(slug) and slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  name text not null check (length(btrim(name)) > 0),
  status text not null default 'active' check (status in ('active', 'suspended')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.platform_admins (
  user_id uuid primary key,
  created_at timestamptz not null default now(),
  constraint platform_admins_user_id_fkey
    foreign key (user_id) references auth.users(id) on delete cascade
);

create table public.audit_events (
  id uuid primary key,
  tenant_id uuid not null,
  actor_id uuid,
  actor_type text not null check (
    actor_type in ('platform_admin', 'customer', 'system', 'approver')
  ),
  event_type text not null check (length(btrim(event_type)) > 0),
  entity_type text not null check (length(btrim(entity_type)) > 0),
  entity_id uuid,
  correlation_id uuid not null,
  payload jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  constraint audit_events_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict,
  constraint audit_events_payload_object_check
    check (jsonb_typeof(payload) = 'object')
);

create table public.outbox_jobs (
  id uuid primary key,
  tenant_id uuid not null,
  idempotency_key text not null check (length(btrim(idempotency_key)) > 0),
  topic text not null check (length(btrim(topic)) > 0),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending' check (
    status in ('pending', 'processing', 'succeeded', 'failed', 'dead_letter')
  ),
  available_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint outbox_jobs_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict,
  constraint outbox_jobs_payload_object_check
    check (jsonb_typeof(payload) = 'object'),
  constraint outbox_jobs_tenant_id_idempotency_key_key
    unique (tenant_id, idempotency_key),
  constraint outbox_jobs_tenant_id_id_key
    unique (tenant_id, id)
);

create table public.job_attempts (
  id uuid primary key,
  tenant_id uuid not null,
  outbox_job_id uuid not null,
  attempt_number integer not null check (attempt_number > 0),
  status text not null check (status in ('started', 'succeeded', 'failed')),
  error_code text check (error_code is null or length(btrim(error_code)) > 0),
  occurred_at timestamptz not null default now(),
  constraint job_attempts_outbox_job_fkey
    foreign key (tenant_id, outbox_job_id)
    references public.outbox_jobs(tenant_id, id) on delete restrict,
  constraint job_attempts_tenant_job_attempt_key
    unique (tenant_id, outbox_job_id, attempt_number)
);

create table public.dead_letter_jobs (
  id uuid primary key,
  tenant_id uuid not null,
  outbox_job_id uuid not null,
  reason_code text not null check (length(btrim(reason_code)) > 0),
  status text not null default 'open' check (status in ('open', 'resolved', 'discarded')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint dead_letter_jobs_outbox_job_fkey
    foreign key (tenant_id, outbox_job_id)
    references public.outbox_jobs(tenant_id, id) on delete restrict,
  constraint dead_letter_jobs_tenant_job_key
    unique (tenant_id, outbox_job_id)
);

create index audit_events_tenant_id_idx
on public.audit_events (tenant_id);

create index job_attempts_outbox_job_id_idx
on public.job_attempts (tenant_id, outbox_job_id);

create index dead_letter_jobs_outbox_job_id_idx
on public.dead_letter_jobs (tenant_id, outbox_job_id);

create index outbox_jobs_pending_due_idx
on public.outbox_jobs (tenant_id, available_at, created_at)
where status = 'pending';

create function agents_factory_private.reject_audit_mutation()
returns trigger
language plpgsql
set search_path = ''
as $function$
begin
  raise exception using
    errcode = '55000',
    message = 'audit_events are append-only';
end
$function$;

revoke all on function agents_factory_private.reject_audit_mutation()
from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;

create trigger audit_events_reject_mutation
before update or delete on public.audit_events
for each row execute function agents_factory_private.reject_audit_mutation();

alter table public.tenants enable row level security;
alter table public.platform_admins enable row level security;
alter table public.audit_events enable row level security;
alter table public.outbox_jobs enable row level security;
alter table public.job_attempts enable row level security;
alter table public.dead_letter_jobs enable row level security;

alter table public.tenants force row level security;
alter table public.audit_events force row level security;
alter table public.outbox_jobs force row level security;
alter table public.job_attempts force row level security;
alter table public.dead_letter_jobs force row level security;

-- BEGIN CANONICAL TENANT ISOLATION POLICIES
create policy tenants_app_select
on public.tenants for select
to agents_factory_app
using (id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy tenants_app_insert
on public.tenants for insert
to agents_factory_app
with check (id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy tenants_app_update
on public.tenants for update
to agents_factory_app
using (id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy tenants_admin_select
on public.tenants for select
to agents_factory_admin
using (true);

create policy tenants_admin_insert
on public.tenants for insert
to agents_factory_admin
with check (true);

create policy tenants_admin_update
on public.tenants for update
to agents_factory_admin
using (true)
with check (true);

create policy platform_admins_admin_select
on public.platform_admins for select
to agents_factory_admin
using (true);

create policy platform_admins_admin_insert
on public.platform_admins for insert
to agents_factory_admin
with check (true);

create policy platform_admins_admin_delete
on public.platform_admins for delete
to agents_factory_admin
using (true);

create policy audit_events_app_select
on public.audit_events for select
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy audit_events_app_insert
on public.audit_events for insert
to agents_factory_app
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy audit_events_admin_select
on public.audit_events for select
to agents_factory_admin
using (true);

create policy audit_events_admin_insert
on public.audit_events for insert
to agents_factory_admin
with check (true);

create policy outbox_jobs_app_select
on public.outbox_jobs for select
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy outbox_jobs_app_insert
on public.outbox_jobs for insert
to agents_factory_app
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy outbox_jobs_app_update
on public.outbox_jobs for update
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy outbox_jobs_admin_select
on public.outbox_jobs for select
to agents_factory_admin
using (true);

create policy outbox_jobs_admin_insert
on public.outbox_jobs for insert
to agents_factory_admin
with check (true);

create policy outbox_jobs_admin_update
on public.outbox_jobs for update
to agents_factory_admin
using (true)
with check (true);

create policy job_attempts_app_select
on public.job_attempts for select
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy job_attempts_app_insert
on public.job_attempts for insert
to agents_factory_app
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy job_attempts_app_update
on public.job_attempts for update
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy job_attempts_admin_select
on public.job_attempts for select
to agents_factory_admin
using (true);

create policy job_attempts_admin_insert
on public.job_attempts for insert
to agents_factory_admin
with check (true);

create policy job_attempts_admin_update
on public.job_attempts for update
to agents_factory_admin
using (true)
with check (true);

create policy dead_letter_jobs_app_select
on public.dead_letter_jobs for select
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy dead_letter_jobs_app_insert
on public.dead_letter_jobs for insert
to agents_factory_app
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy dead_letter_jobs_app_update
on public.dead_letter_jobs for update
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy dead_letter_jobs_admin_select
on public.dead_letter_jobs for select
to agents_factory_admin
using (true);

create policy dead_letter_jobs_admin_insert
on public.dead_letter_jobs for insert
to agents_factory_admin
with check (true);

create policy dead_letter_jobs_admin_update
on public.dead_letter_jobs for update
to agents_factory_admin
using (true)
with check (true);
-- END CANONICAL TENANT ISOLATION POLICIES

revoke all on all tables in schema public
from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;

grant select, insert, update on public.tenants
to agents_factory_app, agents_factory_admin;

grant select, insert on public.audit_events
to agents_factory_app, agents_factory_admin;

grant select, insert, update on public.outbox_jobs
to agents_factory_app, agents_factory_admin;

grant select, insert, update on public.job_attempts
to agents_factory_app, agents_factory_admin;

grant select, insert, update on public.dead_letter_jobs
to agents_factory_app, agents_factory_admin;

grant select, insert, delete on public.platform_admins
to agents_factory_admin;

alter default privileges in schema public
revoke all on tables from public, anon, authenticated, service_role;

alter default privileges in schema public
revoke execute on functions from public, anon, authenticated, service_role;

alter default privileges in schema agents_factory_private
revoke execute on functions from public, anon, authenticated, service_role;
