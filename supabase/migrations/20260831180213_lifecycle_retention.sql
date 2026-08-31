-- Role and column ACLs, FORCE RLS and function ACLs are not captured by migra.
-- No login, secret, app/admin membership or production activation is provisioned.
do $roles$ begin
  if not exists(select 1 from pg_roles where rolname='agents_factory_retention') then
    create role agents_factory_retention nologin noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls;
  end if;
end $roles$;
grant usage on schema public, agents_factory_private to agents_factory_retention;

  create table "public"."retention_policies" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "conversation_days" integer not null default 90,
    "trace_days" integer not null default 30,
    "action_months" integer not null default 12,
    "revision" integer not null default 1
      );


alter table "public"."retention_policies" enable row level security;

CREATE UNIQUE INDEX retention_policies_pkey ON public.retention_policies USING btree (id);

CREATE UNIQUE INDEX retention_policies_tenant_id_id_key ON public.retention_policies USING btree (tenant_id, id);

CREATE UNIQUE INDEX retention_policies_tenant_id_key ON public.retention_policies USING btree (tenant_id);

alter table "public"."retention_policies" add constraint "retention_policies_pkey" PRIMARY KEY using index "retention_policies_pkey";

alter table "public"."retention_policies" add constraint "retention_policies_action_months_check" CHECK (((action_months >= 1) AND (action_months <= 120))) not valid;

alter table "public"."retention_policies" validate constraint "retention_policies_action_months_check";

alter table "public"."retention_policies" add constraint "retention_policies_conversation_days_check" CHECK (((conversation_days >= 1) AND (conversation_days <= 3650))) not valid;

alter table "public"."retention_policies" validate constraint "retention_policies_conversation_days_check";

alter table "public"."retention_policies" add constraint "retention_policies_revision_check" CHECK ((revision > 0)) not valid;

alter table "public"."retention_policies" validate constraint "retention_policies_revision_check";

alter table "public"."retention_policies" add constraint "retention_policies_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) not valid;

alter table "public"."retention_policies" validate constraint "retention_policies_tenant_id_fkey";

alter table "public"."retention_policies" add constraint "retention_policies_tenant_id_id_key" UNIQUE using index "retention_policies_tenant_id_id_key";

alter table "public"."retention_policies" add constraint "retention_policies_tenant_id_key" UNIQUE using index "retention_policies_tenant_id_key";

alter table "public"."retention_policies" add constraint "retention_policies_trace_days_check" CHECK (((trace_days >= 1) AND (trace_days <= 3650))) not valid;

alter table "public"."retention_policies" validate constraint "retention_policies_trace_days_check";


alter table public.retention_policies force row level security;
revoke all on public.retention_policies from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin, agents_factory_retention;

-- Functions precede dependent policies/triggers on a fresh installation.
set check_function_bodies = off;

