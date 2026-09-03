# Rollback

Confirm the previous immutable image is healthy and schema-compatible. Start the
protected Production workflow with the failed release and previous release SHA;
failed smoke invokes the host's fixed `rollback-release` entrypoint. Do not run
arbitrary remote shell commands or reverse an incompatible destructive migration.

Expected evidence is `ROLLED_BACK`, the previous image digest, healthy readiness,
one sandbox conversation and a correlated audit/deployment record. If data is
damaged, stop and use [restore](restore.md) instead of repeatedly rolling back.
