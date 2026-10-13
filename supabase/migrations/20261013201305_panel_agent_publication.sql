create table public.agent_approved_knowledge_versions (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  digest text not null check (digest ~ '^[0-9a-f]{64}$'),
  snapshot jsonb not null check (jsonb_typeof(snapshot) = 'object'),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, digest)
);

alter table public.agent_approved_knowledge_versions enable row level security;
alter table public.agent_approved_knowledge_versions force row level security;

create policy approved_knowledge_select
on public.agent_approved_knowledge_versions for select
to agents_factory_admin, agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id',true)), '')::uuid);

create policy approved_knowledge_insert
on public.agent_approved_knowledge_versions for insert to agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id',true)), '')::uuid);

revoke all on public.agent_approved_knowledge_versions
from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;
grant select on public.agent_approved_knowledge_versions to agents_factory_app;
grant select, insert on public.agent_approved_knowledge_versions to agents_factory_admin;

create function agents_factory_private.reject_approved_knowledge_mutation()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  raise exception 'Approved knowledge versions are immutable';
end;
$$;
revoke all on function agents_factory_private.reject_approved_knowledge_mutation() from public;
create trigger approved_knowledge_immutable
before update or delete on public.agent_approved_knowledge_versions
for each row execute function agents_factory_private.reject_approved_knowledge_mutation();
