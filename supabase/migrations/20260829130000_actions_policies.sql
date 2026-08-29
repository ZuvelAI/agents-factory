create table public.actions (
  id uuid primary key,
  tenant_id uuid not null,
  conversation_id uuid not null,
  customer_ref text not null check (
    customer_ref = btrim(customer_ref) and length(customer_ref) between 1 and 300
  ),
  capability text not null check (capability ~ '^[a-z][a-z0-9_]*$'),
  action_type text not null check (
    action_type ~ '^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$'
  ),
  risk text not null check (risk in ('LOW', 'MEDIUM', 'HIGH')),
  required_identity_level smallint not null check (
    required_identity_level between 0 and 3
  ),
  achieved_identity_level smallint not null check (
    achieved_identity_level between 0 and 3
  ),
  parameters jsonb not null check (jsonb_typeof(parameters) = 'object'),
  parameter_digest text not null check (parameter_digest ~ '^[0-9a-f]{64}$'),
  confirmation_required boolean not null,
  confirmation_digest text check (
    confirmation_digest is null or confirmation_digest ~ '^[0-9a-f]{64}$'
  ),
  confirmed_at timestamptz,
  confirmation_expires_at timestamptz,
  approval_required boolean not null,
  approval_route_ref text,
  approval_reference text,
  approved_at timestamptz,
  connector_binding_id uuid not null,
  connector_name text not null check (
    connector_name ~ '^[a-z][a-z0-9_]*$'
  ),
  state text not null check (
    state in (
      'REQUESTED', 'IDENTITY_VERIFIED', 'AWAITING_CONFIRMATION', 'CONFIRMED',
      'AWAITING_APPROVAL', 'EXECUTING', 'SUCCEEDED', 'REJECTED', 'FAILED',
      'UNCERTAIN', 'EXPIRED', 'HANDED_OFF'
    )
  ),
  result jsonb not null default '{}'::jsonb check (jsonb_typeof(result) = 'object'),
  execution_attempts integer not null default 0 check (execution_attempts >= 0),
  created_at timestamptz not null,
  updated_at timestamptz not null,
  unique (tenant_id, id),
  foreign key (tenant_id, conversation_id)
    references public.conversations(tenant_id, id) on delete restrict,
  check (action_type like capability || '.%'),
  check (
    (not confirmation_required and confirmation_digest is null
      and confirmed_at is null and confirmation_expires_at is null)
    or
    (confirmation_required and confirmation_expires_at is not null
      and (
        (confirmation_digest is null and confirmed_at is null)
        or (confirmation_digest is not null and confirmed_at is not null)
      ))
  ),
  check (
    (not approval_required and approval_route_ref is null
      and approval_reference is null and approved_at is null)
    or
    (approval_required and approval_route_ref is not null and (
      (approval_reference is null and approved_at is null)
      or (approval_reference is not null and approved_at is not null)
    ))
  )
);

create table public.action_events (
  id uuid primary key,
  tenant_id uuid not null,
  action_id uuid not null,
  version integer not null check (version > 0),
  from_state text,
  to_state text not null,
  event_type text not null check (
    event_type = btrim(event_type) and length(event_type) between 1 and 200
  ),
  payload jsonb not null default '{}'::jsonb check (jsonb_typeof(payload) = 'object'),
  created_at timestamptz not null,
  unique (tenant_id, action_id, version),
  foreign key (tenant_id, action_id)
    references public.actions(tenant_id, id) on delete restrict
);

create index actions_conversation_idx
on public.actions (tenant_id, conversation_id, created_at desc);

