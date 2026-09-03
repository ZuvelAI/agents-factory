-- Task 24 only. Omit unrelated pg_net drift from the local schema diff.


  create table "public"."appointment_configurations" (
    "id" uuid not null default gen_random_uuid(),
    "tenant_id" uuid not null,
    "connection_id" uuid not null,
    "configuration" jsonb not null,
    "updated_at" timestamp with time zone not null default now()
      );


alter table "public"."appointment_configurations" enable row level security;
alter table "public"."appointment_configurations" force row level security;


  create table "public"."appointment_operations" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "operation" text not null,
    "parameter_digest" text not null,
    "status" text not null,
    "result" jsonb not null default '{}'::jsonb,
    "created_at" timestamp with time zone not null default now(),
    "updated_at" timestamp with time zone not null default now()
      );


alter table "public"."appointment_operations" enable row level security;
alter table "public"."appointment_operations" force row level security;


  create table "public"."appointments" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "customer_ref" text not null,
    "conversation_id" uuid not null,
    "service_id" text not null,
    "professional_id" text not null,
    "location_id" text not null,
    "start_at" timestamp with time zone not null,
    "end_at" timestamp with time zone not null,
    "busy_start" timestamp with time zone not null,
    "busy_end" timestamp with time zone not null,
    "external_event_id" text not null,
    "etag" text not null,
    "status" text not null,
    "revision" integer not null,
    "last_action_id" uuid not null
      );


alter table "public"."appointments" enable row level security;
alter table "public"."appointments" force row level security;

CREATE INDEX appointment_configurations_connection_idx ON public.appointment_configurations USING btree (tenant_id, connection_id);

CREATE UNIQUE INDEX appointment_configurations_pkey ON public.appointment_configurations USING btree (id);

CREATE UNIQUE INDEX appointment_configurations_tenant_id_key ON public.appointment_configurations USING btree (tenant_id);

CREATE UNIQUE INDEX appointment_operations_pkey ON public.appointment_operations USING btree (id);

CREATE INDEX appointment_operations_tenant_idx ON public.appointment_operations USING btree (tenant_id, created_at);

CREATE INDEX appointments_conversation_idx ON public.appointments USING btree (tenant_id, conversation_id);

CREATE INDEX appointments_customer_idx ON public.appointments USING btree (tenant_id, customer_ref, start_at);

CREATE INDEX appointments_occupancy_idx ON public.appointments USING btree (tenant_id, busy_start, busy_end);

CREATE UNIQUE INDEX appointments_pkey ON public.appointments USING btree (id);

CREATE UNIQUE INDEX appointments_tenant_id_external_event_id_key ON public.appointments USING btree (tenant_id, external_event_id);

CREATE UNIQUE INDEX appointments_tenant_id_id_key ON public.appointments USING btree (tenant_id, id);

alter table "public"."appointment_configurations" add constraint "appointment_configurations_pkey" PRIMARY KEY using index "appointment_configurations_pkey";

alter table "public"."appointment_operations" add constraint "appointment_operations_pkey" PRIMARY KEY using index "appointment_operations_pkey";

alter table "public"."appointments" add constraint "appointments_pkey" PRIMARY KEY using index "appointments_pkey";

alter table "public"."appointment_configurations" add constraint "appointment_configurations_configuration_check" CHECK ((jsonb_typeof(configuration) = 'object'::text)) not valid;

alter table "public"."appointment_configurations" validate constraint "appointment_configurations_configuration_check";

alter table "public"."appointment_configurations" add constraint "appointment_configurations_tenant_id_connection_id_fkey" FOREIGN KEY (tenant_id, connection_id) REFERENCES public.integration_connections(tenant_id, id) not valid;

alter table "public"."appointment_configurations" validate constraint "appointment_configurations_tenant_id_connection_id_fkey";

alter table "public"."appointment_configurations" add constraint "appointment_configurations_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT not valid;

alter table "public"."appointment_configurations" validate constraint "appointment_configurations_tenant_id_fkey";

alter table "public"."appointment_configurations" add constraint "appointment_configurations_tenant_id_key" UNIQUE using index "appointment_configurations_tenant_id_key";

