# MS7 — Control Plane Operational UX

## Authorization and product direction

MS6 was explicitly approved by the user. This branch builds on its accepted
technical checkpoint while retaining the documented live-provider/production gates.
The next approved dependency is Task 36 (Usage Foundation), followed by Tasks 37–43
for the Control Plane. No Superpowers workflow or master-plan rewrite is used.

Agents Factory remains a reusable, tenant-configured framework. The wizard owns
Company → Agent → Capabilities → Integrations → Knowledge & Conflict Review →
Policies & Identity → Human Operations → Approval Routes → WhatsApp → Test →
Quality Gate → Production, with resumable progress and explicit blockers.
SDK/runtime details remain behind the platform boundary. Standard client onboarding
must not require rebuilding the product or routine editing of code/YAML/SSH.

Task 36 is in progress; MS7 and production readiness are not yet accepted.

## Task 36 — ledger, pricing and policy-decision checkpoint

- Implemented a provider-neutral tenant usage ledger with opaque provenance,
  idempotent concurrent recording, conflicting-replay rejection and tenant-scoped
  reference checks. Missing measurements/prices remain unknown rather than zero.
- Effective-date price versions and saved snapshots preserve historical costs;
  Decimal pricing separates cached input and includes reasoning within output.
  Provider-reported costs, WhatsApp metadata and storage/infrastructure units have
  explicit contracts. No live provider prices or credentials are assumed.
- Added revision-checked admin configuration and bounded cost summaries by tenant,
  run, conversation, Action, Case, model and kind. Currency separation, unknown-cost
  flags, null attribution groups and explicit partial-data/truncation flags avoid
  presenting incomplete data as a complete operational report.
- Commercial quota decisions distinguish 70/85/100 alerts and grace/overage from
  independent hard-limit decisions. These new decisions are not yet wired into
  actual runtime/queue execution or distributed capacity reservation.
- Added two FORCE-RLS tables with least-privilege grants and immutable usage history.
  Supabase/Postgres guidance informed isolation, indexing and short transactions.

Seven focused checks passed: two pricing/policy cases, two local attribution/
configuration cases, the two new-table RLS matrices and registry completeness.
Initial failures were confined to missing actor IDs in new fixtures and a UUID/text
parameter conflict in the new matrix insert. Only those three cases were retried;
the four passing cases and all old suites were not rerun. Ruff/mypy passed and local
Supabase advisors found no issues. No live API, dependency upgrade, browser suite
or full regression run was used.

Captured `20260831183315_usage_costs.sql`, preserving FORCE RLS and explicit
revocations omitted by the schema diff. The previous MS6 migration also replayed
successfully in the disposable schema-capture database; no MS6 test was rerun.

Next: producer instrumentation, atomic concurrency/rate limits, persisted quota
alerts and runtime/queue/tool enforcement, followed by the new end-to-end anomaly
scenario. The pure loop decision check here is not represented as that end-to-end
acceptance. See `docs/usage.md` for composition and limitations. Task 36 remains open.

## Task 36 — runtime instrumentation and execution checkpoint

- Connected the agent worker to tenant usage configuration and per-execution
  observations without changing the approved wizard or compiled AgentSpec digest.
- Recorded model response measurements before tools/assistant persistence, in
  independent tenant-scoped transactions. Missing provider fields and interrupted
  requests stay unknown; cache/reasoning fields use preserved provider usage rather
  than normalized SDK zero defaults. No prompts or raw payloads enter the ledger.
- Added counted/recorded tool attempts, including validation and handler failures.
  SDK tool concurrency is serialized and attempts reserve synchronously before I/O.
  The smaller tenant/AgentSpec bound stops tool bursts and loops.
- Disabled hidden HTTP/SDK retries, checked durable worker attempt counts against
  tenant policy and made the queue respect explicitly non-retryable errors. Typed
  terminal errors survive SDK wrapping and create sanitized stop audits.
