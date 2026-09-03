-- Task 34: captured from the isolated local database; retain FORCE RLS,
-- explicit default-ACL revocations and function-before-trigger dependency order.
  create table "public"."handoff_configurations" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "whatsapp_account_id" uuid not null,
    "revision" integer not null,
    "configuration" jsonb not null
      );


alter table "public"."handoff_configurations" enable row level security;
alter table "public"."handoff_configurations" force row level security;


  create table "public"."handoffs" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "conversation_id" uuid not null,
    "status" text not null,
    "reason" text not null,
    "configuration" jsonb not null,
    "notice_message_id" uuid not null,
    "requested_at" timestamp with time zone not null,
    "last_activity_at" timestamp with time zone not null,
    "closed_at" timestamp with time zone,
    "event_sequence" bigint not null default '-1'::integer
      );


alter table "public"."handoffs" enable row level security;
alter table "public"."handoffs" force row level security;

CREATE UNIQUE INDEX handoff_configurations_pkey ON public.handoff_configurations USING btree (id);

CREATE UNIQUE INDEX handoff_configurations_tenant_id_id_key ON public.handoff_configurations USING btree (tenant_id, id);

CREATE UNIQUE INDEX handoff_configurations_tenant_id_whatsapp_account_id_key ON public.handoff_configurations USING btree (tenant_id, whatsapp_account_id);

CREATE INDEX handoffs_activity_idx ON public.handoffs USING btree (tenant_id, last_activity_at) WHERE (status <> 'CLOSED'::text);

CREATE UNIQUE INDEX handoffs_one_live ON public.handoffs USING btree (tenant_id, conversation_id) WHERE (status <> 'CLOSED'::text);

CREATE UNIQUE INDEX handoffs_pkey ON public.handoffs USING btree (id);

CREATE UNIQUE INDEX handoffs_tenant_id_id_key ON public.handoffs USING btree (tenant_id, id);

CREATE UNIQUE INDEX handoffs_tenant_id_notice_message_id_key ON public.handoffs USING btree (tenant_id, notice_message_id);

alter table "public"."handoff_configurations" add constraint "handoff_configurations_pkey" PRIMARY KEY using index "handoff_configurations_pkey";

alter table "public"."handoffs" add constraint "handoffs_pkey" PRIMARY KEY using index "handoffs_pkey";

alter table "public"."handoff_configurations" add constraint "handoff_configurations_configuration_check" CHECK ((jsonb_typeof(configuration) = 'object'::text)) not valid;

alter table "public"."handoff_configurations" validate constraint "handoff_configurations_configuration_check";

alter table "public"."handoff_configurations" add constraint "handoff_configurations_revision_check" CHECK ((revision > 0)) not valid;

alter table "public"."handoff_configurations" validate constraint "handoff_configurations_revision_check";

alter table "public"."handoff_configurations" add constraint "handoff_configurations_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) not valid;

alter table "public"."handoff_configurations" validate constraint "handoff_configurations_tenant_id_fkey";

alter table "public"."handoff_configurations" add constraint "handoff_configurations_tenant_id_id_key" UNIQUE using index "handoff_configurations_tenant_id_id_key";

alter table "public"."handoff_configurations" add constraint "handoff_configurations_tenant_id_whatsapp_account_id_fkey" FOREIGN KEY (tenant_id, whatsapp_account_id) REFERENCES public.whatsapp_accounts(tenant_id, id) not valid;

alter table "public"."handoff_configurations" validate constraint "handoff_configurations_tenant_id_whatsapp_account_id_fkey";

alter table "public"."handoff_configurations" add constraint "handoff_configurations_tenant_id_whatsapp_account_id_key" UNIQUE using index "handoff_configurations_tenant_id_whatsapp_account_id_key";

alter table "public"."handoffs" add constraint "handoffs_check" CHECK (((status = 'CLOSED'::text) = (closed_at IS NOT NULL))) not valid;

alter table "public"."handoffs" validate constraint "handoffs_check";

alter table "public"."handoffs" add constraint "handoffs_check1" CHECK ((last_activity_at >= requested_at)) not valid;

alter table "public"."handoffs" validate constraint "handoffs_check1";

alter table "public"."handoffs" add constraint "handoffs_configuration_check" CHECK ((jsonb_typeof(configuration) = 'object'::text)) not valid;

