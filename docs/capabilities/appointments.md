# Appointments Capability Pack — Task 24

The v1 pack uses the native Google Calendar connector from Task 23 and the
existing Action layer. It supports one main professional and one location per
tenant; it does not introduce temporary slot holds or multi-resource scheduling.

## Operation gates

All names below are prefixed with `appointments.`. Identity and ownership come
from the trusted backend, never from model arguments.

| Operation | Risk | Identity | Additional gates |
| --- | --- | --- | --- |
| `check_availability` | LOW | Level 0 | Configured public schedule only |
| `create_appointment` | MEDIUM | Level 1 | Customer confirmation |
| `get_appointment` | LOW | Level 1 | Appointment belongs to the customer |
| `reschedule_appointment` | MEDIUM | Level 2 | Ownership and confirmation |
| `request_cancellation` | HIGH | Level 2 | Ownership, confirmation and verified backoffice approval |

Cancellation is a **request**, not deletion of the Calendar event. It persists
`CANCELLATION_REQUESTED`, retains occupancy and returns `cancellation_executed:
false`. Backoffice processing must not be represented as already completed.
Stricter tenant action policies remain applicable.

## Configuration and composition

`AppointmentsConfig` defines a fixed Calendar connection/binding/resource,
IANA timezone, professional and location identifiers/names, services with
duration and before/after buffers, weekly local working-hour windows, closed
dates, minimum lead time, booking horizon, slot step, approval route and
WhatsApp communication configuration. Unknown fields, additional resource
collections, overlapping hours and naive appointment timestamps are rejected.

An identified platform administrator calls `AppointmentsService.configure`.
The referenced connection must be that tenant's `google_calendar` connection.
Calendar, binding, connection, professional, location and timezone cannot be
silently replaced on an existing configuration. Configuration changes invalidate
previously requested actions through their pinned configuration digest.

`GoogleAppointmentCalendarFactory` composes the native adapter with
`IntegrationService`: encrypted credential resolution, refresh and sanitized
audit remain in the backend. Google OAuth setup and lifecycle are documented in
`docs/integrations/google-workspace.md`. The complete pack needs Calendar event
read/write access and free/busy access; credentials are never tool arguments.

The manifest maps each capability action to required connector primitives on
the **same binding**:

| Capability operation | Calendar primitives |
| --- | --- |
| Availability | `calendar.check_availability` |
| Create | `calendar.check_availability`, `calendar.create_event` |
| Get | `calendar.get_event` |
| Reschedule | `calendar.list_events`, `calendar.get_event`, `calendar.reschedule_event` |
| Cancellation request | `calendar.get_event` |

Unsupported bindings cannot publish the corresponding capability operation.
`AppointmentToolSession` supplies the five runtime tools using trusted turn
context, customer identity assessment and an `ActionService` configured with
`AppointmentActionConnector`. Read actions can execute immediately when allowed.
Write tools return the action state, ID, normalized parameters and digest for
the existing confirmation/approval flow; the model cannot set those gates.
Commit the request transaction before confirming/executing a write. Use the
existing trusted approval verifier for backoffice decisions.

## Availability, writes and recovery

Slots are evaluated in the configured timezone, with DST gaps skipped and both
valid instants of ambiguous local times retained. Duration is elapsed time;
buffers must fit inside working hours. Calendar occupancy and persisted local
buffers are combined. Availability responses explicitly state `held: false`.

A tenant/resource transaction-level advisory mutex serializes this service's
mutations across workers. Availability is fetched again immediately before
create/reschedule. Rescheduling excludes its own event and uses the provider's
ETag as an `If-Match` precondition. This is not an atomic reservation against an
independent human or application writing directly to Google Calendar; conflicts
are rejected when provider state exposes them.

External event IDs/ETags are persisted. Create/reschedule carry a deterministic
hash of tenant, binding and `action_id` in provider metadata. A durable receipt
is claimed before the external write and completed with the local result.
Replays return that receipt. Interrupted or ambiguous mutations stay `UNCERTAIN`
and require reconciliation; they are never blindly retried as new writes.
Receipts deliberately have no foreign key to the locked Action row, so the
independent durable claim cannot deadlock on its parent transaction.

The three tenant-owned tables enforce RLS and explicit least-privilege grants.
Runtime reads are scoped to the tenant; configuration and mutation persistence
require an identified backend actor. Customer-facing appointment results omit
provider IDs, ETags, tenant identifiers and other internal references.

## WhatsApp communications

Configure an existing WhatsApp account plus three approved template names and
an `es`/`en` locale. Shared template variables are `appointment_id`, `service`,
`professional`, `location` and timezone-qualified `start`.

- Successful creation/rescheduling queues an immediate confirmation.
- One reminder per current appointment revision is queued at the configured
  lead time if that time is still in the future. It includes
  `attendance_confirmation` and `reschedule_option` instructions; this does not
  introduce extra reminders or bypass the reschedule action gates.
- A successful cancellation request queues its own status update, not a claim
  that the event has been cancelled.

The scheduler consumes `appointments.notify` through the durable outbox.
Preparation verifies the persisted job, tenant, appointment revision, due time,
account and conversation recipient. Superseded jobs are skipped and previously
prepared messages for an older revision are blocked. Template policy and
idempotency are reused. The conversation must remain `AI_ACTIVE`; the outbound
worker checks human-control state again before sending. No live WhatsApp or
Google account was connected as part of the development tests.

## Focused verification

New unit cases cover configuration/availability, DST, primitive binding gates
and native reschedule metadata/ETag handling. Database scenarios cover competing
bookings, replay, identity, ownership, confirmation/approval, notification
idempotency, stale revisions and ambiguous external writes. Only the three new
tables' isolation cases and table-registration check were added to this run.

`evals/cases/appointments.jsonl` supplies six deterministic cases for the same
action gate called by the connector. Run with `python -m evals.run_local --cases
evals/cases/appointments.jsonl --output evals/results/appointments-task24.json
--seed 24`. These v0 development observations do not replace the later
exact-digest Production Quality Gate.