- Added reported-token accumulation and output-budget reduction. Unknown or
  over-budget responses stop before business tools/follow-up calls. Input admission
  can still overshoot on the current request: this is not yet the strict total
  model-token hard cap required to close Task 36.
- Preserved commercial grace: the local acceptance scenario configures an exhausted
  commercial token quota and still allows the normal client response.

Five new focused scenarios passed (three SDK contracts, two local worker/database
scenarios). They cover unexpected tool bursts, failed tool attempts, raw/unknown
usage, cancellation, simultaneous tenants, a runaway loop whose billed observations
survive conversation rollback, replay without a new call and provider retry limits.
The tests execute the installed SDK loop against a synthetic model, with tracing
disabled and no API client. No live API, dependency upgrade or old test suite ran.

One new SDK test first exposed wrapping of a terminal tool error; only that failed
case was retried after preserving its typed cause. The first database invocation
could not connect because Docker was stopped; Docker was opened and the existing
local database recovered without a schema reset. One new database assertion used
the wrong message-column name; only that failing case was retried after fixing
the assertion. Static format/lint/type checks were limited to the affected Python
files. No schema or grants changed, so no migration or repeated RLS suite was needed.

Agents SDK guidance informed lifecycle-based observations and disabled nested
retries; Supabase/Postgres guidance kept observations in separate short transactions
under the existing tenant RLS boundary.

Next Task 36 block: shared concurrency/rate reservations and durable commercial
threshold alerts, then remaining non-runtime producers, strict token-input admission
and uncertain-occurrence reconciliation. The technical stop audit is not a delivered
commercial quota alert. Task 36 and MS7 remain open; no PR merge or production
readiness is implied by this checkpoint.

## Task 36 — shared capacity and commercial alert checkpoint

- Added Redis-coordinated run leases and rolling per-tenant SDK request windows,
  preserving the specification's Redis/Supabase responsibility split. Admission
  uses atomic scripts and server time; model requests and business tools check
  ownership before execution. Leases and Redis calls have bounded deadlines.
- Connected capacity to the configured agent worker. A busy client does not block
  an independent tenant. A stale owner cannot authorize more work or release a
  replacement lease. Limits remain tenant settings, not per-customer code forks.
- Added durable capacity deferral before provider work. `outbox_jobs.deferral_count`
  separates scheduling waits from chargeable retries while retaining monotonic
  attempt history and a database CHECK on the actual retry budget. Partial runs
  that hit a shared rate limit stop rather than replay earlier tools for free.
- Added immutable, FORCE-RLS commercial alerts and `GET /usage/alerts` under the
  existing tenant PlatformAdmin route prefix. Cursor pagination is bounded; alerts
  and matching audits deduplicate per tenant/window/revision/metric/threshold.
- Added explicit `quota_window.start/end` configuration. No monthly billing cycle
  is assumed, no payment/subscription behavior is added, and 100% remains grace/
  overage. Unsupported/missing measurements and mixed currencies stay unknown.
  Alerts describe recorded usage only; storage-byte producers remain pending.

Seven focused checks passed: five new feature scenarios (atomic capacity/rate
windows and stale fencing; worker deferral/retry recovery with its database bound;
SDK follow-up throttling without replay; concurrent threshold deduplication and
period/tenant pagination; unknown/mixed-currency/oversized cost aggregates), plus
the new alert-table RLS matrix and updated registry completeness. No old feature
suite or previously passing scenario was rerun. One initial deferral failure
identified the existing delivery-count CHECK; only that failed scenario was retried
after adding the separate deferral counter. Ruff/mypy passed on affected code.

Redis was started using the existing local container; no data reset or live provider
call was used. Supabase advisors identified two new-policy expression warnings;
using the existing initialization-plan form resolved them without changing tenant
authorization. Advisors then reported no issues. Captured
`20260831192143_usage_alerts.sql`, restoring FORCE RLS and explicit revocations
omitted by the generated diff. Migration history is aligned with the local database.
Deploy this migration before the changed workers.