alter table "public"."appointment_operations" add constraint "appointment_operations_parameter_digest_check" CHECK ((parameter_digest ~ '^[0-9a-f]{64}$'::text)) not valid;

alter table "public"."appointment_operations" validate constraint "appointment_operations_parameter_digest_check";

alter table "public"."appointment_operations" add constraint "appointment_operations_result_check" CHECK ((jsonb_typeof(result) = 'object'::text)) not valid;

alter table "public"."appointment_operations" validate constraint "appointment_operations_result_check";

alter table "public"."appointment_operations" add constraint "appointment_operations_status_check" CHECK ((status = ANY (ARRAY['CLAIMED'::text, 'SUCCEEDED'::text, 'FAILED'::text, 'REJECTED'::text, 'UNCERTAIN'::text]))) not valid;

alter table "public"."appointment_operations" validate constraint "appointment_operations_status_check";

alter table "public"."appointment_operations" add constraint "appointment_operations_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.appointment_configurations(tenant_id) not valid;

alter table "public"."appointment_operations" validate constraint "appointment_operations_tenant_id_fkey";

alter table "public"."appointments" add constraint "appointments_check" CHECK (((busy_start <= start_at) AND (start_at < end_at) AND (end_at <= busy_end))) not valid;

alter table "public"."appointments" validate constraint "appointments_check";

alter table "public"."appointments" add constraint "appointments_revision_check" CHECK ((revision > 0)) not valid;

alter table "public"."appointments" validate constraint "appointments_revision_check";

alter table "public"."appointments" add constraint "appointments_status_check" CHECK ((status = ANY (ARRAY['BOOKED'::text, 'CANCELLATION_REQUESTED'::text]))) not valid;

alter table "public"."appointments" validate constraint "appointments_status_check";

alter table "public"."appointments" add constraint "appointments_tenant_id_conversation_id_fkey" FOREIGN KEY (tenant_id, conversation_id) REFERENCES public.conversations(tenant_id, id) not valid;

alter table "public"."appointments" validate constraint "appointments_tenant_id_conversation_id_fkey";

alter table "public"."appointments" add constraint "appointments_tenant_id_external_event_id_key" UNIQUE using index "appointments_tenant_id_external_event_id_key";

alter table "public"."appointments" add constraint "appointments_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.appointment_configurations(tenant_id) not valid;

alter table "public"."appointments" validate constraint "appointments_tenant_id_fkey";

alter table "public"."appointments" add constraint "appointments_tenant_id_id_key" UNIQUE using index "appointments_tenant_id_id_key";

-- Keep privileges explicit even when deployment defaults differ from local.
revoke all on public.appointment_configurations, public.appointment_operations,
  public.appointments
from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;

-- Operation receipts deliberately do not reference actions: the ActionService
-- transaction locks that row while this durable attempt must commit separately.
grant insert on table "public"."appointment_configurations" to "agents_factory_admin";

grant select on table "public"."appointment_configurations" to "agents_factory_admin";

grant update on table "public"."appointment_configurations" to "agents_factory_admin";

grant select on table "public"."appointment_configurations" to "agents_factory_app";

grant insert on table "public"."appointment_operations" to "agents_factory_admin";

grant select on table "public"."appointment_operations" to "agents_factory_admin";

grant update on table "public"."appointment_operations" to "agents_factory_admin";

grant select on table "public"."appointment_operations" to "agents_factory_app";

grant insert on table "public"."appointments" to "agents_factory_admin";

grant select on table "public"."appointments" to "agents_factory_admin";

grant update on table "public"."appointments" to "agents_factory_admin";

grant select on table "public"."appointments" to "agents_factory_app";


  create policy "appointment_configurations_admin"
  on "public"."appointment_configurations"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "appointment_configurations_read"
  on "public"."appointment_configurations"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "appointment_operations_admin"
  on "public"."appointment_operations"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "appointment_operations_read"
  on "public"."appointment_operations"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "appointments_admin"
  on "public"."appointments"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "appointments_read"
  on "public"."appointments"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));
