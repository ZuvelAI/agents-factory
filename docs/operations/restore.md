# Restore

Follow the authoritative [backup/restore runbook](../../infrastructure/runbooks/backup-restore.md).
The Control Plane evidence must include manifest checksum, isolated target, exact
release/migration, measured RPO/RTO, RLS result, Storage retrieval, secret check,
outbox reconciliation and sandbox conversation. Production remains blocked until
all critical checks pass.
