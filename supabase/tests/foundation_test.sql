begin;

create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions, pg_catalog;

select no_plan();

select has_table('public', table_name, format('%s table exists', table_name))
from unnest(
  array[
    'tenants',
    'platform_admins',
    'audit_events',
    'outbox_jobs',
    'job_attempts',
    'dead_letter_jobs'
  ]
) as expected(table_name);

select ok(
  exists (
    select 1
    from pg_constraint as constraint_definition
    join pg_class as relation on relation.oid = constraint_definition.conrelid
    join pg_namespace as namespace on namespace.oid = relation.relnamespace
    join pg_attribute as attribute
      on attribute.attrelid = relation.oid
      and attribute.attnum = any(constraint_definition.conkey)
    where namespace.nspname = 'public'
      and relation.relname = expected.table_name
      and constraint_definition.contype = 'p'
      and attribute.attname = expected.column_name
      and attribute.atttypid = 'uuid'::regtype
  ),
  format('%s has a UUID primary key', expected.table_name)
)
from (
  values
    ('tenants', 'id'),
    ('platform_admins', 'user_id'),
    ('audit_events', 'id'),
    ('outbox_jobs', 'id'),
    ('job_attempts', 'id'),
    ('dead_letter_jobs', 'id')
) as expected(table_name, column_name);

select ok(
  exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = expected.table_name
      and column_name = expected.column_name
      and data_type = 'uuid'
      and column_default is null
  ),
  format('%s.%s is an externally supplied UUID', expected.table_name, expected.column_name)
)
from (
  values
    ('tenants', 'id'),
    ('platform_admins', 'user_id'),
    ('audit_events', 'id'),
    ('outbox_jobs', 'id'),
    ('job_attempts', 'id'),
    ('dead_letter_jobs', 'id')
) as expected(table_name, column_name);

select ok(
  exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = expected.table_name
      and column_name = expected.column_name
      and data_type = 'timestamp with time zone'
      and is_nullable = 'NO'
  ),
  format('%s.%s is a non-null timestamptz', expected.table_name, expected.column_name)
)
from (
  values
    ('tenants', 'created_at'),
    ('tenants', 'updated_at'),
    ('platform_admins', 'created_at'),
    ('audit_events', 'occurred_at'),
    ('outbox_jobs', 'available_at'),
    ('outbox_jobs', 'created_at'),
    ('outbox_jobs', 'updated_at'),
    ('job_attempts', 'occurred_at'),
    ('dead_letter_jobs', 'created_at')
) as expected(table_name, column_name);

select ok(
  coalesce(
    (
      select rolcanlogin
        and not rolsuper
        and not rolcreatedb
        and not rolcreaterole
        and not rolreplication
        and not rolbypassrls
      from pg_roles
      where rolname = expected.role_name
    ),
    false
  ),
  format('%s is a constrained non-BYPASSRLS login role', expected.role_name)
)
from unnest(array['agents_factory_app', 'agents_factory_admin']) as expected(role_name);

select ok(
  not exists (
    select 1
    from pg_auth_members as membership
    join pg_roles as member_role on member_role.oid = membership.member
    join pg_roles as granted_role on granted_role.oid = membership.roleid
    where member_role.rolname in ('agents_factory_app', 'agents_factory_admin')
      and granted_role.rolname in (
        'postgres',
        'supabase_admin',
        'service_role',
        'supabase_auth_admin',
        'supabase_storage_admin'
      )
  ),
  'runtime roles do not inherit elevated Supabase roles'
);

select ok(
  coalesce(
    (
      select relation.relrowsecurity
      from pg_class as relation
      join pg_namespace as namespace on namespace.oid = relation.relnamespace
      where namespace.nspname = 'public'
        and relation.relname = expected.table_name
    ),
    false
  ),
  format('%s has RLS enabled', expected.table_name)
)
from unnest(
  array[
    'tenants',
    'platform_admins',
    'audit_events',
    'outbox_jobs',
    'job_attempts',
    'dead_letter_jobs'
  ]
) as expected(table_name);

