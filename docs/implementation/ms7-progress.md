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
