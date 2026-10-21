begin;
create extension if not exists pgtap with schema extensions;
set local search_path=public,extensions,pg_catalog;
select no_plan();
select has_table('public','agent_operation_states','operation state exists');
select ok((select relrowsecurity and relforcerowsecurity from pg_class
  where oid='public.agent_operation_states'::regclass),'RLS is forced');
select ok(not has_table_privilege(role_name,'public.agent_operation_states',privilege_name),
  format('%s cannot %s operation state',role_name,privilege_name))
from unnest(array['anon','authenticated','service_role']) role_name
cross join unnest(array['SELECT','INSERT','UPDATE','DELETE']) privilege_name;
select ok(not has_table_privilege('agents_factory_app','public.agent_operation_states','UPDATE'),
  'runtime cannot change operation state');
select ok(not has_table_privilege('agents_factory_admin','public.agent_operation_states','DELETE'),
  'admin cannot delete operation state');
select ok(has_column_privilege('agents_factory_admin','public.agent_operation_states','enabled','UPDATE'),
  'admin can transition operation state');
select ok(not has_column_privilege('agents_factory_admin','public.agent_operation_states','tenant_id','UPDATE'),
  'admin cannot reassign tenant');
select * from finish();
rollback;
