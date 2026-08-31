# Cases — Task 30 backend

`CaseService(session_factory, policies=trusted_tenant_policies)` owns short,
independently committed transactions. It never accepts a customer/LLM context as a
backend actor. Reads filter both tenant and customer. Runtime identity and exact
confirmation remain the responsibility of the existing Action workflow; there is
no public create-case endpoint.

## Composition

Inject `PersistentClaimCases(service)` into `ClaimsWorkflow.cases` and
`PersistentClaimDeliveryLedger(session_factory)` into `GoogleClaimsDelivery.ledger`.
Inject `PersistentOrderCases(service)` into `OrdersService.cases`. These implement
the MS5 ports without changing product integrations to MCP or using production
memory stores. They are explicit dependencies, not automatic tenant activation.

Backend lifespan installs `CaseService` for the authenticated admin router. The
scheduler registers `cases.timer`; each outbox job uses the case as `aggregate_id`.
The durable worker validates the job's tenant/topic/aggregate. Stale/repeated timers
recheck the case, so reopening or a newer silence deadline cancels the old timer's
effect without deleting jobs.

## State and policy

The canonical lifecycle is OPEN → AWAITING_INFORMATION → READY_FOR_REVIEW →
PENDING_APPROVAL → IN_PROGRESS → RESOLVED → CLOSED, plus the approved additional
states. Direct intake may start at the completeness-derived state. Complete intake
is not a business approval. Backoffice transitions require a revision, operation ID
and nonblank reason; customer results may only be recorded with a human decision.
Logical approval/action references are audit evidence, not capability to execute a
provider action. Task 31 supplies the actual verified approval mechanism.

`record_customer_response` is for an explicitly classified inbound/backoffice
report; it is not called by `status`. An issue persisting during the window reopens
the same case. Other responses restart the silence deadline. The default window
is 72 hours and is snapshotted from tenant configuration. A report after closure
creates/reuses a successor with a fresh response clock. A status-only query never
creates a case, changes conversation control or sends a pending reminder.

Priority is assigned by trusted structured issue rules, falling back to NORMAL;
customer urgency text is not an override. LOW/NORMAL/HIGH/CRITICAL targets default
to 48h/24h/4h/30m. The configurable approaching fraction defaults to 0.8. Alerts
appear in case/audit history, not in customer WhatsApp reminders; operational UI
and broader alert handling remain later planned work.

## Persistence and delivery

- `cases`: current snapshot, immutable identity key in service logic, revision,
  lifecycle, priority, policy and target timestamps. One active equivalent key per
  tenant/customer/capability/issue/scoped resource; collection details update that
  incident rather than inventing another case.
- `case_events`: append-only actor/correlation/reason/state history, operation /
  approval references and evidence IDs. Full intake/provenance lives in Cases and
  immutable operation receipts; private evidence content stays in Media storage.
- `case_operations`: append-only independent idempotency receipts. No Action FK
  that could block behind the calling transaction's Action row lock.
- `case_delivery_operations`: committed CLAIMED/terminal results per scoped effect
  key. Returned Drive IDs are retained for reconciliation and later privacy cleanup.

Lock order is operation → equivalence → case row. Case writes do not hold database
transactions across provider calls. Delivery uses separate advisory coordination
transactions, with short claim/result transactions; an interrupted claim is never
automatically sent again. Reconciliation must establish the real provider outcome
before any future retry mechanism. No reconciliation UI or unsafe reset is added.

The database-role grants are explicit: app reads, backend admin writes, no public /
anon / authenticated / service_role table grants. Every new table forces tenant
RLS. Local test fixtures temporarily allow SET ROLE and disable append-only
truncate guards only for isolated fixture cleanup, restoring them afterward.

No live accounts were used to verify this module. Production composition must
configure approved Knowledge, identity, connector bindings and private evidence
storage; retain the existing Action guards and verify provider permissions and
downstream retention before release.
