create table public.agent_operation_states (
  tenant_id uuid not null,
  agent_instance_id uuid not null,
  enabled boolean not null default true,
  revision bigint not null default 1 check (revision > 0),
  resumed_at timestamptz,
  updated_at timestamptz not null default clock_timestamp(),
  primary key (tenant_id, agent_instance_id),
  foreign key (tenant_id,agent_instance_id)
    references public.agent_instances(tenant_id,id) on delete restrict
);

insert into public.agent_operation_states (tenant_id,agent_instance_id)
select tenant_id,id from public.agent_instances;

alter table public.agent_operation_states enable row level security;
alter table public.agent_operation_states force row level security;
revoke all on public.agent_operation_states
  from public,anon,authenticated,service_role,agents_factory_app,agents_factory_admin;
grant select on public.agent_operation_states to agents_factory_app,agents_factory_admin;
grant insert on public.agent_operation_states to agents_factory_app,agents_factory_admin;
grant update (enabled,revision,resumed_at,updated_at) on public.agent_operation_states
  to agents_factory_admin;
create policy agent_operations_read on public.agent_operation_states
  for select to agents_factory_app,agents_factory_admin
  using (tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy agent_operations_insert on public.agent_operation_states
  for insert to agents_factory_app,agents_factory_admin
  with check (tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid
    and enabled and revision=1 and resumed_at is null);
create policy agent_operations_update on public.agent_operation_states
  for update to agents_factory_admin
  using (tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid)
  with check (tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
