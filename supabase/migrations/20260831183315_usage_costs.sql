
  create table "public"."usage_configurations" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "configuration" jsonb not null,
    "revision" integer not null
      );


alter table "public"."usage_configurations" enable row level security;


  create table "public"."usage_records" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "source_key" text not null,
    "payload_digest" text not null,
    "occurred_at" timestamp with time zone not null,
    "recorded_at" timestamp with time zone not null default now(),
    "kind" text not null,
    "provider" text not null,
    "product" text not null,
    "model" text,
    "run_id" uuid,
    "conversation_id" uuid,
    "action_id" uuid,
    "case_id" uuid,
    "currency" text not null,
    "cost_amount" numeric(30,12),
    "event" jsonb not null,
    "quote" jsonb not null,
    "price_snapshot" jsonb,
    "configuration_revision" integer not null
      );


alter table "public"."usage_records" enable row level security;

-- Explicit security boundaries omitted by the schema diff.
alter table public.usage_configurations force row level security;
alter table public.usage_records force row level security;
revoke all on public.usage_configurations,public.usage_records
from public,anon,authenticated,service_role,agents_factory_app,agents_factory_admin;

CREATE UNIQUE INDEX usage_configurations_pkey ON public.usage_configurations USING btree (id);

CREATE UNIQUE INDEX usage_configurations_tenant_id_id_key ON public.usage_configurations USING btree (tenant_id, id);

CREATE UNIQUE INDEX usage_configurations_tenant_id_key ON public.usage_configurations USING btree (tenant_id);

CREATE INDEX usage_records_action_time ON public.usage_records USING btree (tenant_id, action_id, occurred_at) WHERE (action_id IS NOT NULL);

CREATE INDEX usage_records_case_time ON public.usage_records USING btree (tenant_id, case_id, occurred_at) WHERE (case_id IS NOT NULL);

CREATE INDEX usage_records_conversation_time ON public.usage_records USING btree (tenant_id, conversation_id, occurred_at) WHERE (conversation_id IS NOT NULL);

CREATE UNIQUE INDEX usage_records_pkey ON public.usage_records USING btree (id);

CREATE UNIQUE INDEX usage_records_tenant_id_id_key ON public.usage_records USING btree (tenant_id, id);

CREATE UNIQUE INDEX usage_records_tenant_id_source_key_key ON public.usage_records USING btree (tenant_id, source_key);

CREATE INDEX usage_records_tenant_time ON public.usage_records USING btree (tenant_id, occurred_at);

alter table "public"."usage_configurations" add constraint "usage_configurations_pkey" PRIMARY KEY using index "usage_configurations_pkey";

alter table "public"."usage_records" add constraint "usage_records_pkey" PRIMARY KEY using index "usage_records_pkey";

alter table "public"."usage_configurations" add constraint "usage_configurations_configuration_check" CHECK ((jsonb_typeof(configuration) = 'object'::text)) not valid;

alter table "public"."usage_configurations" validate constraint "usage_configurations_configuration_check";

alter table "public"."usage_configurations" add constraint "usage_configurations_revision_check" CHECK ((revision > 0)) not valid;

alter table "public"."usage_configurations" validate constraint "usage_configurations_revision_check";

alter table "public"."usage_configurations" add constraint "usage_configurations_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) not valid;

alter table "public"."usage_configurations" validate constraint "usage_configurations_tenant_id_fkey";

alter table "public"."usage_configurations" add constraint "usage_configurations_tenant_id_id_key" UNIQUE using index "usage_configurations_tenant_id_id_key";

alter table "public"."usage_configurations" add constraint "usage_configurations_tenant_id_key" UNIQUE using index "usage_configurations_tenant_id_key";

alter table "public"."usage_records" add constraint "usage_records_configuration_revision_check" CHECK ((configuration_revision >= 0)) not valid;

alter table "public"."usage_records" validate constraint "usage_records_configuration_revision_check";

alter table "public"."usage_records" add constraint "usage_records_cost_amount_check" CHECK ((cost_amount >= (0)::numeric)) not valid;

alter table "public"."usage_records" validate constraint "usage_records_cost_amount_check";

alter table "public"."usage_records" add constraint "usage_records_currency_check" CHECK ((currency ~ '^[A-Z]{3}$'::text)) not valid;

alter table "public"."usage_records" validate constraint "usage_records_currency_check";

alter table "public"."usage_records" add constraint "usage_records_event_check" CHECK ((jsonb_typeof(event) = 'object'::text)) not valid;

alter table "public"."usage_records" validate constraint "usage_records_event_check";

alter table "public"."usage_records" add constraint "usage_records_kind_check" CHECK ((kind = ANY (ARRAY['llm'::text, 'whatsapp'::text, 'tool'::text, 'storage'::text, 'infrastructure'::text]))) not valid;

alter table "public"."usage_records" validate constraint "usage_records_kind_check";

alter table "public"."usage_records" add constraint "usage_records_payload_digest_check" CHECK ((payload_digest ~ '^[0-9a-f]{64}$'::text)) not valid;

alter table "public"."usage_records" validate constraint "usage_records_payload_digest_check";

alter table "public"."usage_records" add constraint "usage_records_price_snapshot_check" CHECK ((jsonb_typeof(price_snapshot) = 'object'::text)) not valid;

alter table "public"."usage_records" validate constraint "usage_records_price_snapshot_check";

alter table "public"."usage_records" add constraint "usage_records_quote_check" CHECK ((jsonb_typeof(quote) = 'object'::text)) not valid;

alter table "public"."usage_records" validate constraint "usage_records_quote_check";

alter table "public"."usage_records" add constraint "usage_records_source_key_check" CHECK (((length(source_key) >= 1) AND (length(source_key) <= 180))) not valid;

alter table "public"."usage_records" validate constraint "usage_records_source_key_check";

alter table "public"."usage_records" add constraint "usage_records_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) not valid;

alter table "public"."usage_records" validate constraint "usage_records_tenant_id_fkey";

alter table "public"."usage_records" add constraint "usage_records_tenant_id_id_key" UNIQUE using index "usage_records_tenant_id_id_key";

alter table "public"."usage_records" add constraint "usage_records_tenant_id_source_key_key" UNIQUE using index "usage_records_tenant_id_source_key_key";

grant insert on table "public"."usage_configurations" to "agents_factory_admin";

grant select on table "public"."usage_configurations" to "agents_factory_admin";

grant update on table "public"."usage_configurations" to "agents_factory_admin";

grant select on table "public"."usage_configurations" to "agents_factory_app";

grant insert on table "public"."usage_records" to "agents_factory_admin";

grant select on table "public"."usage_records" to "agents_factory_admin";

grant insert on table "public"."usage_records" to "agents_factory_app";

grant select on table "public"."usage_records" to "agents_factory_app";


  create policy "usage_configurations_admin"
  on "public"."usage_configurations"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "usage_configurations_read"
  on "public"."usage_configurations"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "usage_records_insert"
  on "public"."usage_records"
  as permissive
  for insert
  to agents_factory_app, agents_factory_admin
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "usage_records_read"
  on "public"."usage_records"
  as permissive
  for select
  to agents_factory_app, agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));


CREATE TRIGGER usage_records_immutable BEFORE DELETE OR UPDATE ON public.usage_records FOR EACH ROW EXECUTE FUNCTION agents_factory_private.reject_agent_spec_deployment_mutation();