CREATE OR REPLACE FUNCTION agents_factory_private.action_retention_due(action_id uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
select exists(select 1 from public.actions a where a.tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid
  and a.id=action_id and a.state in ('SUCCEEDED','REJECTED','FAILED','EXPIRED','HANDED_OFF','UNCERTAIN')
  and a.updated_at<agents_factory_private.retention_cutoff('action')
  and not exists(select 1 from public.approval_requests r where r.tenant_id=a.tenant_id and r.action_id=a.id and r.state='PENDING')
  and not exists(select 1 from public.outbox_jobs j where j.tenant_id=a.tenant_id
    and j.status not in ('succeeded','dead_letter')
    and (j.payload->>'aggregate_id'=a.id::text or j.payload->>'aggregate_id' in
      (select r.id::text from public.approval_requests r where r.tenant_id=a.tenant_id and r.action_id=a.id))))
$function$
;

CREATE OR REPLACE FUNCTION agents_factory_private.guard_retention_minimization()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  if current_user<>'agents_factory_retention' then return new; end if;
  if tg_table_name='messages' then
    if new.content is distinct from old.content and
      (old.created_at>=agents_factory_private.retention_cutoff('conversation') or new.content<>'{}'::jsonb) then
      raise exception 'conversation retention boundary' using errcode='42501';
    end if;
    if new.runtime_metadata is distinct from old.runtime_metadata and
      (old.created_at>=agents_factory_private.retention_cutoff('trace') or new.runtime_metadata is distinct from
        jsonb_strip_nulls(jsonb_build_object('model',old.runtime_metadata->'model','reasoning_effort',old.runtime_metadata->'reasoning_effort',
        'agent_spec_digest',old.runtime_metadata->'agent_spec_digest','usage',old.runtime_metadata->'usage',
        'conversation_state_version',old.runtime_metadata->'conversation_state_version'))) then
      raise exception 'trace retention boundary' using errcode='42501';
    end if;
  elsif tg_table_name='whatsapp_webhook_events' then
    if new.raw_payload<>'{}'::jsonb or new.normalized_content<>'{}'::jsonb then
      raise exception 'retention only minimizes webhook content' using errcode='42501';
    end if;
  elsif tg_table_name='outbound_messages' then
    if new.payload<>'{}'::jsonb then raise exception 'retention only minimizes payload' using errcode='42501'; end if;
  elsif tg_table_name='media_observations' then
    if new.media_id is not null or new.observation is distinct from jsonb_build_object('kind',old.observation->>'kind','status','DELETED','reason_code','retention_expired') then
      raise exception 'retention only minimizes non-file observations' using errcode='42501';
    end if;
  end if;
  return new;
end $function$
;

CREATE OR REPLACE FUNCTION agents_factory_private.retention_cutoff(data_class text)
 RETURNS timestamp with time zone
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
select current_timestamp - case data_class
  when 'conversation' then make_interval(days=>coalesce((select p.conversation_days from public.retention_policies p where p.tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid),90))
  when 'trace' then make_interval(days=>coalesce((select p.trace_days from public.retention_policies p where p.tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid),30))
  when 'action' then make_interval(months=>coalesce((select p.action_months from public.retention_policies p where p.tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid),12))
  else null end
$function$
;

CREATE OR REPLACE FUNCTION agents_factory_private.enforce_action_lifecycle()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
begin
  if current_user = 'agents_factory_retention' and tg_op <> 'DELETE' then
    raise exception 'retention cannot rewrite actions' using errcode = '42501';
  end if;
  if tg_op = 'INSERT' then
    if new.state <> 'REQUESTED' or new.execution_attempts <> 0
      or new.result <> '{}'::jsonb then
      raise exception 'Actions must begin in REQUESTED'
        using errcode = '55000';
    end if;
    return new;
  end if;
  if tg_op = 'DELETE' then
    if current_user = 'agents_factory_retention' and agents_factory_private.action_retention_due(old.id) then
      return old;
    end if;
    raise exception 'Action history is immutable'
      using errcode = '55000';
  end if;
  if row(
    new.id, new.tenant_id, new.conversation_id, new.customer_ref,
    new.capability, new.action_type, new.risk, new.required_identity_level,
    new.achieved_identity_level, new.parameters, new.parameter_digest,
    new.confirmation_required, new.confirmation_expires_at,
    new.approval_required, new.approval_route_ref,
    new.connector_binding_id, new.connector_name, new.created_at
  ) is distinct from row(
    old.id, old.tenant_id, old.conversation_id, old.customer_ref,
    old.capability, old.action_type, old.risk, old.required_identity_level,
    old.achieved_identity_level, old.parameters, old.parameter_digest,
    old.confirmation_required, old.confirmation_expires_at,
    old.approval_required, old.approval_route_ref,
    old.connector_binding_id, old.connector_name, old.created_at
  ) then
    raise exception 'Action request fields are immutable'
      using errcode = '55000';
  end if;
  if new.state <> old.state and not (
    (old.state = 'REQUESTED' and new.state in ('IDENTITY_VERIFIED', 'REJECTED'))
    or (old.state = 'IDENTITY_VERIFIED'
      and new.state in ('AWAITING_CONFIRMATION', 'CONFIRMED'))
    or (old.state = 'AWAITING_CONFIRMATION'
      and new.state in ('CONFIRMED', 'REJECTED', 'EXPIRED'))
    or (old.state = 'CONFIRMED'
      and new.state in ('AWAITING_APPROVAL', 'EXECUTING', 'FAILED'))
    or (old.state = 'AWAITING_APPROVAL'
      and new.state in ('EXECUTING', 'REJECTED', 'FAILED', 'EXPIRED'))
    or (old.state = 'EXECUTING'
      and new.state in ('SUCCEEDED', 'FAILED', 'UNCERTAIN', 'HANDED_OFF'))
  ) then
    raise exception 'Invalid action lifecycle transition'
      using errcode = '55000';
  end if;
  if new.execution_attempts <> old.execution_attempts
    and not (
      new.state = 'EXECUTING'
      and old.state in ('CONFIRMED', 'AWAITING_APPROVAL')
      and new.execution_attempts = old.execution_attempts + 1
    ) then
    raise exception 'Invalid action execution attempt update'
      using errcode = '55000';
  end if;
  if row(new.confirmation_digest, new.confirmed_at)
    is distinct from row(old.confirmation_digest, old.confirmed_at)
    and not (
      old.state = 'AWAITING_CONFIRMATION'
      and new.state = 'CONFIRMED'
      and old.confirmation_digest is null
      and old.confirmed_at is null
      and new.confirmation_digest is not null
      and new.confirmed_at is not null
    ) then
    raise exception 'Invalid confirmation evidence update'
      using errcode = '55000';
  end if;
  if row(new.approval_reference, new.approved_at)
    is distinct from row(old.approval_reference, old.approved_at)
    and not (
      old.state = 'AWAITING_APPROVAL'
      and new.state = 'AWAITING_APPROVAL'
      and old.approval_reference is null
      and old.approved_at is null
      and new.approval_reference is not null
      and new.approved_at is not null
    ) then
    raise exception 'Invalid approval evidence update'
      using errcode = '55000';
  end if;
  if new.result is distinct from old.result
    and not (
      old.state = 'EXECUTING'
      and new.state in ('SUCCEEDED', 'FAILED', 'UNCERTAIN', 'HANDED_OFF')
      or old.state in ('CONFIRMED', 'AWAITING_APPROVAL')
      and new.state = 'FAILED'
      or old.state = 'AWAITING_APPROVAL'
      and new.state in ('REJECTED', 'EXPIRED')
    ) then
    raise exception 'Invalid action result update'
      using errcode = '55000';
  end if;
  return new;
end
$function$
;

CREATE OR REPLACE FUNCTION agents_factory_private.reject_agent_spec_deployment_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
begin
  if tg_op='DELETE' and current_user='agents_factory_retention'
    and tg_table_schema='public' and tg_table_name in ('action_events','approval_decisions') then return null; end if;
  raise exception 'AgentSpec deployment history is append-only' using errcode='55000';
end $function$
;

CREATE OR REPLACE FUNCTION agents_factory_private.reject_audit_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  if tg_op='DELETE' and current_user='agents_factory_retention' then
    if old.occurred_at<agents_factory_private.retention_cutoff('action') then return old; end if;
  end if;
  raise exception 'audit_events are append-only' using errcode='55000';
end $function$
;

set check_function_bodies = on;

revoke all on function agents_factory_private.retention_cutoff(text) from public, anon, authenticated, service_role;
revoke all on function agents_factory_private.action_retention_due(uuid) from public, anon, authenticated, service_role;
revoke all on function agents_factory_private.guard_retention_minimization() from public, anon, authenticated, service_role;
grant execute on function agents_factory_private.retention_cutoff(text) to agents_factory_retention;
grant execute on function agents_factory_private.action_retention_due(uuid) to agents_factory_retention;

grant update (content,runtime_metadata) on public.messages to agents_factory_retention;
grant update (raw_payload,normalized_content) on public.whatsapp_webhook_events to agents_factory_retention;
grant update (payload) on public.outbound_messages to agents_factory_retention;
grant update (observation) on public.media_observations to agents_factory_retention;
-- Required only to lock eligible Actions; enforce_action_lifecycle rejects rewrites.
grant update (updated_at) on public.actions to agents_factory_retention;

grant delete on table "public"."action_events" to "agents_factory_retention";

grant select on table "public"."action_events" to "agents_factory_retention";

grant delete on table "public"."actions" to "agents_factory_retention";

grant select on table "public"."actions" to "agents_factory_retention";

grant delete on table "public"."approval_decisions" to "agents_factory_retention";

grant select on table "public"."approval_decisions" to "agents_factory_retention";

grant delete on table "public"."approval_links" to "agents_factory_retention";

grant select on table "public"."approval_links" to "agents_factory_retention";

grant delete on table "public"."approval_requests" to "agents_factory_retention";

grant select on table "public"."approval_requests" to "agents_factory_retention";

grant delete on table "public"."audit_events" to "agents_factory_retention";

grant insert on table "public"."audit_events" to "agents_factory_retention";

grant select on table "public"."audit_events" to "agents_factory_retention";

grant select on table "public"."media_observations" to "agents_factory_retention";

grant select on table "public"."messages" to "agents_factory_retention";

grant select on table "public"."outbound_messages" to "agents_factory_retention";

grant select on table "public"."outbox_jobs" to "agents_factory_retention";

grant insert on table "public"."retention_policies" to "agents_factory_admin";

grant select on table "public"."retention_policies" to "agents_factory_admin";

grant update on table "public"."retention_policies" to "agents_factory_admin";

grant select on table "public"."retention_policies" to "agents_factory_app";

grant select on table "public"."retention_policies" to "agents_factory_retention";

grant select on table "public"."whatsapp_webhook_events" to "agents_factory_retention";


  create policy "action_events_retention_delete"
  on "public"."action_events"
  as permissive
  for delete
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND agents_factory_private.action_retention_due(action_id)));



  create policy "action_events_retention_read"
  on "public"."action_events"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "actions_retention_delete"
  on "public"."actions"
  as permissive
  for delete
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND agents_factory_private.action_retention_due(id)));



  create policy "actions_retention_read"
  on "public"."actions"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "actions_retention_update"
  on "public"."actions"
  as permissive
  for update
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND agents_factory_private.action_retention_due(id)))
with check (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND agents_factory_private.action_retention_due(id)));



  create policy "approval_decisions_retention_delete"
  on "public"."approval_decisions"
  as permissive
  for delete
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND agents_factory_private.action_retention_due(action_id)));



  create policy "approval_decisions_retention_read"
  on "public"."approval_decisions"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "approval_links_retention_delete"
  on "public"."approval_links"
  as permissive
  for delete
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND (EXISTS ( SELECT 1
   FROM public.approval_requests r
  WHERE ((r.tenant_id = approval_links.tenant_id) AND (r.id = approval_links.request_id) AND agents_factory_private.action_retention_due(r.action_id))))));



  create policy "approval_links_retention_read"
  on "public"."approval_links"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "approval_requests_retention_delete"
  on "public"."approval_requests"
  as permissive
  for delete
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND agents_factory_private.action_retention_due(action_id)));



  create policy "approval_requests_retention_read"
  on "public"."approval_requests"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "audit_events_retention_delete"
  on "public"."audit_events"
  as permissive
  for delete
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND (occurred_at < agents_factory_private.retention_cutoff('action'::text))));



  create policy "audit_events_retention_insert"
  on "public"."audit_events"
  as permissive
  for insert
  to agents_factory_retention
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "audit_events_retention_read"
  on "public"."audit_events"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "media_observations_retention_read"
  on "public"."media_observations"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "media_observations_retention_update"
  on "public"."media_observations"
  as permissive
  for update
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND (EXISTS ( SELECT 1
   FROM public.messages m
  WHERE ((m.tenant_id = media_observations.tenant_id) AND (m.id = media_observations.id) AND (m.created_at < agents_factory_private.retention_cutoff('conversation'::text)))))))
