# Google Sheets order adapter — Task 25

The Orders adapter reuses Task 23's native Sheets transport, OAuth scopes,
SecretRef lifecycle and typed row primitives. Configure
`ConnectedGoogleConnector(product="google_sheets", resource=OrdersSheetResource(...))`.
The factory selects the order adapter inside the same backend credential lease.
Do not replace product APIs with Codex MCP tools; MCP remains our development
tooling choice, not the runtime protocol.

## Approved mapping and operation visibility

`OrdersSheetResource` fixes the spreadsheet, tab, exact ordered headers and
domain-field-to-header map. It requires `order_id`, `status`, and at least one of
`customer_id` or `email`. A row represents one order. Keep identifiers as text and
give every order a unique canonical ID; duplicate matches block the operation.

| Domain field | Cell representation / use |
| --- | --- |
| `order_id`, `customer_id`, `email`, `status` | Scalar identifiers and provider status |
| `tracking` | JSON object with optional `number` and HTTPS `url`; empty means unavailable |
| `items` | JSON array of `item_id`, `name`, `quantity`, optional `sku` |
| `shipping_address` | JSON address object |
| `delivery_information` | JSON delivery-information object |
| `contact_information` | JSON email/phone object; its email, when present, is used for ownership matching |
| `notes` | JSON array of internal note entries |
| `cancellation_request` | JSON object recording a request, not cancelled order status |
| `action_receipts` | JSON object mapping action hashes to request digests |

Mapping names outside this set, duplicate headers/targets, missing identity
mapping and unexpected header changes are rejected. Empty structured cells use
their empty object/array defaults; malformed JSON is not guessed or coerced into
an order. Statuses use a trusted mapping and otherwise become `UNKNOWN`.

`resource.supported_operations` derives the subset of the nine shared order
operations from available fields. Status/find need the base mapping. Tracking,
items and delivery require their corresponding mapped fields. A write needs its
target field **and** `action_receipts` in `writable_fields`; the default is empty.
For contact updates, map contact information explicitly, not a general arbitrary
cell-edit operation. `configured_order_binding` additionally defaults to reads
until approved provider grants permit writes. Use this derived binding in
AgentSpec; the static connector catalog is only a superset. Runtime execution also
checks the resource mapping even if a binding tries to request extra operations.

Read-only OAuth uses `spreadsheets.readonly`; updates require `spreadsheets`.
Insufficient scopes fail closed. Existing generic `sheets.*` primitives remain
separate from the order resource; no arbitrary cell tools are offered by this pack.

## Reads, writes and limitations

Specific order lookup scans bounded windows up to configured `max_rows`, including
across blank gaps, then checks the trusted customer match. Treat `max_rows` as the
approved data boundary and raise it during setup if the operational table grows.
Search pagination refers to physical row windows; a matching-empty page may still
have a next page. Results do not expose unrelated customers or whole raw rows.
Canonical read payloads match the WooCommerce adapter, except provider-dependent
snapshot version digests.

Writes require `expected_version` from a prior read and the stable action key.
The adapter checks the order state, rechecks the exact full mapped row immediately
before writing, and changes only approved cells plus the receipt. It preserves
unrelated cells/formulas. Matching receipts reconcile replays; mismatches reject.
Receipt/note growth reaching the cell limit returns `reconciliation_required`
rather than silently truncating history. Cancellation records `REQUESTED` and
leaves the order's status unchanged. It never executes a refund or cancellation.

The underlying API sends target cells together with `valueInputOption: RAW`, so
user-provided text is not submitted as spreadsheet formulas.
([Google values.batchUpdate reference](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/batchUpdate))

The connected wrapper's existing connection-row lock serializes platform workers
on that connection. Google Sheets compare-before-write is **not atomic CAS**;
other connections or human edits can still race between the read and write. Do
not automatically retry an ambiguous write or claim database-grade transactions.
The Action layer in Task 26 must retain uncertain outcomes and reconcile them.
Runtime identity, risk, confirmation and approval are also Task 26 responsibilities;
`CustomerMatch` fields are not a substitute for verification.

## Verification

Focused mocked-HTTP scenarios cover read parity, sparse pagination, duplicate and
invalid mappings, all four mutations, receipts/replay, preservation, stale-row
conflicts, scope/read-only/partial-operation gating and ambiguous writes. No real
customer spreadsheet was read or modified. There was no new database schema or
rerun of previous milestone suites.
