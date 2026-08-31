# Usage foundation — Task 36

## Product boundary

This module serves the common framework and the canonical client configuration
wizard. Prices, commercial quotas and technical limits belong to tenant
configuration, not a customer-specific code fork. It does not add billing,
subscription collection, a customer portal, extra model routing or live API access.

This is a partial Task 36 checkpoint: persistence, pricing, aggregate reads,
runtime metering and part of technical enforcement are implemented. Non-runtime
producer instrumentation, distributed capacity reservations, durable commercial
threshold alerts and strict input-token preflight are still required before
accepting Task 36 or its dashboards.

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
the execution integration below enforces the currently wired subset. Distributed
capacity/rate reservations and commercial threshold delivery are still pending.

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
- Reported input+output usage accumulates per execution. The next output allowance
  cannot exceed its remaining token budget. A response over budget (or with unknown
  total usage) is recorded and stopped before its tools/follow-up request. This is
  **not yet a strict preflight cap on input+output billing**: input tokens of the
  current request can overshoot the remaining budget. Exact input admission is a
  remaining Task 36 requirement, not a claimed completed hard cap.
- Terminal runtime failures write a sanitized `usage.runtime_stopped` audit event.
  The SDK wraps local tool errors; the adapter preserves typed terminal causes
  rather than accidentally treating limit violations as retryable provider errors.
  Commercial 100% quota remains grace/overage, with no implicit runtime cutoff.

Accounting failures fail closed and are not retried as another potentially billed
run. A process crash or unavailable database can still leave an unknown/unrecorded
provider occurrence; durable reconciliation is not implemented by these hooks.
No exactly-once billing guarantee is claimed. Live provider validation remains
deferred, and no key or live rate was added.

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

Continue Task 36 with atomic tenant concurrency/rate reservations, strict token
input admission, other producers (WhatsApp, external connectors, storage/infra),
uncertain-occurrence reconciliation and commercial threshold crossings once per
tenant/period/revision. The new local end-to-end scenario proves two-tenant runtime
attribution, runaway-loop stop and a durable technical audit; it does not substitute
for the pending commercial alerts or distributed-capacity acceptance. Only then
accept Task 36 and build its MS7 views.
