# Tenant isolation release blocker

## Threat model

Agents Factory assumes application input, tenant identifiers, actor identifiers,
HTTP requests, jobs, and provider payloads are untrusted. A compromised or buggy
application request must not read, count, infer, mutate, or delete durable data
owned by another tenant. The PostgreSQL roles `postgres`, `supabase_admin`,
provider `service_role`, and any role with `BYPASSRLS` are migration or local-test
control identities, never application runtime identities.

The backend runtime uses one constrained `agents_factory_app` database role.
Actor A and actor B are represented by separate transaction-local tenant
contexts, not separate database roles. Each business transaction sets
`app.tenant_id` with `set_config(..., true)` and RLS compares it with the table's
tenant-owner UUID. Missing, empty, invalid, stale, or wrong context fails closed.
The transaction-local value must not survive commit or rollback.

## Mandatory registration

Every public tenant-owned table must be registered in both explicit registries:

- `TENANT_ISOLATION_REGISTRY` in
  `apps/backend/tests/security/test_tenant_isolation_matrix.py` seeds two real
  tenants and calls `assert_tenant_isolated(table_name,
  owner_column="tenant_id")`.
- `task5_tenant_isolation_registry` in
  `supabase/tests/rls_matrix_test.sql` calls the pgTAP helper with the same
  contract.

Use `owner_column="id"` only for `public.tenants`; normal tenant-owned tables use
`tenant_id`. Catalog completeness assertions compare the registry with every
public base or partitioned table containing `tenant_id`, so adding a migration
without registration fails the release blocker automatically. Views are not
base-table registrations; any tenant-facing view must independently retain the
approved `security_invoker` contract. `public.platform_admins` is intentionally
excluded because it is global authorization membership with no tenant-owned
payload.

Adding a table must begin RED. Apply its migration locally without registering
it, run `make test-tenant-isolation`, and confirm the catalog-completeness test
names the unregistered base table. Then extend every applicable adapter before
expecting GREEN:

- add the table and owner column to both the Python and pgTAP registries;
- explicitly set `insert_allowed`, `update_allowed`, and `delete_allowed` in the
  Python registration, including explicit `False` for deliberately ungranted
  operations;
- seed a valid `row_a` and `row_b` for the two tenant actors and preserve their
  IDs for survival checks;
- add the real insert SQL to `_insert_statement()` and all of its bind values to
  `_insert_parameters()`;
- add a harmless same-tenant assignment to `_matching_update()`, or `None` when
  the application role deliberately has no update grant;
- seed any tenant-consistent parent rows required by foreign keys, including a
  tenant-A parent and an existing tenant-B parent so the foreign-versus-absent
  parent probe reaches the FK boundary after the owner check passes; and
- keep the pgTAP helper and catalog query aligned if a table uses an exceptional
  owner-column contract.

The expected GREEN is the focused Python attack matrix plus the pgTAP registry
and completeness checks from the same `make test-tenant-isolation` invocation.
A `KeyError`, missing seed, or skipped CRUD adapter is not an acceptable
registration result.

## CRUD contract

For every registered table, the matrix verifies own-row visibility and hidden
foreign-row select/count behavior; inserts with matching context when granted;
denial of foreign, absent, missing-context, empty-context, invalid-context, and
wrong-context inserts; matching updates when granted; zero-row foreign updates;
rejected owner reassignment; and tenant-scoped delete or uniform relation-level
denial. Denied mutations are followed by privileged survival checks.

Existing and nonexistent foreign references use identical SQL statement shapes.
An RLS-hidden row returns zero rows. An operation deliberately omitted from the
role's grants returns stable SQLSTATE `42501`. Invalid UUID context may return
`22P02`, but it never depends on whether a foreign row exists. Application error
mapping, row counts, logs, and response detail must not branch on foreign-row
existence. Denial comparisons use a UUID-normalized fingerprint of the exception
type, SQLSTATE, server message/detail, schema, table, and constraint. Timing is
controlled structurally through identical query paths and database policies;
flaky wall-clock equality microbenchmarks are prohibited.

## Platform administrator separation

Cross-tenant administration never grants raw application-role access. The
existing `PlatformAdminAuthorizer` must first verify the signed
`app_metadata.platform_role` claim and then find the principal in
`public.platform_admins` while using the constrained `agents_factory_admin`
role. Claim-only and membership-only principals are denied. Provider
`user_metadata` is never an authorization source.

## Local and CI execution

Run the focused matrix while developing Task 5:

```sh
make test-tenant-isolation
```

Run the aggregate security release blocker once at the acceptance gate:

```sh
make test-security
```

Both commands reject a linked Supabase project and derive `DB_URL` from
`supabase status -o json`. Before any connection, the runner rejects query or
fragment overrides, ambiguous/multihost authorities, Unix sockets, a non-loopback
host, and any port/database other than the repository's local Supabase target.
It rebuilds a canonical DSN from the validated effective SQLAlchemy/asyncpg
arguments, owns exactly one local reset, and passes only that DSN to the Python
matrix. The required GitHub check remains `ci-baseline`; its locked command
sequence invokes `make test-security`. A pre-matrix wiring verifier makes removal
or bypass of the Python/pgTAP runner fail before the excluded matrix file could
execute.

## Debugging failures

1. Confirm Docker is running and `pnpm supabase status -o json` reports a
   loopback `DB_URL`.
2. Confirm `supabase/.temp/project-ref` does not exist. Never substitute a hosted
   project or provider credentials.
3. Run `make test-tenant-isolation` and identify the registered table and CRUD
   operation that failed.
4. Compare grants and the table's explicit `SELECT`, `INSERT`, `UPDATE`, and
   `DELETE` policies. `UPDATE` requires both `USING` and `WITH CHECK`.
5. Reproduce a policy defect with the focused matrix before changing a
   migration. Keep the application role non-superuser and non-`BYPASSRLS`.

Never “fix” this gate with a service-role key, privileged provider connection,
`SECURITY DEFINER` bypass, hosted-test fallback, or a weakened assertion.
