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
  has_table_privilege('agents_factory_app', 'public.tenants', 'SELECT')
    and not has_table_privilege('agents_factory_app', 'public.tenants', 'INSERT')
    and not has_table_privilege('agents_factory_app', 'public.tenants', 'UPDATE'),
  'the app role can read but cannot provision or mutate tenants'
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
    'outbox_jobs_pending_due_idx'
  ]
) as expected(index_name);

select hasnt_index(
  'public',
  expected.index_name,
  format('%s redundant index is absent', expected.index_name)
)
from unnest(
  array[
    'job_attempts_outbox_job_id_idx',
    'dead_letter_jobs_outbox_job_id_idx'
  ]
) as expected(index_name);

select ok(
  exists (
    select 1
    from pg_indexes
    where schemaname = 'public'
      and indexname = 'outbox_jobs_pending_due_idx'
      and indexdef like '%(available_at, created_at, tenant_id, id)%'
      and indexdef like '%WHERE (status = ''pending''::text)%'
  ),
  'pending outbox queue index matches global claim order'
);

create function pg_temp.task3_global_claim_plan()
returns jsonb
language plpgsql
as $function$
declare
  query_plan jsonb;
begin
  execute $explain$
    explain (format json, costs off)
    select id
    from public.outbox_jobs
    where status = 'pending' and available_at <= now()
    order by available_at, created_at, tenant_id, id
    limit 1
    for update skip locked
  $explain$ into query_plan;
  return query_plan;
end
$function$;

