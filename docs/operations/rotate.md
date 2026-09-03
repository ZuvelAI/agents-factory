# Rotate secrets

Follow the authoritative [key-rotation runbook](../../infrastructure/runbooks/secret-rotation.md).
Use protected environment variables, rotate tenant by tenant, verify every test
connector and confirm no old-version envelope remains. Retire the old key only
after completeness evidence; otherwise keep both keys protected and roll the
application back to the previous version.
