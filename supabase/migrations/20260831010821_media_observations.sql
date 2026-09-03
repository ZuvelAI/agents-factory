-- Separate media observations; original messages and their grants are unchanged.


  create table "public"."media_observations" (
    "id" uuid not null,
    "tenant_id" uuid not null,
    "media_id" uuid,
    "observation" jsonb not null
      );


alter table "public"."media_observations" enable row level security;
alter table "public"."media_observations" force row level security;

CREATE UNIQUE INDEX media_evidence_tenant_id_id_key ON public.media_evidence USING btree (tenant_id, id);

CREATE UNIQUE INDEX media_observations_pkey ON public.media_observations USING btree (id);

CREATE INDEX media_observations_tenant_media_idx ON public.media_observations USING btree (tenant_id, media_id);

alter table "public"."media_observations" add constraint "media_observations_pkey" PRIMARY KEY using index "media_observations_pkey";

alter table "public"."media_evidence" add constraint "media_evidence_tenant_id_id_key" UNIQUE using index "media_evidence_tenant_id_id_key";

alter table "public"."media_observations" add constraint "media_observations_observation_check" CHECK ((jsonb_typeof(observation) = 'object'::text)) not valid;

alter table "public"."media_observations" validate constraint "media_observations_observation_check";

alter table "public"."media_observations" add constraint "media_observations_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT not valid;

alter table "public"."media_observations" validate constraint "media_observations_tenant_id_fkey";

alter table "public"."media_observations" add constraint "media_observations_tenant_id_id_fkey" FOREIGN KEY (tenant_id, id) REFERENCES public.messages(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."media_observations" validate constraint "media_observations_tenant_id_id_fkey";

alter table "public"."media_observations" add constraint "media_observations_tenant_id_media_id_fkey" FOREIGN KEY (tenant_id, media_id) REFERENCES public.media_evidence(tenant_id, id) ON DELETE RESTRICT not valid;

alter table "public"."media_observations" validate constraint "media_observations_tenant_id_media_id_fkey";

revoke all on public.media_observations from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin;
grant insert on table "public"."media_observations" to "agents_factory_admin";

grant select on table "public"."media_observations" to "agents_factory_admin";

grant update on table "public"."media_observations" to "agents_factory_admin";

grant select on table "public"."media_observations" to "agents_factory_app";


  create policy "media_observations_admin"
  on "public"."media_observations"
  as permissive
  for all
  to agents_factory_admin
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid))
with check ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));



  create policy "media_observations_read"
  on "public"."media_observations"
  as permissive
  for select
  to agents_factory_app
using ((tenant_id = (NULLIF(( SELECT current_setting('app.tenant_id'::text, true) AS current_setting), ''::text))::uuid));