set local enable_seqscan = off;
select ok(
  pg_temp.task3_global_claim_plan()::text not like '%"Node Type": "Sort"%',
  'global pending claim plan uses index order without Sort'
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
    (
      select
        tablename::text,
        policyname::text,
        cmd::text,
        array_to_string(roles, ',')
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
      except
      select * from (
        values
          ('audit_events', 'audit_events_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('audit_events', 'audit_events_admin_select', 'SELECT', 'agents_factory_admin'),
          ('audit_events', 'audit_events_app_insert', 'INSERT', 'agents_factory_app'),
          ('audit_events', 'audit_events_app_select', 'SELECT', 'agents_factory_app'),
          ('dead_letter_jobs', 'dead_letter_jobs_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('dead_letter_jobs', 'dead_letter_jobs_admin_select', 'SELECT', 'agents_factory_admin'),
          ('dead_letter_jobs', 'dead_letter_jobs_admin_update', 'UPDATE', 'agents_factory_admin'),
          ('dead_letter_jobs', 'dead_letter_jobs_app_insert', 'INSERT', 'agents_factory_app'),
          ('dead_letter_jobs', 'dead_letter_jobs_app_select', 'SELECT', 'agents_factory_app'),
          ('dead_letter_jobs', 'dead_letter_jobs_app_update', 'UPDATE', 'agents_factory_app'),
          ('job_attempts', 'job_attempts_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('job_attempts', 'job_attempts_admin_select', 'SELECT', 'agents_factory_admin'),
          ('job_attempts', 'job_attempts_admin_update', 'UPDATE', 'agents_factory_admin'),
          ('job_attempts', 'job_attempts_app_insert', 'INSERT', 'agents_factory_app'),
          ('job_attempts', 'job_attempts_app_select', 'SELECT', 'agents_factory_app'),
          ('job_attempts', 'job_attempts_app_update', 'UPDATE', 'agents_factory_app'),
          ('outbox_jobs', 'outbox_jobs_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('outbox_jobs', 'outbox_jobs_admin_select', 'SELECT', 'agents_factory_admin'),
          ('outbox_jobs', 'outbox_jobs_admin_update', 'UPDATE', 'agents_factory_admin'),
          ('outbox_jobs', 'outbox_jobs_app_insert', 'INSERT', 'agents_factory_app'),
          ('outbox_jobs', 'outbox_jobs_app_select', 'SELECT', 'agents_factory_app'),
          ('outbox_jobs', 'outbox_jobs_app_update', 'UPDATE', 'agents_factory_app'),
          ('platform_admins', 'platform_admins_admin_delete', 'DELETE', 'agents_factory_admin'),
          ('platform_admins', 'platform_admins_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('platform_admins', 'platform_admins_admin_select', 'SELECT', 'agents_factory_admin'),
          ('tenants', 'tenants_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('tenants', 'tenants_admin_select', 'SELECT', 'agents_factory_admin'),
          ('tenants', 'tenants_admin_update', 'UPDATE', 'agents_factory_admin'),
          ('tenants', 'tenants_app_select', 'SELECT', 'agents_factory_app')
      ) as expected(tablename, policyname, cmd, roles)
    )
    union all
    (
      select * from (
        values
          ('audit_events', 'audit_events_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('audit_events', 'audit_events_admin_select', 'SELECT', 'agents_factory_admin'),
          ('audit_events', 'audit_events_app_insert', 'INSERT', 'agents_factory_app'),
          ('audit_events', 'audit_events_app_select', 'SELECT', 'agents_factory_app'),
          ('dead_letter_jobs', 'dead_letter_jobs_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('dead_letter_jobs', 'dead_letter_jobs_admin_select', 'SELECT', 'agents_factory_admin'),
          ('dead_letter_jobs', 'dead_letter_jobs_admin_update', 'UPDATE', 'agents_factory_admin'),
          ('dead_letter_jobs', 'dead_letter_jobs_app_insert', 'INSERT', 'agents_factory_app'),
          ('dead_letter_jobs', 'dead_letter_jobs_app_select', 'SELECT', 'agents_factory_app'),
          ('dead_letter_jobs', 'dead_letter_jobs_app_update', 'UPDATE', 'agents_factory_app'),
          ('job_attempts', 'job_attempts_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('job_attempts', 'job_attempts_admin_select', 'SELECT', 'agents_factory_admin'),
          ('job_attempts', 'job_attempts_admin_update', 'UPDATE', 'agents_factory_admin'),
          ('job_attempts', 'job_attempts_app_insert', 'INSERT', 'agents_factory_app'),
          ('job_attempts', 'job_attempts_app_select', 'SELECT', 'agents_factory_app'),
          ('job_attempts', 'job_attempts_app_update', 'UPDATE', 'agents_factory_app'),
          ('outbox_jobs', 'outbox_jobs_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('outbox_jobs', 'outbox_jobs_admin_select', 'SELECT', 'agents_factory_admin'),
          ('outbox_jobs', 'outbox_jobs_admin_update', 'UPDATE', 'agents_factory_admin'),
          ('outbox_jobs', 'outbox_jobs_app_insert', 'INSERT', 'agents_factory_app'),
          ('outbox_jobs', 'outbox_jobs_app_select', 'SELECT', 'agents_factory_app'),
          ('outbox_jobs', 'outbox_jobs_app_update', 'UPDATE', 'agents_factory_app'),
          ('platform_admins', 'platform_admins_admin_delete', 'DELETE', 'agents_factory_admin'),
          ('platform_admins', 'platform_admins_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('platform_admins', 'platform_admins_admin_select', 'SELECT', 'agents_factory_admin'),
          ('tenants', 'tenants_admin_insert', 'INSERT', 'agents_factory_admin'),
          ('tenants', 'tenants_admin_select', 'SELECT', 'agents_factory_admin'),
          ('tenants', 'tenants_admin_update', 'UPDATE', 'agents_factory_admin'),
          ('tenants', 'tenants_app_select', 'SELECT', 'agents_factory_app')
      ) as expected(tablename, policyname, cmd, roles)
      except
      select
        tablename::text,
        policyname::text,
        cmd::text,
        array_to_string(roles, ',')
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
    )
  ),
  'foundation policy name, role, and command inventory is exact'
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

create function public.task3_default_privilege_probe()
returns integer
language sql
as 'select 1';

create function agents_factory_private.task3_default_privilege_probe()
returns integer
language sql
as 'select 1';

select ok(
  not has_function_privilege(
    expected.role_name,
    format('%I.task3_default_privilege_probe()', expected.schema_name),
    'EXECUTE'
  ),
  format(
    '%s cannot execute a new %s function without an explicit grant',
    expected.role_name,
    expected.schema_name
  )
)
from (
  select role_name, schema_name
  from unnest(
    array[
      'anon',
      'authenticated',
      'service_role',
      'agents_factory_app',
      'agents_factory_admin'
    ]
  ) as role_names(role_name)
  cross join unnest(array['public', 'agents_factory_private'])
    as schema_names(schema_name)
) as expected;

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
  values
    (
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f61',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
      null,
      'system',
      'tenant.created',
      'tenant',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f62',
      '{}'::jsonb
    ),
    (
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f71',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f5e',
      null,
      'system',
      'tenant.created',
      'tenant',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f5e',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f72',
      '{}'::jsonb
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
  values
    (
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f63',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
      'same-key',
      'tenant.created',
      '{}'::jsonb,
      'pending',
      now()
    ),
    (
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f65',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f5e',
      'same-key',
      'tenant.created',
      '{}'::jsonb,
      'pending',
      now()
    );

  insert into public.job_attempts (
    id, tenant_id, outbox_job_id, attempt_number, status
  )
  values
    (
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f66',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f63',
      1,
      'started'
    ),
    (
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f67',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f5e',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f65',
      1,
      'started'
    );

  insert into public.dead_letter_jobs (
    id, tenant_id, outbox_job_id, reason_code, status
  )
  values
    (
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f68',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f63',
      'test',
      'open'
    ),
    (
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f69',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f5e',
      '0198f3df-cbb5-7ec9-98f8-4ca608db0f65',
      'test',
      'open'
    );

  set local role agents_factory_app;
  select results_eq(
    format('select count(*)::bigint from public.%I', expected.table_name),
    array[0::bigint],
    format('%s reads fail closed when tenant context is absent', expected.table_name)
  )
  from unnest(
    array['tenants', 'audit_events', 'outbox_jobs', 'job_attempts', 'dead_letter_jobs']
  ) as expected(table_name);

  select set_config('app.tenant_id', '', true);
  select results_eq(
    format('select count(*)::bigint from public.%I', expected.table_name),
    array[0::bigint],
    format('%s reads fail closed when tenant context is empty', expected.table_name)
  )
  from unnest(
    array['tenants', 'audit_events', 'outbox_jobs', 'job_attempts', 'dead_letter_jobs']
  ) as expected(table_name);

  select set_config('app.tenant_id', '0198f3df-cbb5-7ec9-98f8-4ca608db0f99', true);
  select results_eq(
    format('select count(*)::bigint from public.%I', expected.table_name),
    array[0::bigint],
    format('%s reads fail closed for the wrong tenant context', expected.table_name)
  )
  from unnest(
    array['tenants', 'audit_events', 'outbox_jobs', 'job_attempts', 'dead_letter_jobs']
  ) as expected(table_name);

  select set_config('app.tenant_id', 'not-a-uuid', true);
  select throws_ok(
    format('select count(*)::bigint from public.%I', expected.table_name),
    '22P02',
    null,
    format('%s rejects an invalid tenant context', expected.table_name)
  )
  from unnest(
    array['tenants', 'audit_events', 'outbox_jobs', 'job_attempts', 'dead_letter_jobs']
  ) as expected(table_name);

  select set_config('app.tenant_id', '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d', true);
  select results_eq(
    format('select count(*)::bigint from public.%I', expected.table_name),
    array[1::bigint],
    format('%s exposes only the correct tenant row', expected.table_name)
  )
  from unnest(
    array['tenants', 'audit_events', 'outbox_jobs', 'job_attempts', 'dead_letter_jobs']
  ) as expected(table_name);

  select set_config('app.tenant_id', '0198f3df-cbb5-7ec9-98f8-4ca608db0f70', true);
  select throws_ok(
    $$
      insert into public.tenants (id, slug, name, status)
      values (
        '0198f3df-cbb5-7ec9-98f8-4ca608db0f70',
        'matching-context',
        'Matching Context',
        'active'
      )
    $$,
    '42501',
    null,
    'the app role cannot provision a tenant even with matching context'
  );

  select set_config('app.tenant_id', '0198f3df-cbb5-7ec9-98f8-4ca608db0f5d', true);
  select throws_ok(
    $$update public.audit_events set event_type = 'changed'$$,
    '42501',
    null,
    'the app role cannot update audit events'
  );
  select throws_ok(
    $$delete from public.audit_events$$,
    '42501',
    null,
    'the app role cannot delete audit events'
  );
  select throws_ok(
    $$truncate public.audit_events$$,
    '42501',
    null,
    'the app role cannot truncate audit events'
  );

  reset role;
  select throws_ok(
    $$update public.audit_events set event_type = 'changed'$$,
    '55000',
    'audit_events are append-only',
    'the owner cannot update audit events'
  );
  select throws_ok(
    $$delete from public.audit_events$$,
    '55000',
    'audit_events are append-only',
    'the owner cannot delete audit events'
  );
  select throws_ok(
    $$truncate public.audit_events$$,
    '55000',
    'audit_events are append-only',
    'the owner cannot truncate audit events'
  );

  set local role agents_factory_admin;
  select throws_ok(
    $$update public.audit_events set event_type = 'changed'$$,
    '42501',
    null,
    'the admin role cannot update audit events'
  );
  select throws_ok(
    $$delete from public.audit_events$$,
    '42501',
    null,
    'the admin role cannot delete audit events'
  );
  select throws_ok(
    $$truncate public.audit_events$$,
    '42501',
    null,
    'the admin role cannot truncate audit events'
  );
  reset role;

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
  select results_eq(
    $$select count(*)::bigint from public.outbox_jobs where idempotency_key = 'same-key'$$,
    array[2::bigint],
    'the same idempotency key is valid in two tenants'
  );

  set local role agents_factory_admin;
  select results_eq(
    'select count(*)::bigint from public.tenants',
    array[2::bigint],
    'the non-bypass admin role has explicit cross-tenant read access'
  );
\else
  select * from skip(1, 'foundation schema is intentionally absent during RED');
\endif

select * from finish();
rollback;
