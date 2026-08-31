# MS6 — Cases, Approvals, and Human Operations

## Authorization and scope

The user's approval permits starting MS6 on `codex/m6-cases`, based on the
reviewed MS5 checkpoint. It does not merge MS5/MS6 into `main` or waive the deferred
real-provider/corpus evidence. No Superpowers workflow or master-plan rewrite was
used. The approved specification, plan and v1 boundary remain unchanged.

## Task 30 — deterministic Cases and durable delivery

Implemented the Cases backend, independent PostgreSQL persistence and the deferred
MS5 delivery ledger:

- Tenant/customer/resource-equivalent deduplication, transaction advisory locking,
  immutable operation receipts and compare-and-set revisions. Replays precede
  revision validation; outer Action rollback cannot erase a saved case. Concurrent
  semantically identical messages keep one case/revision and preserve both sources.
- Canonical and additional lifecycle states, explicit actor/reason events,
  backoffice-only transitions, customer-safe reads and recorded human results.
  Intake cannot overwrite advanced or changed backoffice states. Case transitions
  do not mutate conversation control or authorize external business actions.
- Same-case reopening within the configured silence window; default 72 hours.
  Customer responses are explicitly recorded, not inferred from a status read.
  A response without a persisting issue restarts the silence window; a persisting
  issue reopens the case. Closed/out-of-window reports create/reuse an active
  successor instead. Timers recheck current state/deadline before closing.
- Structured tenant-priority rules with NORMAL fallback and the four approved
  Response Target defaults. Policy snapshots stay with the case. The configurable
  approaching threshold defaults to 80% elapsed; this is an internal operational
  setting, not an SLA or additional customer-facing feature.
- Durable `cases.timer` outbox scheduling and scheduler handler. Approaching/overdue
  alerts are persisted as case events and audit events. No periodic pending
  WhatsApp messages, new monetary operations or Generic REST functionality.
- Persistent adapters for both existing Orders and Returns & Claims ports. The
  legacy Orders interface reuses equivalent records without overwriting newer
  facts because it has no revision/CAS input.
- Distributed destination/effect serialization and separately committed delivery
  claims/receipts. Terminal results replay; abandoned claims become UNCERTAIN,
  never an automatic resend. Native Drive file IDs remain in durable results.
- Four new tables with explicit grants, FORCE RLS and tenant predicates; composite
  case foreign keys and immutable event/receipt triggers. Action and approval
  references are logical provenance links, avoiding locks on an outer Action
  transaction. Task 31 will implement verified approval decisions; this task does
  not treat an arbitrary reference as authorization to execute an Action.

Admin routes are registered under `/admin/tenants/{tenant_id}/cases`; no public
case-creation/execute endpoint was added. Customer runtime composition must keep
using the existing identity/confirmation checks before invoking the persistent
adapters. See `docs/cases.md` for wiring and operational boundaries.

## Focused verification (no old passing suites rerun)

- One compact unit scenario passed: complete state graph and deterministic target
  policy/boundaries.
- Three new integration scenarios passed on their first run: durable Cases and
  native Google composition across Action rollback/restart/concurrent replay;
  lifecycle/reopen/targets/scheduler; and crash-safe delivery plus Orders adapter.
- The four new tables passed the reusable RLS attack matrix. The table-registration
  check passed. Existing table scenarios were deselected.
- One new security scenario passed: backend/admin enforcement, tenant/customer
  denial, immutable history, RLS reassignment denial, unauthenticated HTTP denial,
  and concurrent message provenance without backoffice-state regression. Its test
  fixture needed the shared session alias and fixture-only admin-role SET grant;
  only that setup-failing scenario was retried, not previously passing scenarios.
- Focused Ruff, formatting and mypy checks passed. Supabase local advisors reported
  no issues before migration capture. No full CI, database reset, dependency
  upgrade, live API call or OpenAI key was used.
- Captured `20260831033300_cases.sql` with the local Supabase CLI. The migration
  list matches the isolated database; FORCE RLS and explicit revocations were
  retained in the captured SQL, and unrelated pg_net extension drift was excluded.

## Task 31 — secure first-response approvals

Implemented the backend approval foundation without changing the master plan:

- Persisted per-Capability/Action routes, explicit authorized recipients, revision
  checks and audit digests. Requests pin the committed confirmed Action, tenant,
  exact parameter digest, route revision digest and expiry; replay is idempotent.
- Stable SecretRef-backed HMAC proofs, per-reviewer links and separate email OTPs.
  OTP hashes, cumulative attempt/send limits, expiry and cooldown; no plaintext
  proof in persistence, audit, outbox or returned validation errors.
- Atomic first valid decision, immutable actor/time/structured proposal, and
  invalidation of every remaining link/challenge. Expiry/rejection cannot enqueue
  execution; only approval emits one uniquely keyed execution job.
- Native Gmail mailer through existing encrypted IntegrationService connections.
  Independently committed delivery claims prevent blind resend after uncertain
  results. Missing proof/mail configuration fails closed; no live API was called.
- Registered authenticated admin endpoints and token-bound public JSON endpoints
  with origin checking, sanitized errors, no-store and no-referrer. The public UI,
  final customer-safe result and execution coordinator remain Tasks 32 and 33.
- Four FORCE-RLS tables, explicit grants/revocations, tenant-composite references
  and append-only decisions. Supabase/Postgres guidance informed those boundaries
  and short transaction/lock ordering; provider calls happen after claims commit.
- Scheduler handlers for notice/expiry only when the service is configured.
  `approvals.execute` stays pending until Task 33 revalidates all execution guards.

Verification: the five new unit/integration/security scenarios passed on their
first test run. The four new-table RLS scenarios and updated registration check
also passed (47 existing scenarios deselected). Focused Ruff/mypy passed after
correcting two new type annotations and a test-import lint annotation before
running tests. No old passing suite was rerun. One harmless Pydantic/FastAPI warning
about Field repr metadata appeared; SecretStr masking and HTTP sanitization passed.
Supabase local advisors reported no issues. Captured
`20260831042410_approvals.sql` through the local CLI, retaining FORCE RLS and
explicit revocations and excluding unrelated pg_net drift. Credential-pattern
checks found no matches after renaming synthetic fixture variables that triggered
the repository's conservative scanner; test behavior was unchanged and no passing
test was repeated. See `docs/approvals.md` for exact
configuration, remaining integration boundaries and proof/privacy defaults.

## Continuation

Next work is Task 32: the secure approval page and customer-safe DecisionResult.
Then Task 33 supplies the revalidating execution/notification coordinator. Continue
the remaining MS6 tasks and present the milestone gate before MS7. MS6 is not
declared complete by this Task 31 backend checkpoint.

Still pending for release: deferred Task 27 live-media/corpus acceptance, real
Google/WooCommerce account verification, downstream evidence retention/deletion,
and production configuration/deployment validation. This offline checkpoint is
not a certification of provider behavior or production readiness.
