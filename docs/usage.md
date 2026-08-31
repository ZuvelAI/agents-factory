# Usage foundation — Task 36

## Product boundary

This module serves the common framework and the canonical client configuration
wizard. Prices, commercial quotas and technical limits belong to tenant
configuration, not a customer-specific code fork. It does not add billing,
subscription collection, a customer portal, extra model routing or live API access.

This is a partial Task 36 checkpoint: persistence, pricing, aggregate reads,
runtime metering, shared runtime capacity/rate reservations and durable commercial
alerts, exact input-token admission, and outbound WhatsApp attempt recording are
implemented. External connector/storage/infrastructure producers, complete WhatsApp
cost reconciliation and uncertain-occurrence reconciliation are still required
before accepting Task 36 or its dashboards.

## Recording and historical prices

`UsageRecorder.record(context, event)` is a trusted backend port. There is no public
usage-ingestion endpoint. Context requires an identified backend/admin actor; an
event cannot choose another tenant. Optional conversation/Action/Case references
are checked within that tenant. Run IDs are opaque producer correlation IDs, not
independently authenticated execution receipts.

An event records kind, provider/product/model, currency, timestamps, optional
run/conversation/Action/Case IDs and closed structured measurements. It must not
contain prompts, transcripts, customer identifiers, credentials or raw provider
responses. Use an opaque deterministic `source_key` per billable occurrence;
separate actual retry attempts need separate source keys. Replaying the same key
and data returns the saved record. Reusing it with different data fails.

Measurements distinguish unreported (`null`) from explicitly reported zero.
Input includes cached tokens; output includes reasoning tokens. Pricing subtracts
cached input before charging uncached input, and never charges reasoning again on
top of output. Provider-reported cost takes precedence over estimates. Otherwise,
the latest matching effective-date price version is chosen and its full snapshot
is saved. Missing price or required measurements gives an unknown cost, not zero.

Price versions cannot be changed or removed through configuration; append a new
effective-date version. Old records are never automatically repriced, including
replays after configuration changes. Price corrections/reconciliation must remain
explicit future work, not silent mutation of history.

Arithmetic uses Decimal and rounds estimated record cost to 12 decimal places
with half-even rounding. Supported units include token components, requests,
WhatsApp messages, tool calls, byte-hours and allocated infrastructure units.
WhatsApp category, recipient market and billable status have a closed metadata
contract; its future producer must select the corresponding approved tariff.
No provider rates are shipped as current facts: all test rates are fictional.

## Configuration, reports and wizard consumers

PlatformAdmin routes under `/admin/tenants/{tenant_id}/usage`:

- `GET /configuration`: current configuration and revision (empty prices/default
  policy when not configured).
- `PUT /configuration`: revision-checked prices, commercial quotas and hard-limit
  settings. This saves settings; it does not claim all runtime producers are wired.
- `GET /summary`: bounded half-open date range, grouped by tenant, run,
  conversation, Action, Case, model or kind. Case reports may filter currently
  RESOLVED/CLOSED cases. Unattributed records remain a visible null group.
- `GET /alerts`: tenant-scoped immutable threshold alerts, newest first, with
  bounded `limit` (1–200), UUID `before` cursor and `has_more`.

Every cost group has its own currency, known subtotal, unknown-cost record count
and completeness flag. Token/request sums and mean latency use reported values
only. No implicit currency conversion is performed. `has_more` prevents a capped
group list from appearing exhaustive; full pagination remains future consumer work.
All summaries explicitly describe recorded data only. They are not complete live
cost or quota totals until all required producers are connected.

`estimate_margin` accepts a manual revenue estimate and a complete non-overlapping
set of cost groups for the same period/currency. It returns unknown margin if any
cost is unknown or currencies differ, and no percentage for zero revenue. This is
an analytical function, not a payment workflow. Do not feed it capped reports or
mix alternative grouping dimensions of the same records (which would double-count).

## Commercial versus technical policy

Commercial quotas support messages, conversations, model tokens, currency-specific
cost, storage, concurrency and tool calls. Thresholds default to 70/85/100 and are
configurable. Crossing 100 produces grace/overage signals, not automatic service
shutdown. Missing measurements or mismatched currency produce an unknown signal.

`check_hard_limits` separately evaluates projected tool calls, retries, model
tokens, concurrent runs and requests/minute. It remains a pure decision function;
the execution integration below enforces the currently wired subset. Commercial
alerts are persisted for the Control Plane, not sent by email or WhatsApp.

