# WooCommerce order adapter — Task 25

Native REST v3 implementation for the approved Orders workflows. This task does
not add a Generic REST connector, refunds, autonomous cancellation, storefront
creation, or the Task 26 customer-facing capability/identity flows.

## Setup and secret boundary

Set backend-only `WOOCOMMERCE_STORES` to a JSON array of exact approved HTTPS
store installation URLs, without trailing slash. Subdirectory installations are
supported. An empty array (the default) leaves the provider unavailable. URLs
cannot contain credentials, query strings, fragments, ports or traversal paths.

An identified platform administrator uses the existing tenant-scoped
`POST /admin/tenants/{tenant_id}/integrations/api-key` endpoint, with
`connector_name: woocommerce` and a secret JSON credential string containing
`store_url`, `consumer_key`, `consumer_secret`, and `permission` (`read` or
`read_write`, default `read`). Send actual credentials only through this existing
secured backend path; never put them in AgentSpec, tool arguments, Git or logs.
The existing connection lifecycle encrypts the complete payload into a
tenant/record-bound SecretRef before persistence. Health performs a bounded read;
it does not claim to have proved write access. Configure keys with the required
permissions in WooCommerce and separately approve the resource's write set.
WooCommerce supports consumer-key/secret Basic authentication over HTTPS.
([Official authentication reference](https://developer.woocommerce.com/docs/apis/rest-api/authentication))

`ConnectedWooCommerceConnector` contains IDs and trusted resource configuration,
not decrypted keys. It uses `IntegrationService.execute_connector` for backend-only
credential leasing, connection locking, revocation gating and redacted auditing.
Instantiate its `WooHTTP` with the same deployment allowlist. `WooResource.store_url`
must match the encrypted credential's store exactly. DNS results must all be
public; the connection is pinned to the validated IP with the original TLS SNI
and Host. Redirects, query-string credentials and automatic retries are disabled.

Disconnect immediately disables local use through the existing lifecycle. Native
API keys also require manual revocation in the store administration interface;
the adapter does not pretend to revoke them remotely or create a broader admin
integration. Reconnection uses the existing API-key path with the connection ID.

## Declared operations and binding

Both order providers share these qualified names:

| Reads | Writes / requests |
| --- | --- |
| `orders.find_order` | `orders.update_shipping_address` |
| `orders.get_status` | `orders.update_contact_information` |
| `orders.get_tracking` | `orders.add_order_note` |
| `orders.get_items` | `orders.request_order_cancellation` |
| `orders.get_delivery_information` | |

Create the AgentSpec binding through `configured_order_binding`, using the trusted
resource configuration and `allow_writes` only when the administrator has approved
the provider grants. The helper defaults to reads. `WooResource.writable_operations`
is empty by default; execution independently enforces that exact set and the key's
configured permission. The manifest's superset is not a grant to a tenant.

`CustomerMatch` is trusted identity-resolution input, not identity proof. Every
specific order read/write checks the supplied customer ID and/or verified email;
if both are supplied, both must match. Guest customer ID `0` is never accepted as
an identity. Guest/email lookup requires the exact order ID. ID-filtered searches
use bounded provider pages, return only matching summaries and expose `next_page`.
Custom display order numbers must first be resolved to the canonical provider ID.
The later Orders pack must derive these identifiers from the existing verified
identity context and apply its required identity/confirmation/approval gates.

Responses project only order ID/version and the requested status, items, delivery
address or tracking information. Unknown statuses remain `UNKNOWN`; tracking is
explicitly unavailable unless configured metadata contains it. No tracking plugin
is silently assumed. Configure `tracking_number_meta`, `tracking_url_meta` and any
custom status mapping during trusted setup. Standard WooCommerce fields and order
metadata are the adapter's native backing representation.
([Official orders reference](https://developer.woocommerce.com/docs/apis/rest-api/v3/orders/))

## Mutations and reconciliation

All writes require the exact read snapshot's `expected_version` plus the stable
action idempotency key. The adapter reads and checks ownership/state immediately
before mutation. Address/contact/cancellation-request operations reject terminal,
unknown or shipped/tracked orders. Shipping updates are typed complete addresses;
contact updates change only the supplied email/phone fields.

Address/contact updates and cancellation requests include an action/digest receipt
in order metadata. Cancellation only records `_agents_factory_cancellation_request`
as `REQUESTED`; it never sets order status to cancelled or issues a refund. A
matching receipt returns `replayed: true`; a changed payload with the same key is
rejected. Internal order notes use a stable action/digest marker in the note body
and bounded note-page reconciliation; they never set `customer_note: true` or
trigger a customer notification through this adapter.
([Official order-notes reference](https://developer.woocommerce.com/docs/apis/rest-api/v3/order-notes/))

Use the connected wrapper, not a bare credential-bearing adapter in production.
Its connection lock serializes this platform's calls using that connection.
Compare-before-write and metadata are not a database transaction against another
connection, a human editor or a WooCommerce plugin. They do not promise atomic
CAS or universal exactly-once delivery. Timeouts, 5xx or unconfirmed write
responses return `UNCERTAIN`; the Task 26 Action layer must persist that state and
require reconciliation rather than automatically submitting a fresh write.
Provider diagnostics and credentials never enter result messages.

## Verification

Synthetic provider contract scenarios exercise all nine operations, ownership,
pagination, absent tracking, partial permissions, receipts/replay, stale versions,
shipped-order rejection, cancellation-request-only semantics, encrypted payload
binding, HTTPS/DNS/redirect restrictions, redaction and write timeout classification.
No live WooCommerce store/key was connected and no schema migration was needed.
