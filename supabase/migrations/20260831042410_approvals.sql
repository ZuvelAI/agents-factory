-- Task 31 approval foundation; captured from the isolated local database.
-- Exclude unrelated extension drift and retain explicit RLS/default-ACL hardening.

  create table "public"."approval_decisions" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "request_id" uuid not null,
    "action_id" uuid not null,
    "parameter_digest" text not null,
    "approver_email" text not null,
    "decision" text not null,
    "requested_result" jsonb not null,
    "decided_at" timestamp with time zone not null,
    "verification" text not null,
    "metadata" jsonb not null default '{}'::jsonb
      );


alter table "public"."approval_decisions" enable row level security;
alter table "public"."approval_decisions" force row level security;


  create table "public"."approval_links" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "request_id" uuid not null,
    "email" text not null,
    "token_digest" text not null,
    "notice_state" text not null default 'PENDING'::text,
    "invalidated_at" timestamp with time zone,
    "challenge_id" uuid,
    "otp_digest" text,
    "otp_expires_at" timestamp with time zone,
    "otp_attempts" integer not null default 0,
    "otp_sends" integer not null default 0,
    "last_sent_at" timestamp with time zone,
    "otp_delivery" text not null default 'PENDING'::text
      );


alter table "public"."approval_links" enable row level security;
alter table "public"."approval_links" force row level security;


  create table "public"."approval_requests" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "action_id" uuid not null,
    "parameter_digest" text not null,
    "route_id" uuid not null,
    "route_digest" text not null,
    "state" text not null,
    "expires_at" timestamp with time zone not null,
    "created_at" timestamp with time zone not null,
    "closed_at" timestamp with time zone
      );


alter table "public"."approval_requests" enable row level security;
alter table "public"."approval_requests" force row level security;


  create table "public"."approval_routes" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "ref" text not null,
    "capability" text not null,
    "action" text not null,
    "revision" integer not null,
    "configuration" jsonb not null,
    "digest" text not null
      );


alter table "public"."approval_routes" enable row level security;
alter table "public"."approval_routes" force row level security;

CREATE INDEX approval_decisions_action_idx ON public.approval_decisions USING btree (tenant_id, action_id);

CREATE UNIQUE INDEX approval_decisions_pkey ON public.approval_decisions USING btree (id);

CREATE UNIQUE INDEX approval_decisions_tenant_id_request_id_key ON public.approval_decisions USING btree (tenant_id, request_id);

CREATE UNIQUE INDEX approval_links_pkey ON public.approval_links USING btree (id);

CREATE UNIQUE INDEX approval_links_tenant_id_id_key ON public.approval_links USING btree (tenant_id, id);

CREATE UNIQUE INDEX approval_links_tenant_id_request_id_email_key ON public.approval_links USING btree (tenant_id, request_id, email);

CREATE INDEX approval_requests_expiry_idx ON public.approval_requests USING btree (tenant_id, expires_at) WHERE (state = 'PENDING'::text);

CREATE UNIQUE INDEX approval_requests_pkey ON public.approval_requests USING btree (id);

CREATE INDEX approval_requests_route_idx ON public.approval_requests USING btree (tenant_id, route_id);

CREATE UNIQUE INDEX approval_requests_tenant_id_action_id_key ON public.approval_requests USING btree (tenant_id, action_id);

CREATE UNIQUE INDEX approval_requests_tenant_id_id_action_id_parameter_digest_key ON public.approval_requests USING btree (tenant_id, id, action_id, parameter_digest);

CREATE UNIQUE INDEX approval_requests_tenant_id_id_key ON public.approval_requests USING btree (tenant_id, id);

CREATE UNIQUE INDEX approval_routes_pkey ON public.approval_routes USING btree (id);

CREATE UNIQUE INDEX approval_routes_tenant_id_id_key ON public.approval_routes USING btree (tenant_id, id);

CREATE UNIQUE INDEX approval_routes_tenant_id_ref_capability_action_key ON public.approval_routes USING btree (tenant_id, ref, capability, action);

alter table "public"."approval_decisions" add constraint "approval_decisions_pkey" PRIMARY KEY using index "approval_decisions_pkey";

alter table "public"."approval_links" add constraint "approval_links_pkey" PRIMARY KEY using index "approval_links_pkey";

alter table "public"."approval_requests" add constraint "approval_requests_pkey" PRIMARY KEY using index "approval_requests_pkey";

alter table "public"."approval_routes" add constraint "approval_routes_pkey" PRIMARY KEY using index "approval_routes_pkey";

alter table "public"."approval_decisions" add constraint "approval_decisions_decision_check" CHECK ((decision = ANY (ARRAY['APPROVE'::text, 'REJECT'::text]))) not valid;

alter table "public"."approval_decisions" validate constraint "approval_decisions_decision_check";

