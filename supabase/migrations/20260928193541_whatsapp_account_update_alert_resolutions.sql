create table agents_factory_private.whatsapp_account_update_alert_resolutions (
  alert_id uuid primary key references agents_factory_private.whatsapp_account_update_alerts (id),
  resolved_by uuid not null,
  resolution_note text not null check (
    resolution_note = btrim(resolution_note)
    and char_length(resolution_note) between 1 and 500
  ),
  resolved_at timestamptz not null default now()
);

alter table agents_factory_private.whatsapp_account_update_alert_resolutions
  enable row level security;
alter table agents_factory_private.whatsapp_account_update_alert_resolutions
  force row level security;

revoke all on agents_factory_private.whatsapp_account_update_alert_resolutions
  from public, anon, authenticated, service_role,
    agents_factory_app, agents_factory_admin;
grant select, insert
  on agents_factory_private.whatsapp_account_update_alert_resolutions
  to agents_factory_admin;

create policy whatsapp_account_update_alert_resolutions_admin_read
  on agents_factory_private.whatsapp_account_update_alert_resolutions for select
  to agents_factory_admin using (true);
create policy whatsapp_account_update_alert_resolutions_admin_insert
  on agents_factory_private.whatsapp_account_update_alert_resolutions for insert
  to agents_factory_admin with check (true);