Supabase/Postgres guidance informed tenant isolation and atomic alert writes; the
Agents SDK guide informed admission at lifecycle boundaries. Redis scripting docs
confirmed atomic server-side admission. The approved master plan is unchanged and
no Superpowers workflow was used.

Next: strict model-token input admission, non-runtime usage producers and uncertain
provider-occurrence reconciliation. Later operational closure still needs live
provider checks, Redis recovery/load validation, retention and production setup.
Alerts are persisted for the future Control Plane, not external notifications or a
completed dashboard. Task 36 and MS7 remain open.

## Task 36 — strict model-token admission checkpoint

- Added exact input-token admission before every OpenAI generation using the
  Responses input-token count endpoint already supported by the pinned SDK. The
  count payload reuses the SDK's Responses payload builder, so instructions,
  evolving tool-call history, function schemas and model settings match generation.
- The whole-run token limit now subtracts prior reported usage plus current exact
  input and clamps `max_output_tokens` to the smaller remaining allowance. Input
  that cannot leave one output token stops before model generation; missing or
  malformed counters fail closed.
- Count and generation calls each reserve the shared tenant request window. A
  denial before any external work remains deferrable; a partial run never replays
  already executed tools as free work. The count is not duplicated as billable LLM
  token usage in the ledger.
- The implementation remains one shared runtime configured by the client wizard.
  No model routing, customer-specific code, live key, provider call or master-plan
  scope change was introduced.

Four focused cases passed in one new contract file: exact first/follow-up payload
counting through a real SDK loop, per-response output clamping, and fail-closed
behavior for missing, malformed and exhausted token counts. A first assertion
captured a mutable SDK settings reference; only this new file was retried after the
fixture saved the value at call time. Affected-file lint passed. No old passing suite,
database test, live API or credential setup was repeated.

The official Agents SDK guide and Responses input-token count reference confirmed
the lifecycle and endpoint contract. Live provider validation remains deferred as
approved. Next: non-runtime usage producers and uncertain provider-occurrence
reconciliation. Task 36 and MS7 remain open.

## Task 36 — outbound WhatsApp usage checkpoint

- Wired the existing outbound worker to the common usage ledger. Every provider
  attempt is attributed to tenant, durable job/run, conversation, Cloud API message
  kind, request/message units and measured latency without persisting message content,
  recipient identifiers or provider payloads.
- Persisted final outbound state, its audit and its usage record in one existing
  tenant-scoped transaction. The recorder now supports this already-scoped path
  while retaining backend-actor validation, RLS, idempotency, versioned pricing and
  atomic commercial-alert evaluation.
- Accepted sends record one request/message; known rejections record zero messages
  with unknown request count; uncertain outcomes keep the message unit unknown.
  Replaying a final outbound message creates neither another provider call nor
  another usage row.
- No schema, migration, live tariff, market inference, credential or new connector
  was added. Callback cost reconciliation and crash-window occurrence recovery remain
  explicit pending work instead of mutating immutable records or assuming zero cost.

One new local database scenario passed, proving accepted state and usage commit once
together and a replay stays single-send/single-record. Its first execution was
blocked before the test by missing local database configuration; the actual first
assertion then exposed only JSON Decimal representation, and only this new case was
retried. Affected-file lint, formatting and mypy passed; no old suite or database
reset ran.

The Supabase transaction/RLS guidance kept the write inside the existing tenant
transaction; the current changelog has no applicable breaking change for this path.
Next: external connector request producers, storage/infrastructure allocation and
uncertain occurrence/callback cost reconciliation. Task 36 and MS7 remain open.

## Task 36 — native external connector usage checkpoint

- Added physical provider-request accounting to the existing Google Workspace and
  WooCommerce transports. Pagination or reconciliation inside one business operation
  records every actual request instead of assuming one HTTP call per connector use.
- Kept the agent's local tool attempt separate from external API measurements.
  Provider occurrences use `requests` and therefore do not double-count the runtime
  `tool_calls` quota. A response proves one request; a transport failure without a
  response remains unknown rather than falsely free or billed.
