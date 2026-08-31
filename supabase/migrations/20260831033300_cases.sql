-- Task 30 only: omit unrelated local pg_net extension drift.
-- Receipts commit independently of the outer Action; action/approval references
-- are logical audit links, not foreign keys to its potentially locked row.


  create table "public"."case_delivery_operations" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "effect_key" text not null,
    "parameter_digest" text not null,
    "operation" text not null,
    "status" text not null,
    "result" jsonb not null default '{}'::jsonb,
    "created_at" timestamp with time zone not null default now(),
    "updated_at" timestamp with time zone not null default now()
      );


alter table "public"."case_delivery_operations" enable row level security;
alter table "public"."case_delivery_operations" force row level security;


  create table "public"."case_events" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "case_id" uuid not null,
    "revision" integer not null,
    "event_type" text not null,
    "actor_id" uuid not null,
    "actor_type" text not null,
    "correlation_id" uuid not null,
    "reason" text not null,
    "from_status" text,
    "to_status" text not null,
    "action_reference" uuid,
    "approval_reference" text,
    "evidence_ids" jsonb not null default '[]'::jsonb,
    "created_at" timestamp with time zone not null default now()
      );


alter table "public"."case_events" enable row level security;
alter table "public"."case_events" force row level security;


  create table "public"."case_operations" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "customer_ref" text not null,
    "case_id" uuid not null,
    "parameter_digest" text not null,
    "receipt" jsonb not null,
    "created_at" timestamp with time zone not null default now()
      );


alter table "public"."case_operations" enable row level security;
alter table "public"."case_operations" force row level security;


  create table "public"."cases" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "customer_ref" text not null,
    "capability" text not null,
    "issue_type" text not null,
    "binding_id" uuid not null,
    "resource_id" text not null,
    "deduplication_key" text not null,
    "content_digest" text not null,
    "intake" jsonb not null,
    "revision" integer not null,
    "status" text not null,
    "priority" text not null,
    "policy" jsonb not null,
    "target_status" text not null default 'ON_TRACK'::text,
    "approaching_at" timestamp with time zone not null,
    "target_at" timestamp with time zone not null,
    "resolved_at" timestamp with time zone,
    "close_at" timestamp with time zone,
    "customer_result" text,
    "result_recorded_by" uuid,
    "created_at" timestamp with time zone not null,
    "updated_at" timestamp with time zone not null
      );


alter table "public"."cases" enable row level security;
alter table "public"."cases" force row level security;

CREATE UNIQUE INDEX case_delivery_operations_pkey ON public.case_delivery_operations USING btree (id);

CREATE UNIQUE INDEX case_delivery_operations_tenant_id_effect_key_key ON public.case_delivery_operations USING btree (tenant_id, effect_key);

CREATE INDEX case_events_history_idx ON public.case_events USING btree (tenant_id, case_id, created_at, id);

CREATE UNIQUE INDEX case_events_pkey ON public.case_events USING btree (id);

CREATE INDEX case_operations_case_idx ON public.case_operations USING btree (tenant_id, case_id);

CREATE UNIQUE INDEX case_operations_pkey ON public.case_operations USING btree (tenant_id, id);

CREATE INDEX cases_close_idx ON public.cases USING btree (tenant_id, close_at) WHERE (status = 'RESOLVED'::text);

CREATE INDEX cases_customer_idx ON public.cases USING btree (tenant_id, customer_ref, created_at);

CREATE UNIQUE INDEX cases_equivalent_active_idx ON public.cases USING btree (tenant_id, customer_ref, deduplication_key) WHERE (status <> ALL (ARRAY['CLOSED'::text, 'REJECTED'::text, 'CANCELLED'::text, 'EXPIRED'::text, 'DUPLICATE'::text]));

CREATE UNIQUE INDEX cases_pkey ON public.cases USING btree (id);

CREATE INDEX cases_target_idx ON public.cases USING btree (tenant_id, target_at) WHERE (status <> ALL (ARRAY['RESOLVED'::text, 'CLOSED'::text, 'REJECTED'::text, 'CANCELLED'::text, 'EXPIRED'::text, 'DUPLICATE'::text]));

CREATE UNIQUE INDEX cases_tenant_id_id_key ON public.cases USING btree (tenant_id, id);

alter table "public"."case_delivery_operations" add constraint "case_delivery_operations_pkey" PRIMARY KEY using index "case_delivery_operations_pkey";

alter table "public"."case_events" add constraint "case_events_pkey" PRIMARY KEY using index "case_events_pkey";

