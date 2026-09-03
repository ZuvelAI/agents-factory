# Integration connections — Task 22

This is the shared lifecycle underneath the approved v1 connectors. It does not
add a Generic REST adapter or any new product capability.

## Control Plane API

All routes are under `/admin/tenants/{tenant_id}/integrations` and require the
existing platform-admin JWT and database membership checks.

| Route | Purpose |
| --- | --- |
| `GET /catalog` | Declared availability, operations and tenant connection health |
| `GET /connections` | Credential-free connection summaries, including existing Meta accounts |
| `POST /oauth/start` | New authorization or reconnect, with explicit allowlisted scopes |
| `POST /oauth/callback` | Exchange an authorization code using the backend-held PKCE verifier |
| `POST /api-key` | Validate and store an approved WooCommerce credential payload |
| `POST /connections/{id}/health` | Check one connection, without disabling unrelated providers |
| `POST /connections/{id}/refresh` | Refresh an OAuth credential in the backend |
| `POST /connections/{id}/revoke` | Durably disable locally, then revoke with the provider |

Provider registrations are code-owned and restricted to the v1 names. Task 23
supplies Google adapters; Task 25 supplies the WooCommerce adapter. Until those
adapters are configured, authorization fails closed with
`integration_not_configured`. The catalog does not advertise undeclared business
operations. These routes are backend foundations; the Control Plane screens remain
in their originally planned milestone.

Meta connects/reconnects through the existing Embedded Signup routes. The catalog
and health/revoke routes delegate to the Task 11 account service, retaining the
original account ID, encrypted credential reference and revocation coordinator.
There is no copied token or second Meta credential lifecycle.

## Credential and authorization boundary

- Connections persist only `SecretRef` IDs with same-tenant foreign keys. The
  existing Secrets Foundation binds encrypted payloads to tenant, purpose and
  connection ID. There is no second vault implementation.
- OAuth state is random, stored only as a digest, and bound to tenant, admin user,
  admin session, connection and authorization generation. It expires after ten
  minutes. Starting another authorization invalidates older generations.
- PKCE uses S256. Its verifier is encrypted through SecretVault, never sent to the
  frontend, and its reference is detached and deleted after callback processing.
- State consumption commits independently before the provider exchange. A failed
  exchange or rolled-back later operation cannot make that state reusable.
- Only the backend lifecycle loads credentials for provider calls. Repositories,
  routers, responses and runtime tools do not decrypt credential references.
- Responses and audit events contain scopes, stable reason codes, state and
  health, never raw provider exceptions, tokens, authorization codes or verifiers.
  Input validation responses also omit the original request values.

## Concurrency and failure behavior

Lifecycle mutations lock the connection row. Refresh and reconnect cannot revive
a connection that has entered `REVOKING` or `REVOKED`. Revocation commits
`REVOKING` before contacting the provider. If the process or provider fails, the
connection remains disabled and the same revoke route may retry. Its encrypted
reference remains available only to complete revocation; on success the reference
is detached and its envelope deleted.

A transient health failure is localized to that connection. Expiry or revoked
authorization requires refresh/reauthorization. Provider scope grants must match
the explicitly requested set; broader or insufficient grants are not activated.

The provider contracts use deterministic fakes in the Task 22 verification.
Real client authorizations and provider-specific API checks belong to Tasks 23/25;
no live customer credentials were requested or connected for this foundation.
