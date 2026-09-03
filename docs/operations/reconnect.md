# Reconnect a connector

In Operations, select the tenant and run Check health. For `REAUTH_REQUIRED`, use
Reconnect and complete the provider-owned OAuth or Embedded Signup screen with
the approved least scopes. Never copy a token into chat, tickets or database SQL.

Confirm `CONNECTED`/`HEALTHY`, current scope set, new authorization generation and
successful sandbox read. A failed reconnect leaves the connector isolated and
does not affect other providers. Repeated failure opens a deduplicated incident;
escalate with its correlation ID and stable error code only.