alter table "public"."case_operations" add constraint "case_operations_pkey" PRIMARY KEY using index "case_operations_pkey";

alter table "public"."cases" add constraint "cases_pkey" PRIMARY KEY using index "cases_pkey";

alter table "public"."case_delivery_operations" add constraint "case_delivery_operations_effect_key_check" CHECK (((length(effect_key) >= 1) AND (length(effect_key) <= 1500))) not valid;

alter table "public"."case_delivery_operations" validate constraint "case_delivery_operations_effect_key_check";

alter table "public"."case_delivery_operations" add constraint "case_delivery_operations_parameter_digest_check" CHECK ((parameter_digest ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."case_delivery_operations" validate constraint "case_delivery_operations_parameter_digest_check";

alter table "public"."case_delivery_operations" add constraint "case_delivery_operations_result_check" CHECK ((jsonb_typeof(result) = 'object'::text)) not valid;

alter table "public"."case_delivery_operations" validate constraint "case_delivery_operations_result_check";

alter table "public"."case_delivery_operations" add constraint "case_delivery_operations_status_check" CHECK ((status = ANY (ARRAY['CLAIMED'::text, 'SUCCEEDED'::text, 'REJECTED'::text, 'FAILED'::text, 'UNCERTAIN'::text]))) not valid;

alter table "public"."case_delivery_operations" validate constraint "case_delivery_operations_status_check";

alter table "public"."case_delivery_operations" add constraint "case_delivery_operations_tenant_id_effect_key_key" UNIQUE using index "case_delivery_operations_tenant_id_effect_key_key";

alter table "public"."case_delivery_operations" add constraint "case_delivery_operations_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT not valid;

alter table "public"."case_delivery_operations" validate constraint "case_delivery_operations_tenant_id_fkey";

alter table "public"."case_events" add constraint "case_events_actor_type_check" CHECK ((actor_type = ANY (ARRAY['system'::text, 'platform_admin'::text]))) not valid;

alter table "public"."case_events" validate constraint "case_events_actor_type_check";

alter table "public"."case_events" add constraint "case_events_evidence_ids_check" CHECK ((jsonb_typeof(evidence_ids) = 'array'::text)) not valid;

alter table "public"."case_events" validate constraint "case_events_evidence_ids_check";

alter table "public"."case_events" add constraint "case_events_reason_check" CHECK ((length(btrim(reason)) > 0)) not valid;

alter table "public"."case_events" validate constraint "case_events_reason_check";

alter table "public"."case_events" add constraint "case_events_revision_check" CHECK ((revision > 0)) not valid;

alter table "public"."case_events" validate constraint "case_events_revision_check";

alter table "public"."case_events" add constraint "case_events_tenant_id_case_id_fkey" FOREIGN KEY (tenant_id, case_id) REFERENCES public.cases(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."case_events" validate constraint "case_events_tenant_id_case_id_fkey";

alter table "public"."case_operations" add constraint "case_operations_parameter_digest_check" CHECK ((parameter_digest ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."case_operations" validate constraint "case_operations_parameter_digest_check";

alter table "public"."case_operations" add constraint "case_operations_receipt_check" CHECK ((jsonb_typeof(receipt) = 'object'::text)) not valid;

alter table "public"."case_operations" validate constraint "case_operations_receipt_check";

alter table "public"."case_operations" add constraint "case_operations_tenant_id_case_id_fkey" FOREIGN KEY (tenant_id, case_id) REFERENCES public.cases(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."case_operations" validate constraint "case_operations_tenant_id_case_id_fkey";

alter table "public"."cases" add constraint "cases_capability_check" CHECK ((capability = ANY (ARRAY['orders'::text, 'returns_claims'::text]))) not valid;

alter table "public"."cases" validate constraint "cases_capability_check";

alter table "public"."cases" add constraint "cases_check" CHECK ((target_at > approaching_at)) not valid;

alter table "public"."cases" validate constraint "cases_check";

alter table "public"."cases" add constraint "cases_check1" CHECK (((customer_result IS NULL) OR (result_recorded_by IS NOT NULL))) not valid;

alter table "public"."cases" validate constraint "cases_check1";

alter table "public"."cases" add constraint "cases_check2" CHECK (((status <> 'RESOLVED'::text) OR ((resolved_at IS NOT NULL) AND (close_at IS NOT NULL)))) not valid;

alter table "public"."cases" validate constraint "cases_check2";

alter table "public"."cases" add constraint "cases_content_digest_check" CHECK ((content_digest ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."cases" validate constraint "cases_content_digest_check";

alter table "public"."cases" add constraint "cases_customer_ref_check" CHECK (((length(customer_ref) >= 1) AND (length(customer_ref) <= 300))) not valid;

alter table "public"."cases" validate constraint "cases_customer_ref_check";

alter table "public"."cases" add constraint "cases_deduplication_key_check" CHECK ((deduplication_key ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."cases" validate constraint "cases_deduplication_key_check";

alter table "public"."cases" add constraint "cases_intake_check" CHECK ((jsonb_typeof(intake) = 'object'::text)) not valid;

alter table "public"."cases" validate constraint "cases_intake_check";

alter table "public"."cases" add constraint "cases_policy_check" CHECK ((jsonb_typeof(policy) = 'object'::text)) not valid;

alter table "public"."cases" validate constraint "cases_policy_check";

alter table "public"."cases" add constraint "cases_priority_check" CHECK ((priority = ANY (ARRAY['LOW'::text, 'NORMAL'::text, 'HIGH'::text, 'CRITICAL'::text]))) not valid;

alter table "public"."cases" validate constraint "cases_priority_check";

alter table "public"."cases" add constraint "cases_revision_check" CHECK ((revision > 0)) not valid;

alter table "public"."cases" validate constraint "cases_revision_check";

alter table "public"."cases" add constraint "cases_status_check" CHECK ((status = ANY (ARRAY['OPEN'::text, 'AWAITING_INFORMATION'::text, 'READY_FOR_REVIEW'::text, 'PENDING_APPROVAL'::text, 'IN_PROGRESS'::text, 'RESOLVED'::text, 'CLOSED'::text, 'REOPENED'::text, 'REJECTED'::text, 'CANCELLED'::text, 'EXPIRED'::text, 'DUPLICATE'::text]))) not valid;

alter table "public"."cases" validate constraint "cases_status_check";

alter table "public"."cases" add constraint "cases_target_status_check" CHECK ((target_status = ANY (ARRAY['ON_TRACK'::text, 'APPROACHING_TARGET'::text, 'OVERDUE'::text]))) not valid;

alter table "public"."cases" validate constraint "cases_target_status_check";

alter table "public"."cases" add constraint "cases_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT not valid;

alter table "public"."cases" validate constraint "cases_tenant_id_fkey";

alter table "public"."cases" add constraint "cases_tenant_id_id_key" UNIQUE using index "cases_tenant_id_id_key";

-- Preserve least privilege regardless of deployment default privileges.
revoke all on public.cases, public.case_events, public.case_operations,
  public.case_delivery_operations
from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;

grant insert on table "public"."case_delivery_operations" to "agents_factory_admin";

grant select on table "public"."case_delivery_operations" to "agents_factory_admin";

grant update on table "public"."case_delivery_operations" to "agents_factory_admin";

grant select on table "public"."case_delivery_operations" to "agents_factory_app";

grant insert on table "public"."case_events" to "agents_factory_admin";

grant select on table "public"."case_events" to "agents_factory_admin";

grant select on table "public"."case_events" to "agents_factory_app";

grant insert on table "public"."case_operations" to "agents_factory_admin";

grant select on table "public"."case_operations" to "agents_factory_admin";

grant select on table "public"."case_operations" to "agents_factory_app";

grant insert on table "public"."cases" to "agents_factory_admin";

grant select on table "public"."cases" to "agents_factory_admin";

grant update on table "public"."cases" to "agents_factory_admin";

grant select on table "public"."cases" to "agents_factory_app";


  create policy "case_delivery_operations_admin"
  on "public"."case_delivery_operations"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "case_delivery_operations_read"
  on "public"."case_delivery_operations"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "case_events_admin"
  on "public"."case_events"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "case_events_read"
  on "public"."case_events"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "case_operations_admin"
  on "public"."case_operations"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "case_operations_read"
  on "public"."case_operations"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "cases_admin"
  on "public"."cases"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "cases_read"
  on "public"."cases"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));


CREATE TRIGGER case_events_append_only BEFORE DELETE OR UPDATE OR TRUNCATE ON public.case_events FOR EACH STATEMENT EXECUTE FUNCTION agents_factory_private.reject_agent_spec_deployment_mutation();

CREATE TRIGGER case_operations_append_only BEFORE DELETE OR UPDATE OR TRUNCATE ON public.case_operations FOR EACH STATEMENT EXECUTE FUNCTION agents_factory_private.reject_agent_spec_deployment_mutation();
