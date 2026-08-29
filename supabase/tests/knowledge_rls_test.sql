begin;

create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions, pg_catalog;

select no_plan();

select has_table('public', table_name, format('%s table exists', table_name))
from unnest(
  array[
    'knowledge_sources',
    'knowledge_source_versions',
    'structured_facts',
    'knowledge_documents',
    'knowledge_versions',
    'knowledge_version_members'
  ]
) as expected(table_name);

select ok(
  coalesce(relation.relrowsecurity and relation.relforcerowsecurity, false),
  format('%s enables and forces RLS', expected.table_name)
)
from unnest(
  array[
    'knowledge_sources',
    'knowledge_source_versions',
    'structured_facts',
    'knowledge_documents',
    'knowledge_versions',
    'knowledge_version_members'
  ]
) as expected(table_name)
left join pg_class as relation on relation.relname = expected.table_name
left join pg_namespace as namespace
  on namespace.oid = relation.relnamespace and namespace.nspname = 'public';

select ok(
  has_table_privilege('agents_factory_app', format('public.%I', table_name), 'SELECT')
  and not has_table_privilege(
    'agents_factory_app', format('public.%I', table_name), 'INSERT'
  )
  and not has_table_privilege(
    'agents_factory_app', format('public.%I', table_name), 'UPDATE'
  )
  and not has_table_privilege(
    'agents_factory_app', format('public.%I', table_name), 'DELETE'
  ),
  format('%s is runtime read-only', table_name)
)
from unnest(
  array[
    'knowledge_sources',
    'knowledge_source_versions',
    'structured_facts',
    'knowledge_documents',
    'knowledge_versions',
    'knowledge_version_members'
  ]
) as expected(table_name);

select ok(
  exists (
    select 1
    from pg_trigger
    where tgrelid = format('public.%I', table_name)::regclass
      and not tgisinternal
      and tgname like '%append_only%'
  ),
  format('%s has append-only protection', table_name)
)
from unnest(
  array[
    'knowledge_source_versions',
    'structured_facts',
    'knowledge_documents',
    'knowledge_version_members'
  ]
) as expected(table_name);

select * from finish();
rollback;
