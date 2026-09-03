# Single-VPS disaster recovery

Declare a disaster when the VPS cannot be restored in place, durable data is
suspected corrupt, or credential compromise requires rebuild. Assign incident,
security and customer-communication owners and stop automated Production promotion.

1. Isolate the failed host and revoke its deploy credentials; preserve provider
   evidence without copying secrets into tickets.
2. Select the latest verified off-host database and Storage backup plus the exact
   compatible image/configuration versions. Record the observed recovery point.
3. Build a clean VPS, least-privilege deploy identity, firewall and Caddy endpoint.
   Restore using the backup runbook. Redis starts empty and outbox jobs reconcile
   from PostgreSQL.
4. Run checksums, RLS/security suite, readiness, connector health, DLQ inspection,
   one sandbox conversation and the exact-version Quality Gate. Keep DNS/traffic
   away until every critical item passes.
5. With manual Production approval, route traffic, monitor first conversations,
   costs and provider errors, and record the observed recovery time.

Rollback means returning traffic to the last healthy host only if it is proven
uncompromised and schema-compatible. This topology is not high availability;
recovery time includes VPS provisioning, data restore and verification.
