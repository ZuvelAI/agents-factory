create function agents_factory_private.apply_whatsapp_partner_removed(
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
  account record;
begin
  select id, status, verified_at
    into account
  from public.whatsapp_accounts
  where provider = 'meta'
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
  where id = account.id;
  return 'deactivated';
end;
$function$;

revoke all on function
  agents_factory_private.apply_whatsapp_partner_removed(text, text, timestamptz)
from public, anon, authenticated, service_role, agents_factory_admin;

grant execute on function
  agents_factory_private.apply_whatsapp_partner_removed(text, text, timestamptz)
to agents_factory_app;
