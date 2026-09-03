# Backup and restore runbook

## Scope and limits

The durable recovery set includes Supabase PostgreSQL, Supabase Storage objects,
encrypted secret envelopes, versioned deployment/configuration metadata, immutable
container image digests, the GitHub repository and external account mappings.
Redis is rebuildable coordination state and is never a source of truth. A single
VPS has an unavoidable availability window while it is rebuilt.

## Backup

1. Use a dedicated Staging/backup identity and create an encrypted directory with
   `database/`, `storage/`, `configuration/`, `images/`, `external-mappings/` and
   `metadata/`. Never place a master key in that directory.
2. Export PostgreSQL in a transactionally consistent format and export Storage
   objects separately. Record exact release, migration, AgentSpec and Knowledge
   digests in `metadata/release.json`.
3. Run `infrastructure/scripts/backup_manifest.sh BACKUP_ROOT`. Copy the package
   to the approved off-host encrypted destination and record the manifest digest.

## Isolated restore drill

1. Provision a disposable Supabase project and VPS/network isolated from
   Production. Supply secrets through the environment, never command arguments.
2. Restore PostgreSQL and Storage, configure a `pg_service.conf` entry, then set
   `RESTORE_PGSERVICE` to its name.
3. Run `infrastructure/scripts/verify_restore.sh RESTORE_ROOT --full`; then verify
   tenant, AgentSpec, Knowledge, action and audit counts, RLS attack tests, one
   media object, secret decryption, pending-outbox reconciliation, readiness and
   one sandbox conversation.
4. Record start/end timestamps, observed RPO/RTO, gaps and image digests. Destroy
   the disposable environment after evidence is retained without customer data.

Rollback: if any checksum, RLS or application check fails, stop before routing
traffic, preserve sanitized diagnostics, and start a new isolated restore. Never
repair the only backup in place.
