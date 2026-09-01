alter table public.media_evidence
add column stored_at timestamptz;

update public.media_evidence
set stored_at = created_at
where byte_size > 0 and stored_at is null;

alter table public.media_evidence
add constraint media_evidence_storage_measurement_check check (
  (byte_size = 0 and stored_at is null)
  or (byte_size > 0 and stored_at is not null and stored_at >= created_at)
) not valid;

alter table public.media_evidence
validate constraint media_evidence_storage_measurement_check;

alter table public.knowledge_ingestions
add column byte_size integer not null default 0,
add column stored_at timestamptz;

alter table public.knowledge_ingestions
add constraint knowledge_ingestions_byte_size_check check (
  byte_size between 0 and 20971520
) not valid;

alter table public.knowledge_ingestions
validate constraint knowledge_ingestions_byte_size_check;

alter table public.knowledge_ingestions
add constraint knowledge_ingestions_storage_measurement_check check (
  (byte_size = 0 and stored_at is null)
  or (byte_size > 0 and stored_at is not null and stored_at >= created_at)
) not valid;

alter table public.knowledge_ingestions
validate constraint knowledge_ingestions_storage_measurement_check;

create index usage_media_storage_allocation_idx
on public.media_evidence (tenant_id, stored_at, deleted_at)
where stored_at is not null;

create index usage_knowledge_storage_allocation_idx
on public.knowledge_ingestions (tenant_id, stored_at)
where stored_at is not null;
