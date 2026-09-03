set check_function_bodies = off;

CREATE OR REPLACE FUNCTION agents_factory_private.enforce_action_lifecycle()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
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
      or old.state = 'AWAITING_APPROVAL'
      and new.state in ('REJECTED', 'EXPIRED')
    ) then
    raise exception 'Invalid action result update'
      using errcode = '55000';
  end if;
  return new;
end
$function$
;