with check (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND (EXISTS ( SELECT 1
   FROM public.messages m
  WHERE ((m.tenant_id = media_observations.tenant_id) AND (m.id = media_observations.id) AND (m.created_at < agents_factory_private.retention_cutoff('conversation'::text)))))));



  create policy "messages_retention_read"
  on "public"."messages"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "messages_retention_update"
  on "public"."messages"
  as permissive
  for update
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND ((created_at < agents_factory_private.retention_cutoff('trace'::text)) OR (created_at < agents_factory_private.retention_cutoff('conversation'::text)))))
with check (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND ((created_at < agents_factory_private.retention_cutoff('trace'::text)) OR (created_at < agents_factory_private.retention_cutoff('conversation'::text)))));



  create policy "outbound_messages_retention_read"
  on "public"."outbound_messages"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "outbound_messages_retention_update"
  on "public"."outbound_messages"
  as permissive
  for update
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND ((created_at < agents_factory_private.retention_cutoff('conversation'::text)) AND (status = ANY (ARRAY['ACCEPTED'::text, 'SENT'::text, 'DELIVERED'::text, 'READ'::text, 'FAILED'::text, 'UNCERTAIN'::text, 'BLOCKED'::text])))))
with check (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND ((created_at < agents_factory_private.retention_cutoff('conversation'::text)) AND (status = ANY (ARRAY['ACCEPTED'::text, 'SENT'::text, 'DELIVERED'::text, 'READ'::text, 'FAILED'::text, 'UNCERTAIN'::text, 'BLOCKED'::text])))));



  create policy "outbox_jobs_retention_read"
  on "public"."outbox_jobs"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "retention_policies_admin"
  on "public"."retention_policies"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "retention_policies_read"
  on "public"."retention_policies"
  as permissive
  for select
  to agents_factory_app, agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "whatsapp_webhook_events_retention_read"
  on "public"."whatsapp_webhook_events"
  as permissive
  for select
  to agents_factory_retention
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "whatsapp_webhook_events_retention_update"
  on "public"."whatsapp_webhook_events"
  as permissive
  for update
  to agents_factory_retention
using (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND (received_at < agents_factory_private.retention_cutoff('conversation'::text))))
with check (((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid) AND (received_at < agents_factory_private.retention_cutoff('conversation'::text))));


CREATE TRIGGER observations_retention_guard BEFORE UPDATE ON public.media_observations FOR EACH ROW EXECUTE FUNCTION agents_factory_private.guard_retention_minimization();

CREATE TRIGGER messages_retention_guard BEFORE UPDATE ON public.messages FOR EACH ROW EXECUTE FUNCTION agents_factory_private.guard_retention_minimization();

CREATE TRIGGER outbound_retention_guard BEFORE UPDATE ON public.outbound_messages FOR EACH ROW EXECUTE FUNCTION agents_factory_private.guard_retention_minimization();

CREATE TRIGGER webhook_retention_guard BEFORE UPDATE ON public.whatsapp_webhook_events FOR EACH ROW EXECUTE FUNCTION agents_factory_private.guard_retention_minimization();

