#!/usr/bin/env sh

set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

fail() {
  printf '%s\n' "ensure_local_database: $*" >&2
  exit 1
}

test "$(pnpm --version)" = "11.24.0" || fail 'pnpm 11.24.0 is required'
test "$(pnpm supabase --version)" = "2.115.0" || \
  fail 'Supabase CLI 2.115.0 is required'
test ! -f supabase/.temp/project-ref || \
  fail 'linked Supabase projects are forbidden for local test gates'

if ! pnpm supabase status -o json >/dev/null 2>&1; then
  pnpm supabase db start >/dev/null
fi

pnpm supabase status -o json >/dev/null 2>&1 || \
  fail 'local Supabase Postgres is unavailable'

printf '%s\n' 'ensure_local_database: local Postgres is ready'
