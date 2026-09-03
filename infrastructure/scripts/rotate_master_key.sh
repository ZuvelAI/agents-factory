#!/usr/bin/env sh
set -eu

tenant_id=${1:?usage: rotate_master_key.sh TENANT_UUID}
printf '%s' "$tenant_id" | grep -Eq '^[0-9a-fA-F-]{36}$'
for variable in ROTATION_DATABASE_URL OLD_APP_MASTER_KEY NEW_APP_MASTER_KEY OLD_APP_MASTER_KEY_VERSION NEW_APP_MASTER_KEY_VERSION; do
  value=$(printenv "$variable" || true)
  test -n "$value" || {
    printf '%s\n' "rotate_master_key: missing $variable" >&2
    exit 78
  }
done

batch=0
while test "$batch" -lt 100; do
  output=$(uv run --all-packages python -m agents_factory.modules.secrets.rotation --tenant "$tenant_id" --limit 100)
  printf '%s\n' "$output"
  count=$(printf '%s\n' "$output" | awk '/rotation batch completed:/ {print $4}')
  test "${count:-}" = 0 && break
  batch=$((batch + 1))
done
test "$batch" -lt 100 || {
  printf '%s\n' 'rotate_master_key: completeness not reached within bounded batches' >&2
  exit 1
}
printf '%s\n' 'rotate_master_key: rewrap complete; verify connectors before retiring old key'
