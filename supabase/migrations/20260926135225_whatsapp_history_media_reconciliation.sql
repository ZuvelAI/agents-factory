grant update (content) on public.whatsapp_history_messages
  to agents_factory_app, agents_factory_admin;

create policy whatsapp_history_messages_media_update on public.whatsapp_history_messages
for update to agents_factory_app, agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create function agents_factory_private.enforce_history_media_reconciliation()
returns trigger language plpgsql set search_path = pg_catalog as $$
begin
  if old.content->>'type' <> 'media_placeholder'
    or new.content->>'id' is distinct from old.content->>'id'
    or new.content->>'type' not in ('image', 'audio', 'video', 'document') then
    raise exception 'Invalid historical media reconciliation' using errcode = '23514';
  end if;
  return new;
end;
$$;

create trigger whatsapp_history_messages_media_reconciliation_guard
before update of content on public.whatsapp_history_messages
for each row execute function agents_factory_private.enforce_history_media_reconciliation();
