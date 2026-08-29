create table public.knowledge_sources (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  name text not null check (
    name = btrim(name) and length(name) between 1 and 300
  ),
  source_type text not null check (
    source_type in (
      'WEBSITE', 'PDF', 'DOCX', 'GOOGLE_DRIVE', 'SPREADSHEET', 'MANUAL'
    )
  ),
  authority text not null check (
    authority in ('AUTHORITATIVE', 'SECONDARY', 'REFERENCE')
  ),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, id, authority)
);

create table public.knowledge_source_versions (
  id uuid primary key,
  tenant_id uuid not null,
  source_id uuid not null,
  version_number integer not null check (version_number > 0),
  authority text not null check (
    authority in ('AUTHORITATIVE', 'SECONDARY', 'REFERENCE')
  ),
  content_digest text not null check (content_digest ~ '^[0-9a-f]{64}$'),
  verified_at timestamptz not null,
  approved_by_admin_id uuid not null,
  locator jsonb not null default '{}'::jsonb check (
    jsonb_typeof(locator) = 'object'
  ),
  created_at timestamptz not null default now(),
  unique (tenant_id, source_id, id),
  unique (tenant_id, source_id, version_number),
  unique (tenant_id, source_id, content_digest),
  foreign key (tenant_id, source_id)
    references public.knowledge_sources(tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id, authority)
    references public.knowledge_sources(tenant_id, id, authority)
    on delete restrict
);

create table public.structured_facts (
  id uuid primary key,
  tenant_id uuid not null,
  source_id uuid not null,
  source_version_id uuid not null,
  key text not null check (
    key ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'
  ),
  kind text not null check (
    kind in (
      'BUSINESS_HOURS', 'LOCATION', 'SERVICE', 'PRICE', 'CONTACT',
      'BOOKING_RULE', 'APPROVAL_CONTACT'
    )
  ),
  value jsonb not null check (jsonb_typeof(value) = 'object'),
  content_digest text not null check (content_digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, source_version_id, key, content_digest),
  foreign key (tenant_id, source_id, source_version_id)
    references public.knowledge_source_versions(tenant_id, source_id, id)
    on delete restrict
);

create table public.knowledge_documents (
  id uuid primary key,
  tenant_id uuid not null,
  source_id uuid not null,
  source_version_id uuid not null,
  category text not null check (
    category in (
      'POLICY', 'MANUAL', 'FAQ', 'CATALOG_DESCRIPTION', 'PROCEDURE',
      'DOCUMENTATION'
    )
  ),
  title text not null check (
    title = btrim(title) and length(title) between 1 and 300
  ),
  document_text text not null check (
    length(document_text) between 1 and 2000000
  ),
  locator jsonb not null default '{}'::jsonb check (
    jsonb_typeof(locator) = 'object'
  ),
  content_digest text not null check (content_digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, source_version_id, content_digest),
  foreign key (tenant_id, source_id, source_version_id)
    references public.knowledge_source_versions(tenant_id, source_id, id)
    on delete restrict
);

create table public.knowledge_versions (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  name text not null check (
    name = btrim(name) and length(name) between 1 and 300
  ),
  version_number integer not null check (version_number > 0),
  state text not null check (state in ('DRAFT', 'TEST', 'PRODUCTION')),
  digest text check (digest is null or digest ~ '^[0-9a-f]{64}$'),
  based_on_version_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, version_number),
  foreign key (tenant_id, based_on_version_id)
    references public.knowledge_versions(tenant_id, id) on delete restrict,
  check (based_on_version_id is null or based_on_version_id <> id),
  check (
    (state = 'DRAFT' and digest is null)
    or (state <> 'DRAFT' and digest is not null)
  )
);

create table public.knowledge_version_members (
  id uuid primary key,
  tenant_id uuid not null,
  knowledge_version_id uuid not null,
  structured_fact_id uuid,
  document_id uuid,
  position integer not null check (position >= 0),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, knowledge_version_id, position),
  foreign key (tenant_id, knowledge_version_id)
    references public.knowledge_versions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, structured_fact_id)
    references public.structured_facts(tenant_id, id) on delete restrict,
  foreign key (tenant_id, document_id)
    references public.knowledge_documents(tenant_id, id) on delete restrict,
  check ((structured_fact_id is null) <> (document_id is null))
);

create unique index knowledge_version_members_fact_unique_idx
on public.knowledge_version_members (
  tenant_id, knowledge_version_id, structured_fact_id
)
where structured_fact_id is not null;

create unique index knowledge_version_members_document_unique_idx
on public.knowledge_version_members (tenant_id, knowledge_version_id, document_id)
where document_id is not null;

create index structured_facts_lookup_idx
on public.structured_facts (tenant_id, key, kind);

create index knowledge_documents_source_idx
on public.knowledge_documents (tenant_id, source_version_id);

create index knowledge_versions_state_idx
on public.knowledge_versions (tenant_id, state, version_number desc);

create function agents_factory_private.reject_knowledge_append_only_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $function$
begin
  raise exception 'Knowledge artifact history is append-only'
    using errcode = '55000';
end
$function$;

revoke all on function
agents_factory_private.reject_knowledge_append_only_mutation()
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

