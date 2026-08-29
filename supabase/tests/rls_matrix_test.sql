begin;

create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions, pg_catalog;

select no_plan();

create temp table task5_tenant_isolation_registry (
  table_name text primary key,
  owner_column text not null
) on commit drop;

insert into task5_tenant_isolation_registry (table_name, owner_column)
values
  ('public.tenants', 'id'),
  ('public.audit_events', 'tenant_id'),
  ('public.outbox_jobs', 'tenant_id'),
  ('public.job_attempts', 'tenant_id'),
  ('public.dead_letter_jobs', 'tenant_id'),
  ('public.secret_envelopes', 'tenant_id'),
  ('public.whatsapp_accounts', 'tenant_id'),
  ('public.whatsapp_webhook_events', 'tenant_id'),
  ('public.whatsapp_templates', 'tenant_id'),
  ('public.conversations', 'tenant_id'),
  ('public.messages', 'tenant_id'),
  ('public.conversation_state_events', 'tenant_id'),
  ('public.outbound_messages', 'tenant_id'),
  ('public.agent_instances', 'tenant_id'),
  ('public.agent_spec_versions', 'tenant_id'),
  ('public.agent_spec_deployments', 'tenant_id'),
  ('public.identity_subjects', 'tenant_id'),
  ('public.identity_challenges', 'tenant_id'),
  ('public.identity_evidence', 'tenant_id');

create function pg_temp.tenant_owned_catalog()
returns table (qualified_name text, owner_column text)
language sql
stable
set search_path = pg_catalog
as $function$
  select
    format('%I.%I', namespace.nspname, relation.relname) as qualified_name,
    attribute.attname as owner_column
  from pg_class as relation
  join pg_namespace as namespace on namespace.oid = relation.relnamespace
  join pg_attribute as attribute on attribute.attrelid = relation.oid
  where namespace.nspname = 'public'
    and relation.relkind in ('r', 'p')
    and not attribute.attisdropped
    and (
      attribute.attname = 'tenant_id'
      or (
        relation.relname = 'tenants'
        and attribute.attname = 'id'
      )
    )
$function$;

create function pg_temp.assert_tenant_isolated(
  table_name text,
  owner_column text default 'tenant_id'
)
returns setof text
language plpgsql
set search_path = pg_catalog, public, extensions
as $function$
declare
  relation_id regclass;
  relation_schema text;
  relation_name text;
  app_can_insert boolean;
  app_can_update boolean;
  app_can_delete boolean;
