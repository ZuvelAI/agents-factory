# Tenant Extension boundary

Standard onboarding is configuration-only. Customer-specific behavior must
not be implemented with tenant UUID literals, `if tenant_id == ...` branches,
or customer-named conditionals in core Python or TypeScript.

A future Tenant Extension must declare all of the following in a versioned
manifest:

- stable name and semantic version;
- accountable owner;
- Agents Factory compatibility range;
- isolated contract/security tests;
- explicit enable/disable state;
- immutable deployment artifact;
- rollback target; and
- a pre-registered entry point.

Extensions load only through the `TenantExtensionRegistry`. Unknown entry
points are rejected, and an extension is disabled by default. Agents Factory
v1 ships no Tenant Extensions and the registry rejects enabled extensions.

Reusable customer work may later be proposed as an official Capability Pack or
Connector, but that requires its own reviewed platform version; it does not
become core behavior implicitly.
