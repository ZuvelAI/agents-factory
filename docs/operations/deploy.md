# Deploy

Prerequisites: green `ci-baseline`, exact passing Quality Gate, immutable image
digests, compatible migration, healthy backup and protected GitHub environments.
Merging `main` builds and pushes versioned images, migrates and promotes Staging,
then runs smoke checks. Inspect correlated deployment and connector health in the
Control Plane.

Production is a manual `Deploy Production` workflow using the exact Staging-tested
git SHA, migration and last known-good rollback SHA. A GitHub environment reviewer
must approve. Never put credentials in workflow inputs or logs. If migration,
readiness or smoke fails, stop traffic promotion and follow [rollback](rollback.md).
