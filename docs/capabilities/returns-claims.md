# Returns & Claims — Task 28 intake checkpoint

This checkpoint implements conservative **preparation**, not a live case workflow.
It follows the approved v1 specification: identify, classify, collect evidence,
validate completeness/policy, create case, backoffice review, communicate verified
status/result. Task 28 is not complete and MS5 is not accepted by this checkpoint.

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
- A candidate manifest declares only case submission/update and case-status read.
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

## Composition still pending in Task 28

The candidate manifest is intentionally **not registered** and no runtime tools,
HTTP endpoint, background job or external writes are activated by this checkpoint.
The existing Orders/Cases contracts and original master plan remain unchanged.

Remaining Task 28 work:

1. Connect the trusted Knowledge adapter to the exact published policy membership
   and provenance. The core accepts a backend-owned `ApprovedClaimPolicy`; that
   type alone does not prove publication. Customer/model text must never construct
   this trusted object. Connect Orders ownership/reference resolution as well.
2. Wire confirmed Actions, runtime tools and a typed incremental Cases handoff.
   The Cases port must enforce durable tenant isolation, compare-and-set revisions,
   equivalent-open-case deduplication and action idempotency. The pure reducer does
   not solve concurrency or persist data. No in-memory production fallback is
   allowed. Full Cases persistence/lifecycle remains Task 30 in MS6.
3. Compose the standard no-CRM destination using the existing native adapters:
   Sheets queue/status, private Drive evidence and Gmail notices. Require configured
   destinations, durable per-effect receipts and uncertainty handling; a timeout
   must not trigger blind duplicate uploads/rows/email. Only report completed writes.
4. Register only executable operations, expose verified human-recorded status/results,
   and run the focused integration acceptance for partial/duplicate case handoff and
   destination failures. Do not register this manifest ahead of that composition.

The core is offline and requires no OpenAI key. Its deterministic checks do not
validate LLM extraction/classification quality, actual provider behavior, database
case persistence or production readiness. No MS6 implementation or MS5 merge is
authorized by this checkpoint.

## Focused verification

Two compact new unit scenarios cover the class/policy/forbidden-operation matrix
and the incremental/replay/provenance/isolation behavior with an explicit evidence
fixture. The Claims JSONL suite invokes the real classifier, completeness function
and manifest gate through Eval Runner v0; it does not grade canned response text as
proof of the claim workflow. Run only this new file/suite at this checkpoint; no
earlier passing task suites or live APIs are required.
