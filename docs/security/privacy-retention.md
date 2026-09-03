# Privacy and retention

Agents Factory v1 keeps tenant boundaries during export, deletion, connector
revocation and scheduled retention. The default policy minimizes conversation
content after 90 days, detailed traces after 30 days and action/audit evidence
after 12 months. A platform administrator may configure stricter tenant values.

Privacy requests are durable and idempotent. Their lifecycle is `REQUESTED`,
`STARTED`, then `COMPLETED`, `FAILED` or `HELD`. Legal or operational holds stop
destruction and remain visible; they are never silently bypassed. Conversation
deletion replaces direct identifiers with a tenant-specific pseudonym and clears
message content while preserving non-identifying operational counts. Exports use
checksummed manifests and must be delivered through private time-limited storage;
content and signed links must never appear in application logs.

Tenant-wide integration revocation clears credential references and granted
scopes. Provider-side revocation and physical media/object deletion are retryable
external steps and must be confirmed by receipts before commercialization. Legal
counsel must review retention classes, lawful holds, export content and deletion
exceptions for each operating jurisdiction before the first real customer.
