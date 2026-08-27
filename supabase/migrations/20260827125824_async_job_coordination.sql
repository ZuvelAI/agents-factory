alter table public.outbox_jobs
drop constraint outbox_jobs_status_check;

alter table public.outbox_jobs
add constraint outbox_jobs_status_check check (
  status in (
    'pending', 'dispatching', 'queued', 'processing', 'succeeded', 'failed',
    'dead_letter'
  )
);

alter table public.outbox_jobs
add column dispatch_lease_id uuid,
add column dispatch_lease_expires_at timestamptz,
add column dispatched_at timestamptz,
add column attempt_count integer not null default 0,
add column max_attempts integer not null default 5,
add column last_error_code text,
add column completed_at timestamptz,
add constraint outbox_jobs_dispatch_lease_pair_check check (
  (dispatch_lease_id is null) = (dispatch_lease_expires_at is null)
),
add constraint outbox_jobs_attempt_count_check check (
  attempt_count >= 0 and attempt_count <= max_attempts
),
add constraint outbox_jobs_max_attempts_check check (
  max_attempts between 1 and 100
),
add constraint outbox_jobs_last_error_code_check check (
  last_error_code is null
  or (
    last_error_code = btrim(last_error_code)
    and length(last_error_code) between 1 and 200
  )
);

drop index public.outbox_jobs_pending_due_idx;

create index outbox_jobs_dispatchable_idx
on public.outbox_jobs (available_at, created_at, id)
where status in ('pending', 'failed', 'dispatching');