create function agents_factory_private.enforce_action_lifecycle()
returns trigger
language plpgsql
set search_path = pg_catalog
as $function$
begin
  if tg_op = 'INSERT' then
    if new.state <> 'REQUESTED' or new.execution_attempts <> 0
      or new.result <> '{}'::jsonb then
      raise exception 'Actions must begin in REQUESTED'
        using errcode = '55000';
    end if;
    return new;
  end if;
  if tg_op = 'DELETE' then
    raise exception 'Action history is immutable'
      using errcode = '55000';
  end if;
  if row(
    new.id, new.tenant_id, new.conversation_id, new.customer_ref,
    new.capability, new.action_type, new.risk, new.required_identity_level,
    new.achieved_identity_level, new.parameters, new.parameter_digest,
    new.confirmation_required, new.confirmation_expires_at,
    new.approval_required, new.approval_route_ref,
    new.connector_binding_id, new.connector_name, new.created_at
  ) is distinct from row(
    old.id, old.tenant_id, old.conversation_id, old.customer_ref,
    old.capability, old.action_type, old.risk, old.required_identity_level,
    old.achieved_identity_level, old.parameters, old.parameter_digest,
    old.confirmation_required, old.confirmation_expires_at,
    old.approval_required, old.approval_route_ref,
    old.connector_binding_id, old.connector_name, old.created_at
  ) then
    raise exception 'Action request fields are immutable'
      using errcode = '55000';
  end if;
  if new.state <> old.state and not (
    (old.state = 'REQUESTED' and new.state in ('IDENTITY_VERIFIED', 'REJECTED'))
    or (old.state = 'IDENTITY_VERIFIED'
      and new.state in ('AWAITING_CONFIRMATION', 'CONFIRMED'))
    or (old.state = 'AWAITING_CONFIRMATION'
      and new.state in ('CONFIRMED', 'REJECTED', 'EXPIRED'))
    or (old.state = 'CONFIRMED'
      and new.state in ('AWAITING_APPROVAL', 'EXECUTING', 'FAILED'))
    or (old.state = 'AWAITING_APPROVAL'
      and new.state in ('EXECUTING', 'REJECTED', 'FAILED', 'EXPIRED'))
    or (old.state = 'EXECUTING'
      and new.state in ('SUCCEEDED', 'FAILED', 'UNCERTAIN', 'HANDED_OFF'))
  ) then
    raise exception 'Invalid action lifecycle transition'
      using errcode = '55000';
  end if;
  if new.execution_attempts <> old.execution_attempts
    and not (
      new.state = 'EXECUTING'
      and old.state in ('CONFIRMED', 'AWAITING_APPROVAL')
      and new.execution_attempts = old.execution_attempts + 1
    ) then
    raise exception 'Invalid action execution attempt update'
      using errcode = '55000';
  end if;
  if row(new.confirmation_digest, new.confirmed_at)
    is distinct from row(old.confirmation_digest, old.confirmed_at)
    and not (
      old.state = 'AWAITING_CONFIRMATION'
      and new.state = 'CONFIRMED'
      and old.confirmation_digest is null
      and old.confirmed_at is null
      and new.confirmation_digest is not null
      and new.confirmed_at is not null
    ) then
    raise exception 'Invalid confirmation evidence update'
      using errcode = '55000';
  end if;
  if row(new.approval_reference, new.approved_at)
    is distinct from row(old.approval_reference, old.approved_at)
    and not (
      old.state = 'AWAITING_APPROVAL'
      and new.state = 'AWAITING_APPROVAL'
      and old.approval_reference is null
      and old.approved_at is null
      and new.approval_reference is not null
      and new.approved_at is not null
    ) then
    raise exception 'Invalid approval evidence update'
      using errcode = '55000';
  end if;
  if new.result is distinct from old.result
    and not (
      old.state = 'EXECUTING'
      and new.state in ('SUCCEEDED', 'FAILED', 'UNCERTAIN', 'HANDED_OFF')
      or old.state in ('CONFIRMED', 'AWAITING_APPROVAL')
      and new.state = 'FAILED'
    ) then
    raise exception 'Invalid action result update'
      using errcode = '55000';
  end if;
  return new;
end
$function$;

create trigger actions_lifecycle_guard
before insert or update or delete on public.actions
for each row execute function agents_factory_private.enforce_action_lifecycle();

create trigger action_events_append_only
before update or delete or truncate on public.action_events
for each statement execute function
agents_factory_private.reject_agent_spec_deployment_mutation();

alter table public.actions enable row level security;
alter table public.actions force row level security;
alter table public.action_events enable row level security;
alter table public.action_events force row level security;

create policy actions_app_select on public.actions for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy actions_app_insert on public.actions for insert to agents_factory_app
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy actions_app_update on public.actions for update to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy actions_admin_all on public.actions for all to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy action_events_app_select
on public.action_events for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy action_events_app_insert
on public.action_events for insert to agents_factory_app
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy action_events_admin_select
on public.action_events for select to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy action_events_admin_insert
on public.action_events for insert to agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

revoke all on table public.actions, public.action_events from public, anon,
  authenticated, service_role, agents_factory_app, agents_factory_admin;
grant select, insert, update on table public.actions
to agents_factory_app, agents_factory_admin;
grant select, insert on table public.action_events
to agents_factory_app, agents_factory_admin;
