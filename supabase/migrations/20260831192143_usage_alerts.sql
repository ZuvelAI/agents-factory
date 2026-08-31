alter table "public"."outbox_jobs" drop constraint "outbox_jobs_attempt_count_check";


  create table "public"."usage_alerts" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "period_start" timestamp with time zone not null,
    "period_end" timestamp with time zone not null,
    "configuration_revision" integer not null,
    "metric" text not null,
    "threshold" integer not null,
    "percentage" numeric not null,
    "state" text not null,
    "recorded_at" timestamp with time zone not null default now()
      );


alter table "public"."usage_alerts" enable row level security;

-- Security properties omitted by the schema diff must survive fresh installs.
alter table public.usage_alerts force row level security;
revoke all on public.usage_alerts
from public,anon,authenticated,service_role,agents_factory_app,agents_factory_admin;

alter table "public"."outbox_jobs" add column "deferral_count" integer not null default 0;

CREATE UNIQUE INDEX usage_alerts_pkey ON public.usage_alerts USING btree (id);

CREATE UNIQUE INDEX usage_alerts_tenant_id_id_key ON public.usage_alerts USING btree (tenant_id, id);

CREATE UNIQUE INDEX usage_alerts_tenant_id_period_start_period_end_configuratio_key ON public.usage_alerts USING btree (tenant_id, period_start, period_end, configuration_revision, metric, threshold);

CREATE INDEX usage_alerts_tenant_page ON public.usage_alerts USING btree (tenant_id, id DESC);

alter table "public"."usage_alerts" add constraint "usage_alerts_pkey" PRIMARY KEY using index "usage_alerts_pkey";

alter table "public"."outbox_jobs" add constraint "outbox_jobs_deferral_count_check" CHECK (((deferral_count >= 0) AND (deferral_count <= attempt_count))) not valid;

alter table "public"."outbox_jobs" validate constraint "outbox_jobs_deferral_count_check";

alter table "public"."usage_alerts" add constraint "usage_alerts_check" CHECK ((period_end > period_start)) not valid;

alter table "public"."usage_alerts" validate constraint "usage_alerts_check";

alter table "public"."usage_alerts" add constraint "usage_alerts_configuration_revision_check" CHECK ((configuration_revision >= 0)) not valid;

alter table "public"."usage_alerts" validate constraint "usage_alerts_configuration_revision_check";

alter table "public"."usage_alerts" add constraint "usage_alerts_metric_check" CHECK ((metric = ANY (ARRAY['messages'::text, 'conversations'::text, 'model_tokens'::text, 'cost'::text, 'storage_bytes'::text, 'concurrent_runs'::text, 'tool_calls'::text]))) not valid;

alter table "public"."usage_alerts" validate constraint "usage_alerts_metric_check";

alter table "public"."usage_alerts" add constraint "usage_alerts_percentage_check" CHECK ((percentage >= (0)::numeric)) not valid;

alter table "public"."usage_alerts" validate constraint "usage_alerts_percentage_check";

alter table "public"."usage_alerts" add constraint "usage_alerts_state_check" CHECK ((state = ANY (ARRAY['alert'::text, 'grace_overage'::text]))) not valid;

alter table "public"."usage_alerts" validate constraint "usage_alerts_state_check";

alter table "public"."usage_alerts" add constraint "usage_alerts_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) not valid;

alter table "public"."usage_alerts" validate constraint "usage_alerts_tenant_id_fkey";

alter table "public"."usage_alerts" add constraint "usage_alerts_tenant_id_id_key" UNIQUE using index "usage_alerts_tenant_id_id_key";

alter table "public"."usage_alerts" add constraint "usage_alerts_tenant_id_period_start_period_end_configuratio_key" UNIQUE using index "usage_alerts_tenant_id_period_start_period_end_configuratio_key";

alter table "public"."usage_alerts" add constraint "usage_alerts_threshold_check" CHECK (((threshold >= 1) AND (threshold <= 100))) not valid;

alter table "public"."usage_alerts" validate constraint "usage_alerts_threshold_check";

alter table "public"."outbox_jobs" add constraint "outbox_jobs_attempt_count_check" CHECK (((attempt_count >= 0) AND ((attempt_count - deferral_count) <= max_attempts))) not valid;

alter table "public"."outbox_jobs" validate constraint "outbox_jobs_attempt_count_check";

grant insert on table "public"."usage_alerts" to "agents_factory_admin";

grant select on table "public"."usage_alerts" to "agents_factory_admin";

grant insert on table "public"."usage_alerts" to "agents_factory_app";

grant select on table "public"."usage_alerts" to "agents_factory_app";


  create policy "usage_alerts_insert"
  on "public"."usage_alerts"
  as permissive
  for insert
  to agents_factory_app, agents_factory_admin
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "usage_alerts_read"
  on "public"."usage_alerts"
  as permissive
  for select
  to agents_factory_app, agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));


CREATE TRIGGER usage_alerts_immutable BEFORE DELETE OR UPDATE ON public.usage_alerts FOR EACH ROW EXECUTE FUNCTION agents_factory_private.reject_agent_spec_deployment_mutation();
