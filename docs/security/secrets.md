# Secrets

Provider tokens and API keys are backend-only `SecretRef` values. Envelope
encryption uses a unique data key and AES-256-GCM authenticated bindings for the
tenant, purpose, record context and format version. PostgreSQL stores ciphertext,
wrapped data keys and nonces; the master key exists only in the protected runtime
environment. API, UI, audit, trace and eval artifacts never contain plaintext.

Runtime access requires an authenticated tenant context and records bounded audit
metadata. Denied access fails closed. Rotation rewraps data keys under a higher
master-key version in bounded batches; old keys are retired only after every
envelope and connector is verified. See [rotation](../operations/rotate.md).
