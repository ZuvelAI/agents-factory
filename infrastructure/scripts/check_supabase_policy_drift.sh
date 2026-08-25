#!/usr/bin/env sh

set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

fail() {
  printf '%s\n' "check_supabase_policy_drift: $*" >&2
  exit 1
}

set -- supabase/migrations/*_foundation.sql
test "$#" -eq 1 || fail 'exactly one foundation migration is required'
migration_path=$1
test -f "$migration_path" || fail 'foundation migration is missing'
policy_path=supabase/policies/tenant_isolation.sql
test -f "$policy_path" || fail 'canonical tenant policy fragment is missing'

extracted_policy=$(mktemp "${TMPDIR:-/tmp}/agents-factory-policy.XXXXXX")
trap 'rm -f "$extracted_policy"' EXIT HUP INT TERM

sed -n \
  '/^-- BEGIN CANONICAL TENANT ISOLATION POLICIES$/,/^-- END CANONICAL TENANT ISOLATION POLICIES$/p' \
  "$migration_path" | sed '1d;$d' >"$extracted_policy"

test -s "$extracted_policy" || fail 'canonical policy section is missing from migration'
diff -u "$policy_path" "$extracted_policy" >/dev/null || \
  fail 'canonical policy fragment differs from deployable migration'

printf '%s\n' 'check_supabase_policy_drift: canonical policy is mirrored verbatim'
