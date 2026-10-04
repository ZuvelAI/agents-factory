# Preserve Meta review access during coexistence rollout

This is a deployment checklist, not deployment authorization. The Meta
reviewer account remains dedicated to its existing API_ONLY test account;
it is not a customer demo and must not be rebound to Zuvel's real number.

## Required server configuration

Before deploying the reviewer correction, place all five values from
`infrastructure/meta-review-binding.env.example` into the **backend and
control-plane server environments**, identically. Do not prefix them with
`NEXT_PUBLIC_`, include them in browser code, or replace them with user-editable
metadata. The example contains identifiers only, not passwords or access tokens.

Keep the existing Auth account, credentials, app_metadata scope and expiry.
This branch does not extend expiry, rotate credentials, reconnect the test
account or edit any Meta setting. If the actual scope has expired, restoration
requires a separate authorized account change; never remove the expiry guard.

Absent/partial configuration disables review. Invalid backend identifiers fail
configuration validation with field names only. There is no fallback customer
profile in application code. A mismatch between servers must block rollout,
not be repaired by trusting the caller's tenant/account values.

## Authorized environment checks before rollout

1. Confirm the reviewer profile and API_ONLY test assets match on both servers.
2. Sign in using the existing reviewer account. Confirm `/review` is available
   and displays the same test WABA/phone and masked recipient suffix.
3. Confirm reviewer requests to administrator/customer/coexistence controls
   remain denied. Ordinary admin access must remain separate.
4. Confirm missing configuration, foreign tenant/account, revoked role and
   expired access fail closed. Do not mutate the live reviewer to test these;
   use isolated test fixtures or a separately authorized staging account.
5. A templates refresh makes a live provider request. A test send contacts the
   owner's existing approved recipient, never the reviewer's phone. Both need
   explicit authorization for the target environment; local tests mock them.
6. Do not publish until configuration parity and reviewer smoke checks pass.
   Keep the previous deployment/configuration recoverable. Do not revoke the
   review account as a rollback step.

## Coexistence pilot is a separate gate

The panel still blocks live COEXISTENCE signup. There is no evidence yet that
Meta accepts Zuvel's number. A pilot needs a separately approved deployment,
backup/rollback plan and a narrow activation decision, then owner-operated Meta
signup from the AI Workers panel. Never use the reviewer account for this, remove
WhatsApp Business from the phone, fall back to API_ONLY or register/deregister
the existing number. General availability for new clients follows only after
the supervised pilot passes mobile/agent takeover, synchronization and recovery
checks; local tests are not evidence of live provider behavior.
