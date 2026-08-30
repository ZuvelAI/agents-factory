# MS5 execution checkpoint

Date: 2026-08-30
Branch: `codex/m5-integrations`
Base: final MS4 content merged in PR #4 (`f9fd136` on GitHub).

The approved implementation plan is unchanged. No Superpowers workflow was used.
MCP-only access applies to external services used by Codex, not to a redesign of
the product's approved OAuth/API connectors.

## Task 22 — connection lifecycle foundation

Implemented tenant-scoped connection persistence, OAuth state/session/PKCE
binding, encrypted references through the existing Secrets Foundation, refresh,
reconnect, durable revocation, isolated health reporting, admin API routes and
Integration Catalog metadata. Existing Meta accounts are reused through their
original service, not copied into a second credential store.

New provider adapters remain unavailable until their planned tasks register them.
No Generic REST executable, authentication flow or webhook was added.

Verification is focused on new/changed behavior only; previous milestone suites
were not rerun. The migration was applied to the existing local database without
a reset. Provider exchanges use sanitized fakes, not real client authorizations.

## Task 22 verification

Verified evidence for this checkpoint:

- 8 new database integration scenarios passed (OAuth lifecycle, credential
  rotation, binding/PKCE attacks, replay, reconnect, concurrency and localized health).
- 2 new secret-boundary/HTTP-redaction scenarios passed.
- 1 new Meta/catalog projection scenario passed.
- Registry coverage and the new connection table's reusable isolation case passed.
- Focused Ruff and mypy checks passed; Supabase advisors reported no warnings/errors.
- Existing secret-scanner expression found no credential-like assignments in the changes.

The first database attempt was blocked by the sandbox before execution. The
subsequent run exposed a missing schema USAGE grant; only the six affected OAuth
scenarios were rerun after adding that minimal grant. Successful cases were not
rerun. No full local CI, database reset, or previous milestone suite was run.

## Task 23 — Google Workspace connector primitives

Implemented 11 native, typed operations across Calendar, Gmail, Drive and Sheets.
The connector manifests now declare those operations, with connection/configuration
and per-binding scope gates. Google Contacts and Generic REST remain absent.

Google OAuth is configurable per product through backend-only `GOOGLE_OAUTH_CLIENTS`.
The existing encrypted connection lifecycle is reused. A backend execution boundary
leases credentials, refreshes near expiry under the connection lock, and records
sanitized audit outcomes. Workers must supply an identified job/action actor;
anonymous secret access remains prohibited. No schema migration was necessary.

Documented limitations: no live client accounts were authorized; Google revocation
can affect combined grants in one Cloud project; Sheets precondition checks are not
atomic compare-and-swap. Capability packs must still use the existing Action layer
for approval, idempotency and reconciliation. No account credentials are in Git.

Focused verification at this checkpoint:

- 8 new contract scenarios passed on their first execution, covering all 11
  advertised operations plus scope/error/binding/size/header restrictions.
- The single modified catalog/schema unit case passed; no old milestone suite ran.
- 1 new local database scenario passed: real vault resolution, pre-execution
  refresh, audit redaction, actor/tenant gating, and independent Google health.
- That database scenario alone was retried once after it caught an anonymous
  worker actor in the new composition. The existing vault restriction was kept.
- Focused Ruff/mypy checks passed. No database reset, full CI, live Google request,
  dependency update or additional product scope was required.

See `docs/integrations/google-workspace.md` for scopes, composition and safe
operation contracts. Source plan and master specification remain unchanged.

## Continuation

Continue with Task 24: Appointments Capability Pack. Tasks 24–28 remain
pending. MS5 has not been declared complete and will still require its approved
milestone review before proceeding to MS6.