- Bound the observer to the trusted connector execution context. Local validation
  failures do not emit provider usage, and OAuth/health traffic outside a business
  execution is not misattributed. The observer is reset after every execution.
- Persisted provider usage in the same tenant-scoped transaction as integration
  state and audit. Price cards can target stable products such as
  `woocommerce:orders.get`; no URL, credential, header, argument, response or
  customer content enters the ledger.
- Preserved the shared wizard/framework model. This adds no connector, customer fork,
  live tariff, provider credential, schema or migration.

One new database scenario passed. A single logical WooCommerce operation performed
two mock provider requests and produced exactly two priced request records, while
`tool_calls` remained unset. The first invocation stopped before product execution
because a sibling-folder fixture was not discoverable; only the same new scenario
was made self-contained and rerun. Targeted formatting, lint and source type checks
passed. No previously passing test or live provider call was repeated.

The existing tenant transaction/RLS boundary keeps the usage row atomic with the
integration operation. Next: storage/infrastructure allocation and the remaining
WhatsApp/uncertain-occurrence reconciliation. Task 36 and MS7 remain open.

## Task 36 — private-original storage allocation checkpoint

- Added durable `stored_at` and byte-size measurement for WhatsApp media originals
  and successful Knowledge originals. Media deletion now retains only those
  non-content accounting facts after removing the physical object, digest and key.
- Added an hourly tenant allocator that integrates exact known byte-hours and records
  the active byte snapshot separately. Versioned price cards use byte-hours; the
  commercial storage quota reads the latest bytes snapshot instead of summing it.
- Added deterministic hourly source keys, idempotent replay and one-hour-at-a-time
  recovery after scheduler downtime. Tenant traversal is bounded and one tenant
  failure does not prevent the remaining tenants from being processed.
- Kept unknown coverage honest: temporary uploads, pre-receipt crash orphans, legacy
  rows without size and deployment/database infrastructure are not estimated.
- Added migration `20260901013000_usage_storage_allocations.sql`; it was applied and
  registered in the existing local Supabase migration history. No live provider,
  customer data, tariff or customer-specific branch was introduced.

One new database scenario passed: 100 bytes stored for one hour plus 40 bytes stored
for half an hour yielded 120 byte-hours, a 140-byte current snapshot, the configured
price and the 100% storage grace/overage alert. Replaying the completed hour created
no duplicate. Targeted formatting, lint and type checks passed before this scenario;
no earlier passing test was repeated.

Next: trustworthy infrastructure allocation and the remaining WhatsApp/uncertain-
occurrence reconciliation. Task 36 and MS7 remain open.

## Task 36 — WhatsApp callback cost reconciliation checkpoint

- Added a distinct `billable_messages` meter for delivery-cost evidence. The original
  outbound occurrence continues to own the commercial message count; a callback
  cost occurrence sets `messages=0`, preventing quota and volume duplication.
- Reconciled Meta category, billable flag and pricing model in the existing callback
  transaction. Non-billable provider evidence quotes zero; billable evidence can use
  a tenant-configured category price card. Identical callbacks are idempotent.
- Kept immutable history explicit. Changed later evidence produces a sanitized audit
  conflict instead of silently repricing the original cost occurrence.
- Made webhook system actors durable by using the request correlation ID, allowing
  the common backend-only usage recorder to retain its actor boundary.
- Kept `recipient_market` unknown because Meta's callback does not supply it. No phone
  prefix inference, live tariff, credential, schema, migration or customer fork was
  added. Market-specific pricing stays unknown without a trustworthy mapping.

One new database scenario passed: an accepted send plus two identical billable
service callbacks produced one message unit, one cost occurrence and the configured
USD 0.02 quote. Targeted formatting, lint and source type checks passed; no previous
WhatsApp or usage test was rerun.

Infrastructure remains intentionally unreported: v1 uses shared workers/database and
has no measured host-resource attribution per tenant before deployment hardening.
Next: crash-window occurrence reconciliation and, once deployment telemetry exists,
measured infrastructure allocation. Task 36 and MS7 remain open.
