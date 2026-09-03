create table public.conversation_reviews (
  id uuid primary key,
  tenant_id uuid not null,
  conversation_id uuid not null,
  revision integer not null default 1 check (revision > 0),
  categories text[] not null default '{}',
  labels text[] not null default '{}',
  note text,
  reviewed_by_admin_id uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint conversation_reviews_conversation_fkey
    foreign key (tenant_id, conversation_id)
    references public.conversations(tenant_id, id) on delete restrict,
  constraint conversation_reviews_tenant_conversation_key
    unique (tenant_id, conversation_id),
  constraint conversation_reviews_categories_check check (
    categories <@ array[
      'AI_RESOLVED','HUMAN_HANDOFF','TOOL_FAILURE','POLICY_VIOLATION',
      'COMPLAINT','HIGH_COST','FLAGGED'
    ]::text[]
  ),
  constraint conversation_reviews_labels_check check (
    labels <@ array[
      'CORRECT','INCORRECT','UNSAFE','KNOWLEDGE_PROBLEM',
      'INTEGRATION_PROBLEM','MODEL_REASONING_PROBLEM'
    ]::text[]
  ),
  constraint conversation_reviews_note_check check (
    note is null or (note = btrim(note) and length(note) between 1 and 2000)
  )
);

create table public.eval_case_drafts (
  id uuid primary key,
  tenant_id uuid not null,
  conversation_id uuid not null,
  case_id text not null check (case_id ~ '^[a-z0-9][a-z0-9._-]{2,99}$'),
  schema_version integer not null check (schema_version = 1),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  status text not null default 'DRAFT' check (status = 'DRAFT'),
  created_by_admin_id uuid not null,
  created_at timestamptz not null default now(),
  constraint eval_case_drafts_conversation_fkey
    foreign key (tenant_id, conversation_id)
    references public.conversations(tenant_id, id) on delete restrict,
  constraint eval_case_drafts_tenant_case_key unique (tenant_id, case_id),
  constraint eval_case_drafts_tenant_id_id_key unique (tenant_id, id)
);

create index conversation_reviews_categories_idx
on public.conversation_reviews using gin (categories);
create index conversation_reviews_labels_idx
on public.conversation_reviews using gin (labels);
create index eval_case_drafts_page_idx
on public.eval_case_drafts (tenant_id, created_at desc, id desc);

alter table public.conversation_reviews enable row level security;
alter table public.conversation_reviews force row level security;
alter table public.eval_case_drafts enable row level security;
alter table public.eval_case_drafts force row level security;

revoke all on public.conversation_reviews, public.eval_case_drafts
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;
grant select, insert, update on public.conversation_reviews
to agents_factory_admin;
grant select, insert on public.eval_case_drafts to agents_factory_admin;

create policy conversation_reviews_admin_select
on public.conversation_reviews for select to agents_factory_admin
using (
  tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
);
create policy conversation_reviews_admin_insert
on public.conversation_reviews for insert to agents_factory_admin
with check (
  tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
);
create policy conversation_reviews_admin_update
on public.conversation_reviews for update to agents_factory_admin
using (
  tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
)
with check (
  tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
);
create policy eval_case_drafts_admin_select
on public.eval_case_drafts for select to agents_factory_admin
using (
  tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
);
create policy eval_case_drafts_admin_insert
on public.eval_case_drafts for insert to agents_factory_admin
with check (
  tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
);

create trigger eval_case_drafts_immutable
before update or delete on public.eval_case_drafts
for each row execute function
  agents_factory_private.reject_agent_spec_deployment_mutation();