### Commercial alert periods and evidence

`UsageConfiguration.quota_window` explicitly supplies an aware `start` and `end`
(half-open, at most 366 days). Without it, no commercial period or billing cycle
is invented and no commercial alerts are emitted. Configuring/rolling this window
is separate from payment collection and remains a future wizard consumer.

Each new ledger event atomically evaluates recorded usage in that window and
persists each crossed threshold once per tenant/window/configuration-revision/
metric/threshold. A tenant-scoped transaction lock serializes this with configuration
updates, and a unique constraint is the final deduplication boundary. A matching
`usage.quota_threshold_crossed` audit event is saved in the same transaction.
Alert history saves the threshold, percentage and state at that revision; it is not
a full historical copy of the customer's commercial contract.

Known recorded model tokens, WhatsApp messages, tool invocations, distinct attributed
conversations and same-currency cost can trigger alerts. Concurrency uses the
admission snapshot and is only evaluated for the currently active quota window.
Incomplete token/cost measurements, mixed currencies and unsupported aggregate
magnitudes remain unknown. Byte-hours are not converted into a storage-byte quota.
Alerts explicitly identify `recorded_data_only`; absence of an alert is not proof
that uninstrumented consumption is below budget. At 100%, state is `grace_overage`,
with no commercial shutdown or request denial.

### Shared runtime capacity and rate limits

The configured worker always supplies `UsageCapacity` using its existing Redis
connection, as required by the master specification. Optional uncoordinated runtime
composition exists only for isolated internal/test callers; it is not the production
worker setup. No per-client Redis instance or runtime fork is introduced.

An atomic Redis script reserves a tenant-tagged run lease and checks the shared
rolling 60-second **OpenAI request** window using Redis server time. Separate
workers cannot admit more than the configured run capacity or request rate. Exact
input-token counts and model generations each reserve before provider I/O, including
later calls in the same SDK loop. Business tools re-check lease ownership before
execution. Other connectors' request-rate producers are not wired by this
runtime-only boundary.

Leases have an absolute deadline of the bounded runtime timeout plus a five-second
cleanup margin, no indefinite renewal, and owner-specific release in `finally`.
Redis commands have a three-second timeout. Expired/lost ownership cannot authorize
another model/tool invocation, and a stale owner cannot release a replacement run.
This is admission control, not a way to retract an already sent external request;
process pauses, network partitions and Redis data-loss recovery still need the
production operational safeguards. Redis AOF is already enabled in local Compose.

If capacity/rate is unavailable before the first external request, the queue records
`capacity_deferred`, returns the job to `pending` with a future `available_at`, and
releases its lease. Physical deliveries remain auditable; `deferral_count` separates
these waits from chargeable attempts. Both runtime and queue retry budgets use the
non-deferred count, with a database CHECK still enforcing the maximum. Apply the
new migration before starting these worker versions.

If a run has already issued a request, losing capacity or reaching the shared rate
limit is a terminal technical stop, not a free replay of earlier tools. Missing
Redis never grants unlimited execution. Cancellation/error releases the lease;
if Redis cannot acknowledge cleanup, its bounded deadline remains the fallback.

## Runtime execution integration

The agent worker wraps the shared runtime with `MeteredAgentRuntime`, loading
tenant policy once per execution. The runtime receives effective limits separately
from its immutable AgentSpec: configuration must not rewrite a compiled digest.
Existing completed-message replay/control checks still run before this wrapper.
This implements a common framework boundary; it does not introduce per-client code.

The real Agents SDK loop records each model response through lifecycle hooks before
business tool execution, final output validation or assistant persistence. Each
record has an opaque run ID, sequence, tenant/conversation attribution, model,
reported token components, requests and monotonic elapsed time. Observation writes
use separate, short tenant-scoped transactions, so a later conversation rollback
does not erase already consumed usage. Cancellation shields only the accounting
write, not the provider request. A request without a usable response produces an
unknown-usage record, never a zero-cost assertion.

`preserve_raw_usage` is enabled. The accounting boundary selects only closed token
fields from that SDK payload; it never persists the raw payload, prompts, tool
arguments/results or transcripts. Missing, invalid or contradictory token details
remain unknown instead of using the SDK's normalized zero defaults. Internal
alternative/test adapters may fall back to one aggregate completion observation;
the production SDK path records individual responses, including partial failed runs.

