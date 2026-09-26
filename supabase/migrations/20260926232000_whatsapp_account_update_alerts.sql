create table agents_factory_private.whatsapp_account_update_alerts (
  id uuid primary key,
  event_fingerprint text not null unique
    check (event_fingerprint ~ '^[0-9a-f]{64}$'),
  waba_id text not null check (
    waba_id = btrim(waba_id) and length(waba_id) between 1 and 200
  ),
  event text not null check (
    event = btrim(event) and length(event) between 1 and 100
  ),
  display_phone_digits text check (
    display_phone_digits is null or display_phone_digits ~ '^[0-9]{7,20}$'
  ),
  occurred_at timestamptz not null,
  reason text not null check (reason in ('unmatched', 'unverified', 'unsupported_event')),
  received_at timestamptz not null default now()
);

create index whatsapp_account_update_alerts_received_idx
  on agents_factory_private.whatsapp_account_update_alerts (received_at, id);

alter table agents_factory_private.whatsapp_account_update_alerts
  enable row level security;
alter table agents_factory_private.whatsapp_account_update_alerts
  force row level security;

revoke all on agents_factory_private.whatsapp_account_update_alerts
  from public, anon, authenticated, service_role,
    agents_factory_app, agents_factory_admin;
grant insert on agents_factory_private.whatsapp_account_update_alerts
  to agents_factory_app;
grant select on agents_factory_private.whatsapp_account_update_alerts
  to agents_factory_admin;

create policy whatsapp_account_update_alerts_app_insert
  on agents_factory_private.whatsapp_account_update_alerts for insert
  to agents_factory_app with check (true);
create policy whatsapp_account_update_alerts_admin_read
  on agents_factory_private.whatsapp_account_update_alerts for select
  to agents_factory_admin using (true);
