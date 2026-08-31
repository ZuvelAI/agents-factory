# Usage foundation — Task 36, first checkpoint

## Product boundary

This module serves the common framework and the canonical client configuration
wizard. Prices, commercial quotas and technical limits belong to tenant
configuration, not a customer-specific code fork. It does not add billing,
subscription collection, a customer portal, extra model routing or live API access.

This is a partial Task 36 checkpoint: persistence, pricing, aggregate reads and
policy decisions are implemented. Automatic producer instrumentation, distributed
capacity reservations, durable threshold alerts and runtime enforcement of the
new policies are still required before accepting Task 36 or its dashboards.

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
tokens, concurrent runs and requests/minute. A proposed operation exceeding a
technical bound is denied irrespective of commercial grace. This is a pure decision
function: it does not yet reserve distributed capacity, intercept provider calls,
emit durable alerts, or replace the runtime's existing limits.

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

Continue Task 36 by wiring metering around actual runtime/provider attempts,
including errors and duplicate delivery reconciliation; enforce tenant policies in
runtime/queue/tool services with atomic concurrency/rate reservations; record
commercial threshold crossings once per tenant/period/revision; and prove the
end-to-end runaway-loop stop. Only then accept Task 36 and build its MS7 views.
