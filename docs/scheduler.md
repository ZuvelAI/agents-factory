# Lifecycle scheduler and retention — Task 35

## Scheduling

The scheduler scans at startup and once a minute. Tenant discovery uses bounded
pages; each tenant scan holds a short advisory transaction lock. One tenant's
failure does not prevent the remaining page from progressing. The durable outbox
continues to own dispatch, claims, retries and dead-letter handling.

The scan recovers missing due intents, with deterministic keys, for:

- One configurable appointment reminder, with attendance confirmation and the
  rescheduling option in the same approved template. Time subtraction uses UTC
  elapsed time, including daylight-saving boundaries.
- Resolved-case closure after the configured silence window (72 hours by default),
  and approaching/overdue Response Target events. These are internal events, not
  periodic customer reminders and not a new SLA.
- Expired Action confirmations and pending approval requests.
- Human handoff inactivity, using its configuration snapshot (12 hours by default)
  and the latest human/customer activity.
- Retention cleanup, only when a maintenance service is explicitly configured.

Each handler reloads the tenant-bound durable job and current domain state before
acting. A superseded appointment revision cannot notify. Changing reminder timing
can defer an existing job or recover an earlier deadline; all such locators share
one canonical outbound key. A reminder is skipped after its appointment begins or
when the conversation lacks AI authority. Existing approved-template and outbound
delivery controls remain in effect.

New scheduling intents are audited without message content. Domain transitions
have their own existing audit records. Replays do not repeat state changes or
customer sends. There is no periodic “still pending” WhatsApp notification for
`PENDING_APPROVAL` cases. Dead-letter jobs retain their existing operational
redrive policy; the scanner does not erase or blindly resurrect them.

## Expiry without provider credentials

`LifecycleJobs` registers `actions.expire`, `approvals.expire` and
`handoffs.inactivity` independently of a configured approval mailer/proof key or
live handoff adapter. Approval expiry shares the review service's close operation:
it closes the request, invalidates links, clears OTP evidence, expires the waiting
Action and queues one structured result. External execution is never attempted.

The result waits durably if the existing notification coordinator is not configured.
This does not enable approval creation, email delivery, business execution or live
handoff without their explicit trusted dependencies.

## Retention policy and isolation

`RetentionPolicy` defaults match master specification §42: conversation content
90 days, detailed traces 30 days, and Action/audit history 12 calendar months.
An authenticated platform administrator can configure tenant-specific values
through the backend `RetentionService.configure` port with revision checking.
There is no additional public retention endpoint or UI in this task.

The new `retention_policies` table has FORCE RLS. A separate
`agents_factory_retention` role is NOLOGIN, non-superuser and NOBYPASSRLS. Ordinary
app/admin roles are not members. It has tenant-scoped reads and narrowly restricted
content updates/aged deletes, not permission to change policy or rewrite Action
history. Database cutoffs use the database clock rather than a timestamp supplied
in the job. Column grants, RLS and minimization triggers prevent the shorter trace
window from permitting premature removal of conversation content.

Each run processes bounded batches and:

- Clears expired message and webhook content, completed outbound payloads, and
  non-file contact/location observations while preserving identity/reference rows.
- Minimizes detailed runtime metadata to model/reasoning/spec identifiers, control
  version and the existing usage snapshot. It does not implement the later usage
  aggregates or retain detailed traces indefinitely.
- Removes aged terminal Actions and their approval/event children only when no
  pending approval or nonterminal related outbox job exists. Recent or active
  Actions remain protected, including against history rewrites by the cleanup role.
- Deletes only audit records beyond the Action/audit cutoff. Other roles still
  cannot mutate the append-only audit trail.
- Writes aggregate counts, never the removed content, into the cleanup audit.

Physical media cleanup reuses `MediaService.delete` when that service is explicitly
provided. It revokes access first and retries exact pending object deletions using
the existing receipt. A separate storage failure does not roll back database
minimization. This task does not silently provision storage credentials.

## Deployment boundary

Inject a `RetentionService` into the scheduler context's `retention_service` before
startup. Its session factory must use a dedicated maintenance login authorized to
SET the retention role, not a production superuser. Credential provisioning is a
deployment prerequisite; no production login, password or app/admin membership is
created here. Supply the already configured `MediaService` for file deletion.
Without this composition, retention scheduling is disabled rather than run with
broader application credentials. Other lifecycle expiry remains enabled.

This is scheduled class-based minimization, not complete customer erasure: stable
IDs/contact references and workflow skeletons remain. Customer deletion/export,
revocation procedures, downstream copied Drive evidence deletion, backup/restore
and production privacy acceptance remain part of the approved later release work.
Live Meta/Google/WooCommerce and handoff evidence are not established by offline
tests. No deployment or real customer data cleanup was performed in this task.

## Focused evidence

Eleven focused checks passed: DST/defaults, recovery across case/target/handoff time
jumps, keyless approval/Action expiry, missing reminder recovery, timing changes
without duplicate delivery, per-tenant retention boundaries, immutable/aged history,
the new RLS matrix/registry coverage, and bounded recovery despite retry backoff.
The additional timing case exposed a SQL
literal interpreted as a bound parameter; only that failing case was retried after
correction. Previously passing milestone suites were not rerun. All data in these
checks was synthetic. Supabase local advisors reported no issues. Captured
`20260831180213_lifecycle_retention.sql`; local migration history matches. The
capture retains explicit role/column/function grants, revocations, FORCE RLS and
function-before-policy/trigger dependency ordering omitted by the schema diff.
