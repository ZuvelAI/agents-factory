create table public.whatsapp_templates (
  id uuid primary key,
  tenant_id uuid not null,
  whatsapp_account_id uuid not null,
  provider_template_id text not null check (
    provider_template_id = btrim(provider_template_id)
    and length(provider_template_id) between 1 and 200
  ),
  name text not null check (
    name = btrim(name) and length(name) between 1 and 512
  ),
  language text not null check (
    language = btrim(language) and length(language) between 2 and 35
  ),
  status text not null check (
    status in ('APPROVED', 'PENDING', 'REJECTED', 'PAUSED', 'DISABLED')
  ),
  category text not null check (
    category in ('UTILITY', 'MARKETING', 'AUTHENTICATION')
  ),
  variable_names jsonb not null default '[]'::jsonb check (
    jsonb_typeof(variable_names) = 'array'
  ),
  synced_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint whatsapp_templates_account_fkey
    foreign key (tenant_id, whatsapp_account_id)
    references public.whatsapp_accounts(tenant_id, id) on delete restrict,
  constraint whatsapp_templates_tenant_id_id_key unique (tenant_id, id),
  constraint whatsapp_templates_provider_id_key
    unique (tenant_id, whatsapp_account_id, provider_template_id),
  constraint whatsapp_templates_name_language_key
    unique (tenant_id, whatsapp_account_id, name, language)
);

create table public.outbound_messages (
  id uuid primary key,
  tenant_id uuid not null,
  conversation_id uuid,
  source_message_id uuid,
  whatsapp_account_id uuid not null,
  whatsapp_template_id uuid,
  recipient_wa_id text not null check (
    recipient_wa_id = btrim(recipient_wa_id)
    and length(recipient_wa_id) between 1 and 100
  ),
  kind text not null check (kind in ('text', 'template')),
  idempotency_key text not null check (
    idempotency_key = btrim(idempotency_key)
    and length(idempotency_key) between 1 and 500
  ),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  status text not null default 'PREPARED' check (
    status in (
      'PREPARED', 'SENDING', 'ACCEPTED', 'SENT', 'DELIVERED', 'READ',
      'FAILED', 'UNCERTAIN', 'BLOCKED'
    )
  ),
  provider_message_id text check (
    provider_message_id is null
    or (
      provider_message_id = btrim(provider_message_id)
      and length(provider_message_id) between 1 and 500
    )
  ),
  provider_error_code text check (
    provider_error_code is null
    or (
      provider_error_code = btrim(provider_error_code)
      and length(provider_error_code) between 1 and 200
    )
  ),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  status_history jsonb not null default '[]'::jsonb check (
    jsonb_typeof(status_history) = 'array'
  ),
  cost_attribution jsonb not null default '{}'::jsonb check (
    jsonb_typeof(cost_attribution) = 'object'
  ),
  last_attempt_at timestamptz,
  accepted_at timestamptz,
  delivered_at timestamptz,
  read_at timestamptz,
  failed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint outbound_messages_tenant_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict,
  constraint outbound_messages_account_fkey
    foreign key (tenant_id, whatsapp_account_id)
    references public.whatsapp_accounts(tenant_id, id) on delete restrict,
  constraint outbound_messages_conversation_fkey
    foreign key (tenant_id, conversation_id)
    references public.conversations(tenant_id, id) on delete restrict,
  constraint outbound_messages_source_message_fkey
    foreign key (tenant_id, source_message_id)
    references public.messages(tenant_id, id) on delete restrict,
  constraint outbound_messages_template_fkey
    foreign key (tenant_id, whatsapp_template_id)
    references public.whatsapp_templates(tenant_id, id) on delete restrict,
  constraint outbound_messages_tenant_id_id_key unique (tenant_id, id),
  constraint outbound_messages_idempotency_key
    unique (tenant_id, idempotency_key),
  constraint outbound_messages_source_message_key
    unique (tenant_id, source_message_id),
  constraint outbound_messages_provider_message_key
    unique (tenant_id, provider_message_id),
  constraint outbound_messages_kind_shape_check check (
    (
      kind = 'text'
      and conversation_id is not null
      and source_message_id is not null
      and whatsapp_template_id is null
    )
    or (
      kind = 'template'
      and source_message_id is null
      and whatsapp_template_id is not null
    )
  )
);

create index whatsapp_templates_lookup_idx
on public.whatsapp_templates (
  tenant_id, whatsapp_account_id, name, language, status
);

create index outbound_messages_conversation_idx
on public.outbound_messages (tenant_id, conversation_id, created_at);

create index outbound_messages_status_idx
on public.outbound_messages (tenant_id, status, updated_at);

alter table public.whatsapp_templates enable row level security;
alter table public.whatsapp_templates force row level security;
alter table public.outbound_messages enable row level security;
alter table public.outbound_messages force row level security;

revoke all on table public.whatsapp_templates
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

revoke all on table public.outbound_messages
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

create policy whatsapp_templates_app_select
on public.whatsapp_templates for select
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy whatsapp_templates_app_insert
on public.whatsapp_templates for insert
to agents_factory_app
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy whatsapp_templates_app_update
on public.whatsapp_templates for update
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
)
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy whatsapp_templates_admin_select
on public.whatsapp_templates for select
to agents_factory_admin
using (true);

create policy whatsapp_templates_admin_insert
on public.whatsapp_templates for insert
to agents_factory_admin
with check (true);

create policy whatsapp_templates_admin_update
on public.whatsapp_templates for update
to agents_factory_admin
using (true)
with check (true);

create policy outbound_messages_app_select
on public.outbound_messages for select
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy outbound_messages_app_insert
on public.outbound_messages for insert
to agents_factory_app
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy outbound_messages_app_update
on public.outbound_messages for update
to agents_factory_app
using (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
)
with check (
  tenant_id = nullif(
    (select current_setting('app.tenant_id', true)),
    ''
  )::uuid
);

create policy outbound_messages_admin_select
on public.outbound_messages for select
to agents_factory_admin
using (true);

create policy outbound_messages_admin_insert
on public.outbound_messages for insert
to agents_factory_admin
with check (true);

create policy outbound_messages_admin_update
on public.outbound_messages for update
to agents_factory_admin
using (true)
with check (true);

grant select, insert, update on table public.whatsapp_templates
to agents_factory_app, agents_factory_admin;

grant select, insert, update on table public.outbound_messages
to agents_factory_app, agents_factory_admin;