alter table "public"."handoffs" validate constraint "handoffs_configuration_check";

alter table "public"."handoffs" add constraint "handoffs_event_sequence_check" CHECK ((event_sequence >= '-1'::integer)) not valid;

alter table "public"."handoffs" validate constraint "handoffs_event_sequence_check";

alter table "public"."handoffs" add constraint "handoffs_reason_check" CHECK ((reason = ANY (ARRAY['EXPLICIT_REQUEST'::text, 'MANDATORY_ESCALATION'::text, 'REPEATED_INTEGRATION_FAILURE'::text, 'CONSEQUENTIAL_ACTION_UNRESOLVED'::text]))) not valid;

alter table "public"."handoffs" validate constraint "handoffs_reason_check";

alter table "public"."handoffs" add constraint "handoffs_status_check" CHECK ((status = ANY (ARRAY['REQUESTED'::text, 'ACTIVE'::text, 'CLOSED'::text]))) not valid;

alter table "public"."handoffs" validate constraint "handoffs_status_check";

alter table "public"."handoffs" add constraint "handoffs_tenant_id_conversation_id_fkey" FOREIGN KEY (tenant_id, conversation_id) REFERENCES public.conversations(tenant_id, id) not valid;

alter table "public"."handoffs" validate constraint "handoffs_tenant_id_conversation_id_fkey";

alter table "public"."handoffs" add constraint "handoffs_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) not valid;

alter table "public"."handoffs" validate constraint "handoffs_tenant_id_fkey";

alter table "public"."handoffs" add constraint "handoffs_tenant_id_id_key" UNIQUE using index "handoffs_tenant_id_id_key";

alter table "public"."handoffs" add constraint "handoffs_tenant_id_notice_message_id_fkey" FOREIGN KEY (tenant_id, notice_message_id) REFERENCES public.messages(tenant_id, id) not valid;

alter table "public"."handoffs" validate constraint "handoffs_tenant_id_notice_message_id_fkey";

alter table "public"."handoffs" add constraint "handoffs_tenant_id_notice_message_id_key" UNIQUE using index "handoffs_tenant_id_notice_message_id_key";

revoke all on public.handoff_configurations, public.handoffs from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;

grant insert on table "public"."handoff_configurations" to "agents_factory_admin";

grant select on table "public"."handoff_configurations" to "agents_factory_admin";

grant update on table "public"."handoff_configurations" to "agents_factory_admin";

grant select on table "public"."handoff_configurations" to "agents_factory_app";

grant insert on table "public"."handoffs" to "agents_factory_admin";

grant select on table "public"."handoffs" to "agents_factory_admin";

grant update on table "public"."handoffs" to "agents_factory_admin";

grant select on table "public"."handoffs" to "agents_factory_app";


  create policy "handoff_configurations_admin"
  on "public"."handoff_configurations"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "handoff_configurations_read"
  on "public"."handoff_configurations"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "handoffs_admin"
  on "public"."handoffs"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "handoffs_read"
  on "public"."handoffs"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));


set check_function_bodies = off;

CREATE OR REPLACE FUNCTION agents_factory_private.guard_handoff_control()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  if new.control_state is distinct from old.control_state then
    if new.control_state in ('AWAITING_HUMAN', 'HUMAN_ACTIVE') and not exists (
      select 1 from public.handoffs h where h.tenant_id = new.tenant_id
      and h.conversation_id = new.id
      and h.status = case new.control_state when 'AWAITING_HUMAN' then 'REQUESTED' else 'ACTIVE' end
    ) then
      raise exception 'verified handoff required' using errcode = '42501';
    end if;
    if new.control_state in ('AI_ACTIVE', 'CLOSED') and exists (
      select 1 from public.handoffs h where h.tenant_id = new.tenant_id
      and h.conversation_id = new.id and h.status <> 'CLOSED'
    ) then
      raise exception 'human control must be ended first' using errcode = '42501';
    end if;
  end if;
  return new;
end;
$function$
;

revoke all on function agents_factory_private.guard_handoff_control() from public, anon, authenticated, service_role;
CREATE TRIGGER conversations_handoff_guard BEFORE UPDATE OF control_state ON public.conversations FOR EACH ROW EXECUTE FUNCTION agents_factory_private.guard_handoff_control();
set check_function_bodies = on;
