# MS5 execution checkpoint

Date: 2026-08-30
Branch: `codex/m5-integrations`
Base: final MS4 content merged in PR #4 (`f9fd136` on GitHub).

The approved implementation plan is unchanged. No Superpowers workflow was used.
MCP-only access applies to external services used by Codex, not to a redesign of
the product's approved OAuth/API connectors.

## Task 22 — connection lifecycle foundation

Implemented tenant-scoped connection persistence, OAuth state/session/PKCE
binding, encrypted references through the existing Secrets Foundation, refresh,
reconnect, durable revocation, isolated health reporting, admin API routes and
Integration Catalog metadata. Existing Meta accounts are reused through their
original service, not copied into a second credential store.

New provider adapters remain unavailable until their planned tasks register them.
No Generic REST executable, authentication flow or webhook was added.

Verification is focused on new/changed behavior only; previous milestone suites
were not rerun. The migration was applied to the existing local database without
a reset. Provider exchanges use sanitized fakes, not real client authorizations.

## Task 22 verification

Verified evidence for this checkpoint:

- 8 new database integration scenarios passed (OAuth lifecycle, credential
  rotation, binding/PKCE attacks, replay, reconnect, concurrency and localized health).
- 2 new secret-boundary/HTTP-redaction scenarios passed.
- 1 new Meta/catalog projection scenario passed.
- Registry coverage and the new connection table's reusable isolation case passed.
- Focused Ruff and mypy checks passed; Supabase advisors reported no warnings/errors.
- Existing secret-scanner expression found no credential-like assignments in the changes.

The first database attempt was blocked by the sandbox before execution. The
subsequent run exposed a missing schema USAGE grant; only the six affected OAuth
scenarios were rerun after adding that minimal grant. Successful cases were not
rerun. No full local CI, database reset, or previous milestone suite was run.

## Task 23 — Google Workspace connector primitives

Implemented 11 native, typed operations across Calendar, Gmail, Drive and Sheets.
The connector manifests now declare those operations, with connection/configuration
and per-binding scope gates. Google Contacts and Generic REST remain absent.

Google OAuth is configurable per product through backend-only `GOOGLE_OAUTH_CLIENTS`.
The existing encrypted connection lifecycle is reused. A backend execution boundary
leases credentials, refreshes near expiry under the connection lock, and records
sanitized audit outcomes. Workers must supply an identified job/action actor;
anonymous secret access remains prohibited. No schema migration was necessary.

Documented limitations: no live client accounts were authorized; Google revocation
can affect combined grants in one Cloud project; Sheets precondition checks are not
atomic compare-and-swap. Capability packs must still use the existing Action layer
for approval, idempotency and reconciliation. No account credentials are in Git.

Focused verification at this checkpoint:

- 8 new contract scenarios passed on their first execution, covering all 11
  advertised operations plus scope/error/binding/size/header restrictions.
- The single modified catalog/schema unit case passed; no old milestone suite ran.
- 1 new local database scenario passed: real vault resolution, pre-execution
  refresh, audit redaction, actor/tenant gating, and independent Google health.
- That database scenario alone was retried once after it caught an anonymous
  worker actor in the new composition. The existing vault restriction was kept.
- Focused Ruff/mypy checks passed. No database reset, full CI, live Google request,
  dependency update or additional product scope was required.

See `docs/integrations/google-workspace.md` for scopes, composition and safe
operation contracts. Source plan and master specification remain unchanged.

## Task 24 — Appointments Capability Pack

Implemented the five approved operations on native Google Calendar, using the
existing Action identity/ownership/confirmation/approval gates. Configuration
supports one professional/location, service duration/buffers, local hours,
closed dates, lead time, horizon and timezone. No slot holds or multi-resource
constraints were added. Cancellation remains an approved request, not an event
deletion.

Create/reschedule revalidate occupancy under a cross-worker resource mutex and
persist external references plus durable action receipts. Ambiguous writes are
not blindly replayed. Calendar mutations carry action metadata and reschedule
uses ETag preconditions. Capability manifests now map their operations to native
connector primitives within the same binding.

The scheduler queues confirmation, one configurable reminder with attendance
confirmation/reschedule instructions, and cancellation-request updates through
approved WhatsApp templates. Stale revisions are suppressed and both preparation
and sending respect human takeover. These are backend capabilities; no live
customer accounts or new admin UI were activated.

Focused verification at this checkpoint:

- Four new unit scenarios passed, including the native reschedule metadata check.
- Two new database integration scenarios passed: the combined booking/action/
  notification flow and uncertain-write/tenant isolation flow.