create trigger knowledge_source_versions_append_only
before update or delete or truncate on public.knowledge_source_versions
for each statement execute function
agents_factory_private.reject_knowledge_append_only_mutation();

create trigger structured_facts_append_only
before update or delete or truncate on public.structured_facts
for each statement execute function
agents_factory_private.reject_knowledge_append_only_mutation();

create trigger knowledge_documents_append_only
before update or delete or truncate on public.knowledge_documents
for each statement execute function
agents_factory_private.reject_knowledge_append_only_mutation();

create trigger knowledge_version_members_append_only
before update or delete or truncate on public.knowledge_version_members
for each statement execute function
agents_factory_private.reject_knowledge_append_only_mutation();

create function agents_factory_private.enforce_knowledge_version_lifecycle()
returns trigger
language plpgsql
set search_path = pg_catalog
as $function$
begin
  if tg_op = 'INSERT' then
    if new.state <> 'DRAFT' or new.digest is not null then
      raise exception 'Knowledge versions must begin as DRAFT'
        using errcode = '55000';
    end if;
    return new;
  end if;
  if tg_op = 'DELETE' then
    raise exception 'Knowledge version history is immutable'
      using errcode = '55000';
  end if;
  if row(
    new.id, new.tenant_id, new.name, new.version_number,
    new.based_on_version_id, new.created_at
  ) is distinct from row(
    old.id, old.tenant_id, old.name, old.version_number,
    old.based_on_version_id, old.created_at
  ) then
    raise exception 'Knowledge content changes require a new Draft'
      using errcode = '55000';
  end if;
  if old.state = 'DRAFT' and new.state = 'TEST'
    and old.digest is null and new.digest is not null then
    return new;
  end if;
  if row(new.state, new.digest) is distinct from row(old.state, old.digest) then
    raise exception 'Invalid or gated Knowledge lifecycle transition'
      using errcode = '55000';
  end if;
  return new;
end
$function$;

revoke all on function agents_factory_private.enforce_knowledge_version_lifecycle()
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

create trigger knowledge_versions_lifecycle_guard
before insert or update or delete on public.knowledge_versions
for each row execute function
agents_factory_private.enforce_knowledge_version_lifecycle();

create function agents_factory_private.enforce_draft_knowledge_membership()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $function$
begin
  if not exists (
    select 1 from public.knowledge_versions as version
    where version.tenant_id = new.tenant_id
      and version.id = new.knowledge_version_id
      and version.state = 'DRAFT'
  ) then
    raise exception 'Knowledge members may only be added to a Draft'
      using errcode = '55000';
  end if;
  return new;
end
$function$;

revoke all on function
agents_factory_private.enforce_draft_knowledge_membership()
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

create trigger knowledge_version_members_draft_only
before insert on public.knowledge_version_members
for each row execute function
agents_factory_private.enforce_draft_knowledge_membership();

alter table public.knowledge_sources enable row level security;
alter table public.knowledge_sources force row level security;
alter table public.knowledge_source_versions enable row level security;
alter table public.knowledge_source_versions force row level security;
alter table public.structured_facts enable row level security;
alter table public.structured_facts force row level security;
alter table public.knowledge_documents enable row level security;
alter table public.knowledge_documents force row level security;
alter table public.knowledge_versions enable row level security;
alter table public.knowledge_versions force row level security;
alter table public.knowledge_version_members enable row level security;
alter table public.knowledge_version_members force row level security;

create policy knowledge_sources_app_select
on public.knowledge_sources for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_sources_admin_select
on public.knowledge_sources for select to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_sources_admin_insert
on public.knowledge_sources for insert to agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy knowledge_source_versions_app_select
on public.knowledge_source_versions for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_source_versions_admin_select
on public.knowledge_source_versions for select to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_source_versions_admin_insert
on public.knowledge_source_versions for insert to agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy structured_facts_app_select
on public.structured_facts for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy structured_facts_admin_select
on public.structured_facts for select to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy structured_facts_admin_insert
on public.structured_facts for insert to agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy knowledge_documents_app_select
on public.knowledge_documents for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_documents_admin_select
on public.knowledge_documents for select to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_documents_admin_insert
on public.knowledge_documents for insert to agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy knowledge_versions_app_select
on public.knowledge_versions for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_versions_admin_select
on public.knowledge_versions for select to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_versions_admin_insert
on public.knowledge_versions for insert to agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_versions_admin_update
on public.knowledge_versions for update to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy knowledge_version_members_app_select
on public.knowledge_version_members for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_version_members_admin_select
on public.knowledge_version_members for select to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_version_members_admin_insert
on public.knowledge_version_members for insert to agents_factory_admin
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

revoke all on table public.knowledge_sources,
  public.knowledge_source_versions, public.structured_facts,
  public.knowledge_documents, public.knowledge_versions,
  public.knowledge_version_members
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;

grant select on table public.knowledge_sources,
  public.knowledge_source_versions, public.structured_facts,
  public.knowledge_documents, public.knowledge_versions,
  public.knowledge_version_members
to agents_factory_app;

grant select, insert on table public.knowledge_sources,
  public.knowledge_source_versions, public.structured_facts,
  public.knowledge_documents, public.knowledge_version_members
to agents_factory_admin;

grant select, insert, update on table public.knowledge_versions
to agents_factory_admin;
