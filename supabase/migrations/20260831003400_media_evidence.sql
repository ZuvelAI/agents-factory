-- Media evidence only: unrelated local extension drift is intentionally omitted.


  create table "public"."media_evidence" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "whatsapp_account_id" uuid not null,
    "provider_media_id" text not null,
    "customer_ref" text not null,
    "first_message_id" uuid not null,
    "kind" text not null,
    "status" text not null,
    "content_digest" text,
    "storage_key" text,
    "media_type" text,
    "byte_size" integer not null default 0,
    "scan_status" text not null default 'PENDING'::text,
    "observation" jsonb,
    "created_at" timestamp with time zone not null default now(),
    "expires_at" timestamp with time zone not null,
    "deleted_at" timestamp with time zone
      );


alter table "public"."media_evidence" enable row level security;
alter table "public"."media_evidence" force row level security;

CREATE INDEX media_evidence_customer_idx ON public.media_evidence USING btree (tenant_id, customer_ref);

CREATE UNIQUE INDEX media_evidence_pkey ON public.media_evidence USING btree (id);

CREATE INDEX media_evidence_retention_idx ON public.media_evidence USING btree (tenant_id, expires_at) WHERE (deleted_at IS NULL);

CREATE UNIQUE INDEX media_evidence_tenant_id_whatsapp_account_id_provider_media_key ON public.media_evidence USING btree (tenant_id, whatsapp_account_id, provider_media_id);

alter table "public"."media_evidence" add constraint "media_evidence_pkey" PRIMARY KEY using index "media_evidence_pkey";

alter table "public"."media_evidence" add constraint "media_evidence_byte_size_check" CHECK (((byte_size >= 0) AND (byte_size <= 20971520))) not valid;

alter table "public"."media_evidence" validate constraint "media_evidence_byte_size_check";

alter table "public"."media_evidence" add constraint "media_evidence_check" CHECK ((expires_at > created_at)) not valid;

alter table "public"."media_evidence" validate constraint "media_evidence_check";

alter table "public"."media_evidence" add constraint "media_evidence_content_digest_check" CHECK ((content_digest ~ '^[a-f0-9]{64}$'::text)) not valid;

alter table "public"."media_evidence" validate constraint "media_evidence_content_digest_check";

alter table "public"."media_evidence" add constraint "media_evidence_kind_check" CHECK ((kind = ANY (ARRAY['audio'::text, 'image'::text, 'document'::text, 'video'::text]))) not valid;

alter table "public"."media_evidence" validate constraint "media_evidence_kind_check";

alter table "public"."media_evidence" add constraint "media_evidence_observation_check" CHECK (((observation IS NULL) OR (jsonb_typeof(observation) = 'object'::text))) not valid;

alter table "public"."media_evidence" validate constraint "media_evidence_observation_check";

alter table "public"."media_evidence" add constraint "media_evidence_scan_status_check" CHECK ((scan_status = ANY (ARRAY['PENDING'::text, 'CLEAN'::text, 'INFECTED'::text, 'UNAVAILABLE'::text]))) not valid;

alter table "public"."media_evidence" validate constraint "media_evidence_scan_status_check";

alter table "public"."media_evidence" add constraint "media_evidence_status_check" CHECK ((status = ANY (ARRAY['PROCESSING'::text, 'READY'::text, 'PENDING_PROVIDER'::text, 'HUMAN_REVIEW'::text, 'QUARANTINED'::text, 'FAILED'::text, 'DELETED'::text]))) not valid;

alter table "public"."media_evidence" validate constraint "media_evidence_status_check";

alter table "public"."media_evidence" add constraint "media_evidence_tenant_id_first_message_id_fkey" FOREIGN KEY (tenant_id, first_message_id) REFERENCES public.messages(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."media_evidence" validate constraint "media_evidence_tenant_id_first_message_id_fkey";

alter table "public"."media_evidence" add constraint "media_evidence_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT not valid;

alter table "public"."media_evidence" validate constraint "media_evidence_tenant_id_fkey";

alter table "public"."media_evidence" add constraint "media_evidence_tenant_id_whatsapp_account_id_fkey" FOREIGN KEY (tenant_id, whatsapp_account_id) REFERENCES public.whatsapp_accounts(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."media_evidence" validate constraint "media_evidence_tenant_id_whatsapp_account_id_fkey";

alter table "public"."media_evidence" add constraint "media_evidence_tenant_id_whatsapp_account_id_provider_media_key" UNIQUE using index "media_evidence_tenant_id_whatsapp_account_id_provider_media_key";

-- Do not inherit permissive deployment default privileges.
revoke all on public.media_evidence from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;
grant insert on table "public"."media_evidence" to "agents_factory_admin";

grant select on table "public"."media_evidence" to "agents_factory_admin";

grant update on table "public"."media_evidence" to "agents_factory_admin";

grant select on table "public"."media_evidence" to "agents_factory_app";


  create policy "media_evidence_admin"
  on "public"."media_evidence"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "media_evidence_read"
  on "public"."media_evidence"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));
