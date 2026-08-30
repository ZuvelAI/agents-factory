-- Orders receipt table only; omit unrelated local pg_net extension drift.


  create table "public"."order_operations" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "binding_id" uuid not null,
    "operation" text not null,
    "parameter_digest" text not null,
    "status" text not null,
    "result" jsonb not null default '{}'::jsonb,
    "created_at" timestamp with time zone not null default now(),
    "updated_at" timestamp with time zone not null default now()
      );


alter table "public"."order_operations" enable row level security;
alter table "public"."order_operations" force row level security;

CREATE UNIQUE INDEX order_operations_pkey ON public.order_operations USING btree (id);

CREATE INDEX order_operations_tenant_binding_idx ON public.order_operations USING btree (tenant_id, binding_id, created_at);

alter table "public"."order_operations" add constraint "order_operations_pkey" PRIMARY KEY using index "order_operations_pkey";

alter table "public"."order_operations" add constraint "order_operations_parameter_digest_check" CHECK ((parameter_digest ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."order_operations" validate constraint "order_operations_parameter_digest_check";

alter table "public"."order_operations" add constraint "order_operations_result_check" CHECK ((jsonb_typeof(result) = 'object'::text)) not valid;

alter table "public"."order_operations" validate constraint "order_operations_result_check";

alter table "public"."order_operations" add constraint "order_operations_status_check" CHECK ((status = ANY (ARRAY['CLAIMED'::text, 'SUCCEEDED'::text, 'REJECTED'::text, 'FAILED'::text, 'UNCERTAIN'::text]))) not valid;

alter table "public"."order_operations" validate constraint "order_operations_status_check";

alter table "public"."order_operations" add constraint "order_operations_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT not valid;

alter table "public"."order_operations" validate constraint "order_operations_tenant_id_fkey";

-- Keep privileges explicit independently of deployment default privileges.
revoke all on public.order_operations
from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;

-- No FK to the locked Action row: the claim commits before the provider call.
grant insert on table "public"."order_operations" to "agents_factory_admin";

grant select on table "public"."order_operations" to "agents_factory_admin";

grant update on table "public"."order_operations" to "agents_factory_admin";

grant select on table "public"."order_operations" to "agents_factory_app";


  create policy "order_operations_admin"
  on "public"."order_operations"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "order_operations_read"
  on "public"."order_operations"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));
