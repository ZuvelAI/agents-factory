# Approval foundation — Task 31

## Boundary and composition

This backend implements approval requests and decisions, not external execution.
Task 32 supplies the public review page and sanitized `DecisionResult`. Task 33
supplies delayed Action revalidation/execution and customer notification. Do not
dispatch `approvals.execute` before that coordinator exists.

Inject an `ApprovalService` into `create_app(approval_service=...)` and the scheduler
context's `approval_service`. Its dependencies are the backend session factory,
stable `ApprovalProofs`, a tenant-native mailer and the configured HTTPS origin.
There is deliberately no generated-at-boot key or fallback email transport.
Missing service configuration returns 503; unconfigured worker topics remain in
the durable outbox, not a retry/dead-letter loop.

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
  access-log URLs or referrers. Task 32 can use the planned dynamic page segment
  `review`, read the fragment client-side and remove it from browser history.
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
  route digest, enabled state and expiry. The Task 33 coordinator must revalidate
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
those next actions. Task 32 validates/sanitizes the customer-facing contract;
Task 33 combines it with actual execution outcome.

Network metadata retention is off by default. If justified and explicitly enabled,
store only tenant/day-keyed HMACs of the IPv4 /24 or IPv6 /48 prefix and bounded
user agent. Do not trust forwarded headers without trusted-proxy configuration.
Do not enable request-body tracing on approval endpoints or native mail transport.
Task 32 also supplies the page CSP, public rate-limit surface, accessible review
details and complete browser/history checks; this backend checkpoint is not a
public production launch.

Four tables use explicit least-privilege grants and FORCE RLS. All links/requests/
decisions have composite tenant foreign keys; the decision's Action and parameter
digest also reference the same request. Decision rows are append-only. Audit and
outbox payloads contain identifiers/digests, never OTPs or link bearers.

## Evidence

One compact unit scenario, three integration scenarios, one HTTP/security scenario
and the four new-table RLS scenarios plus registry completeness passed. Google
transport was synthetic; vault encryption, native Gmail composition, transactions,
concurrency and PostgreSQL constraints were real/local. Existing suites were not
rerun. Live Gmail deliverability, UI behavior and production configuration remain
separate acceptance evidence.
