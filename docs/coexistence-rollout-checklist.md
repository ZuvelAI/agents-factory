# Coexistence: test deployment and Zuvel pilot

This checklist is preparation, not authorization to deploy, migrate a remote
database, change Meta, start workers or connect a real number. The current API
and panel still reject live COEXISTENCE signup. Local tests cannot establish
Meta eligibility for Zuvel or any future customer.

## 1. Identify the target before changing it

- Record the exact candidate commit, backend/panel images and current deployed
  versions. `infrastructure/VPS.md` describes `/opt/aiworkers` and
  `aiworkers.zuvel.ai`; it does not prove that a separate staging environment
  exists. Do not turn the existing deployment into staging by assumption.
- Identify the target database/project, runtime configuration, Redis and worker
  ownership without printing credentials. A test environment needs separate
  data and queues; the existing VPS instructions warn that local/VPS workers
  may share the database despite having separate Redis queues.
- Obtain explicit approval for the named target and actions. No remote reset,
  `down -v`, Redis flush, outbox deletion or change to unrelated Zuvel/OpenClaw
  services belongs in this rollout.
- Establish which compatible backend receives the public signed WhatsApp
  webhook. A second panel alone is not an isolated provider integration. Do
  not replace the existing Meta callback or move customer/reviewer traffic as
  an incidental staging setup step; any routing change needs its own scope.

Stop if the environment is ambiguous, shared data could be modified, or the
previous compatible deployment cannot be recovered.

## 2. Deploy a gated candidate only after approval

- Keep private configuration out of build arguments, browser bundles and logs.
  Preserve the existing encryption master key wherever existing ciphertext is
  used; do not substitute the temporary keys from local tests.
- Capture a protected database/configuration backup and verify restore to a
  separate disposable target. Include key recovery and any Storage objects;
  applying migrations to an empty local database is not a backup/restore drill.
- Compare the remote migration history with the candidate and review the
  pending migrations before applying them. The local test reconstruction
  applies all 27 migrations; that does not identify the remote pending set.
  Never run the local reset script against a deployed project.
- Supply the same five server-only reviewer settings to both servers, following
  [the reviewer preservation checklist](meta-review-preservation.md). Both
  Compose manifests now pass the same interpolated values to the backend and
  panel; a host override must not affect only one of them. Independent/manual
  deployments still require a five-value comparison.
- Preserve the current reviewer identity, role/scope, credentials and expiry.
  Verify login and denial of admin/customer controls in the authorized target.
  Do not extend an expired account automatically. A provider template refresh
  or test send remains a separately approved external action.
- Check backend readiness, database connectivity/migration compatibility and
  panel health separately. The public panel `/health/ready` is a static liveness
  response; HTTP 200 alone does not prove database, reviewer or Meta readiness.
- Leave live coexistence signup closed and workers stopped unless their
  activation has been approved. Do not run two schedulers against shared durable
  outbox data. Record queue ownership and cutover before any worker activation.

Stop on a failed migration, configuration mismatch, expired reviewer access,
unhealthy dependency or unexpected outbound job. Retain the earlier compatible
images and configuration rather than overwriting the only rollback copy.

## 3. Open a supervised Zuvel-only pilot separately

Before a real-number pilot, approve and verify a tenant-scoped activation
mechanism on both API and panel. The current hard gate must not be removed
globally to test one customer. An approved/published Meta app is not evidence
that a particular number is accepted for coexistence.

The owner performs all Meta UI and phone actions. Confirm current official Meta
requirements and the exact Embedded Signup configuration before starting; the
saved configuration name or token lifetime is not proof of coexistence support.
No computer-use automation, WhatsApp Business uninstall, number deregistration,
API_ONLY fallback or forced ELIGIBLE database update is allowed.

Use the Zuvel admin/tenant, not the restricted reviewer account. Keep the
existing phone app installed. The server must verify returned asset ownership,
the exact number and provider evidence of coexistence; an ambiguous phone
selection or unavailable eligibility is a stop, not a reason to guess.

Record evidence for each pilot check without tokens or customer message bodies:

- Owner-approved inbound message, agent response and delivery status.
- Mobile outbound echo, AI pause, queued-reply cancellation and explicit audited
  resume. Document the residual in-flight send race rather than promising that
  a sent request can be recalled.
- Contacts/history consent, refusal and completion states. ACCEPTED is request
  acceptance, not completed synchronization. UNKNOWN requires reconciliation,
  never a blind retry of a one-shot request.
- Duplicate/reordered events, cross-tenant denial and connection loss. Use
  isolated fixtures for destructive or scope-changing fault injection; do not
  revoke live assets merely to manufacture a test result.
- Mobile access remains usable; unexpected double replies or access loss stop
  the pilot. Do not send to arbitrary customers for testing.

## 4. Rollback and broader availability

On an incident, close further onboarding and pause pilot outbound execution
before promoting a recovery version. Keep the number in the phone app and
retain encrypted credentials, durable jobs, audit/history data and reviewer
access. Do not deregister the number or delete the account as rollback.

Restore only an application version proven compatible with the current schema
and coexistence records. A pre-coexistence image is not automatically a safe
rollback after onboarding. Database restoration is a separate incident decision:
do not reverse migrations or overwrite newer live data as an automatic rollback.

General availability for new clients requires the supervised pilot evidence,
configuration/renewal ownership, privacy/consent checks and an explicit release
decision. Eligibility must still be checked independently for every number.
