# Approvals — Tasks 31–33

## Boundary and composition

The backend implements approval requests/decisions, the secure review page and
delayed revalidate-execute-notify. Public HTTP handlers never execute business
operations or send WhatsApp messages inline. Task 33's coordinator must be explicitly
configured in both scheduler and agent-worker before its topics are dispatched.

Inject an `ApprovalService` into `create_app(approval_service=...)` and the scheduler
context's `approval_service`. Its dependencies are the backend session factory,
stable `ApprovalProofs`, a tenant-native mailer and the configured HTTPS origin.
There is deliberately no generated-at-boot key or fallback email transport.
Missing service configuration returns 503; unconfigured worker topics remain in
the durable outbox, not a retry/dead-letter loop.

Task 35 independently registers expiry of pending requests and Action
confirmations. These jobs require no mailer, proof key or external API. They close
expired requests, invalidate links and queue one result; delivery waits for the
configured notification coordinator. See `docs/scheduler.md`.

Load the proof key with `ApprovalProofs.from_vault`, a `SecretRef`, identified
backend actor, purpose `approval_proofs` and record context `approval_service`.
Provision cryptographically random material of at least 32 bytes through the
existing Secrets Foundation. Keep it stable across API/worker restarts. Key
rotation must account for pending links: changing the key invalidates their
proofs; never silently regenerate a replacement request for a consumed Action.

`NativeApprovalMailer` uses the existing `IntegrationService`, connected Gmail,
encrypted credentials and a trusted per-tenant `ApprovalMailbox` (connection,
binding and `GmailResource`). Every route recipient must appear in that mailbox's
allowlist. It only calls the native `gmail.send_approval_notice` operation. No
Generic REST connector, OpenAI key or real provider account is needed for fixtures.

Configure one or more normalized unique authorized emails per Capability + Action
using `save_route`; route changes use expected revision and record an audit digest.
Only registered v1 Actions are accepted. `validate_required_routes` is the explicit
composition/publication gate for enabled HIGH/approval-required definitions.
The existing compiler is not rewritten here; Task 33 must compose persisted route
validation and `PersistedApprovalVerifier`, never a permissive test verifier.

After the customer's exact-parameter confirmation commits, call
`ApprovalService.request(context=..., action_id=...)`. It locks the Action and
requires the matching enabled persisted route, identity level, confirmation proof
and unexpired confirmation before creating a request. Calling this from inside a
transaction holding that Action is forbidden: it can wait on its own row lock.

## Lifecycle and delivery

- A request pins tenant, Action, parameter digest, route/configuration digest and
  deadline. One request per tenant/Action; replays return the existing record.
- Each email gets a separate signed link. The signature binds tenant, request,
  reviewer link and expiry. The database retains a token digest, not the bearer.
- The initial notice contains no OTP, customer parameters or customer secrets.
  It uses `/approval/review#token=...`: the fragment avoids sending the bearer in
  access-log URLs or referrers. The dynamic page uses the constant segment `review`,
  consumes the fragment client-side and immediately removes it from browser history.
- A separate OTP email goes only to that link's configured recipient. Store only
  challenge-bound, keyed hashes; default lifetime 10 minutes, five cumulative
  attempts, three sends and a 60-second cooldown. Configurable values are bounded;
  issuing a new challenge never resets attempts. Link lifetime defaults to 24 hours.
- Claims commit before native email delivery. Unknown outcomes and abandoned
  claims are not blindly retried. Only a confirmed `SENT` OTP can verify; later
  deliberate reissuance uses a new challenge, cooldown and remaining send budget.
- All closure paths lock in order: Action, shared route, request, child links.
  The first valid approval/rejection records the immutable actor/email, time,
  proof method and structured reviewer proposal. All links/OTP hashes are then
  invalidated atomically. Route change/revocation also invalidates pending requests.
- Only APPROVED adds the uniquely keyed `approvals.execute` job. REJECTED/EXPIRED
  closes the awaiting Action without business execution. No HTTP handler calls a
  business connector or tells the customer an operation succeeded.
- `PersistedApprovalVerifier` checks the decision, tenant, Action, parameter digest,
  route digest, enabled state and expiry. The Task 33 coordinator revalidates
  this and current identity/confirmation/business preconditions immediately before
  execution, outside the public approval transaction.

## HTTP and privacy

Admin endpoints are under `/admin/tenants/{tenant_id}/approvals`: PUT `/routes`,
POST `/actions/{action_id}`, GET `/requests/{request_id}`. All require Platform
Admin authentication and membership via the existing authorizer.

Public POST `/approvals/inspect`, `/approvals/otp`, `/approvals/decide` accept the
bearer in a secret-typed JSON body, require the exact configured Origin, reject
query parameters and bound input size. Validation/errors never echo the supplied
code or bearer. Responses are no-store/no-referrer; decision responses expose only
generic state, not winner identity, connector results or reviewer explanation.

`RequestedDecisionResult` is a proposal with reason code, explanation and requested
next-action codes. It is **not** a customer-safe result or authority to execute
those next actions. `DecisionResult` validates the customer-facing contract;
Task 33 combines it with the actual execution outcome.

