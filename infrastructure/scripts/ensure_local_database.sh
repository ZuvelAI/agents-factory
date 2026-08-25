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

local_status_is_safe() {
  pnpm supabase status -o json 2>/dev/null | python3 -c '
import json
import sys
from urllib.parse import urlsplit

try:
    database_url = json.load(sys.stdin)["DB_URL"]
    parsed = urlsplit(database_url)
except (KeyError, TypeError, ValueError):
    raise SystemExit(1)

if parsed.scheme != "postgresql" or parsed.hostname not in {
    "127.0.0.1",
    "::1",
    "localhost",
}:
    raise SystemExit(1)
'
}

if ! local_status_is_safe >/dev/null 2>&1; then
  pnpm supabase db start >/dev/null
fi

local_status_is_safe >/dev/null 2>&1 || \
  fail 'local Supabase Postgres is unavailable or non-loopback'

pnpm supabase db reset --local --no-seed >/dev/null

local_status_is_safe >/dev/null 2>&1 || \
  fail 'local Supabase Postgres failed post-reset validation'

printf '%s\n' 'ensure_local_database: local Postgres reset and verified'
