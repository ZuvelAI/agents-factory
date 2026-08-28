alter table public.whatsapp_webhook_events
add column normalized_content jsonb not null default '{}'::jsonb,
add constraint whatsapp_webhook_events_normalized_content_object_check
  check (jsonb_typeof(normalized_content) = 'object'),
add constraint whatsapp_webhook_events_tenant_id_id_key
  unique (tenant_id, id);

create table public.conversations (
  id uuid primary key,
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  customer_wa_id text not null check (
    customer_wa_id = btrim(customer_wa_id)
    and length(customer_wa_id) between 1 and 100
  ),
  control_state text not null default 'AI_ACTIVE' check (
    control_state in ('AI_ACTIVE', 'AWAITING_HUMAN', 'HUMAN_ACTIVE', 'CLOSED')
  ),
  state_version integer not null default 1 check (state_version > 0),
  opened_at timestamptz not null default now(),
  closed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint conversations_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict,
  constraint conversations_whatsapp_account_fkey
    foreign key (tenant_id, whatsapp_account_id)
    references public.whatsapp_accounts(tenant_id, id) on delete restrict,
  constraint conversations_closed_state_check check (
    (control_state = 'CLOSED') = (closed_at is not null)
  ),
  constraint conversations_tenant_account_customer_key
    unique (tenant_id, whatsapp_account_id, customer_wa_id),
  constraint conversations_tenant_id_id_key unique (tenant_id, id)
);

create table public.messages (
  id uuid primary key,
  tenant_id uuid not null,
  conversation_id uuid not null,
  source_event_id uuid,
  direction text not null check (direction in ('inbound', 'outbound', 'system')),
  sender_type text not null check (
    sender_type in ('customer', 'ai', 'human', 'system')
  ),
  provider_message_id text check (
    provider_message_id is null
    or (
      provider_message_id = btrim(provider_message_id)
      and length(provider_message_id) between 1 and 500
    )
  ),
  message_type text not null check (
    message_type in (
      'text', 'audio', 'image', 'document', 'location', 'contacts', 'video',
      'template'
    )
  ),
  content jsonb not null default '{}'::jsonb check (
    jsonb_typeof(content) = 'object'
  ),
  provider_timestamp timestamptz not null,
  arrival_sequence bigint not null check (arrival_sequence > 0),
  created_at timestamptz not null default now(),
  constraint messages_conversation_fkey
    foreign key (tenant_id, conversation_id)
    references public.conversations(tenant_id, id) on delete restrict,
  constraint messages_source_event_fkey
    foreign key (tenant_id, source_event_id)
    references public.whatsapp_webhook_events(tenant_id, id) on delete restrict,
  constraint messages_tenant_source_event_key unique (tenant_id, source_event_id),
  constraint messages_conversation_arrival_key
    unique (tenant_id, conversation_id, arrival_sequence),
  constraint messages_tenant_id_id_key unique (tenant_id, id)
);

create table public.conversation_state_events (
  id uuid primary key,
  tenant_id uuid not null,
  conversation_id uuid not null,
  from_state text check (
    from_state is null
    or from_state in ('AI_ACTIVE', 'AWAITING_HUMAN', 'HUMAN_ACTIVE', 'CLOSED')
  ),
  to_state text not null check (
    to_state in ('AI_ACTIVE', 'AWAITING_HUMAN', 'HUMAN_ACTIVE', 'CLOSED')
  ),
  version integer not null check (version > 0),
  actor_id uuid,
  actor_type text not null check (
    actor_type in ('platform_admin', 'customer', 'system', 'approver')
  ),
  reason text not null check (
    reason = btrim(reason) and length(reason) between 1 and 200
  ),
  occurred_at timestamptz not null default now(),
  constraint conversation_state_events_conversation_fkey
    foreign key (tenant_id, conversation_id)
    references public.conversations(tenant_id, id) on delete restrict,
  constraint conversation_state_events_conversation_version_key
    unique (tenant_id, conversation_id, version)
);

create index messages_conversation_order_idx
on public.messages (
  tenant_id, conversation_id, provider_timestamp, arrival_sequence
);

create index conversation_state_events_conversation_idx
on public.conversation_state_events (tenant_id, conversation_id, version);

create function agents_factory_private.enforce_initial_conversation_state()
returns trigger
language plpgsql
set search_path = ''
as $function$
begin
  if new.control_state <> 'AI_ACTIVE'
    or new.state_version <> 1
    or new.closed_at is not null
  then
    raise exception 'conversation must start AI_ACTIVE at version 1'
      using errcode = '22023';
  end if;
  return new;
end;
$function$;

create trigger conversations_enforce_initial_state
before insert on public.conversations
for each row execute function
  agents_factory_private.enforce_initial_conversation_state();

revoke all on function
  agents_factory_private.enforce_initial_conversation_state()
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

