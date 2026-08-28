alter table public.messages
add column in_reply_to_message_id uuid,
add column agent_spec_id uuid,
add column agent_spec_version text check (
  agent_spec_version is null
  or (
    agent_spec_version = btrim(agent_spec_version)
    and length(agent_spec_version) between 1 and 100
  )
),
add column runtime_metadata jsonb not null default '{}'::jsonb check (
  jsonb_typeof(runtime_metadata) = 'object'
),
add constraint messages_in_reply_to_message_fkey
  foreign key (tenant_id, in_reply_to_message_id)
  references public.messages(tenant_id, id) on delete restrict,
add constraint messages_tenant_reply_key
  unique (tenant_id, in_reply_to_message_id),
add constraint messages_runtime_reply_shape_check check (
  in_reply_to_message_id is null
  or (
    direction = 'outbound'
    and sender_type = 'ai'
    and message_type = 'text'
    and agent_spec_id is not null
    and agent_spec_version is not null
  )
);

create index messages_in_reply_to_idx
on public.messages (tenant_id, in_reply_to_message_id)
where in_reply_to_message_id is not null;
