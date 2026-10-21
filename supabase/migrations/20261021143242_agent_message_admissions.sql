create table public.agent_message_admissions (
  tenant_id uuid not null,
  source_event_id uuid not null,
  whatsapp_account_id uuid not null,
  agent_instance_id uuid,
  operation_revision bigint,
  binding_revision integer,
  eligible boolean not null,
  reason text not null check (reason in ('eligible','paused','before_resume','invalid_timestamp','unassigned','operation_unavailable')),
  admitted_at timestamptz not null default clock_timestamp(),
  primary key (tenant_id,source_event_id),
  foreign key (tenant_id,source_event_id) references public.whatsapp_webhook_events(tenant_id,id) on delete restrict,
  foreign key (tenant_id,whatsapp_account_id) references public.whatsapp_accounts(tenant_id,id) on delete restrict,
  foreign key (tenant_id,agent_instance_id) references public.agent_instances(tenant_id,id) on delete restrict,
  check (eligible=(reason='eligible')),
  check (not eligible or (agent_instance_id is not null and operation_revision>0 and binding_revision>0))
);
alter table public.agent_message_admissions enable row level security;
alter table public.agent_message_admissions force row level security;
revoke all on public.agent_message_admissions from public,anon,authenticated,service_role,agents_factory_admin,agents_factory_app;
grant select on public.agent_message_admissions to agents_factory_admin,agents_factory_app;
grant insert on public.agent_message_admissions to agents_factory_app;
create policy admissions_read on public.agent_message_admissions for select to agents_factory_admin,agents_factory_app
using (tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy admissions_insert on public.agent_message_admissions for insert to agents_factory_app
with check (tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create trigger admissions_immutable before update or delete on public.agent_message_admissions
for each row execute function agents_factory_private.reject_approved_knowledge_mutation();