SDK function-tool attempts, including failed argument validation/handlers, reserve
their counter before an await and record `kind=tool`, `provider=agents_factory`.
These are local invocation counts, **not** measured external API costs. External
connector producers must record their own provider-specific billable occurrences.
Without a configured price these local invocation costs remain unknown. This
checkpoint uses USD as the runtime quote currency, not a live provider rate.

Wired technical behavior:

- Tool attempts use the smaller of the AgentSpec limit and tenant policy. Even
  an unexpected burst of model tool calls cannot exceed that counter. Successful
  calls remain the only entries in the customer-visible runtime tool result list.
- HTTP and SDK model retries are disabled; the durable queue owns retries. The
  worker reads the attempt number from the tenant-scoped durable job, not its
  payload. Once `attempt_number - 1 > max_retries`, it stops before calling the
  provider. The queue honors explicit non-retryable exceptions as dead letters.
- Reported input+output usage accumulates per execution. Before every generation,
  the runtime uses OpenAI's exact Responses input-token endpoint with the same
  instructions, evolving input, reasoning settings and function-tool schemas. It
  reserves one rate-window request for that count, subtracts exact input plus prior
  reported usage, and clamps the current output allowance to what remains. Input
  that leaves no output token is rejected before generation. A missing or malformed
  counter fails closed. A provider response with unknown or unexpectedly excessive
  usage is still recorded and stopped before tools/follow-up work. This implements
  the strict per-execution model-token hard cap for the fixed v1 runtime contract.
  The count itself is admission evidence, not a second billable LLM usage record.
- Terminal runtime failures write a sanitized `usage.runtime_stopped` audit event.
  The SDK wraps local tool errors; the adapter preserves typed terminal causes
  rather than accidentally treating limit violations as retryable provider errors.
  Commercial 100% quota remains grace/overage, with no implicit runtime cutoff.

Accounting failures fail closed and are not retried as another potentially billed
run. A process crash or unavailable database can still leave an unknown/unrecorded
provider occurrence; durable reconciliation is not implemented by these hooks.
No exactly-once billing guarantee is claimed. Live provider validation remains
deferred, and no key or live rate was added.

## Outbound WhatsApp producer

The durable outbound worker now supplies `UsageRecorder` to the existing shared
WhatsApp service. Every claimed provider attempt receives a stable source key from
the outbound message ID plus persisted attempt number. The final outbound status,
sanitized audit event and usage record commit together in the same tenant-scoped
transaction. Replaying an already final message neither calls the provider nor
creates another usage occurrence.

Accepted sends record one provider request and one message. A known rejection
records zero messages and leaves request count unknown because the provider boundary
cannot prove whether rejection happened before or after transport. An uncertain
send records one attempted request and unknown messages, so cost and message quota
remain unknown rather than falsely free. Product attribution distinguishes Cloud
API text from template sends; run and conversation IDs remain opaque references,
and message bodies, recipient numbers and provider payloads never enter usage.

No live Meta tariff, recipient-market inference or delivery-callback cost is invented.
Without a matching configured price card, the outbound cost is explicitly unknown.
Meta callback category/billable evidence already retained on the outbound record is
not yet reconciled into immutable usage because a trustworthy recipient-market
mapping and correction occurrence are still pending. A process loss after provider
I/O but before the atomic completion stays `UNCERTAIN` and is never blindly resent;
Task 36 reconciliation must recover or mark the corresponding missing occurrence.

## Persistence and remaining work

`usage_configurations` and `usage_records` have explicit role grants, FORCE RLS,
tenant policies and tenant/time attribution indexes. App roles can read configuration
and append records, but cannot configure prices or update/delete history. The
admin API uses the existing verified PlatformAdmin boundary. Database maintenance
owners remain privileged; no new bypass role or security-definer function is added.
These decisions follow the official [Supabase RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security).

Usage records keep only structured measurements and opaque provenance references.
They are not yet anonymized aggregates; the later retention/privacy closure must
define minimization of these raw references rather than claiming indefinite
anonymous retention. No real customer data has been collected in this checkpoint.

Continue Task 36 with external connector, storage/infrastructure and remaining
WhatsApp/reconciliation producers. The local scenarios now cover exact per-request
token admission, shared capacity/rate admission, persisted commercial alerts,
outbound WhatsApp attribution, runtime attribution and loop termination. They do
not substitute for live-provider validation, Redis failure-recovery/load verification
or remaining producer coverage. Task 36 and the MS7 views are not yet accepted.
