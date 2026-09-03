# Returns & Claims — Task 28 connected workflow (offline checkpoint)

The backend now composes intake, confirmed Actions, the incremental Cases handoff
and the standard Google destination. It follows the approved v1 workflow: identify,
classify, collect evidence, validate completeness/policy, create case, backoffice
review, communicate verified status/result. This is an offline implementation
checkpoint, not live-provider or production acceptance. MS5 is not yet accepted.

## Implemented

- Strict customer-input schema for all seven issue classes. Tenant/customer scope,
  policy, verification, confirmations, case state and business decisions cannot be
  supplied as tool arguments. Classification accepts an explicit supported class;
  unknown/ambiguous classes require clarification, not a guessed classification.
- Incremental merging preserves item/evidence references, accepts corrections to
  descriptions/requested resolution and rejects silent class/resource changes.
  Null/empty patches do not delete collected data. Each inbound message is bound
  to its normalized patch digest. Replaying an older message does not overwrite
  newer corrections; replaying the same message with different data is rejected.
- An identified backend actor and a fresh tenant/customer identity assessment are
  required even for preparation. Trusted Orders references and pinned Knowledge
  provenance are checked against their configured scope. Customer media cannot
  establish identity, ownership or policy authority.
- Every retained evidence ID is rechecked through Task 27's `EvidenceAccess`
  interface, including on replay. Its default denies access. Expired/deleted or
  foreign evidence therefore cannot be reused by silently trusting an old draft.
- Stable deduplication and semantic-content digests exclude message delivery IDs.
  The key includes tenant, customer, capability, issue class, binding and canonical
  resource. An Orders adapter must keep purchase-reference/order-ID aliases on the
  same canonical resource; a changed established key is rejected.
- The registered manifest declares only case submission/update and case-status read.
  Submission has MEDIUM risk, level-1 identity minimum and exact confirmation;
  status has LOW risk and level-1 identity minimum. Stronger tenant policy must be
  enforced by the existing Action engine. There is no approval, refund, credit-note
  or acceptance-promise operation, even for a fully verified customer.

## Collection requirements

Every claim needs a class, description, order/purchase reference and requested
resolution. The latter is customer input, **never an approved outcome**.

| Class | Additional baseline collection |
| --- | --- |
| Wrong product | Item IDs; evidence or an explicit explanation of unavailability |
| Damaged product | Item IDs; evidence or an explicit explanation of unavailability |
| Incomplete order | Item IDs |
| Not received | No invented universal evidence requirement |
| Late delivery | No invented universal evidence requirement |
| Product/service nonconformity | Evidence or an explanation of unavailability |
| Return request | No invented universal evidence requirement |

The approved policy explicitly configures all seven classes and can additionally
require item IDs, incident/purchase dates or evidence. A customer explanation does
not bypass a policy that requires evidence. No evidence raises a review flag when
the customer reports it unavailable. Missing policy is an operator/backoffice
issue, not something a customer can approve. No automatic eligibility, deadlines,
monetary calculations, acceptance or rejection rules are inferred from prose.

`READY_FOR_REVIEW` only means the collection checks passed. Missing customer
fields yield `AWAITING_INFORMATION`; absent policy or scoped Orders reference
keeps an otherwise complete preparation `OPEN`. A trusted adapter may represent
an unverified reported purchase for human review, explicitly flagged as unverified;
it must not attach another customer's private order or infer ownership from an ID.

`PreparedClaimIntake` always has `case_created=false` and
`business_decision=NOT_MADE`. It is not a receipt and must not be shown to a
customer as proof of a saved case, Google delivery or accepted return.

## Confirmed workflow and native sources

`ClaimsWorkflow` and `ClaimsActionConnector` use the existing Action engine. Tool
sessions can request an action, but cannot confirm themselves. Exact digests,
confirmation expiry, fresh identity, stronger tenant policy and optional verified
approval requirements are checked before execution. Configuration, policy, order
ownership and all retained evidence are revalidated against the confirmed snapshot.
Changed configuration or a concurrent case revision requires review, not a silent
update. Stable inbound replay reuses the original action and confirmation snapshot.

`NativeClaimSources` reads only the exact Knowledge version/environment, approved
POLICY member, document digest and authoritative source provenance. Open critical
conflicts fail closed. The collection-field mapping is trusted backend configuration
bound to that document, not an LLM-generated rule. TEST access requires an explicit
backend opt-in. Queries use the existing tenant-scoped application role, without
new tables, privileges or RLS changes.