alter table "public"."approval_decisions" add constraint "approval_decisions_metadata_check" CHECK ((jsonb_typeof(metadata) = 'object'::text)) not valid;

alter table "public"."approval_decisions" validate constraint "approval_decisions_metadata_check";

alter table "public"."approval_decisions" add constraint "approval_decisions_parameter_digest_check" CHECK ((parameter_digest ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."approval_decisions" validate constraint "approval_decisions_parameter_digest_check";

alter table "public"."approval_decisions" add constraint "approval_decisions_requested_result_check" CHECK ((jsonb_typeof(requested_result) = 'object'::text)) not valid;

alter table "public"."approval_decisions" validate constraint "approval_decisions_requested_result_check";

alter table "public"."approval_decisions" add constraint "approval_decisions_tenant_id_action_id_fkey" FOREIGN KEY (tenant_id, action_id) REFERENCES public.actions(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."approval_decisions" validate constraint "approval_decisions_tenant_id_action_id_fkey";

alter table "public"."approval_decisions" add constraint "approval_decisions_tenant_id_request_id_action_id_paramete_fkey" FOREIGN KEY (tenant_id, request_id, action_id, parameter_digest) REFERENCES public.approval_requests(tenant_id, id, action_id, parameter_digest) ON DELETE RESTRICT not valid;

alter table "public"."approval_decisions" validate constraint "approval_decisions_tenant_id_request_id_action_id_paramete_fkey";

alter table "public"."approval_decisions" add constraint "approval_decisions_tenant_id_request_id_fkey" FOREIGN KEY (tenant_id, request_id) REFERENCES public.approval_requests(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."approval_decisions" validate constraint "approval_decisions_tenant_id_request_id_fkey";

alter table "public"."approval_decisions" add constraint "approval_decisions_tenant_id_request_id_key" UNIQUE using index "approval_decisions_tenant_id_request_id_key";

alter table "public"."approval_decisions" add constraint "approval_decisions_verification_check" CHECK ((verification = 'LINK_AND_EMAIL_OTP'::text)) not valid;

alter table "public"."approval_decisions" validate constraint "approval_decisions_verification_check";

alter table "public"."approval_links" add constraint "approval_links_notice_state_check" CHECK ((notice_state = ANY (ARRAY['PENDING'::text, 'CLAIMED'::text, 'SENT'::text, 'FAILED'::text, 'UNCERTAIN'::text]))) not valid;

alter table "public"."approval_links" validate constraint "approval_links_notice_state_check";

alter table "public"."approval_links" add constraint "approval_links_otp_attempts_check" CHECK (((otp_attempts >= 0) AND (otp_attempts <= 5))) not valid;

alter table "public"."approval_links" validate constraint "approval_links_otp_attempts_check";

alter table "public"."approval_links" add constraint "approval_links_otp_delivery_check" CHECK ((otp_delivery = ANY (ARRAY['PENDING'::text, 'CLAIMED'::text, 'SENT'::text, 'FAILED'::text, 'UNCERTAIN'::text]))) not valid;

alter table "public"."approval_links" validate constraint "approval_links_otp_delivery_check";

alter table "public"."approval_links" add constraint "approval_links_otp_digest_check" CHECK (((otp_digest IS NULL) OR (otp_digest ~ '^[a-f0-9]{64}$'::text))) not valid;

alter table "public"."approval_links" validate constraint "approval_links_otp_digest_check";

alter table "public"."approval_links" add constraint "approval_links_otp_sends_check" CHECK (((otp_sends >= 0) AND (otp_sends <= 5))) not valid;

alter table "public"."approval_links" validate constraint "approval_links_otp_sends_check";

alter table "public"."approval_links" add constraint "approval_links_tenant_id_id_key" UNIQUE using index "approval_links_tenant_id_id_key";

alter table "public"."approval_links" add constraint "approval_links_tenant_id_request_id_email_key" UNIQUE using index "approval_links_tenant_id_request_id_email_key";

alter table "public"."approval_links" add constraint "approval_links_tenant_id_request_id_fkey" FOREIGN KEY (tenant_id, request_id) REFERENCES public.approval_requests(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."approval_links" validate constraint "approval_links_tenant_id_request_id_fkey";

alter table "public"."approval_links" add constraint "approval_links_token_digest_check" CHECK ((token_digest ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."approval_links" validate constraint "approval_links_token_digest_check";

alter table "public"."approval_requests" add constraint "approval_requests_check" CHECK ((expires_at > created_at)) not valid;

alter table "public"."approval_requests" validate constraint "approval_requests_check";

alter table "public"."approval_requests" add constraint "approval_requests_check1" CHECK ((((state = 'PENDING'::text) AND (closed_at IS NULL)) OR ((state <> 'PENDING'::text) AND (closed_at IS NOT NULL)))) not valid;

alter table "public"."approval_requests" validate constraint "approval_requests_check1";

alter table "public"."approval_requests" add constraint "approval_requests_parameter_digest_check" CHECK ((parameter_digest ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."approval_requests" validate constraint "approval_requests_parameter_digest_check";

alter table "public"."approval_requests" add constraint "approval_requests_route_digest_check" CHECK ((route_digest ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."approval_requests" validate constraint "approval_requests_route_digest_check";

alter table "public"."approval_requests" add constraint "approval_requests_state_check" CHECK ((state = ANY (ARRAY['PENDING'::text, 'APPROVED'::text, 'REJECTED'::text, 'EXPIRED'::text, 'INVALIDATED'::text]))) not valid;

alter table "public"."approval_requests" validate constraint "approval_requests_state_check";

alter table "public"."approval_requests" add constraint "approval_requests_tenant_id_action_id_fkey" FOREIGN KEY (tenant_id, action_id) REFERENCES public.actions(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."approval_requests" validate constraint "approval_requests_tenant_id_action_id_fkey";

alter table "public"."approval_requests" add constraint "approval_requests_tenant_id_action_id_key" UNIQUE using index "approval_requests_tenant_id_action_id_key";

alter table "public"."approval_requests" add constraint "approval_requests_tenant_id_id_action_id_parameter_digest_key" UNIQUE using index "approval_requests_tenant_id_id_action_id_parameter_digest_key";

alter table "public"."approval_requests" add constraint "approval_requests_tenant_id_id_key" UNIQUE using index "approval_requests_tenant_id_id_key";

alter table "public"."approval_requests" add constraint "approval_requests_tenant_id_route_id_fkey" FOREIGN KEY (tenant_id, route_id) REFERENCES public.approval_routes(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."approval_requests" validate constraint "approval_requests_tenant_id_route_id_fkey";

alter table "public"."approval_routes" add constraint "approval_routes_configuration_check" CHECK ((jsonb_typeof(configuration) = 'object'::text)) not valid;

alter table "public"."approval_routes" validate constraint "approval_routes_configuration_check";

alter table "public"."approval_routes" add constraint "approval_routes_digest_check" CHECK ((digest ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."approval_routes" validate constraint "approval_routes_digest_check";

alter table "public"."approval_routes" add constraint "approval_routes_revision_check" CHECK ((revision > 0)) not valid;

alter table "public"."approval_routes" validate constraint "approval_routes_revision_check";

alter table "public"."approval_routes" add constraint "approval_routes_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT not valid;

alter table "public"."approval_routes" validate constraint "approval_routes_tenant_id_fkey";

alter table "public"."approval_routes" add constraint "approval_routes_tenant_id_id_key" UNIQUE using index "approval_routes_tenant_id_id_key";

alter table "public"."approval_routes" add constraint "approval_routes_tenant_id_ref_capability_action_key" UNIQUE using index "approval_routes_tenant_id_ref_capability_action_key";

revoke all on public.approval_routes, public.approval_requests,
  public.approval_links, public.approval_decisions
from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;

grant insert on table "public"."approval_decisions" to "agents_factory_admin";

grant select on table "public"."approval_decisions" to "agents_factory_admin";

grant select on table "public"."approval_decisions" to "agents_factory_app";

grant insert on table "public"."approval_links" to "agents_factory_admin";

grant select on table "public"."approval_links" to "agents_factory_admin";

grant update on table "public"."approval_links" to "agents_factory_admin";

grant select on table "public"."approval_links" to "agents_factory_app";

grant insert on table "public"."approval_requests" to "agents_factory_admin";

grant select on table "public"."approval_requests" to "agents_factory_admin";

grant update on table "public"."approval_requests" to "agents_factory_admin";

grant select on table "public"."approval_requests" to "agents_factory_app";

grant insert on table "public"."approval_routes" to "agents_factory_admin";

grant select on table "public"."approval_routes" to "agents_factory_admin";

grant update on table "public"."approval_routes" to "agents_factory_admin";

grant select on table "public"."approval_routes" to "agents_factory_app";


  create policy "approval_decisions_admin"
  on "public"."approval_decisions"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "approval_decisions_read"
  on "public"."approval_decisions"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "approval_links_admin"
  on "public"."approval_links"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "approval_links_read"
  on "public"."approval_links"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "approval_requests_admin"
  on "public"."approval_requests"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "approval_requests_read"
  on "public"."approval_requests"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "approval_routes_admin"
  on "public"."approval_routes"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "approval_routes_read"
  on "public"."approval_routes"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));


CREATE TRIGGER approval_decisions_append_only BEFORE DELETE OR UPDATE OR TRUNCATE ON public.approval_decisions FOR EACH STATEMENT EXECUTE FUNCTION agents_factory_private.reject_agent_spec_deployment_mutation();

