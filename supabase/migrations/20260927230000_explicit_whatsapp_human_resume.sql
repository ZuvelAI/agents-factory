-- A human takeover may return to AI only through an identified admin action.
-- Preserve the existing tenant, actor, reason, version and audit-event guards.
create or replace function agents_factory_private.transition_conversation_control(
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
  v_account_id uuid;
  v_customer_wa_id text;
  v_eligible boolean;
begin
  v_tenant_id := nullif(current_setting('app.tenant_id', true), '')::uuid;
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
    or (
      p_expected_state = 'HUMAN_ACTIVE'
      and p_target_state = 'AI_ACTIVE'
      and p_actor_type = 'platform_admin'
      and p_actor_id is not null
      and current_setting('role', true) = 'agents_factory_admin'
    )
    or (p_expected_state = 'CLOSED' and p_target_state = 'AI_ACTIVE')
  ) then
    raise exception 'invalid conversation transition' using errcode = '22023';
  end if;

  if p_expected_state = 'HUMAN_ACTIVE' and p_target_state = 'AI_ACTIVE' then
    select c.whatsapp_account_id, c.customer_wa_id
    into v_account_id, v_customer_wa_id
    from public.conversations as c
    where c.id = p_conversation_id and c.tenant_id = v_tenant_id;
    if v_account_id is null then
      raise exception 'conversation transition precondition failed'
        using errcode = '40001';
    end if;

    -- Serialize with mobile echoes and outbound dispatch before row locks.
    perform pg_advisory_xact_lock(hashtextextended(
      'whatsapp-dispatch:' || v_tenant_id::text || ':' ||
      v_account_id::text || ':' || v_customer_wa_id, 0
    ));
    select (
      a.status = 'active'
      and a.mode = 'COEXISTENCE'
      and a.coexistence_eligibility = 'ELIGIBLE'
      and c.control_state = 'HUMAN_ACTIVE'
    )
    into v_eligible
    from public.conversations as c
    join public.whatsapp_accounts as a
      on a.tenant_id = c.tenant_id and a.id = c.whatsapp_account_id
    where c.id = p_conversation_id and c.tenant_id = v_tenant_id
    for update of c, a;
    if not coalesce(v_eligible, false) then
      raise exception 'active coexistence account required for AI resume'
        using errcode = '40001';
    end if;
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
    id, tenant_id, conversation_id, from_state, to_state, version,
    actor_id, actor_type, reason
  ) values (
    p_event_id, v_tenant_id, conversation_id, p_expected_state,
    p_target_state, state_version, p_actor_id, p_actor_type, p_reason
  );

  return next;
end;
$function$;