begin
  relation_id := to_regclass(table_name);
  return next extensions.ok(
    relation_id is not null,
    format('%s is a registered relation', table_name)
  );
  if relation_id is null then
    return;
  end if;

  select namespace.nspname, relation.relname
  into relation_schema, relation_name
  from pg_class as relation
  join pg_namespace as namespace on namespace.oid = relation.relnamespace
  where relation.oid = relation_id;

  return next extensions.ok(
    exists (
      select 1
      from pg_attribute
      where attrelid = relation_id
        and attname = owner_column
        and atttypid = 'uuid'::regtype
        and attnotnull
        and not attisdropped
    ),
    format('%s.%s is a non-null UUID tenant owner', table_name, owner_column)
  );

  return next extensions.ok(
    coalesce(
      (
        select relrowsecurity and relforcerowsecurity
        from pg_class
        where oid = relation_id
      ),
      false
    ),
    format('%s enables and forces RLS', table_name)
  );

  return next extensions.ok(
    has_table_privilege('agents_factory_app', relation_id, 'SELECT'),
    format('%s grants constrained application reads', table_name)
  );

  return next extensions.ok(
    exists (
      select 1
      from pg_policies
      where schemaname = relation_schema
        and tablename = relation_name
        and cmd = 'SELECT'
        and 'agents_factory_app' = any(roles)
        and coalesce(qual, '') like '%' || owner_column || '%'
        and coalesce(qual, '') like '%current_setting%app.tenant_id%'
    ),
    format('%s SELECT policy binds %s to app.tenant_id', table_name, owner_column)
  );

  app_can_insert := has_table_privilege(
    'agents_factory_app', relation_id, 'INSERT'
  );
  return next extensions.ok(
    not app_can_insert
    or exists (
      select 1
      from pg_policies
      where schemaname = relation_schema
        and tablename = relation_name
        and cmd = 'INSERT'
        and 'agents_factory_app' = any(roles)
        and coalesce(with_check, '') like '%' || owner_column || '%'
        and coalesce(with_check, '') like '%current_setting%app.tenant_id%'
    ),
    format('%s INSERT grant has a tenant WITH CHECK policy', table_name)
  );

  app_can_update := has_table_privilege(
    'agents_factory_app', relation_id, 'UPDATE'
  );
  return next extensions.ok(
    not app_can_update
    or exists (
      select 1
      from pg_policies
      where schemaname = relation_schema
        and tablename = relation_name
        and cmd = 'UPDATE'
        and 'agents_factory_app' = any(roles)
        and coalesce(qual, '') like '%' || owner_column || '%'
        and coalesce(qual, '') like '%current_setting%app.tenant_id%'
        and coalesce(with_check, '') like '%' || owner_column || '%'
        and coalesce(with_check, '') like '%current_setting%app.tenant_id%'
    ),
    format('%s UPDATE grant has tenant USING and WITH CHECK policies', table_name)
  );

  app_can_delete := has_table_privilege(
    'agents_factory_app', relation_id, 'DELETE'
  );
  return next extensions.ok(
    not app_can_delete
    or exists (
      select 1
      from pg_policies
      where schemaname = relation_schema
        and tablename = relation_name
        and cmd = 'DELETE'
        and 'agents_factory_app' = any(roles)
        and coalesce(qual, '') like '%' || owner_column || '%'
        and coalesce(qual, '') like '%current_setting%app.tenant_id%'
    ),
    format('%s DELETE grant has a tenant USING policy', table_name)
  );

  return next extensions.ok(
    not exists (
      select 1
      from pg_policies
      where schemaname = relation_schema
        and tablename = relation_name
        and 'agents_factory_app' = any(roles)
        and (
          cmd = 'ALL'
          or lower(coalesce(qual, '')) = 'true'
          or lower(coalesce(with_check, '')) = 'true'
        )
    ),
    format('%s has no unscoped application policy', table_name)
  );
end
$function$;

select assertion
from task5_tenant_isolation_registry as registration
cross join lateral pg_temp.assert_tenant_isolated(
  registration.table_name,
  registration.owner_column
) as result(assertion)
order by registration.table_name, assertion;

create view public.task5_pgtap_tenant_projection
with (security_invoker = true)
as select tenant_id from public.audit_events;

select is(
  (
    select jsonb_agg(
      jsonb_build_array(qualified_name, owner_column)
      order by qualified_name
    )
    from pg_temp.tenant_owned_catalog()
  ),
  (
    select jsonb_agg(
      jsonb_build_array(table_name, owner_column)
      order by table_name
    )
    from task5_tenant_isolation_registry
  ),
  'security_invoker tenant views are excluded from the base-table catalog'
);

create table public.task5_pgtap_unregistered_tenant_data (
  id uuid primary key,
  tenant_id uuid not null
);

select isnt(
  (
    select jsonb_agg(
      jsonb_build_array(qualified_name, owner_column)
      order by qualified_name
    )
    from pg_temp.tenant_owned_catalog()
  ),
  (
    select jsonb_agg(
      jsonb_build_array(table_name, owner_column)
      order by table_name
    )
    from task5_tenant_isolation_registry
  ),
  'an unregistered tenant-owned base table makes catalog completeness fail'
);

drop table public.task5_pgtap_unregistered_tenant_data;
drop view public.task5_pgtap_tenant_projection;

select is(
  (
    select jsonb_agg(
      jsonb_build_array(qualified_name, owner_column)
      order by qualified_name
    )
    from pg_temp.tenant_owned_catalog()
  ),
  (
    select jsonb_agg(
      jsonb_build_array(table_name, owner_column)
      order by table_name
    )
    from task5_tenant_isolation_registry
  ),
  'every public tenant-owned table is registered in the RLS matrix'
);

select ok(
  not exists (
    select 1
    from task5_tenant_isolation_registry
    where table_name = 'public.platform_admins'
  )
  and not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'platform_admins'
      and column_name = 'tenant_id'
  ),
  'platform_admins is global authorization state, not tenant-owned data'
);

select * from finish();
rollback;
