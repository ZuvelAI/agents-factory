# Orders Capability Pack — Task 26

The v1 pack composes the native WooCommerce and Google Sheets adapters from
Task 25 with the existing Action layer. Provider differences remain behind the
connector contracts. It does not add a cancellation/refund executor or the
later Cases engine.

## Operation gates

All names below are prefixed with `orders.`. The backend supplies the customer
match and fresh identity assessment; neither is accepted from tool arguments.

| Operation | Risk | Identity | Additional gates |
| --- | --- | --- | --- |
| `find_order`, `get_status`, `get_tracking`, `get_items`, `get_delivery_information` | LOW | Level 1 | Trusted customer filter and order ownership |
| `update_shipping_address`, `update_contact_information` | MEDIUM | Level 2 | Ownership and exact customer confirmation |
| `add_order_note` | MEDIUM | Level 2 | Ownership and exact customer confirmation |
| `request_order_cancellation` | HIGH | Level 2 | Ownership, confirmation and verified backoffice approval |
| `create_claim` | MEDIUM | Level 1 | Complete intake, customer confirmation and available Cases contract |

Notes use the conservative Level 2 write gate. Stricter tenant policies remain
applicable. Cancellation only records a request: it never cancels the order or
issues a refund. The provider rechecks the current order state/version after
approval and rejects a no-longer-mutable order.

## Binding and runtime composition

`OrdersBinding` pins the tenant, binding, connection, provider and typed
`WooResource` or `OrdersSheetResource`. Writes default to disabled. The provider
resource's approved permissions and mapped fields determine the available
operations. A binding supporting cancellation must have an approval route.
Changing configuration invalidates pending actions through its pinned digest.

`NativeOrderConnectors` composes `IntegrationService` with the existing native
adapters. Backend credential resolution, refresh, connection locking and audit
redaction reuse Task 22/25; credentials are never runtime tool parameters.
`VerifiedOrderCustomers` combines `IdentityService` with a trusted
`OrderCustomerDirectory` that maps this tenant/customer/binding to its verified
provider customer ID or contact match. Model-provided identifiers cannot replace
that directory. An assessment must match the tenant/customer and be at most five
minutes old, with a thirty-second future-clock tolerance.

The backend supplies a tenant-scoped binding lookup to `OrdersService` and an
`ActionService` configured with `OrdersActionConnector`. `OrdersToolSession`
exposes only supported actions for the trusted inbound turn. Disabled bindings
produce no tools; an unavailable binding does not disable other capability
sessions. This is backend composition, not a new configuration UI or public
mutation endpoint.

Reads execute through Actions after authorization. Write tools return the action
ID, state, normalized parameters and digest. Commit the request transaction
before the existing confirmation/approval flow executes it. The model cannot
set `customer`, `confirmed`, `approved`, or `expected_version`. The backend pins
the provider version and exact normalized resource/field values before asking
for confirmation; another digest cannot confirm that action.

## Idempotency and uncertain writes

The inbound message, binding, operation and arguments determine the tool action
ID. Repeating that request reuses the original action and pinned snapshot rather
than silently changing the customer's confirmation. Execution rechecks binding,
customer identity/ownership and configuration before using the provider.

For mutations, a tenant/action advisory mutex and `order_operations` receipt
claim are committed independently before the external operation. Completed
replays return the stored result. A process interruption after the claim leaves
the operation `UNCERTAIN`; it is not blindly repeated even if the outer Action
transaction rolled back. The receipt deliberately has no foreign key to the
locked Action row. RLS is forced, the application role can only read its tenant's
receipts, and the backend role has scoped insert/update access without delete.

The Task 25 provider receipt/precondition checks are retained. Compare-before-write
does not claim an atomic transaction against independent WooCommerce/Sheets
editors. Uncertain outcomes require reconciliation through the existing Action
workflow. Spanish/English messages distinguish lookup success, recorded change,
cancellation request, unavailable operation and uncertainty without exposing
provider diagnostics or claiming an unconfirmed outcome.

## Issue intake and planned dependencies

The `orders.create_claim` tool supports the five approved issue types:
`missing_order`, `wrong_product`, `damaged_product`, `delivery_delay`, and
`create_claim`. All require a description and order ID or purchase reference;
wrong/damaged-product reports also require item IDs, and damaged-product reports
require evidence IDs. Incident date and requested resolution are retained when
provided. Incomplete intake returns `NEEDS_INFORMATION` and does not create a case.

An order ID is checked through the customer-scoped provider. A missing-order
report can retain an unverified reference as a customer report, not as verified
order ownership. Other reports with an order ID require a successful ownership
lookup. Evidence is represented by private UUID references, never arbitrary
URLs; the supplied `EvidenceAccess` must authorize each tenant/customer reference
at request and execution time.

`CaseIntake` carries the tenant/customer/conversation, issue type, binding/resource,
verification flag, collected fields, action idempotency key and deterministic
deduplication key. `CasesPort.create_or_update` must persist idempotency and reuse
an equivalent open case. A returned receipt must match the tenant, customer and
deduplication key before the tool reports the case ID/status. Registration does
not promise claim acceptance, cancellation, reimbursement or a resolution.

The production media/evidence implementation remains **Task 27**. The default
evidence port denies access. The persistent Cases engine and lifecycle remain
**Task 30 / MS6**; the default `UnavailableCases` hides case creation. Task 26
tests use explicit in-memory ports to verify this handoff contract, not to claim
that the later engines are implemented. No live customer integration is activated.

## Focused verification

One compact unit scenario verifies operation risks, strict arguments and truthful
localized messages. Three local-database integration scenarios cover provider
read parity, all four writes per provider, identity/ownership, exact confirmation,
approval, replay, crash receipts, changed cancellation state, binding isolation,
all five issue types, evidence checks, deduplication and unavailable Cases.
The new receipt table's isolation matrix case and registration check also passed.
Provider calls use sanitized HTTP fixtures; no live store or spreadsheet is used.

`evals/cases/orders.jsonl` contains 17 deterministic probes of the actual action
gate and issue-completeness functions. All passed through Eval Runner v0. These
are development checks, not the later exact-digest Production Quality Gate.
Already-passing tests from earlier tasks were not rerun.