Verified Orders ownership is reused through the configured WooCommerce or Sheets
adapter. Unknown/foreign order IDs are not treated as owned orders. A purchase
reference without an order ID is explicitly customer-reported and flagged for
review. Resolving a reported purchase to a different canonical order key requires
explicit backoffice reconciliation; the native bridge does not invent aliases.

`ClaimSubmission.case_id` supports later partial messages, but is only a locator:
every case lookup also checks tenant, customer and binding. The separate
`ClaimCasesPort` contract preserves the existing Orders Cases contract. It requires
independent durable receipts, semantic deduplication, compare-and-set revisions and
provenance preservation. A receipt is checked before reporting a saved case. Intake
cannot overwrite an advanced backoffice state or supply a result. Status tools
return only the scoped case and a backoffice-recorded customer result.

## Standard no-CRM destination

`GoogleClaimsDelivery` composes the existing native adapters, in this order:

1. Export scoped, clean original evidence from MediaService and store it in the
   configured Drive folder; keep the returned file IDs in the delivery ledger.
2. Locate the case row and append/update the configured Sheets queue using RAW
   values and the adapter's expected-row check. Duplicate IDs, incomplete bounded
   scans and conflicting revisions fail closed. Older revisions cannot overwrite
   newer ones through this pipeline.
3. Send a Gmail notice only after the queue operation succeeds, only to the
   configured allowlisted backoffice recipient. No approval is inferred from email.

No public-sharing operation, arbitrary destination or Generic REST connector is
added. Drive accepts WebP and MP4 as evidence binaries, without video analysis;
its maximum configurable upload size is now 20 MiB, while the default stays 10 MiB.
The original media remains private and access-checked. Production onboarding must
verify the destination folder's access policy; this code does not certify inherited
Drive permissions. Downstream copies need retention/deletion propagation using the
recorded file IDs before a privacy-complete release.

The required `ClaimDeliveryLedger` port must serialize per tenant/destination/case,
commit an effect claim before each write, compare fingerprints and replay durable
receipts independently of the outer Action transaction. Interrupted/uncertain
writes require reconciliation, never blind retries. Successful uploads/rows/notices
are not resent for the same semantic revision. Sheets' own compare-before-write is
not atomic against external human edits; uncertain or conflicting writes remain
operator-reconciled rather than being represented as database-grade transactions.

A case that was saved remains saved if its Google delivery fails. The action result
reports case persistence and each destination status separately; delivery failure
does not claim the case was lost or invite duplicate case creation. An upstream
destination failure suppresses dependent downstream steps, while case-status reads
remain available independently of Google delivery.

## Runtime composition and persistence

AgentSpec validation now supports explicitly declared requirements across multiple
bindings for this workflow, while existing single-binding requirements keep their
behavior. Claim submission requires the bound order-read, Drive, Sheets and Gmail
operations. Case-status reads are internal; runtime selection still requires the
Cases port. Only the two declared operations are registered, never refund/approval
operations.

There is no new public execute endpoint. Backend startup must inject configuration,
sources, intake, Action service, Cases and destination ports. With unavailable Cases
or delivery persistence, tools fail closed; there is **no in-memory production
fallback**. Following the user's milestone review, Task 30/MS6 now supplies
`PersistentClaimCases` and `PersistentClaimDeliveryLedger`; inject those concrete
adapters as described in `docs/cases.md`. No live integration or tenant deployment
was enabled.

The workflow needs no OpenAI key for local implementation. Its deterministic checks
do not validate model extraction/classification quality, actual Google behavior or
provider permissions. Real PostgreSQL persistence/rollback/concurrency evidence is
recorded separately in `docs/implementation/ms6-progress.md`; it is not evidence of
live-provider acceptance. MS5 and MS6 have not been merged into `main`.

## Focused verification

The earlier two compact unit scenarios cover the class/policy/forbidden-operation matrix
and the incremental/replay/provenance/isolation behavior with an explicit evidence
fixture. The Claims JSONL suite invokes the real classifier, completeness function
and manifest gate through Eval Runner v0; it does not grade canned response text as
proof of the claim workflow. Their passing results were not rerun in this continuation.

This continuation added three focused database scenarios plus one composition
scenario. They exercise the real Action engine and native adapters with synthetic
provider transports, scoped Knowledge reads, private original export, partial
updates, duplicates, exact confirmation, revision conflicts, source revocation,
Google uncertainty, outer Action rollback, runtime gates and queue reconciliation.
The Cases and delivery ledger are explicitly test-only contract doubles: surviving
an outer database rollback in those fixtures is not proof of production durability.
All four scenarios passed. Only the failed scenario was retried after correcting
its expectation to the existing Action engine's FAILED/connector-REJECTED mapping;
already-passing tests were not repeated. No old eval suite or live API was run.
