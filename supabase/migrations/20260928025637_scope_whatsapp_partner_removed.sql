-- A verified webhook must first resolve the exact account, then enter that
-- tenant's transaction context. The mutation itself never crosses context.
create function agents_factory_private.resolve_whatsapp_update_tenant(
  p_waba_id text,
  p_display_phone_digits text
)
returns uuid
language sql
stable
security definer
set search_path = ''
as $function$
  select account.tenant_id
  from public.whatsapp_accounts as account
  where account.provider = 'meta'
    and account.mode = 'COEXISTENCE'
    and account.waba_id = p_waba_id
    and account.display_phone_digits = p_display_phone_digits
  order by (account.status = 'active') desc,
           account.verified_at desc nulls last
  limit 1;
$function$;

revoke all on function
  agents_factory_private.resolve_whatsapp_update_tenant(text, text)
from public, anon, authenticated, service_role, agents_factory_admin;
grant execute on function
  agents_factory_private.resolve_whatsapp_update_tenant(text, text)
to agents_factory_app;

create or replace function agents_factory_private.apply_whatsapp_partner_removed(
  p_waba_id text,
  p_display_phone_digits text,
  p_occurred_at timestamptz
)
returns text
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_tenant_id uuid;
  account record;
begin
  v_tenant_id := nullif(current_setting('app.tenant_id', true), '')::uuid;
  if v_tenant_id is null then
    raise exception 'tenant context is required' using errcode = '42501';
  end if;

  select id, status, verified_at
    into account
  from public.whatsapp_accounts
  where tenant_id = v_tenant_id
    and provider = 'meta'
    and mode = 'COEXISTENCE'
    and waba_id = p_waba_id
    and display_phone_digits = p_display_phone_digits
  order by (status = 'active') desc, verified_at desc nulls last
  limit 1
  for update;

  if not found then
    return 'unmatched';
  end if;
  if account.status = 'inactive' then
    return 'already_inactive';
  end if;
  if account.verified_at is null then
    return 'unverified';
  end if;
  if p_occurred_at < account.verified_at then
    return 'stale';
  end if;

  update public.whatsapp_accounts
  set status = 'inactive',
      health_status = 'REAUTH_REQUIRED',
      last_error_code = 'meta_partner_removed',
      last_health_checked_at = now(),
      updated_at = now()
  where id = account.id and tenant_id = v_tenant_id;
  return 'deactivated';
end;
$function$;
