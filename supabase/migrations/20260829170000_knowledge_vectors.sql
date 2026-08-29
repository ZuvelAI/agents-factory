create extension if not exists vector with schema extensions;

grant usage on schema extensions to agents_factory_app, agents_factory_admin;

create table public.knowledge_chunks (
  id uuid primary key,
  tenant_id uuid not null,
  knowledge_version_id uuid not null,
  document_id uuid not null,
  source_id uuid not null,
  source_version_id uuid not null,
  authority text not null check (
    authority in ('AUTHORITATIVE', 'SECONDARY', 'REFERENCE')
  ),
  chunk_index integer not null check (chunk_index >= 0),
  chunk_text text not null check (
    length(chunk_text) between 1 and 4000
  ),
  content_digest text not null check (content_digest ~ '^[0-9a-f]{64}$'),
  locale text not null check (locale ~ '^[a-z]{2}(-[A-Z]{2})?$'),
  locator jsonb not null check (jsonb_typeof(locator) = 'object'),
  embedding extensions.vector(1536) not null,
  embedding_model text not null check (
    embedding_model = btrim(embedding_model)
    and length(embedding_model) between 1 and 200
  ),
  embedding_version text not null check (
    embedding_version = btrim(embedding_version)
    and length(embedding_version) between 1 and 100
  ),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (
    tenant_id, knowledge_version_id, document_id, chunk_index,
    embedding_model, embedding_version
  ),
  foreign key (tenant_id, knowledge_version_id)
    references public.knowledge_versions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, document_id)
    references public.knowledge_documents(tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id, source_version_id)
    references public.knowledge_source_versions(tenant_id, source_id, id)
    on delete restrict
);

create index knowledge_chunks_version_idx
on public.knowledge_chunks (
  tenant_id, knowledge_version_id, embedding_model, embedding_version
);

create index knowledge_chunks_embedding_hnsw_idx
on public.knowledge_chunks
using hnsw (embedding extensions.vector_cosine_ops);

create trigger knowledge_chunks_append_only
before update or delete or truncate on public.knowledge_chunks
for each statement execute function
agents_factory_private.reject_knowledge_append_only_mutation();

create function agents_factory_private.append_knowledge_chunk(
  p_id uuid,
  p_tenant_id uuid,
  p_knowledge_version_id uuid,
  p_document_id uuid,
  p_chunk_index integer,
  p_chunk_text text,
  p_content_digest text,
  p_locale text,
  p_locator jsonb,
  p_embedding text,
  p_embedding_model text,
  p_embedding_version text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_tenant_id uuid;
  v_chunk_id uuid;
begin
  v_tenant_id := nullif(current_setting('app.tenant_id', true), '')::uuid;
  if v_tenant_id is null or v_tenant_id <> p_tenant_id then
    raise exception 'tenant context is required' using errcode = '42501';
  end if;
  if not exists (
    select 1
    from public.knowledge_versions as version
    join public.knowledge_version_members as member
      on member.tenant_id = version.tenant_id
      and member.knowledge_version_id = version.id
      and member.document_id = p_document_id
    where version.tenant_id = v_tenant_id
      and version.id = p_knowledge_version_id
      and version.state = 'DRAFT'
  ) then
    raise exception 'Knowledge chunk requires a Draft version document member'
      using errcode = '23503';
  end if;

  insert into public.knowledge_chunks (
    id, tenant_id, knowledge_version_id, document_id, source_id,
    source_version_id, authority, chunk_index, chunk_text, content_digest,
    locale, locator, embedding, embedding_model, embedding_version
  )
  select
    p_id, v_tenant_id, p_knowledge_version_id, document.id,
    document.source_id, document.source_version_id, source.authority,
    p_chunk_index, p_chunk_text, p_content_digest, p_locale, p_locator,
    p_embedding::extensions.vector, p_embedding_model, p_embedding_version
  from public.knowledge_documents as document
  join public.knowledge_source_versions as source
    on source.tenant_id = document.tenant_id
    and source.id = document.source_version_id
  where document.tenant_id = v_tenant_id
    and document.id = p_document_id
  on conflict (
    tenant_id, knowledge_version_id, document_id, chunk_index,
    embedding_model, embedding_version
  ) do nothing
  returning id into v_chunk_id;

  if v_chunk_id is null then
    select chunk.id into v_chunk_id
    from public.knowledge_chunks as chunk
    where chunk.tenant_id = v_tenant_id
      and chunk.knowledge_version_id = p_knowledge_version_id
      and chunk.document_id = p_document_id
      and chunk.chunk_index = p_chunk_index
      and chunk.embedding_model = p_embedding_model
      and chunk.embedding_version = p_embedding_version;
  end if;
  return v_chunk_id;
end
$function$;

revoke all on function agents_factory_private.append_knowledge_chunk(
  uuid, uuid, uuid, uuid, integer, text, text, text, jsonb, text, text, text
)
from public, anon, authenticated, service_role, agents_factory_admin;

grant execute on function agents_factory_private.append_knowledge_chunk(
  uuid, uuid, uuid, uuid, integer, text, text, text, jsonb, text, text, text
)
to agents_factory_app;

alter table public.knowledge_chunks enable row level security;
alter table public.knowledge_chunks force row level security;

create policy knowledge_chunks_app_select
on public.knowledge_chunks for select to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);
create policy knowledge_chunks_admin_select
on public.knowledge_chunks for select to agents_factory_admin
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

revoke all on table public.knowledge_chunks
from public, anon, authenticated, service_role, agents_factory_app,
  agents_factory_admin;
grant select on table public.knowledge_chunks
to agents_factory_app, agents_factory_admin;
