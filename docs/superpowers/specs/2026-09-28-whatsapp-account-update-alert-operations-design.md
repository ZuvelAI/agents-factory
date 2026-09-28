# WhatsApp account-update alerts in Operations — design

Date: 2026-09-28

Status: design approved in conversation; written-spec review pending

Scope: isolated `codex/whatsapp-coexistence` branch only

## Purpose and success criteria

An ambiguous, signed Meta `account_update` event must be visible to a Zuvel
platform administrator in the AI Workers Operations panel until that person
investigates it. The administrator can close the alert only with a short note
describing what they verified in Meta. The system records who closed it and
when. Closing an alert never connects, disconnects, resumes, or suppresses a
WhatsApp account or agent.

The user selected panel-only notification, not email. The Meta reviewer account
and any potential customer-demo account are outside this change. The
coexistence release gate remains closed; this design does not authorize a live
Meta request, a production migration, deployment, or onboarding Zuvel's number.

## Existing boundary

The webhook already persists deduplicated ambiguous events before it
acknowledges them in the private, insert-only
`agents_factory_private.whatsapp_account_update_alerts` table. The backend has
a platform-admin-only, paginated, metadata-only read route at
`GET /admin/whatsapp/account-update-alerts`. The Operations page is currently a
placeholder. The existing alert row and fingerprint remain immutable.

## Selected approach

Use a persistent, administrator-authenticated resolution record and render
open alerts in Operations. A presentation-only “viewed” marker would not prove
investigation; automatically inferring the affected account from an ambiguous
event would risk changing the wrong number. Neither alternative meets the
agreed safety requirement.

### Data and authorization

Add a private `whatsapp_account_update_alert_resolutions` table with exactly
one row per alert: `alert_id` (primary key and foreign key to the existing
alert), `resolved_by` (platform-admin user ID), `resolution_note` (trimmed,
nonempty, at most 500 characters), and `resolved_at` (server-generated time).
Do not update or delete alert or resolution rows through the app. Preserve
resolution history even if the administrator later loses admin access.

Enable and force RLS. Grant the backend administrator database role only
`SELECT` and `INSERT` on resolutions; do not grant browser, `anon`,
`authenticated`, `service_role`, or webhook roles access. The authenticated
backend route must independently check the platform-admin claim and current
platform-admin membership, then write the acting principal's ID. Keep the note
out of application logs and raw webhook payloads out of both tables' API
responses. The panel asks operators not to paste tokens, message contents, or
other credentials into notes.

### Backend interface and state transitions

- Keep the existing bounded list route and its current unfiltered default;
  add an optional `status=open|resolved` filter for the panel. Include
  resolution metadata only for resolved rows. Preserve bounded pagination and
  avoid returning the event fingerprint.
- Add `GET /admin/whatsapp/account-update-alerts/summary`, returning the count
  of open alerts for the Operations panel.
- Add `POST /admin/whatsapp/account-update-alerts/{alert_id}/resolve` with a
  required note. The server trims and validates it, inserts a single resolution
  row atomically, and returns the resolved record. Unknown IDs return 404;
  already-resolved IDs return 409 without replacing the first note or actor.
  Concurrent close attempts have the same one-winner result.
- A retried webhook with the same fingerprint does not reopen a resolved alert.
  A genuinely new event/fingerprint creates a new open alert. Resolution is
  administrative bookkeeping only; no account-state or AI-control service is
  called by these routes.

### Operations panel

Replace the placeholder Operations page with an “Alertas de WhatsApp” section
for platform administrators. Show the open count and newest open alerts first,
with event, reason, WABA ID, display-number metadata when present, and received
time. Provide a resolved-history view showing the note, actor, and close time.
Each open row has a “Resolver” action with a required note and an explicit
confirmation. Render notes as plain text. On success, refresh the open count
and lists. If the backend is unavailable, show a retryable error rather than
an empty/success state; for a
409, explain that another administrator already resolved the alert and refresh
the view. No email, push notification, or automatic Meta lookup is included.

The browser uses the existing authenticated control-plane/backend boundary;
it never receives a service-role key. This is a panel notification, visible
when administrators open Operations, not a promise of real-time delivery.

## Verification and release boundaries

Use a disposable local database and isolated test dependencies. Verify the
private-table grants and RLS, one-winner concurrent resolution, required note,
404/409 behavior, admin-only access, bounded listing, open-count correctness,
and omission of fingerprints, payloads, and secrets. Exercise the panel's
open, resolve, resolved-history, unavailable-backend, and conflict states with
focused tests or a local browser run. Confirm that resolving an alert leaves
account and AI-control state unchanged. Re-run the relevant coexistence gates
without touching the configured production database or existing workers.

The existing separate release/pilot decision remains required after this
work; completing the panel does not open the coexistence release gate.