Network metadata retention is off by default. If justified and explicitly enabled,
store only tenant/day-keyed HMACs of the IPv4 /24 or IPv6 /48 prefix and bounded
user agent. Do not trust forwarded headers without trusted-proxy configuration.
Do not enable request-body tracing on approval endpoints or native mail transport.
The page now supplies nonce CSP, public rate controls, accessible review details
and browser/history handling described below. This remains an offline checkpoint,
not a public production launch.

Four tables use explicit least-privilege grants and FORCE RLS. All links/requests/
decisions have composite tenant foreign keys; the decision's Action and parameter
digest also reference the same request. Decision rows are append-only. Audit and
outbox payloads contain identifiers/digests, never OTPs or link bearers.

## Evidence

One compact unit scenario, three integration scenarios, one HTTP/security scenario
and the four new-table RLS scenarios plus registry completeness passed. Google
transport was synthetic; vault encryption, native Gmail composition, transactions,
concurrency and PostgreSQL constraints were real/local. Existing suites were not
rerun. Live Gmail deliverability and production configuration remain separate
acceptance evidence. Task 32 UI evidence is recorded below.

## Task 32 — public review surface

`/approval/review` lives outside the authenticated Control Plane layout. Only this
exact page bypasses the administrative guard; other approval path/query values
return a generic response with no reflected input. Existing admin pages still use
verified Supabase claims. No approval grants or database policies were changed.

Set server-only `APPROVAL_PUBLIC_ORIGIN` to the canonical public HTTPS origin and
`BACKEND_API_URL` to the trusted backend origin. Both API and Control Plane must
agree on the public origin. HTTP is accepted by the frontend configuration only
for loopback/local backend development. Neither value comes from a supplied Host,
forwarded header, redirect or form field. Real delivery still needs Task 31's
stable proof key and connected Gmail configuration.

The public flow is email → separately delivered OTP → verified request summary →
explicit approve/reject + reason/internal explanation + confirmation checkbox.
An unverified link holder sees no request details. `/approvals/review` requires the
same bound email/challenge/code as the decision and shares its cumulative attempt
counter. It exposes only Action type, request ID, bounded resource reference and
the effective verification deadline, never complete parameters/contact data.

