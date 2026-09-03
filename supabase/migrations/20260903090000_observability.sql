create table public.observability_events (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  event_kind text not null check (event_kind in ('LOG','METRIC','TRACE','HEALTH','ALERT')),
  severity text not null check (severity in ('DEBUG','INFO','WARNING','ERROR','CRITICAL')),
  name text not null check (name ~ '^[a-z][a-z0-9._-]{2,99}$'),
  trace_id uuid,
  correlation_id uuid not null,
  conversation_id uuid,
  message_id uuid,
  agent_spec_id uuid,
  knowledge_version_id uuid,
  capability text,
  tool_name text,
  connector_name text,
  action_id uuid,
  approval_id uuid,
  incident_id uuid,
  error_code text,
  cost_record_id uuid,
  duration_ms integer check (duration_ms is null or duration_ms >= 0),
  metric_value numeric,
  metric_unit text,
  status text,
  payload jsonb not null default '{}'::jsonb check (
    jsonb_typeof(payload) = 'object'
    and pg_column_size(payload) <= 16384
  ),
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint observability_events_tenant_id_id_key unique (tenant_id, id)
);

create table public.incidents (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  fingerprint text not null check (fingerprint ~ '^[a-f0-9]{64}$'),
  incident_type text not null,
  severity text not null check (severity in ('WARNING','ERROR','CRITICAL')),
  status text not null default 'OPEN' check (
    status in ('OPEN','ACKNOWLEDGED','RESOLVED')
  ),
  title text not null check (length(title) between 1 and 200),
  correlation_id uuid not null,
  occurrence_count integer not null default 1 check (occurrence_count > 0),
  first_detected_at timestamptz not null,
  last_detected_at timestamptz not null,
  evidence_until timestamptz not null,
  updated_at timestamptz not null default now(),
  constraint incidents_tenant_id_id_key unique (tenant_id, id),
  constraint incidents_time_order check (
    first_detected_at <= last_detected_at and last_detected_at <= evidence_until
  )
);

create unique index incidents_open_fingerprint_key
on public.incidents (tenant_id, fingerprint)
where status in ('OPEN','ACKNOWLEDGED');

create table public.incident_signals (
  id uuid primary key,
  tenant_id uuid not null,
  incident_id uuid not null,
  observability_event_id uuid,
  signal_type text not null,
  summary text not null check (length(summary) between 1 and 500),
  observed_at timestamptz not null,
  created_at timestamptz not null default now(),
  constraint incident_signals_incident_fkey
    foreign key (tenant_id, incident_id)
    references public.incidents(tenant_id, id) on delete restrict,
  constraint incident_signals_event_fkey
    foreign key (tenant_id, observability_event_id)
    references public.observability_events(tenant_id, id) on delete restrict,
  constraint incident_signals_tenant_id_id_key unique (tenant_id, id)
);

create index observability_trace_idx
on public.observability_events (tenant_id, trace_id, occurred_at, id);
create index observability_correlation_idx
on public.observability_events (tenant_id, correlation_id, occurred_at, id);
create index observability_health_idx
on public.observability_events (tenant_id, event_kind, name, occurred_at desc);
create index incidents_status_idx
on public.incidents (tenant_id, status, severity, last_detected_at desc);
create index incident_signals_incident_idx
on public.incident_signals (tenant_id, incident_id, observed_at, id);

create trigger observability_events_immutable
before update or delete on public.observability_events
for each row execute function agents_factory_private.reject_agent_spec_deployment_mutation();
create trigger incident_signals_immutable
before update or delete on public.incident_signals
for each row execute function agents_factory_private.reject_agent_spec_deployment_mutation();

alter table public.observability_events enable row level security;
alter table public.observability_events force row level security;
alter table public.incidents enable row level security;
alter table public.incidents force row level security;
alter table public.incident_signals enable row level security;
alter table public.incident_signals force row level security;

revoke all on public.observability_events, public.incidents, public.incident_signals
from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;
grant insert on public.observability_events to agents_factory_app;
grant select, insert on public.observability_events to agents_factory_admin;
grant select, insert, update on public.incidents to agents_factory_admin;
grant select, insert on public.incident_signals to agents_factory_admin;

create policy observability_events_runtime_insert
on public.observability_events for insert to agents_factory_app
with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy observability_events_admin_select
on public.observability_events for select to agents_factory_admin
using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy observability_events_admin_insert
on public.observability_events for insert to agents_factory_admin
with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy incidents_admin_select
on public.incidents for select to agents_factory_admin
using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy incidents_admin_insert
on public.incidents for insert to agents_factory_admin
with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy incidents_admin_update
on public.incidents for update to agents_factory_admin
using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy incident_signals_admin_select
on public.incident_signals for select to agents_factory_admin
using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy incident_signals_admin_insert
on public.incident_signals for insert to agents_factory_admin
with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
