-- Internal, opt-in prospect capture. No Data API grants or external CRM.
create table public.lead_subjects (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  capture_suppressed boolean not null default false,
  suppressed_at timestamptz,
  suppression_message_id uuid,
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  foreign key (tenant_id, suppression_message_id)
    references public.messages(tenant_id, id) on delete restrict,
  check (capture_suppressed = (suppressed_at is not null and suppression_message_id is not null))
);
create index lead_subjects_suppression_idx on public.lead_subjects(tenant_id, suppression_message_id);

create table public.lead_subject_keys (
  id uuid primary key,
  tenant_id uuid not null,
  subject_id uuid not null,
  kind text not null check (kind in ('PHONE', 'PROVIDER')),
  whatsapp_account_id uuid,
  value text not null check (length(value) between 1 and 200),
  created_at timestamptz not null default now(),
  unique nulls not distinct (tenant_id, kind, whatsapp_account_id, value),
  foreign key (tenant_id, subject_id) references public.lead_subjects(tenant_id, id) on delete restrict,
  foreign key (tenant_id, whatsapp_account_id) references public.whatsapp_accounts(tenant_id, id) on delete restrict,
  check ((kind = 'PHONE' and whatsapp_account_id is null and value ~ '^\+[1-9][0-9]{6,14}$')
      or (kind = 'PROVIDER' and whatsapp_account_id is not null))
);
create index lead_subject_keys_subject_idx on public.lead_subject_keys(tenant_id, subject_id);
create index lead_subject_keys_account_idx on public.lead_subject_keys(tenant_id, whatsapp_account_id);

create table public.lead_prospects (
  id uuid primary key,
  tenant_id uuid not null,
  subject_id uuid not null,
  contact_name text check (length(contact_name) between 1 and 1000),
  name_source text check (name_source in ('PROFILE', 'DECLARED')),
  contact_username text check (length(contact_username) between 1 and 200),
  declared_company text check (length(declared_company) between 1 and 200),
  service_interests jsonb not null default '[]' check (jsonb_typeof(service_interests) = 'array'),
  need_summary text check (length(need_summary) between 1 and 2000),
  summary_source text check (summary_source = 'SYNTHESIZED'),
  status text not null default 'NEW' check (status = 'NEW'),
  first_conversation_id uuid not null,
  last_conversation_id uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, subject_id),
  foreign key (tenant_id, subject_id) references public.lead_subjects(tenant_id, id) on delete restrict,
  foreign key (tenant_id, first_conversation_id) references public.conversations(tenant_id, id) on delete restrict,
  foreign key (tenant_id, last_conversation_id) references public.conversations(tenant_id, id) on delete restrict,
  check ((contact_name is null) = (name_source is null)),
  check ((need_summary is null) = (summary_source is null))
);
create index lead_prospects_recent_idx on public.lead_prospects(tenant_id, updated_at desc, id desc);
create index lead_prospects_first_conversation_idx on public.lead_prospects(tenant_id, first_conversation_id);
create index lead_prospects_last_conversation_idx on public.lead_prospects(tenant_id, last_conversation_id);

create table public.lead_capture_events (
  id uuid primary key,
  tenant_id uuid not null,
  prospect_id uuid,
  conversation_id uuid not null,
  inbound_message_id uuid not null,
  agent_instance_id uuid not null,
  agent_version_id uuid not null,
  operation text not null check (operation in ('CAPTURE', 'SUPPRESS', 'CONFLICT')),
  evidence jsonb not null check (jsonb_typeof(evidence) = 'array' and jsonb_array_length(evidence) between 1 and 5),
  changes jsonb not null default '{}' check (jsonb_typeof(changes) = 'object'),
  created_at timestamptz not null default now(),
  unique (tenant_id, inbound_message_id, operation),
  foreign key (tenant_id, prospect_id) references public.lead_prospects(tenant_id, id) on delete restrict,
  foreign key (tenant_id, conversation_id) references public.conversations(tenant_id, id) on delete restrict,
  foreign key (tenant_id, inbound_message_id) references public.messages(tenant_id, id) on delete restrict,
  foreign key (tenant_id, agent_instance_id, agent_version_id)
    references public.agent_spec_versions(tenant_id, agent_instance_id, id) on delete restrict
);
create index lead_capture_events_prospect_idx on public.lead_capture_events(tenant_id, prospect_id, created_at desc, id desc);
create index lead_capture_events_conversation_idx on public.lead_capture_events(tenant_id, conversation_id);
create index lead_capture_events_agent_idx on public.lead_capture_events(tenant_id, agent_instance_id, agent_version_id, created_at desc);

do $policies$
declare t text;
begin
  foreach t in array array['lead_subjects', 'lead_subject_keys', 'lead_prospects', 'lead_capture_events'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated, service_role, agents_factory_app, agents_factory_admin', t);
    execute format('grant select, insert on public.%I to agents_factory_app, agents_factory_admin', t);
    execute format('create policy %I on public.%I for select to agents_factory_app, agents_factory_admin using (tenant_id = nullif((select current_setting(''app.tenant_id'', true)), '''')::uuid)', t || '_read', t);
    execute format('create policy %I on public.%I for insert to agents_factory_app, agents_factory_admin with check (tenant_id = nullif((select current_setting(''app.tenant_id'', true)), '''')::uuid)', t || '_insert', t);
  end loop;
  foreach t in array array['lead_subjects', 'lead_prospects'] loop
    execute format('create policy %I on public.%I for update to agents_factory_app, agents_factory_admin using (tenant_id = nullif((select current_setting(''app.tenant_id'', true)), '''')::uuid) with check (tenant_id = nullif((select current_setting(''app.tenant_id'', true)), '''')::uuid)', t || '_update', t);
  end loop;
end
$policies$;

grant update (capture_suppressed, suppressed_at, suppression_message_id) on public.lead_subjects to agents_factory_app, agents_factory_admin;
grant update (contact_name, name_source, contact_username, declared_company, service_interests, need_summary, summary_source, last_conversation_id, updated_at) on public.lead_prospects to agents_factory_app, agents_factory_admin;
