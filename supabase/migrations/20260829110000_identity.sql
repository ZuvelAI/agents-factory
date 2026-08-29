create table public.identity_subjects (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  customer_ref text not null check (
    customer_ref = btrim(customer_ref)
    and length(customer_ref) between 1 and 300
  ),
  whatsapp_recognized_at timestamptz,
  created_at timestamptz not null default now(),
  unique (tenant_id, customer_ref),
  unique (tenant_id, id)
);

create table public.identity_challenges (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  customer_ref text not null check (
    customer_ref = btrim(customer_ref)
    and length(customer_ref) between 1 and 300
  ),
  required_level smallint not null check (required_level in (2, 3)),
  method text not null check (
    method in ('ADDITIONAL_VERIFICATION', 'OTP', 'EXTERNAL_AUTH')
  ),
  secret_digest text check (
    secret_digest is null or secret_digest ~ '^[0-9a-f]{64}$'
  ),
  status text not null check (
    status in ('PENDING', 'PASSED', 'FAILED', 'EXPIRED', 'LOCKED')
  ),
  attempts smallint not null default 0 check (attempts >= 0),
  max_attempts smallint not null check (max_attempts between 1 and 10),
  bound_action_ref text check (
    bound_action_ref is null or (
      bound_action_ref = btrim(bound_action_ref)
      and length(bound_action_ref) between 1 and 300
    )
  ),
  expires_at timestamptz not null,
  created_at timestamptz not null,
  completed_at timestamptz,
  check (expires_at > created_at),
  check (
    (required_level = 2 and method = 'ADDITIONAL_VERIFICATION'
      and secret_digest is not null and bound_action_ref is null)
    or
    (required_level = 3 and method = 'OTP'
      and secret_digest is not null and bound_action_ref is not null)
    or
    (required_level = 3 and method = 'EXTERNAL_AUTH'
      and secret_digest is null and bound_action_ref is not null)
  ),
  check (
    (status = 'PENDING' and completed_at is null and attempts < max_attempts)
    or (status <> 'PENDING' and completed_at is not null)
  ),
  unique (tenant_id, id)
);

create table public.identity_evidence (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  customer_ref text not null check (
    customer_ref = btrim(customer_ref)
    and length(customer_ref) between 1 and 300
  ),
  method text not null check (
    method in (
      'WHATSAPP_RECOGNITION',
      'ADDITIONAL_VERIFICATION',
      'OTP',
      'EXTERNAL_AUTH'
    )
  ),
  result text not null check (result in ('VERIFIED', 'FAILED')),
  achieved_level smallint not null check (achieved_level between 0 and 3),
  scope text not null check (scope in ('SESSION', 'ACTION')),
  bound_action_ref text check (
    bound_action_ref is null or (
      bound_action_ref = btrim(bound_action_ref)
      and length(bound_action_ref) between 1 and 300
    )
  ),
  evidence_ref_digest text not null check (
    evidence_ref_digest ~ '^[0-9a-f]{64}$'
  ),
  verified_at timestamptz not null,
  expires_at timestamptz not null,
  consumed_at timestamptz,
  created_at timestamptz not null default now(),
  check (expires_at >= verified_at),
  check (
    (scope = 'SESSION' and bound_action_ref is null and consumed_at is null)
    or (scope = 'ACTION' and bound_action_ref is not null)
  ),
  check (
    (result = 'FAILED' and achieved_level = 0)
    or (result = 'VERIFIED' and achieved_level between 1 and 3)
  )
);

create index identity_challenges_pending_idx
on public.identity_challenges (tenant_id, customer_ref, expires_at)
where status = 'PENDING';

create index identity_evidence_assessment_idx
on public.identity_evidence (
  tenant_id, customer_ref, achieved_level desc, expires_at desc
)
where result = 'VERIFIED' and consumed_at is null;

create function agents_factory_private.enforce_identity_evidence_immutability()
returns trigger
language plpgsql
set search_path = pg_catalog
as $function$
begin
  if tg_op = 'DELETE' then
    raise exception 'Identity evidence is immutable'
      using errcode = '55000';
  end if;
  if old.scope <> 'ACTION'
    or old.consumed_at is not null
    or new.consumed_at is null
    or row(
      new.id, new.tenant_id, new.customer_ref, new.method, new.result,
      new.achieved_level, new.scope, new.bound_action_ref,
      new.evidence_ref_digest, new.verified_at, new.expires_at, new.created_at
    ) is distinct from row(
      old.id, old.tenant_id, old.customer_ref, old.method, old.result,
      old.achieved_level, old.scope, old.bound_action_ref,
      old.evidence_ref_digest, old.verified_at, old.expires_at, old.created_at
    ) then
    raise exception 'Identity evidence may only be consumed once'
      using errcode = '55000';
  end if;
  return new;
end
$function$;

create trigger identity_evidence_immutable
before update or delete on public.identity_evidence
for each row execute function
agents_factory_private.enforce_identity_evidence_immutability();

alter table public.identity_subjects enable row level security;
alter table public.identity_subjects force row level security;
alter table public.identity_challenges enable row level security;
alter table public.identity_challenges force row level security;
alter table public.identity_evidence enable row level security;
alter table public.identity_evidence force row level security;

create policy identity_subjects_app_select
on public.identity_subjects for select to agents_factory_app
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy identity_subjects_app_insert
on public.identity_subjects for insert to agents_factory_app
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy identity_subjects_app_update
on public.identity_subjects for update to agents_factory_app
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
)
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy identity_subjects_admin_all
on public.identity_subjects for all to agents_factory_admin
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
)
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);

create policy identity_challenges_app_select
on public.identity_challenges for select to agents_factory_app
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy identity_challenges_app_insert
on public.identity_challenges for insert to agents_factory_app
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy identity_challenges_app_update
on public.identity_challenges for update to agents_factory_app
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
)
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy identity_challenges_admin_all
on public.identity_challenges for all to agents_factory_admin
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
)
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);

create policy identity_evidence_app_select
on public.identity_evidence for select to agents_factory_app
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy identity_evidence_app_insert
on public.identity_evidence for insert to agents_factory_app
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy identity_evidence_app_update
on public.identity_evidence for update to agents_factory_app
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
)
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);
create policy identity_evidence_admin_all
on public.identity_evidence for all to agents_factory_admin
using (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
)
with check (
  tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid
);

revoke all on table public.identity_subjects, public.identity_challenges,
  public.identity_evidence from public, anon, authenticated, service_role,
  agents_factory_app, agents_factory_admin;

grant select, insert, update on table public.identity_subjects,
  public.identity_challenges, public.identity_evidence
to agents_factory_app, agents_factory_admin;
