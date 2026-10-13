create table public.account_agent_bindings (
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  agent_instance_id uuid not null,
  version_id uuid not null,
  revision integer not null check(revision>0),
  updated_at timestamptz not null default now(),
  primary key(tenant_id,whatsapp_account_id),
  foreign key(tenant_id,whatsapp_account_id) references public.whatsapp_accounts(tenant_id,id) on delete restrict,
  foreign key(tenant_id,agent_instance_id,version_id) references public.agent_spec_versions(tenant_id,agent_instance_id,id) on delete restrict
);
create table public.account_agent_binding_history (
  id uuid primary key,
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  agent_instance_id uuid not null,
  version_id uuid not null,
  revision integer not null check(revision>0),
  action text not null check(action in ('PUBLISH','ROLLBACK')),
  created_at timestamptz not null default now(),
  unique(tenant_id,whatsapp_account_id,revision),
  foreign key(tenant_id,whatsapp_account_id) references public.whatsapp_accounts(tenant_id,id) on delete restrict,
  foreign key(tenant_id,agent_instance_id,version_id) references public.agent_spec_versions(tenant_id,agent_instance_id,id) on delete restrict
);
alter table public.account_agent_bindings enable row level security;
alter table public.account_agent_bindings force row level security;
alter table public.account_agent_binding_history enable row level security;
alter table public.account_agent_binding_history force row level security;
create policy bindings_select on public.account_agent_bindings for select to agents_factory_admin,agents_factory_app
using(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy bindings_admin_write on public.account_agent_bindings for all to agents_factory_admin
using(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid)
with check(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy binding_history_select on public.account_agent_binding_history for select to agents_factory_admin,agents_factory_app
using(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy binding_history_insert on public.account_agent_binding_history for insert to agents_factory_admin
with check(tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
revoke all on public.account_agent_bindings,public.account_agent_binding_history
from public,anon,authenticated,service_role,agents_factory_admin,agents_factory_app;
grant select on public.account_agent_bindings,public.account_agent_binding_history to agents_factory_app;
grant select,insert,update on public.account_agent_bindings to agents_factory_admin;
grant select,insert on public.account_agent_binding_history to agents_factory_admin;
create trigger binding_history_immutable before update or delete on public.account_agent_binding_history
for each row execute function agents_factory_private.reject_approved_knowledge_mutation();
