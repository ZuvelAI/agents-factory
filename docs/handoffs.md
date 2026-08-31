# Verified live human handoff — Task 34

Human conversation control is independent from approval routes and business-action
authorization. No Agents Factory human inbox or Generic REST connector is added.

## Admission and control

- Configuration is per tenant/WhatsApp account, revision-checked and admin-only.
  `HumanResponseSurface` is `WHATSAPP_COEXISTENCE` or `EXTERNAL_INBOX`.
- Coexistence requires an active persisted account, ELIGIBLE mode, HEALTHY status,
  verification timestamp and a registered human-surface adapter. API-only without
  a supported external surface cannot enable or request live handoff.
- A registered adapter must verify that its tenant/account/binding can route the
  existing conversation to humans AND supply authenticated control events. An
  arbitrary URL, provider name or a tenant-authored `handoff_surface_available`
  boolean is not verification. The instruction builder defaults to no human option
  unless its caller supplies an explicitly verified availability decision.
- `HandoffService.request` accepts a trusted backend reason. `escalation_reason`
  classifies a conservative set of clear Spanish/English requests and accepts
  mandatory-policy, repeated-integration-failure and unresolved-consequential-action
  outcomes from backend callers only. Ambiguous help, frustration and routine
  `PENDING_APPROVAL` do not trigger handoff. Those non-text outcomes are service
  integration ports, not LLM tool arguments or inferred approval results.
- The agent worker's configured handoff service inspects durable customer text
  before generation. A denied request leaves control unchanged and records its
  denial. Approvals remain usable when all human surfaces are disabled.
- Requests persist reason, immutable configuration snapshot, actor in audit,
  timestamps and one waiting receipt, then enter `AWAITING_HUMAN` atomically.
  Repeated requests reuse the same live handoff.
- `handle_event` resolves an event reference through the registered adapter. It
  never accepts raw public control claims. It binds tenant, account, conversation,
  handoff, surface and timestamp, and rejects stale per-handoff sequences.
  ACTIVATE enters `HUMAN_ACTIVE`; ACTIVITY refreshes activity; END closes control.
  Replays/late events cannot revive a closed handoff. All decisions are audited.
- The existing database transition function is additionally guarded by a durable
  handoff record. Legacy application calls cannot enter live human states without
  a backend-admitted record or close control before the live record is closed.

## Silence and timing

The existing inbound path keeps persisting customer events during human control.
Runtime checks authority before generation and again under the conversation lock
before persisting any AI output. A state-version fence also rejects generation
from an earlier control epoch, even if control has returned to AI. Both denials
record their stage. Delayed outbound sends recheck authority before claiming a
send and audit suppression.

The only exception while `AWAITING_HUMAN` is the exact, backend-created system
receipt referenced by the live handoff. It is not model output. Other system
messages cannot impersonate it. It sends at most once through the existing durable
WhatsApp pipeline and is suppressed if a human has already activated. It respects
the 24-hour free-form messaging window; no unapproved template bypass is added.

The receipt never claims a person is online. Optional IANA timezone and local
weekday support intervals change the copy outside support hours. Registration
outside hours does not assert immediate staffing or delivery to a person.

Default inactivity is 12 hours, configurable per tenant/account (1–168 hours).
The snapshot applies for the lifetime of a handoff. `close_if_inactive` rechecks
the latest human activity and persisted customer-message arrival under the same
conversation lock used by ingestion. It closes without sending periodic notices.
A new inbound message then reopens under the existing conversation session policy.
Task 35 owns scheduling and rescheduling this domain operation.

A provider request already claimed before takeover may already be in flight;
handoff cannot retract an HTTP request or message accepted by Meta. No entity
transaction is held over provider I/O. The guarantee is suppression of generation
and queued sends that lose authority before their final admission check.

## Composition and remaining live evidence

Inject the same tenant-bound `HandoffService`/`HumanSurfaceRegistry` into
`create_app(handoff_service=...)` and the agent worker's `handoff_service` context.
Admin routes under `/admin/tenants/{tenant_id}/handoffs` configure accounts,
request handoff, and read status. Authentication uses the existing PlatformAdmin
claim plus database membership check. No public activate/end endpoint exists.

The default registry is EMPTY. This task supplies and verifies the domain and
adapter contracts, not a fictitious live provider implementation. An actual
supported external-inbox bridge or verified eligible Meta Coexistence event bridge
must still be installed, authenticated and proven against its real provider
before live enablement. `verify` must prove routing, not merely return a configured
boolean; `load_event` must validate provider authentication, retain durable source
evidence and provide monotonic per-handoff sequencing. Its event mapping must
reference the exact currently requested handoff. No such provider is silently
selected or installed by this change. The existing native signup provider still
does not manufacture Coexistence eligibility.

Mandatory-policy and integration-failure producers must call the trusted service
port with their recorded backend reason; they are not enabled merely by a prompt.
Production bridge composition, timer scheduling (Task 35), tenant availability
acceptance and real provider delivery evidence remain explicit prerequisites.
The offline checks do not establish production readiness or complete MS6.

## Focused evidence

Thirteen focused scenarios passed: three unit policy/surface checks, four new
database control checks, three runtime/outbound security checks, the two new-table
RLS attack matrices and registry completeness. Seven passed initially; six shared
one row-lock permission failure. The fix reuses the existing tenant-scoped app
role's narrow locking permission without granting direct control writes; only
those six failures were rerun. Existing runtime/human-silence fixtures were aligned
with verified admission but their previous passing suites were not rerun.

No live provider, OpenAI key, browser, dependency upgrade or broad regression run
was used. Supabase/Postgres guidance informed short transactions, composite tenant
foreign keys, explicit grants/revocations and FORCE RLS on both new tables.