The browser calls Server Actions, which validate origin, host, input shape and
explicit confirmation before forwarding a bounded JSON payload to fixed backend
paths. No administrative session or credential is forwarded. Responses are
whitelisted; upstream error text and unknown fields are not exposed. The page
uses a per-response nonce, dynamic rendering, no-store/no-referrer, noindex,
frame denial and no third-party scripts. These choices follow the official
[Next.js CSP guidance](https://nextjs.org/docs/app/guides/content-security-policy)
and [Server Actions security guidance](https://nextjs.org/docs/app/guides/data-security).

Proofs live only in short-lived JavaScript references. There is no local/session
storage, cookie, hidden input, raw proof prop, bearer path or query string. The
initial static nonce script strips the fragment before hydration. Same-tab hash
navigation discards the previous proof/state, strips the new fragment and verifies
the new link. Navigation/BFCache restoration clears proofs and form fields; stale
async responses cannot reopen a previous request. A refresh without the email link
fails closed. Server Actions necessarily carry proofs in POST bodies; deployment
must keep body logging, HAR/trace capture and analytics off for these paths.

The backend's injected `RedisApprovalRateLimiter` uses atomic INCR/EXPIRE windows:
240 requests/minute per immediate peer and 30/minute per cryptographically valid
reviewer link, shared across endpoints/processes. Only keyed digests go to Redis;
no raw IP, email or bearer. This complements durable OTP attempts/send budgets.
Missing or unavailable rate-limit infrastructure fails closed. No forwarded IP is
trusted by default: behind the Control Plane the peer limit is an aggregate per
server, not a claim of end-user IP identification. Production edge configuration
must enforce its own transport limits and appropriately size the peer threshold.

POST `/approvals/decision` returns a structured receipt only to the winning
reviewer. Approval yields `pending_execution`, never success. Rejection initially
yields the generic reviewed rejection template: even a human-entered business
reason must be revalidated in Task 33 before presenting it as a fact. Free text,
HTML, contact details and requested arbitrary next actions cannot enter
`DecisionResult`; status, reason, explanation and next-action tuple must match a
reviewed template exactly. Next-action codes are suggestions, not authorization
to perform another operation. No WhatsApp notification is sent by this page.

### Focused validation and continuation

Run only this page's new browser cases with `pnpm --filter
@agents-factory/control-plane test:approvals`. It builds production assets and uses
an isolated loopback fixture backend; it does not start the old Auth suites, use
real mail, or need an OpenAI key. Trace/video capture is disabled. The ordinary
`test:e2e` command includes this suite after the existing suites for future CI.
The nonce policy deliberately has no development unsafe-eval relaxation, so use
the production build for these page checks.

New contract and backend integration tests cover sanitized result semantics,
OTP-only detail access, non-consuming review, shared attempt accounting, rate
denial/outage, one winner, closed responses and body-size limits. Browser cases
cover desktop/mobile keyboard use, headers/CSP, hidden private fields, no false
success, refresh/reopen/back, same-tab link changes and rate feedback. Supabase and
native Gmail integration use the existing local/synthetic fixture. Redis's adapter
is checked with an injected command stub; live Redis deployment acceptance remains
separate. No old passing test suite was repeated.

Next: Task 34's Live Human Handoff. The public page does not remove the backend
execution boundary or certify live provider behavior/production readiness.

## Task 33 — durable revalidate-execute-notify

Inject an `ApprovalExecutionService` as `approval_execution_service` into both the
scheduler and agent-worker contexts. Required dependencies are:

- The existing backend session factory; identified backend actors and tenant RLS
  remain mandatory. No anonymous, browser, service-role or model access is added.
- `agent_specs(session, context)`: a trusted factory for the current bound Agent
  Instance, normally `ProductionAgentSpecProvider(session, agent_instance_id=...)`.
  Resolve the instance from trusted tenant/channel configuration, never job text.
  No Milestone 2 fallback is installed by this coordinator.
- `connectors(context, action)`: reload current trusted bindings/connection state
  and construct the appropriate native `OrdersActionConnector` or
  `AppointmentActionConnector`. Do not reuse a different tenant's adapter or
  create a connector from model-supplied settings. Native identity, binding digest,
  resource ownership and business preconditions remain enforced by these adapters.
- Tenant `ApprovalNotificationBinding(template_name, language)`. Before enabling
  dispatch, synchronize an APPROVED WhatsApp UTILITY template with exactly the
  variables `request_id` and `result`. It is sent through the existing Meta outbound
  worker and SecretRef-backed provider configuration. No free-text/LLM fallback.

Only APPROVE queues `approvals.execute`. Rejection and expiry persist their
reviewed terminal result and queue `approvals.result` without execution. Workers
bind envelope IDs/topic/tenant/aggregate to a durable outbox row, then reload the
Action, approval, route, exact parameter digest and active AgentSpec/tool permission.
An approval reference is reverified by ActionService immediately before execution,
including after connector reads. Changed routes/spec/parameters, expired approvals,
shipped orders and cancelled appointments cannot authorize the write.

Execution uses short entity transactions: commit approval evidence and EXECUTING,
invoke the native connector, then atomically persist the terminal result and its
notification job. A separate per-Action advisory mutex serializes duplicate jobs;
only the mutex spans provider I/O, not locked Action/route rows. Existing native
operation receipts remain independently durable. An orphaned EXECUTING Action
becomes UNCERTAIN even if the connector/configuration is now unavailable; it never
blindly repeats the external write. Concurrent/completed replays reuse the same
terminal Action and uniquely keyed result notification.

`actions.result.decision_result` is the closed reviewed `DecisionResult`, alongside
internal provenance and safe connector output where available. Approval alone never
produces success. Native cancellation requests return `request_recorded` and
explicitly say that cancellation is not confirmed. Missing/malformed success
receipts become UNCERTAIN. Reviewer prose, provider exception text and arbitrary
next-action proposals never become customer messages. Suggested next actions remain
subject to a new authorized Action, not automatically executed.

While a conversation is not AI_ACTIVE, notification preparation creates a durable
`approvals.result.held` job keyed by Action and conversation-state version, without
an AI reply. The dispatcher checks that conversation under explicit tenant scope;
held jobs wait 30 seconds between checks without consuming send attempts or blocking
other work. They become dispatchable when normal conversation authority resumes.
Template preparation and outbound send independently recheck authority. A takeover
after message preparation can leave an observably BLOCKED outbound message; it is
not silently resent. Task 34 owns the human takeover/resume policy itself.

Trace reconstruction uses Action ID and `action_events` (request, identity,
confirmation, approval reference, executing, terminal), `approval_decisions`
(reviewer/proof/time), audit `approval.execution_validated` (current spec/binding/
digest), `action.revalidated`, `approval.result_queued` (notification job ID), and
`approval.customer_notification_prepared` (outbound ID). `outbound_messages` retains
the provider message ID, status/history/timestamps through delivery reconciliation.
The stable idempotency key `approvals.result:{action_id}` also links the Action to
its single outbound message if a worker stops before the final audit append.

No tables or grants were added. The lifecycle migration only permits writing a
terminal result while AWAITING_APPROVAL becomes REJECTED/EXPIRED; existing immutable
fields, terminal states and RLS remain intact. Supabase/Postgres guidance informed
the short entity transactions and tenant-scoped hold lookup; see the official
[RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security).

Local evidence: the Task 33 integration scenarios exercise real PostgreSQL, native
WooCommerce/Gmail adapters with synthetic transports, appointment preconditions,
worker envelope checks, held-job release, one outbound send and delivery
reconciliation. The eight new `approval_results.jsonl` cases run through Eval Runner
v0 without a model/API. Earlier passing suites were not rerun. Deployment wiring,
approved live Meta templates, provider credentials and real-account acceptance
remain release prerequisites, not claims established by this offline checkpoint.