select ok(
  coalesce(
    (
      select relation.relforcerowsecurity
      from pg_class as relation
      join pg_namespace as namespace on namespace.oid = relation.relnamespace
      where namespace.nspname = 'public'
        and relation.relname = expected.table_name
    ),
    false
  ),
  format('%s has RLS forced', expected.table_name)
)
from unnest(
  array['tenants', 'audit_events', 'outbox_jobs', 'job_attempts', 'dead_letter_jobs']
) as expected(table_name);

select ok(
  not exists (
    select 1
    from information_schema.role_table_grants
    where table_schema = 'public'
      and table_name in (
        'tenants',
        'platform_admins',
        'audit_events',
        'outbox_jobs',
        'job_attempts',
        'dead_letter_jobs'
      )
      and grantee in ('PUBLIC', 'anon', 'authenticated', 'service_role')
  ),
  'public Data API roles have no product-table grants'
);

select ok(
  not exists (
    select 1
    from information_schema.role_table_grants
    where table_schema = 'public'
      and table_name = 'audit_events'
      and grantee in ('agents_factory_app', 'agents_factory_admin')
      and privilege_type in ('UPDATE', 'DELETE', 'TRUNCATE')
  ),
  'audit event grants are append-only'
);

select ok(
  exists (
    select 1
    from pg_trigger
    where tgrelid = to_regclass('public.audit_events')
      and tgname = 'audit_events_reject_mutation'
      and tgenabled = 'O'
      and not tgisinternal
  ),
  'audit events have a database append-only guard'
);

select ok(
  exists (
    select 1
    from pg_constraint
    where conrelid = to_regclass('public.outbox_jobs')
      and contype = 'u'
      and pg_get_constraintdef(oid) = 'UNIQUE (tenant_id, idempotency_key)'
  ),
  'outbox idempotency is unique per tenant'
);

select ok(
  exists (
    select 1
    from pg_constraint
    where conrelid = to_regclass(format('public.%I', expected.table_name))
      and contype = 'f'
      and pg_get_constraintdef(oid) like
        'FOREIGN KEY (tenant_id, outbox_job_id) REFERENCES outbox_jobs(tenant_id, id)%'
  ),
  format('%s retains a tenant-consistent outbox foreign key', expected.table_name)
)
from unnest(array['job_attempts', 'dead_letter_jobs']) as expected(table_name);

select ok(
  to_regclass(format('public.%I', expected.index_name)) is not null,
  format('%s index exists', expected.index_name)
)
from unnest(
  array[
    'audit_events_tenant_id_idx',
    'job_attempts_outbox_job_id_idx',
    'dead_letter_jobs_outbox_job_id_idx',
    'outbox_jobs_pending_due_idx'
  ]
) as expected(index_name);

select ok(
  exists (
    select 1
    from pg_indexes
    where schemaname = 'public'
      and indexname = 'outbox_jobs_pending_due_idx'
      and indexdef like '%(tenant_id, available_at, created_at)%'
      and indexdef like '%WHERE (status = ''pending''::text)%'
  ),
  'pending outbox queue has a tenant/status/due-time partial index'
);

select ok(
  not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename in (
        'tenants',
        'platform_admins',
        'audit_events',
        'outbox_jobs',
        'job_attempts',
        'dead_letter_jobs'
      )
      and cmd = 'ALL'
  ),
  'foundation RLS uses explicit command policies'
);

select ok(
  not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename in (
        'tenants',
        'platform_admins',
        'audit_events',
        'outbox_jobs',
        'job_attempts',
        'dead_letter_jobs'
      )
      and (
        coalesce(qual, '') ilike '%user_metadata%'
        or coalesce(with_check, '') ilike '%user_metadata%'
      )
  ),
  'foundation policies never authorize from user_metadata'
);

select ok(
  not exists (
    select 1
    from pg_proc as procedure
    join pg_namespace as namespace on namespace.oid = procedure.pronamespace
    where namespace.nspname in ('public', 'agents_factory_private')
      and procedure.prosecdef
  ),
  'foundation defines no SECURITY DEFINER functions'
);

select (
  to_regclass('public.tenants') is not null
  and to_regclass('public.platform_admins') is not null
  and to_regclass('public.audit_events') is not null
  and to_regclass('public.outbox_jobs') is not null
  and to_regclass('public.job_attempts') is not null
  and to_regclass('public.dead_letter_jobs') is not null
  and exists (select 1 from pg_roles where rolname = 'agents_factory_app')
  and exists (select 1 from pg_roles where rolname = 'agents_factory_admin')
) as foundation_ready \gset

