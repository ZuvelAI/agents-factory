#!/usr/bin/env sh
set -eu

restore_root=${1:?usage: verify_restore.sh RESTORE_ROOT [--full]}
mode=${2:-artifacts}
case "$restore_root" in /|"$HOME"|"") exit 64 ;; esac
test -f "$restore_root/manifest.sha256"
(
  cd "$restore_root"
  shasum -a 256 -c manifest.sha256 >/dev/null
)
for asset in database storage configuration images external-mappings metadata; do
  test -e "$restore_root/$asset"
done

if test "$mode" = --full; then
  test -n "${RESTORE_PGSERVICE:-}"
  PGOPTIONS='-c default_transaction_read_only=on' \
    psql "service=$RESTORE_PGSERVICE" --no-psqlrc --set ON_ERROR_STOP=1 \
    --tuples-only --command "select count(*) from public.tenants" >/dev/null
  PGOPTIONS='-c default_transaction_read_only=on' \
    psql "service=$RESTORE_PGSERVICE" --no-psqlrc --set ON_ERROR_STOP=1 \
    --tuples-only --command "select bool_and(relrowsecurity and relforcerowsecurity) from pg_class join pg_namespace on pg_namespace.oid=pg_class.relnamespace where nspname='public' and relname in ('messages','actions','knowledge_versions','audit_events')" | grep -q t
fi
printf '%s\n' "verify_restore: checksums, durable assets and requested checks passed"
