# Master-key rotation runbook

Prerequisites are a tested backup, an isolated Staging environment, maintenance
database credentials allowed to assume `agents_factory_key_rotation`, and old/new
256-bit keys delivered through the secret manager. The new version must be higher.

1. Set `ROTATION_DATABASE_URL`, `OLD_APP_MASTER_KEY`, `NEW_APP_MASTER_KEY`,
   `OLD_APP_MASTER_KEY_VERSION` and `NEW_APP_MASTER_KEY_VERSION` in the protected
   runner environment. Do not paste keys in shell history, tickets, SQL or logs.
2. Run `infrastructure/scripts/rotate_master_key.sh TENANT_UUID`. It rewraps data
   keys in bounded, resumable batches; payload ciphertext is not decrypted or
   rewritten. Audit rows contain versions and counts only.
3. Start the Staging application with the new key/version and verify every test
   connector plus secret store/load. Confirm zero envelopes remain on the old
   version and review completed rotation runs.
4. Only then retire the old key. If any connector fails, keep both keys protected,
   stop rotation, restore the previous application key version and investigate.

Repeat tenant by tenant. Production rotation requires the same manual environment
approval as deployment.
