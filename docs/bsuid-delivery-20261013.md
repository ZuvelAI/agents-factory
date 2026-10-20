# BSUID outbound delivery correction — 2026-10-13

## Evidence and scope

The latest inbound test reached the real coexistence account. The agent produced
a fourth outbound response, but all four persisted sends remained ACCEPTED.
ACCEPTED is not delivery confirmation. No parser diagnostic appeared for that
test; no delivery failure code was observed.

The conversation uses a business-scoped user ID, not a telephone number.
The outbound adapter always placed its destination in `to`. Meta's current
official documentation requires BSUID/parent BSUID in `recipient`, omitting `to`:
https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids

Text and template sends now use `recipient` for the documented BSUID format,
preserving `to` for existing telephone destinations. Delivery callbacks accept
`recipient_user_id` when `recipient_id` is absent, while rejecting callbacks
without either identifier. Telephone recipient precedence is unchanged.

## Verification

Regression tests first failed for four BSUID send variants and a BSUID-only
delivery callback. After the change, the targeted contract suite passed 29 tests.
The backend suite passed 577 tests against the disposable local database/Redis,
excluding the same three historical database/security gates as the prior release.
One pre-existing Starlette/AnyIO deprecation warning remains.

## Release scope

Runtime image: `aiworkers-coex-runtime:bsuid-delivery-20261013`, derived from
the current conversations release, copying only meta_provider.py and schemas.py.
Activation changes only the backend and outbound-worker. It removes the temporary
diagnostic entrypoint, restoring normal uvicorn. The control plane, agent,
scheduler, knowledge worker, Redis, accounts and credentials are unchanged.

Backend rollback config is saved at
`/opt/aiworkers/.timeout-20261012/compose.before-bsuid-delivery.json`.
The outbound override is
`/opt/aiworkers/.timeout-20261012/compose.bsuid-outbound.json`; the original worker
compose file is preserved. Activation automatically rolls both services back if
startup validation fails.

Pending: one new inbound test after activation, followed by persisted delivery
status and actual handset receipt. Do not replay the four old accepted responses:
their final delivery is unknown and replay could duplicate messages.

Activation succeeded: backend healthy, outbound running, diagnostic entrypoint
removed. The first attempt omitted the original Compose --env-file; backend was
restored and the worker was not changed in that attempt. Activation was then
completed with the original env file explicitly specified (contents never read
or changed). Both services now use the new runtime image.