\if :foundation_ready
  grant agents_factory_app, agents_factory_admin to current_user
  with inherit false, set true;
  grant usage on schema extensions to agents_factory_app, agents_factory_admin;

  insert into public.tenants (id, slug, name, status)
  values
    ('0198f3df-cbb5-7ec9-98f8-4ca608db0f5d', 'tenant-a', 'Tenant A', 'active'),
    ('0198f3df-cbb5-7ec9-98f8-4ca608db0f5e', 'tenant-b', 'Tenant B', 'active');

  set local role agents_factory_app;

  select results_eq(
    'select count(*)::bigint from public.tenants',
    array[0::bigint],
    'tenant reads fail closed when app.tenant_id is absent'
  );

  select set_config('app.tenant_id', '', true);
  select results_eq(
    'select count(*)::bigint from public.tenants',
    array[0::bigint],
    'tenant reads fail closed when app.tenant_id is empty'
  );

  select set_config(
    'app.tenant_id',
    '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
    true
  );
  select results_eq(
    'select id from public.tenants order by id',
    array['0198f3df-cbb5-7ec9-98f8-4ca608db0f5d'::uuid],
    'the app role sees only its transaction-local tenant'
  );
  select throws_ok(
    $$
      insert into public.tenants (id, slug, name, status)
      values (
        '0198f3df-cbb5-7ec9-98f8-4ca608db0f60',
        'wrong-tenant',
        'Wrong Tenant',
        'active'
      )
    $$,
    '42501',
    null,
    'the app role cannot insert outside its tenant context'
  );

  reset role;
  insert into public.audit_events (
    id,
    tenant_id,
    actor_id,
    actor_type,
    event_type,
    entity_type,
    entity_id,
    correlation_id,
    payload
  )
  values (
    '0198f3df-cbb5-7ec9-98f8-4ca608db0f61',
    '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
    null,
    'system',
    'tenant.created',
    'tenant',
    '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
    '0198f3df-cbb5-7ec9-98f8-4ca608db0f62',
    '{}'::jsonb
  );

  set local role agents_factory_app;
  select set_config(
    'app.tenant_id',
    '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
    true
  );
  reset role;
  select throws_ok(
    $$update public.audit_events set event_type = 'changed'$$,
    '55000',
    'audit_events are append-only',
    'audit events cannot be updated'
  );
  select throws_ok(
    $$delete from public.audit_events$$,
    '55000',
    'audit_events are append-only',
    'audit events cannot be deleted'
  );

  insert into public.outbox_jobs (
    id,
    tenant_id,
    idempotency_key,
    topic,
    payload,
    status,
    available_at
  )
  values (
    '0198f3df-cbb5-7ec9-98f8-4ca608db0f63',
    '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
    'same-key',
    'tenant.created',
    '{}'::jsonb,
    'pending',
    now()
  );
  select throws_ok(
    $$
      insert into public.outbox_jobs (
        id,
        tenant_id,
        idempotency_key,
        topic,
        payload,
        status,
        available_at
      )
      values (
        '0198f3df-cbb5-7ec9-98f8-4ca608db0f64',
        '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
        'same-key',
        'tenant.created',
        '{}'::jsonb,
        'pending',
        now()
      )
    $$,
    '23505',
    null,
    'an idempotency key cannot repeat within a tenant'
  );
  select lives_ok(
    $$
      insert into public.outbox_jobs (
        id,
        tenant_id,
        idempotency_key,
        topic,
        payload,
        status,
        available_at
      )
      values (
        '0198f3df-cbb5-7ec9-98f8-4ca608db0f65',
        '0198f3df-cbb5-7ec9-98f8-4ca608db0f5e',
        'same-key',
        'tenant.created',
        '{}'::jsonb,
        'pending',
        now()
      )
    $$,
    'the same idempotency key is valid in another tenant'
  );

  set local role agents_factory_admin;
  select results_eq(
    'select count(*)::bigint from public.tenants',
    array[2::bigint],
    'the non-bypass admin role has explicit cross-tenant read access'
  );
\else
  select * from skip(10, 'foundation schema is intentionally absent during RED');
\endif

select * from finish();
rollback;
