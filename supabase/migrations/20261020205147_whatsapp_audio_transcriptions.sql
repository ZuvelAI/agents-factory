create table public.whatsapp_audio_transcriptions (
  id uuid primary key,
  tenant_id uuid not null,
  inbound_message_id uuid not null,
  conversation_id uuid not null,
  whatsapp_account_id uuid not null,
  source_event_id uuid not null,
  media_id text not null check (media_id ~ '^[0-9]{1,200}$'),
  mime_type text not null check (length(mime_type) between 1 and 100),
  expected_sha256 text check (expected_sha256 ~ '^[0-9a-f]{64}$'),
  status text not null default 'QUEUED' check (status in ('QUEUED','PROCESSING','READY','FAILED','CANCELLED','UNCERTAIN')),
  phase text not null default 'PREFLIGHT' check (phase in ('PREFLIGHT','PROVIDER_STARTED')),
  lease_id uuid,
  owner_id uuid,
  lease_expires_at timestamptz,
  first_claim_at timestamptz,
  deadline timestamptz,
  attempt_count integer not null default 0 check (attempt_count between 0 and 100),
  download_attempts integer not null default 0 check (download_attempts between 0 and 2),
  transcript text check (length(btrim(transcript)) between 1 and 25000),
  transcript_digest text check (transcript_digest ~ '^[0-9a-f]{64}$'),
  model text check (model = 'gpt-4o-mini-transcribe-2025-12-15'),
  usage jsonb check (jsonb_typeof(usage)='object'),
  duration_seconds double precision check (duration_seconds > 0 and duration_seconds <= 300),
  size_bytes integer check (size_bytes between 1 and 10000000),
  actual_sha256 text check (actual_sha256 ~ '^[0-9a-f]{64}$'),
  error_code text check (error_code ~ '^[a-z][a-z0-9_]{0,99}$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id,id),
  unique (tenant_id,inbound_message_id),
  foreign key (tenant_id,inbound_message_id) references public.messages(tenant_id,id) on delete restrict,
  foreign key (tenant_id,conversation_id) references public.conversations(tenant_id,id) on delete restrict,
  foreign key (tenant_id,whatsapp_account_id) references public.whatsapp_accounts(tenant_id,id) on delete restrict,
  foreign key (tenant_id,source_event_id) references public.whatsapp_webhook_events(tenant_id,id) on delete restrict,
  check ((lease_id is null)=(owner_id is null) and (lease_id is null)=(lease_expires_at is null)),
  check ((first_claim_at is null)=(deadline is null)),
  check (deadline is null or (deadline=first_claim_at+interval '120 seconds' and lease_expires_at<=deadline)),
  check ((status='PROCESSING')=(lease_id is not null)),
  check ((status='READY')=(transcript is not null and transcript_digest is not null and model is not null)),
  check (status='READY' or (transcript is null and transcript_digest is null and model is null and usage is null))
);
create index whatsapp_audio_pending_idx on public.whatsapp_audio_transcriptions(tenant_id,conversation_id,created_at)
where status in ('QUEUED','PROCESSING');

alter table public.whatsapp_audio_transcriptions enable row level security;
alter table public.whatsapp_audio_transcriptions force row level security;
revoke all on public.whatsapp_audio_transcriptions from public,anon,authenticated,service_role,agents_factory_app,agents_factory_admin;
grant select on public.whatsapp_audio_transcriptions to agents_factory_app,agents_factory_admin;
grant insert on public.whatsapp_audio_transcriptions to agents_factory_app;
grant update (status,phase,lease_id,owner_id,lease_expires_at,first_claim_at,deadline,attempt_count,
download_attempts,transcript,transcript_digest,model,usage,duration_seconds,size_bytes,actual_sha256,error_code,updated_at)
on public.whatsapp_audio_transcriptions to agents_factory_app;
create policy audio_read on public.whatsapp_audio_transcriptions for select to agents_factory_app,agents_factory_admin
using (tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy audio_insert on public.whatsapp_audio_transcriptions for insert to agents_factory_app
with check (tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);
create policy audio_update on public.whatsapp_audio_transcriptions for update to agents_factory_app
using (tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid)
with check (tenant_id=nullif((select current_setting('app.tenant_id',true)),'')::uuid);

create function agents_factory_private.guard_audio_transcription_update() returns trigger
language plpgsql set search_path='' as $body$
begin
  if tg_op='INSERT' then
    if new.status<>'QUEUED' or new.phase<>'PREFLIGHT' or new.lease_id is not null
      or new.first_claim_at is not null or new.attempt_count<>0 or new.download_attempts<>0 or new.error_code is not null then
      raise exception 'audio must start queued' using errcode='55000';
    end if;
    return new;
  end if;
  if old.status in ('READY','FAILED','CANCELLED','UNCERTAIN') then
    raise exception 'audio terminal state is immutable' using errcode='55000';
  end if;
  if new.download_attempts<>old.download_attempts and
    (new.download_attempts<>old.download_attempts+1 or old.status<>'PROCESSING' or old.phase<>'PREFLIGHT' or new.phase<>'PREFLIGHT') then
    raise exception 'audio download budget cannot be reset' using errcode='55000';
  end if;
  if (new.id,new.tenant_id,new.inbound_message_id,new.conversation_id,new.whatsapp_account_id,
      new.source_event_id,new.media_id,new.mime_type,new.expected_sha256,new.created_at)
    is distinct from
     (old.id,old.tenant_id,old.inbound_message_id,old.conversation_id,old.whatsapp_account_id,
      old.source_event_id,old.media_id,old.mime_type,old.expected_sha256,old.created_at) then
    raise exception 'audio source is immutable' using errcode='55000';
  end if;
  if old.first_claim_at is not null and (new.first_claim_at,new.deadline) is distinct from (old.first_claim_at,old.deadline) then
    raise exception 'audio deadline is immutable' using errcode='55000';
  end if;
  if old.phase='PROVIDER_STARTED' and new.phase<>'PROVIDER_STARTED' then
    raise exception 'audio provider phase cannot be reset' using errcode='55000';
  end if;
  if new.phase='PROVIDER_STARTED' and old.phase='PREFLIGHT' and old.status<>'PROCESSING' then
    raise exception 'audio provider requires an active claim' using errcode='55000';
  end if;
  if new.status='READY' and (old.status<>'PROCESSING' or old.phase<>'PROVIDER_STARTED') then
    raise exception 'audio ready requires provider work' using errcode='55000';
  end if;
  return new;
end
$body$;
revoke all on function agents_factory_private.guard_audio_transcription_update() from public,anon,authenticated,service_role;
create trigger audio_update_guard before insert or update on public.whatsapp_audio_transcriptions
for each row execute function agents_factory_private.guard_audio_transcription_update();