- The latter alone was retried after correcting the test's missing tenant scope
  before a raw count query. Previously passing scenarios were not repeated.
- The three new tables' RLS matrix cases and table-registration check passed.
- Six appointment evals passed, exercising the real connector's action gate.
- Focused Ruff/format/mypy checks and whitespace checks passed; the existing
  secret-scanner expression found no credential-like assignments.
- Supabase advisors reported no warnings/errors; local migration history is
  synchronized. The migration was captured from the local schema without a reset,
  excluding unrelated extension drift and retaining explicit RLS/grants.

See `docs/capabilities/appointments.md` for composition and operational boundaries.
The approved plan and master specification remain unchanged.

## Task 25 — WooCommerce and Sheets order adapters

Implemented native WooCommerce REST v3 and typed Google Sheets order adapters
covering the nine approved read/write/request operations. Both enforce trusted
customer matching and expose normalized, limited payloads. Bindings are derived
from approved provider permissions and resource fields; read-only/partial Sheets
cannot offer unsupported mutations.

WooCommerce API-key onboarding reuses the encrypted connection lifecycle, with a
backend exact-store allowlist, HTTPS, public-IP pinning/TLS SNI, no redirects and
redacted errors. Sheets reuses existing scoped OAuth and row primitives. Connected
execution reuses connection locking; provider receipts and compare-before-write
support replay/reconciliation without claiming atomicity against external editors.
Cancellation is only a request; no cancellation/refund endpoint is invoked.

Focused verification:

- Seven new provider scenarios and the one changed catalog case passed on their
  first run (8 passed, 7 unrelated Google cases deselected).
- Covered all nine operations per adapter, customer matching, pagination/sparse
  rows, tracking absence, status normalization, all writes and replay, shipped
  cancellation rejection, mapping conflicts, scopes, partial/read-only bindings,
  DNS/redirect restrictions, redaction and uncertain writes.
- The WooCommerce credential payload was checked with the real envelope cipher,
  including tenant-bound decryption denial. Existing Task 22 database lifecycle
  tests were not repeated; no database migration or reset was necessary.
- Focused Ruff/format/mypy and whitespace checks passed. Secret scanning found
  no credentials; an action-note marker was renamed to avoid a false positive.
- No live store, customer spreadsheet, Google authorization or paid service was
  connected. Orders capability/identity/issue workflows remain Task 26 work.

See `docs/integrations/woocommerce.md` and `docs/integrations/google-sheets-orders.md`.

## Task 26 — Orders Capability Pack and issue flows

Implemented connector-neutral order tools on the two existing native adapters,
with trusted customer/ownership resolution, conservative risk/identity gates,
exact normalized confirmation, verified cancellation approval and execution-time
state revalidation. Unsupported or disabled bindings do not expose tools.
Cancellation remains a request, never an executed cancellation or refund.

Durable tenant-scoped mutation receipts survive an outer Action rollback. Stable
inbound replays reuse the original action and provider snapshot; interrupted
writes become uncertain without repeating the external effect. The new receipt
table has forced RLS and explicit least-privilege grants.

The five issue flows collect identifiers, description and relevant item/evidence
references, then use a typed Cases handoff with action idempotency and open-case
deduplication keys. Default ports fail closed: evidence access awaits Task 27,
and production Cases persistence/lifecycle awaits Task 30 in MS6. Tests supply
explicit fixtures for those contracts; no later engine or live integration was
activated and no resolution is promised.

Focused verification:

- One new combined unit scenario passed for risks, strict inputs and localized
  response semantics.
- Three new local-database scenarios passed for provider parity, all writes,
  confirmation/approval, replay/crash recovery, state changes, binding isolation,
  all five issue types, evidence/deduplication and unavailable Cases.
- The new receipt table's isolation matrix case and table-registration check
  passed in the same database run (5 passed total).
- All 17 Orders evals passed, exercising actual action gates and completeness.
- Focused Ruff/format/mypy checks passed. The existing repository credential
  patterns found no credential-like assignments or private-key material.
- Previous tasks' passed tests/evals were not repeated. No full CI, database
  reset, live provider authorization or dependency upgrade was performed.
- Supabase advisors reported no warnings/errors. The local migration history
  is synchronized; schema capture excludes unrelated extension drift and retains
  forced RLS plus explicit grants.

See `docs/capabilities/orders.md` for composition, guarantees and deferred ports.
The approved implementation plan and master specification are unchanged.

## Continuation

Continue with Task 27: multimodal normalization and tenant-scoped evidence
storage. Tasks 27–28 remain pending. MS5 has not been declared complete and will
still require its approved milestone review before proceeding to MS6.