create function agents_factory_private.transition_conversation_control(
  p_event_id uuid,
  p_conversation_id uuid,
  p_expected_state text,
  p_target_state text,
  p_actor_id uuid,
  p_actor_type text,
  p_reason text
)
returns table (
  conversation_id uuid,
  control_state text,
  state_version integer,
  opened_at timestamptz,
  closed_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_tenant_id uuid;
begin
  v_tenant_id := nullif(
    current_setting('app.tenant_id', true),
    ''
  )::uuid;
  if v_tenant_id is null then
    raise exception 'tenant context is required' using errcode = '42501';
  end if;
  if p_reason is null
    or p_reason <> btrim(p_reason)
    or length(p_reason) not between 1 and 200
  then
    raise exception 'invalid transition reason' using errcode = '22023';
  end if;
  if p_actor_type not in (
    'platform_admin', 'customer', 'system', 'approver'
  ) then
    raise exception 'invalid transition actor' using errcode = '22023';
  end if;
  if not (
    (p_expected_state = 'AI_ACTIVE' and p_target_state in (
      'AWAITING_HUMAN', 'CLOSED'
    ))
    or (
      p_expected_state = 'AWAITING_HUMAN'
      and p_target_state in ('HUMAN_ACTIVE', 'CLOSED')
    )
    or (p_expected_state = 'HUMAN_ACTIVE' and p_target_state = 'CLOSED')
    or (p_expected_state = 'CLOSED' and p_target_state = 'AI_ACTIVE')
  ) then
    raise exception 'invalid conversation transition' using errcode = '22023';
  end if;

  update public.conversations as conversation
  set control_state = p_target_state,
      state_version = conversation.state_version + 1,
      opened_at = case
        when p_target_state = 'AI_ACTIVE' then now()
        else conversation.opened_at
      end,
      closed_at = case
        when p_target_state = 'CLOSED' then now()
        else null
      end,
      updated_at = now()
  where conversation.id = p_conversation_id
    and conversation.tenant_id = v_tenant_id
    and conversation.control_state = p_expected_state
  returning conversation.id,
            conversation.control_state,
            conversation.state_version,
            conversation.opened_at,
            conversation.closed_at
  into conversation_id, control_state, state_version, opened_at, closed_at;

  if conversation_id is null then
    raise exception 'conversation transition precondition failed'
      using errcode = '40001';
  end if;

  insert into public.conversation_state_events (
    id,
    tenant_id,
    conversation_id,
    from_state,
    to_state,
    version,
    actor_id,
    actor_type,
    reason
  ) values (
    p_event_id,
    v_tenant_id,
    conversation_id,
    p_expected_state,
    p_target_state,
    state_version,
    p_actor_id,
    p_actor_type,
    p_reason
  );

  return next;
end;
$function$;

revoke all on function
  agents_factory_private.transition_conversation_control(
    uuid, uuid, text, text, uuid, text, text
  )
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

grant execute on function
  agents_factory_private.transition_conversation_control(
    uuid, uuid, text, text, uuid, text, text
  )
to agents_factory_app, agents_factory_admin;

alter table public.conversations enable row level security;
alter table public.conversations force row level security;
alter table public.messages enable row level security;
alter table public.messages force row level security;
alter table public.conversation_state_events enable row level security;
alter table public.conversation_state_events force row level security;

revoke all on table public.conversations
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

revoke all on table public.messages
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

revoke all on table public.conversation_state_events
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

create policy conversations_app_select
on public.conversations for select
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy conversations_app_insert
on public.conversations for insert
to agents_factory_app
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy conversations_app_update
on public.conversations for update
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
)
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy conversations_admin_select
on public.conversations for select
to agents_factory_admin
using (true);

create policy conversations_admin_insert
on public.conversations for insert
to agents_factory_admin
with check (true);

create policy messages_app_select
on public.messages for select
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy messages_app_insert
on public.messages for insert
to agents_factory_app
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy messages_admin_select
on public.messages for select
to agents_factory_admin
using (true);

create policy messages_admin_insert
on public.messages for insert
to agents_factory_admin
with check (true);

create policy conversation_state_events_app_select
on public.conversation_state_events for select
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy conversation_state_events_app_insert
on public.conversation_state_events for insert
to agents_factory_app
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy conversation_state_events_admin_select
on public.conversation_state_events for select
to agents_factory_admin
using (true);

create policy conversation_state_events_admin_insert
on public.conversation_state_events for insert
to agents_factory_admin
with check (true);

grant select, insert on table public.conversations
to agents_factory_app;

grant update (updated_at) on table public.conversations
to agents_factory_app;

grant select, insert on table public.messages
to agents_factory_app;

grant select, insert on table public.conversation_state_events
to agents_factory_app;

grant select, insert on table public.conversations
to agents_factory_admin;

grant select, insert, update on table public.messages
to agents_factory_admin;

grant select, insert on table public.conversation_state_events
to agents_factory_admin;
